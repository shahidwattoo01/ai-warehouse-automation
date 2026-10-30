"""Answer writers for RAG: the retrieved sections in, a short answer with [section] citations out.

* ExtractiveGenerator (default, free, offline): picks the best-matching sentences of the
  retrieved sections. Every word comes from the documents, so it cannot invent facts, but it
  cannot combine or rephrase either.
* ClaudeGenerator (optional): writes a fluent answer from the same sections with Claude, citing
  section ids, and says NOT_COVERED when the sections do not answer the question. Used only when
  LLM_PROVIDER=anthropic and an Anthropic API key is configured; each question is a paid API call.
"""

from __future__ import annotations

import logging
import re

from ai.rag.retriever import Hit, extractive_answer, section_text

log = logging.getLogger(__name__)

NOT_COVERED = "NOT_COVERED"
CLAUDE_MODEL = "claude-opus-5-5"
SYSTEM_PROMPT = (
    "You answer questions from warehouse operators, using only the numbered document sections "
    "given in the message. Answer in at most four short sentences or a short list of steps. Put "
    "the section id in square brackets after every statement it supports, e.g. [SOP-04]. Do not "
    "use knowledge from outside the sections. If the sections do not answer the question, reply "
    f"with exactly {NOT_COVERED}."
)


class ExtractiveGenerator:
    """style "sentences": the best 3 sentences of the retrieved sections; "section": the whole
    best section, up to `max_section_words` (keeps a procedure's steps and tables together)."""

    def __init__(self, scorer, style: str = "sentences", max_section_words: int = 120) -> None:
        self.scorer = scorer  # scorer(question, sentences) -> relevance scores
        self.style = style
        self.max_section_words = max_section_words
        self.name = f"extractive ({style} from the documents)"

    def answer(self, question: str, hits: list[Hit]) -> str | None:
        if self.style == "section" and hits:
            text = section_text(hits[0].chunk, self.max_section_words)
            return f"{text} [{hits[0].chunk.section_id}]" if text else None
        return extractive_answer(question, hits, self.scorer) or None


class ClaudeGenerator:
    name = f"Claude ({CLAUDE_MODEL})"

    def __init__(self, api_key: str | None = None, model: str = CLAUDE_MODEL) -> None:
        import anthropic

        # No key given: the SDK falls back to ANTHROPIC_API_KEY / an `ant auth login` profile.
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model

    @staticmethod
    def prompt(question: str, hits: list[Hit]) -> str:
        sources = "\n\n".join(
            f"[{h.chunk.section_id}] {h.chunk.title} · {h.chunk.heading}\n{h.chunk.text}"
            for h in hits
        )
        return f"<sections>\n{sources}\n</sections>\n\nQuestion: {question}"

    def answer(self, question: str, hits: list[Hit]) -> str | None:
        """The answer text, or None when Claude finds it not covered (or declines)."""
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},  # short grounded answers: low effort is enough
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # a policy decline is retried server-side on another model
            messages=[{"role": "user", "content": self.prompt(question, hits)}],
        )
        if response.stop_reason == "refusal":
            log.warning("Claude declined a knowledge question: %s", response.stop_details)
            return None
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text or text.startswith(NOT_COVERED):
            return None
        return re.sub(r"\s+\n", "\n", text)
