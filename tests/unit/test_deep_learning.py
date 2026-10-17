"""Phase 5 deep learning: inputs are built the same way in training and live, networks save and
load exactly, training learns, and demand windows never contain the hour they forecast.

Everything uses small synthetic data, so the tests run without the dataset or trained models.
"""

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from ai.deep_learning import anomaly, demand  # noqa: E402
from ai.deep_learning.live import LiveDemandNet, fault_channels  # noqa: E402

STATUSES = ["MOVING", "IDLE", "DELIVERING", "FAULT", "CHARGING"]


def telemetry(n: int = 14, seed: int = 0) -> pd.DataFrame:
    """One robot's raw readings (every 2 ticks), as in robot_status.parquet."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "robot_id": "R1",
            "tick": np.arange(n) * anomaly.STATUS_EVERY,
            "status": rng.choice(STATUSES, n),
            "moved": rng.choice([0.0, 0.5, 1.0], n),
            "battery": np.round(80 - np.cumsum(rng.uniform(0, 1, n)), 2),
            "temperature": np.round(30 + rng.normal(0, 2, n), 2),
            "route_len": rng.integers(0, 30, n),
            "blocked_ticks": rng.integers(0, 4, n),
            "task_elapsed": rng.integers(0, 200, n),
            "zone_congestion": np.round(rng.uniform(0, 1, n), 3),
            "load": rng.integers(0, 2, n),
        }
    )


def test_live_fault_inputs_equal_training_inputs():
    """Training/serving skew guard: the LSTM must see the same numbers live as in training."""
    df = telemetry()
    trained, _ = anomaly._channels(df)  # (robots, readings, channels), as notebook 07
    samples = [
        (
            r.moved,
            r.status,
            r.route_len,
            r.battery,
            r.temperature,
            r.blocked_ticks,
            r.task_elapsed,
            r.zone_congestion,
            False,
            r.load,
        )
        for r in df.itertuples()
    ]  # live_predictor.after_tick sample order
    end = len(samples)
    window = samples[end - anomaly.STEPS : end]
    live = fault_channels(window, samples[end - anomaly.STEPS - 1])
    np.testing.assert_allclose(live, trained[0, end - anomaly.STEPS : end], atol=1e-5)


def test_first_reading_of_a_run_has_no_step():
    df = telemetry()
    trained, _ = anomaly._channels(df)
    c = {name: i for i, name in enumerate(anomaly.CHANNELS)}
    for step in ("battery_step", "temperature_step", "route_step"):
        assert trained[0, 0, c[step]] == 0.0


def test_build_sequences_cuts_the_window_ending_at_tick_end(tmp_path):
    df = telemetry(n=20).assign(run_id="day_1", fault_label="none")
    status = tmp_path / "status.parquet"
    df.to_parquet(status)
    keys = pd.DataFrame(
        {"run_id": ["day_1", "day_1"], "robot_id": ["R1", "R1"], "tick_end": [18, 38]}
    )
    seqs = anomaly.build_sequences(status, keys, tmp_path / "seqs.npy")
    assert seqs.shape == (2, anomaly.STEPS, len(anomaly.CHANNELS))
    battery = anomaly.CHANNELS.index("battery")
    np.testing.assert_allclose(seqs[1, :, battery], df["battery"].to_numpy()[10:20], atol=1e-5)


def test_standardizer_matches_numpy():
    x = np.random.default_rng(1).normal(5, 3, (500, 10, 4)).astype(np.float32)
    scale = anomaly.Standardizer.fit(x, chunk=64)
    flat = x.reshape(-1, 4)
    np.testing.assert_allclose(scale.mean, flat.mean(0), rtol=1e-4)
    np.testing.assert_allclose(scale.std, flat.std(0), rtol=1e-4)


def test_lstm_learns_a_simple_time_pattern():
    """Faulty windows have a falling 'moved' signal; the LSTM must learn to rank them first."""
    rng = np.random.default_rng(0)
    n = 1200
    x = rng.normal(0, 1, (n, anomaly.STEPS, len(anomaly.CHANNELS))).astype(np.float32)
    y = (rng.random(n) < 0.3).astype(np.float32)
    x[y == 1, :, 0] -= np.linspace(0, 3, anomaly.STEPS, dtype=np.float32)
    scale = anomaly.Standardizer.fit(x[:900])
    model = anomaly.LSTMClassifier(len(anomaly.CHANNELS), hidden=16)
    anomaly.train_classifier(model, x[:900], y[:900], x[900:], y[900:], scale, epochs=4, batch=128)
    from sklearn.metrics import average_precision_score

    assert average_precision_score(y[900:], anomaly.predict_proba(model, x[900:], scale)) > 0.9


def test_saved_network_predicts_exactly_like_the_original(tmp_path):
    x = (
        np.random.default_rng(2)
        .normal(0, 1, (8, anomaly.STEPS, len(anomaly.CHANNELS)))
        .astype(np.float32)
    )
    scale = anomaly.Standardizer.fit(x)
    model = anomaly.LSTMClassifier(len(anomaly.CHANNELS), hidden=8)
    path = tmp_path / "lstm.pt"
    anomaly.save_bundle(
        path,
        model,
        "LSTM",
        {"n_channels": len(anomaly.CHANNELS), "hidden": 8},
        scale,
        0.6,
        anomaly.CHANNELS,
    )
    loaded, loaded_scale, bundle = anomaly.load_bundle(path)
    assert bundle["threshold"] == 0.6 and bundle["inputs"] == anomaly.CHANNELS
    np.testing.assert_allclose(
        anomaly.predict_proba(loaded, x, loaded_scale),
        anomaly.predict_proba(model, x, scale),
        atol=1e-6,
    )


# ----- demand ------------------------------------------------------------------------------------
def hourly(hours: int = 400) -> pd.DataFrame:
    t = pd.date_range("2026-09-07", periods=hours, freq="h")
    df = pd.DataFrame(
        {
            "timestamp": t,
            "hour_of_day": t.hour,
            "day_of_week": t.dayofweek,
            "is_weekend": t.dayofweek >= 5,
            "is_promo_day": False,
        }
    )
    df["orders"] = 50 + 30 * np.sin(2 * np.pi * df["hour_of_day"] / 24)
    return demand.calendar(df)


def test_history_window_ends_one_hour_before_the_forecast_hour():
    df = hourly()
    rows = np.array([demand.HISTORY, 300])
    hist, target = demand.history_windows(df, rows, (0.0, 1.0))
    assert hist.shape == (2, demand.HISTORY, len(demand.STEP_FEATURES))
    assert target.shape == (2, len(demand.TARGET_FEATURES))
    for i, row in enumerate(rows):
        assert hist[i, -1, 0] == pytest.approx(
            df["orders"][row - 1]
        )  # previous hour, never the target
    with pytest.raises(AssertionError):
        demand.history_windows(df, np.array([demand.HISTORY - 1]), (0.0, 1.0))


@pytest.mark.parametrize("arch", ["LSTM", "Transformer"])
def test_live_demand_forecast_equals_the_offline_network(tmp_path, arch):
    """The live forecaster rebuilds the inputs itself; it must give the notebook's prediction."""
    df = hourly()
    y_scale = (50.0, 20.0)
    n_step, n_target = len(demand.STEP_FEATURES), len(demand.TARGET_FEATURES)
    torch.manual_seed(0)
    model = (
        demand.DemandLSTM(n_step, n_target, hidden=32)
        if arch == "LSTM"
        else demand.DemandTransformer(n_step, n_target)
    )
    path = tmp_path / "demand.pt"
    torch.save(
        {
            "arch": arch,
            "state_dict": model.state_dict(),
            "history": demand.HISTORY,
            "step_features": demand.STEP_FEATURES,
            "target_features": demand.TARGET_FEATURES,
            "features": [],
            "y_scale": y_scale,
            "feature_mean": [],
            "feature_std": [],
        },
        path,
    )
    net = LiveDemandNet(path, tmp_path / "missing_report.json")

    row = 300
    offline = demand.predict(model, demand.history_windows(df, np.array([row]), y_scale), y_scale)[
        0
    ]
    past = range(row - demand.HISTORY, row)
    live = net.forecast(
        [float(df["orders"][h]) for h in past],
        [
            {
                "hour": int(df["hour_of_day"][h]),
                "is_weekend": float(df["is_weekend"][h]),
                "is_promo_day": float(df["is_promo_day"][h]),
            }
            for h in past
        ],
        {
            "hour": int(df["hour_of_day"][row]),
            "day_of_week": int(df["day_of_week"][row]),
            "is_weekend": float(df["is_weekend"][row]),
            "is_promo_day": float(df["is_promo_day"][row]),
        },
        {},
    )
    assert live == pytest.approx(float(offline), abs=1e-3)


def test_transformer_reads_the_week_in_12_hour_patches():
    model = demand.DemandTransformer(len(demand.STEP_FEATURES), len(demand.TARGET_FEATURES))
    assert model.position.shape[0] == demand.HISTORY // 12
    out = model(
        torch.zeros(3, demand.HISTORY, len(demand.STEP_FEATURES)),
        torch.zeros(3, len(demand.TARGET_FEATURES)),
    )
    assert out.shape == (3,)
