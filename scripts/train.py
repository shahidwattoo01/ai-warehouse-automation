"""Train (retrain) a model with one command, by running its notebook from top to bottom.

    python scripts/train.py --list                 # models, their notebook and output files
    python scripts/train.py --model eta            # run notebooks/01_eta.ipynb, check the outputs
    python scripts/train.py --model anomaly_lstm   # Phase 5 LSTM (about 15 min on a laptop CPU)
    python scripts/train.py --phase 3              # all Phase 3 models, in order
    python scripts/train.py --phase 6              # NLP baselines, then DistilBERT (~1 h on CPU)
    python scripts/train.py --model rag            # RAG settings and evaluation (~5 min)
    python scripts/train.py --model eta --no-save  # run it, but do not overwrite the notebook

The notebooks are the single source of the training code (they explain every step), so this
script executes them headlessly instead of keeping a second copy of the code. After a run it
checks that every model file was written again, and prints the test result from the report.
Data must exist first: `python scripts/generate_data.py` (dataset v3 in data/processed/).

The YOLO detector needs a GPU: it trains on Google Colab (notebooks/cloud/train_yolo_colab.ipynb,
see notebooks/README.md); `--model vision` then re-runs the local evaluation (notebook 09).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks"
MODELS = ROOT / "models"

# model -> (phase, notebook, files it must write, how to read its headline test result)
PIPELINES: dict[str, tuple[int, str, list[str], str]] = {
    "eta": (3, "01_eta.ipynb", ["eta_v1.joblib", "eta_v1_report.json"], "eta"),
    "late_risk": (
        3,
        "02_late_risk.ipynb",
        ["late_risk_v1.joblib", "late_risk_v1_report.json"],
        "late",
    ),
    "demand": (3, "03_demand.ipynb", ["demand_v1.joblib", "demand_v1_report.json"], "demand"),
    "anomaly": (
        3,
        "04_anomaly.ipynb",
        ["anomaly_v1.joblib", "anomaly_iforest_v1.joblib", "anomaly_v1_report.json"],
        "anomaly",
    ),
    "demand_breakdown": (
        3,
        "05_demand_breakdown.ipynb",
        ["demand_breakdown_v1.joblib", "demand_breakdown_v1_report.json"],
        "breakdown",
    ),
    "anomaly_lstm": (
        5,
        "07_deep_learning_faults.ipynb",
        ["anomaly_lstm_v1.pt", "anomaly_mlp_v1.pt", "anomaly_dl_v1_report.json"],
        "anomaly_dl",
    ),
    "demand_net": (
        5,
        "08_deep_learning_demand.ipynb",
        ["demand_dl_v1.pt", "demand_dl_v1_report.json"],
        "demand_dl",
    ),
    "vision": (5, "09_vision_evaluation.ipynb", ["vision_yolo_v1/evaluation.json"], "vision"),
    "nlp_baselines": (
        6,
        "10_nlp_commands_baselines.ipynb",
        ["nlp_tfidf_v1.joblib", "nlp_baselines_report.json"],
        "nlp",
    ),
    "nlp_distilbert": (
        6,
        "11_nlp_transformer.ipynb",
        ["nlp_distilbert_v1/heads.pt", "nlp_distilbert_v1/report.json"],
        "nlp_dl",
    ),
    "rag": (7, "12_rag.ipynb", ["rag_v1.json"], "rag"),
}
NLP_DATA = ROOT / "data" / "processed" / "nlp" / "commands.jsonl"
RAG_DATA = ROOT / "data" / "processed" / "rag" / "questions.jsonl"
NEEDS = {  # inputs that must exist before a notebook can run
    "vision": [MODELS / "vision_yolo_v1" / "best.pt"],
    "nlp_baselines": [NLP_DATA],
    "nlp_distilbert": [NLP_DATA, MODELS / "nlp_tfidf_v1.joblib"],
    "rag": [RAG_DATA, ROOT / "data" / "documents" / "pdf" / "sops.pdf"],
}
DATASET = ROOT / "data" / "processed" / "classical_ml"


def headline(kind: str) -> str:
    """One line with the test result, read from the report the notebook wrote."""

    def load(name: str) -> dict:
        return json.loads((MODELS / name).read_text())

    try:
        if kind == "eta":
            t = load("eta_v1_report.json")["test"]
            return f"test MAE {t['MAE']:.1f} ticks, R² {t['R2']:.3f}"
        if kind == "late":
            t = load("late_risk_v1_report.json")["test"]
            return f"test F1 {t['F1']:.3f}, ROC-AUC {t['ROC-AUC']:.3f}"
        if kind == "demand":
            r = load("demand_v1_report.json")
            return f"test MAE {r['test_mae']} vs {r['test_baseline_mae']} (same hour last week)"
        if kind == "anomaly":
            r = load("anomaly_v1_report.json")
            return f"test F1 {r['test'][r['algorithm']]['F1']:.3f} ({r['algorithm']})"
        if kind == "breakdown":
            rows = load("demand_breakdown_v1_report.json")["test"]
            return ", ".join(f"{x['target']} {x['test MAE']}" for x in rows)
        if kind == "anomaly_dl":
            t = load("anomaly_dl_v1_report.json")["test"]
            return " · ".join(f"{k}: F1 {v['F1']:.3f}" for k, v in t.items())
        if kind == "demand_dl":
            s = load("demand_dl_v1_report.json")["summary"]
            return " · ".join(
                f"{k}: {v['test_MAE']}" for k, v in s.items() if "ensemble" in k or "v1" in k
            )
        if kind == "vision":
            t = load("vision_yolo_v1/evaluation.json")["test_official"]
            return " · ".join(f"{size} px mAP@0.5 {v['mAP50']:.3f}" for size, v in t.items())
        if kind == "nlp":
            s = load("nlp_baselines_report.json")["scores"]
            return " · ".join(
                f"{k.split(' |')[0].split(' (')[0]}: exact tool call {v['exact_tool_call']:.3f}"
                for k, v in s.items()
                if k.endswith("| test")
            )
        if kind == "rag":
            r = load("rag_v1.json")
            t = r["test_retrieval"][0]
            return (
                f"test hit@3 {t['hit@3']}, MRR {t['MRR']}, cite@1 {t['cite@1']}; "
                f"unanswerable refused {r['not_covered']['unanswerable_refused']}"
            )
        if kind == "nlp_dl":
            t = load("nlp_distilbert_v1/report.json")["test"]
            return " · ".join(
                f"{k}: exact tool call {v['exact_tool_call']:.3f}" for k, v in t.items()
            )
    except (OSError, KeyError, ValueError) as err:
        return f"(no report: {err})"
    return ""


def run(name: str, save: bool) -> bool:
    import nbformat
    from nbconvert.preprocessors import CellExecutionError, ExecutePreprocessor

    phase, notebook, outputs, kind = PIPELINES[name]
    missing = [p for p in NEEDS.get(name, []) if not p.exists()]
    if PIPELINES[name][0] in (3, 5) and name != "vision" and not DATASET.exists():
        missing.append(DATASET)
    if missing:
        print(f"✗ {name}: missing input {missing[0].relative_to(ROOT)}")
        if name.startswith("nlp"):
            print("  Generate the commands first: python scripts/generate_nlp_data.py")
        elif name == "rag":
            print("  Build the knowledge base first: python scripts/build_knowledge_base.py")
        elif name == "vision":
            print("  Train the detector on Colab first (notebooks/cloud/train_yolo_colab.ipynb).")
        else:
            print("  Generate the dataset first: python scripts/generate_data.py")
        return False

    path = NB / notebook
    print(f"▶ {name}: running {path.relative_to(ROOT)} (Phase {phase}) ...", flush=True)
    started = time.time()
    book = nbformat.read(path, as_version=4)
    try:
        ExecutePreprocessor(timeout=None, kernel_name="python3").preprocess(
            book, {"metadata": {"path": str(NB)}}
        )
    except CellExecutionError as err:
        print(f"✗ {name}: a cell failed\n{str(err)[-2000:]}")
        return False
    if save:
        nbformat.write(book, path)

    stale = [
        o for o in outputs if not (MODELS / o).exists() or (MODELS / o).stat().st_mtime < started
    ]
    minutes = (time.time() - started) / 60
    if stale:
        print(f"✗ {name}: the notebook ran ({minutes:.1f} min) but did not write {stale}")
        return False
    print(f"✓ {name}: {minutes:.1f} min · {headline(kind)}")
    return True


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--model", choices=sorted(PIPELINES))
    group.add_argument("--phase", type=int, choices=[3, 5, 6, 7])
    group.add_argument("--list", action="store_true", help="show the models and exit")
    parser.add_argument("--no-save", action="store_true", help="do not overwrite the notebook")
    args = parser.parse_args()

    if args.list:
        for name, (phase, notebook, outputs, kind) in PIPELINES.items():
            print(
                f"{name:17s} Phase {phase}  notebooks/{notebook:32s} -> models/{', '.join(outputs)}"
            )
            print(f"{'':17s} current: {headline(kind)}")
        print(
            "vision training   Phase 5  notebooks/cloud/train_yolo_colab.ipynb (Google Colab GPU)"
        )
        return

    names = [args.model] if args.model else [n for n, p in PIPELINES.items() if p[0] == args.phase]
    results = {name: run(name, save=not args.no_save) for name in names}
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
