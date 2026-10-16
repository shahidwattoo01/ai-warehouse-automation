"""Run recording against a real PostgreSQL (skipped when the database is not reachable).

Records a short simulation, checks every table got sensible rows, then deletes the test run.
"""

import pytest
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.services.run_store import RunStore
from simulation.environment.engine import SimulationEngine

TABLES_PER_RUN = [
    "orders",
    "order_items",
    "robot_tasks",
    "robot_status",
    "robot_events",
    "inventory",
]


@pytest.fixture(scope="module")
def db_url() -> str:
    url = get_settings().database_url
    try:
        with create_engine(url).connect() as conn:
            conn.execute(text("SELECT 1 FROM simulation_runs LIMIT 1"))
    except Exception as exc:  # no server, wrong password, or not migrated
        pytest.skip(f"PostgreSQL not available: {str(exc).splitlines()[0]}")
    return url


def test_a_short_run_is_recorded_in_every_table(db_url):
    sim = SimulationEngine(seed=7, overrides={"faults": {"probability_per_hour": 20.0}})
    store = RunStore(db_url)
    store.start_run(sim)
    assert store.enabled and store.run_id, "start_run failed (seeded with another layout?)"
    run_id = store.run_id
    try:
        sim.start()
        for tick in range(400):
            store.collect(sim, sim.tick())
            if tick % 50 == 49:
                store.flush()
        store.end_run(sim)
        assert store.enabled, "a write failed and switched recording off"

        with create_engine(db_url).connect() as conn:
            counts = {
                t: conn.execute(
                    text(f"SELECT count(*) FROM {t} WHERE run_id = :r"), {"r": run_id}
                ).scalar()
                for t in TABLES_PER_RUN
            }
            run = conn.execute(
                text(
                    "SELECT total_ticks, metrics, ended_at FROM simulation_runs WHERE run_id = :r"
                ),
                {"r": run_id},
            ).one()
            completed = conn.execute(
                text("SELECT count(*) FROM robot_tasks WHERE run_id = :r AND status = 'COMPLETED'"),
                {"r": run_id},
            ).scalar()
            delivered = conn.execute(
                text(
                    "SELECT count(*) FROM orders WHERE run_id = :r AND delivered_tick IS NOT NULL"
                ),
                {"r": run_id},
            ).scalar()

        assert all(n > 0 for n in counts.values()), counts
        assert counts["inventory"] == len(sim.inventory.stock)
        assert counts["robot_status"] == 40 * 40  # 40 robots, sampled every 10 of 400 ticks
        assert run.total_ticks == 400 and run.ended_at is not None
        assert run.metrics["orders_completed"] == delivered == completed > 0
    finally:
        with create_engine(db_url).begin() as conn:  # leave the database as we found it
            conn.execute(text("DELETE FROM simulation_runs WHERE run_id = :r"), {"r": run_id})


def test_only_runs_with_a_silent_heartbeat_are_closed_on_next_start(db_url):
    crashed, live = RunStore(db_url), RunStore(db_url)
    crashed.start_run(SimulationEngine(seed=8))  # never end_run(): like a killed server
    live.start_run(SimulationEngine(seed=9))  # still recording (fresh heartbeat)
    with create_engine(db_url).begin() as conn:  # the crashed server went silent 10 min ago
        conn.execute(
            text(
                "UPDATE simulation_runs SET metrics = jsonb_build_object('heartbeat', "
                "now() - interval '10 minutes') WHERE run_id = :r"
            ),
            {"r": crashed.run_id},
        )
    fresh = RunStore(db_url)
    fresh.start_run(SimulationEngine(seed=10))
    ids = {"a": crashed.run_id, "b": live.run_id, "c": fresh.run_id}
    try:
        with create_engine(db_url).connect() as conn:
            rows = dict(
                conn.execute(
                    text(
                        "SELECT run_id::text, ended_at FROM simulation_runs "
                        "WHERE run_id IN (:a, :b)"
                    ),
                    ids,
                ).all()
            )
        by_id = {k.replace("-", ""): v for k, v in rows.items()}
        assert by_id[crashed.run_id] is not None  # abandoned: closed
        assert by_id[live.run_id] is None  # still alive: untouched
    finally:
        with create_engine(db_url).begin() as conn:
            conn.execute(text("DELETE FROM simulation_runs WHERE run_id IN (:a, :b, :c)"), ids)


def test_live_predictions_and_alerts_are_saved_with_their_outcome(db_url):
    from app.services.predictor import MODELS_DIR, Predictor

    if not (MODELS_DIR / "eta_v1.joblib").exists():
        pytest.skip("train notebooks/01-05 first")
    sim = SimulationEngine(seed=8, overrides={"faults": {"probability_per_hour": 4.0}})
    predictor = Predictor()
    predictor.attach(sim)
    store = RunStore(db_url)
    store.start_run(sim, predictor.versions)
    run_id = store.run_id
    try:
        sim.start()
        for _ in range(1300):  # past the first simulated hour (600 ticks), so demand is scored
            store.collect(sim, sim.tick())
            predictor.after_tick()
            store.add_predictions(*predictor.drain())
        store.end_run(sim)
        assert store.enabled, "a write failed and switched recording off"
        with create_engine(db_url).connect() as conn:
            by_model = dict(
                conn.execute(
                    text("""SELECT m.model_name, count(*) FROM predictions p
                            JOIN model_versions m USING (model_version_id)
                            WHERE p.run_id = :r GROUP BY m.model_name"""),
                    {"r": run_id},
                ).all()
            )
            eta = conn.execute(
                text("""SELECT output, actual FROM predictions p JOIN model_versions m
                        USING (model_version_id) WHERE p.run_id = :r AND m.model_name = 'eta'
                        LIMIT 1"""),
                {"r": run_id},
            ).one()
            alerts = conn.execute(
                text("SELECT count(*) FROM alerts WHERE run_id = :r AND type = 'ANOMALY'"),
                {"r": run_id},
            ).scalar()
        assert by_model.get("eta", 0) > 20 and by_model.get("late", 0) > 20
        assert by_model.get("demand") == 2  # hours 0 and 1, each with forecast and actual
        assert by_model.get("demand_breakdown") == 14  # 7 targets x 2 hours
        assert "eta_ticks" in eta.output and "duration_ticks" in eta.actual
        assert alerts > 0
    finally:
        with create_engine(db_url).begin() as conn:
            conn.execute(text("DELETE FROM simulation_runs WHERE run_id = :r"), {"r": run_id})
