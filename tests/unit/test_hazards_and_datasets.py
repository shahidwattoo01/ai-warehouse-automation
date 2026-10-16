"""Aisle closures, floor hazards, motor temperature, and the text datasets (NLP, RAG)."""

import sys
from pathlib import Path

from simulation.environment.engine import SimulationEngine
from simulation.environment.recorder import Recorder

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

LARGE = {
    "layout": "large",
    "ticks_per_hour": 600,
    "orders": {"arrival_prob_per_tick": 0.15},
    "faults": {"enabled": False},
    "hazards": {"enabled": False},
}


def _engine(seed: int = 4, **extra) -> SimulationEngine:
    engine = SimulationEngine(seed=seed, overrides={**LARGE, **extra})
    engine.start()
    return engine


def test_large_layout_has_52_numbered_aisles():
    engine = _engine()
    aisles = engine.layout.aisles
    assert len(aisles) == 52
    assert aisles[6].name == "Aisle 7" and aisles[6].zone_id == "ZONE_B" and aisles[6].y == 7
    assert {a.direction for a in aisles} == {"east", "west"}


def test_closed_aisle_is_never_entered_and_its_orders_wait():
    engine = _engine()
    for _ in range(100):
        engine.tick()
    closure = engine.hazards.close_random_aisle()
    assert closure is not None
    cells = set(closure.cells)
    for _ in range(400):
        engine.tick()
        if engine.time < closure.until:
            assert not any(r.position in cells for r in engine.robots.values())
            for task in engine.controller.tasks.values():
                assert not cells & set(task.stops)  # no order was sent into the closed aisle
    assert closure.aisle_id not in engine.hazards.closures  # reopened after its duration
    assert not cells & engine.layout.grid.closed


def test_floor_hazard_blocks_its_cell_until_cleared():
    engine = _engine()
    obstacle = engine.hazards.drop_random_hazard()
    assert obstacle is not None and obstacle.type in ("PACKAGE", "DEBRIS")
    assert obstacle.position in engine.layout.grid.closed
    events = []
    for _ in range(obstacle.until - engine.time + 2):
        events += engine.tick()
        if engine.time < obstacle.until:
            assert obstacle.position not in {r.position for r in engine.robots.values()}
    assert obstacle not in engine.obstacles
    assert obstacle.position not in engine.layout.grid.closed
    assert any(e.type.value == "HAZARD_CLEARED" for e in events)


def test_overheating_heats_throttles_and_stays_labelled_until_cool():
    engine = _engine()
    engine.faults.inject("R1", "overheating")
    peak = 0.0
    for _ in range(200):
        engine.tick()
        peak = max(peak, engine.robots["R1"].temperature)
    assert peak > 45  # far above the ~24 C of an idle robot (or ~39 C driving)
    for _ in range(600):
        engine.tick()
    assert engine.faults.label("R1") is None
    assert engine.robots["R1"].temperature < engine.thermal["throttle_at"] - 5


def test_recorder_tables_include_temperature_hazards_and_calendar():
    engine = SimulationEngine(
        seed=9,
        overrides={
            **LARGE,
            "hazards": {"enabled": True, "closures_per_hour": 6, "floor_hazards_per_hour": 12},
            "faults": {"enabled": True, "probability_per_hour": 2.0},
        },
    )
    recorder = Recorder(
        engine, "t", status_every=2, calendar={"date": "2026-09-07", "split": "train"}
    )
    engine.start()
    for _ in range(1200):
        engine.tick()
        recorder.after_tick()
    tables = recorder.tables()
    assert {"temperature", "task_elapsed", "aisle_id"} <= set(tables["robot_status"].columns)
    assert {"temperature_max", "stop_count"} <= set(tables["anomaly_windows"].columns)
    assert {"path_distance", "robot_speed", "closures_active", "date"} <= set(
        tables["tasks"].columns
    )
    demand = tables["demand_hourly"]
    cat = demand.filter(like="lines_cat_").to_numpy().sum()
    assert cat == demand.filter(like="lines_zone_").to_numpy().sum()  # every line has a zone
    assert "FLOOR" not in "|".join(tables["orders"]["zones"])
    hazards = tables["hazards"]
    assert {"AISLE_CLOSURE"} <= set(hazards["kind"]) and len(hazards) > 2
    assert (tables["tasks"]["path_distance"] >= tables["tasks"]["est_distance"]).all()


def test_nlp_messages_have_exact_entity_spans_and_tool_calls():
    import random

    from generate_nlp_data import INTENTS, Builder, T, bio, tool_calls

    builder = Builder(random.Random(1))
    for intent in INTENTS:
        for template in T[intent]:
            core, entities = builder.fill(template)
            text, entities = builder.noise(core, entities)
            for e in entities:
                assert text[e["start"] : e["end"]] == e["text"]
            tokens, tags = bio(text, entities)
            assert len(tokens) == len(tags)
            calls = tool_calls(intent, entities, core)
            assert (intent == "out_of_scope") == (calls == [])


def test_knowledge_base_questions_cite_real_sections():
    import yaml
    from build_knowledge_base import DOC_ORDER, DOCS, read_doc, sections

    known = set()
    for doc_id in DOC_ORDER:
        _, body = read_doc(DOCS / f"{doc_id}.md")
        known |= {f"{doc_id}#{s['section_id']}" for s in sections(doc_id, body)}
    questions = yaml.safe_load((DOCS / "eval" / "rag_questions.yaml").read_text(encoding="utf-8"))
    assert len(questions) >= 90
    for q in questions:
        assert all(src in known for src in q["sources"]), q["id"]
