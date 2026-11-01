"""Evaluate the agent on the 92 simulator scenarios (Phase 8; docs/phase8_agents.md).

    python scripts/evaluate_agents.py                  # offline planner (no API key needed)
    python scripts/evaluate_agents.py --type late_order --show
    python scripts/evaluate_agents.py --planner claude # needs LLM_PROVIDER=anthropic, LLM_API_KEY

Writes reports/agents_eval_<planner>.json and .md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "backend")]

from ai.agents.evaluate import evaluate_one, load_scenarios, summarise  # noqa: E402
from ai.agents.planner import OfflinePlanner, make_planner  # noqa: E402


def knowledge_base():
    from ai.rag.pipeline import KnowledgeBase

    kb = KnowledgeBase.load(db=None)
    return kb.ask


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--planner", choices=["offline", "claude"], default="offline")
    ap.add_argument("--type", help="only this scenario type")
    ap.add_argument("--show", action="store_true", help="print every answer next to the reference")
    a = ap.parse_args()
    if a.planner == "claude":
        from app.core.config import get_settings

        s = get_settings()
        planner = make_planner(s.llm_provider, s.llm_api_key, s.llm_model)
        if planner.name != "claude":
            raise SystemExit("Claude is not configured: set LLM_PROVIDER=anthropic and LLM_API_KEY")
    else:
        planner = OfflinePlanner()
    scenarios = [s for s in load_scenarios() if not a.type or s["type"] == a.type]
    print("loading the knowledge base ...", flush=True)
    ask = knowledge_base()
    began, rows = time.perf_counter(), []
    for s in scenarios:
        row = evaluate_one(s, planner, ask)
        rows.append(row)
        mark = "ok  " if row["success"] else "FAIL"
        failed = [k for k, v in row["checks"].items() if not v] + row["forbidden_called"]
        print(f"{mark} {row['id']:34s} {' '.join(row['tools'])}  {failed or ''}", flush=True)
        if a.show:
            print(f"     agent:     {row['answer']}\n     reference: {row['reference']}")
    summary = summarise(rows)
    summary["planner"], summary["seconds"] = planner.name, round(time.perf_counter() - began)
    name = "agents_eval_" + ("claude" if a.planner == "claude" else "offline")
    out = ROOT / "reports" / name
    out.with_suffix(".json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, default=str), encoding="utf-8"
    )
    o = summary["overall"]
    lines = [
        f"# Agent evaluation · {planner.name}",
        "",
        f"{o['scenarios']} scenarios, {o['replayed_exactly']} replayed to the exact state.",
        "",
        "| Type | Scenarios | Task success | Required tools | Forbidden calls | Within budget "
        "| Avg steps |",
        "|---|---|---|---|---|---|---|",
    ]
    for t, v in [*summary["by_type"].items(), ("**all**", o)]:
        lines.append(
            f"| {t} | {v['scenarios']} | {v['task_success']:.0%} | {v['required_tools']:.0%} "
            f"| {v['forbidden_calls']} | {v['within_budget']:.0%} | {v['avg_steps']} |"
        )
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
