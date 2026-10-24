"""Fine-tuned Transformer for operator commands (Phase 6): intent and entities in one model.

    words ──► DistilBERT encoder ──► [CLS] vector ──► intent head ─► "reroute_robot"
                                 └─► one vector per word ──► tag head ─► B-ROBOT, O, B-AISLE...

DistilBERT (Sanh et al., 2019) is a smaller, faster BERT, pretrained on English text: it already
knows that "stop", "halt" and "hold" mean similar things. Fine-tuning adapts it to our 17 intents
and 13 entity types with a few thousand examples. Both heads share the encoder and are trained
together (sum of the two cross-entropy losses).

Words are split into sub-word pieces by the tokenizer ("inspection" -> "insp", "##ection"); each
word's tag is predicted on its first piece. The model is saved in a folder (encoder + tokenizer
in Hugging Face format, plus the two heads), so it loads offline.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

from ai.nlp.commands import BIO_TAGS, INTENTS, spans_from_bio, tokenize
from ai.nlp.understanding import understand

BASE_MODEL = "distilbert-base-uncased"
MAX_PIECES = 64  # sub-word pieces per message (messages are short: median 7 words)


class JointCommandModel(nn.Module):
    def __init__(
        self, encoder: nn.Module, n_intents: int, n_tags: int, dropout: float = 0.1
    ) -> None:
        super().__init__()
        self.encoder = encoder
        dim = encoder.config.hidden_size
        self.dropout = nn.Dropout(dropout)
        self.intent_head = nn.Linear(dim, n_intents)
        self.tag_head = nn.Linear(dim, n_tags)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        hidden = self.dropout(
            self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        )
        return self.intent_head(hidden[:, 0]), self.tag_head(hidden)


def encode(tokenizer, texts: list[str], tags: list[list[str]] | None = None) -> dict:
    """Tokenize messages word by word; tag labels sit on each word's first piece (-100 elsewhere,
    ignored by the loss). Returns tensors plus, per message, the piece index of every word."""
    words = [[w for w, _, _ in tokenize(t)] for t in texts]
    enc = tokenizer(words, is_split_into_words=True, truncation=True, max_length=MAX_PIECES,
                    padding=True, return_tensors="pt")  # fmt: skip
    first_piece, labels = [], []
    tag_id = {t: i for i, t in enumerate(BIO_TAGS)}
    for b in range(len(texts)):
        seen, firsts = set(), []
        row = np.full(enc["input_ids"].shape[1], -100)
        for pos, w in enumerate(enc.word_ids(b)):
            if w is not None and w not in seen:
                seen.add(w)
                firsts.append(pos)
                if tags is not None:
                    row[pos] = tag_id[tags[b][w]]
        first_piece.append(firsts)
        labels.append(row)
    out = {
        "input_ids": enc["input_ids"],
        "attention_mask": enc["attention_mask"],
        "first_piece": first_piece,
    }
    if tags is not None:
        out["tag_labels"] = torch.tensor(np.array(labels))
    return out


class TransformerParser:
    """Fine-tuned DistilBERT command parser with the same `parse` interface as the baselines."""

    name = "DistilBERT (fine-tuned: intent + entities)"

    def __init__(self, model: JointCommandModel, tokenizer) -> None:
        self.model = model.eval()
        self.tokenizer = tokenizer

    # ----- creation and saving -----------------------------------------------------------------
    @classmethod
    def from_pretrained_base(cls, base: str = BASE_MODEL) -> TransformerParser:
        from transformers import AutoModel, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(base)
        model = JointCommandModel(AutoModel.from_pretrained(base), len(INTENTS), len(BIO_TAGS))
        return cls(model, tokenizer)

    def save(self, folder: Path, report: dict | None = None) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.model.encoder.save_pretrained(folder / "encoder")
        self.tokenizer.save_pretrained(folder / "encoder")
        heads = {k: v for k, v in self.model.state_dict().items() if not k.startswith("encoder.")}
        torch.save(heads, folder / "heads.pt")
        meta = {
            "intents": INTENTS,
            "bio_tags": BIO_TAGS,
            "base_model": BASE_MODEL,
            "max_pieces": MAX_PIECES,
        }
        (folder / "labels.json").write_text(json.dumps(meta, indent=2))
        if report is not None:
            (folder / "report.json").write_text(json.dumps(report, indent=2, default=float))

    @classmethod
    def load(cls, folder: Path) -> TransformerParser:
        from transformers import AutoModel, AutoTokenizer

        meta = json.loads((folder / "labels.json").read_text())
        assert meta["intents"] == INTENTS and meta["bio_tags"] == BIO_TAGS, (
            "label lists changed: retrain"
        )
        encoder = AutoModel.from_pretrained(folder / "encoder")
        model = JointCommandModel(encoder, len(INTENTS), len(BIO_TAGS))
        model.load_state_dict(
            torch.load(folder / "heads.pt", map_location="cpu", weights_only=True), strict=False
        )
        return cls(model, AutoTokenizer.from_pretrained(folder / "encoder"))

    # ----- prediction --------------------------------------------------------------------------
    @torch.no_grad()
    def predict(self, texts: list[str], batch: int = 64) -> list[tuple[str, float, list[str]]]:
        """(intent, confidence, BIO tag per word) for each message."""
        self.model.eval()
        out = []
        for i in range(0, len(texts), batch):
            chunk = texts[i : i + batch]
            enc = encode(self.tokenizer, chunk)
            intent_logits, tag_logits = self.model(enc["input_ids"], enc["attention_mask"])
            probs = intent_logits.softmax(-1)
            tags = tag_logits.argmax(-1)
            for b, text in enumerate(chunk):
                k = int(probs[b].argmax())
                word_tags = [BIO_TAGS[int(tags[b, p])] for p in enc["first_piece"][b]]
                word_tags += ["O"] * (len(tokenize(text)) - len(word_tags))  # truncated words
                out.append((INTENTS[k], float(probs[b, k]), word_tags))
        return out

    def parse(self, text: str) -> dict:
        intent, confidence, tags = self.predict([text])[0]
        return understand(text, intent, confidence, spans_from_bio(text, tags))

    def parse_many(self, texts: list[str]) -> list[dict]:
        return [understand(t, i, c, spans_from_bio(t, tags)) for t, (i, c, tags) in
                zip(texts, self.predict(texts), strict=True)]  # fmt: skip

    # ----- training ----------------------------------------------------------------------------
    def fit(
        self,
        train: tuple[list[str], list[str], list[list[str]]],
        validate,
        epochs: int = 6,
        batch: int = 32,
        lr: float = 5e-5,
        patience: int = 2,
        seed: int = 42,
    ) -> list[dict]:
        """Fine-tune on (texts, intents, word tags). `validate()` returns a score (higher is
        better) after each epoch; the best epoch's weights are kept (early stopping)."""
        from transformers import get_linear_schedule_with_warmup

        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        texts, intents, tags = train
        y_intent = torch.tensor([INTENTS.index(i) for i in intents])
        steps = epochs * int(np.ceil(len(texts) / batch))
        optim = torch.optim.AdamW(self.model.parameters(), lr=lr, weight_decay=0.01)
        sched = get_linear_schedule_with_warmup(optim, int(0.1 * steps), steps)
        loss_fn = nn.CrossEntropyLoss(ignore_index=-100)
        history, best, best_state, wait = [], -1.0, None, 0
        for epoch in range(1, epochs + 1):
            start = time.time()
            self.model.train()
            order = rng.permutation(len(texts))
            total = 0.0
            for i in range(0, len(order), batch):
                b = order[i : i + batch]
                enc = encode(self.tokenizer, [texts[j] for j in b], [tags[j] for j in b])
                intent_logits, tag_logits = self.model(enc["input_ids"], enc["attention_mask"])
                loss = loss_fn(intent_logits, y_intent[b]) + loss_fn(
                    tag_logits.reshape(-1, tag_logits.shape[-1]), enc["tag_labels"].reshape(-1)
                )
                optim.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optim.step()
                sched.step()
                total += loss.item() * len(b)
            score = validate()
            history.append({"epoch": epoch, "train_loss": total / len(order), "validation": score,
                            "seconds": time.time() - start})  # fmt: skip
            print(f"epoch {epoch}: loss {history[-1]['train_loss']:.4f}  validation {score:.4f}  "
                  f"({history[-1]['seconds']:.0f} s)", flush=True)  # fmt: skip
            if score > best:
                best, wait = score, 0
                best_state = {k: v.detach().clone() for k, v in self.model.state_dict().items()}
            else:
                wait += 1
                if wait >= patience:
                    print(f"early stop: no improvement for {patience} epochs")
                    break
        self.model.load_state_dict(best_state)
        self.model.eval()
        return history
