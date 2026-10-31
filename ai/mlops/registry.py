"""Model versions and which one is in production (backlog PR-19).

Version 1 of each model is what the notebooks trained (models/, in git). Retrained versions are
written by the platform itself to data/mlops/ (not in git), with their report and reference
profile; data/mlops/registry.json records every version, its status and the promotion history:

    candidate ──gate passed──► production ──replaced──► archived
        └────gate failed─────► rejected        ▲
                                               └─ rollback makes an archived version production

Writes are atomic (temp file + rename), so a crash never leaves half a registry.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "models"
STATE_DIR = ROOT / "data" / "mlops"
# model -> files of version 1 (written by notebooks/01 and 02)
V1 = {
    "eta": ("eta_v1.joblib", "eta_v1_report.json", "eta_v1_reference.json"),
    "late": ("late_risk_v1.joblib", "late_risk_v1_report.json", "late_risk_v1_reference.json"),
}


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class Registry:
    def __init__(self, state_dir: Path = STATE_DIR, models_dir: Path = MODELS_DIR) -> None:
        self.dir = Path(state_dir)
        self.models_dir = Path(models_dir)
        self.path = self.dir / "registry.json"
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            data = {}
        for model, (file, report, reference) in V1.items():
            if model not in data:
                rep = self.models_dir / report
                test = json.loads(rep.read_text())["test"] if rep.exists() else {}
                data[model] = {
                    "production": "v1",
                    "versions": [{
                        "version": "v1", "status": "production", "created": None,
                        "file": f"models/{file}", "report": f"models/{report}",
                        "reference": f"models/{reference}", "trained_on": "dataset v3",
                        "test": test, "history": [{"at": None, "event": "trained by notebook"}],
                    }],
                }  # fmt: skip
        return data

    def save(self) -> None:
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    # ----- reading ---------------------------------------------------------------------------
    def versions(self, model: str) -> list[dict]:
        return self.data[model]["versions"]

    def get(self, model: str, version: str) -> dict:
        for v in self.versions(model):
            if v["version"] == version:
                return v
        raise KeyError(f"{model} has no version {version}")

    def production(self, model: str) -> dict:
        return self.get(model, self.data[model]["production"])

    def path_of(self, entry: dict, key: str = "file") -> Path:
        return ROOT / entry[key]

    def next_version(self, model: str) -> str:
        return f"v{max(int(v['version'][1:]) for v in self.versions(model)) + 1}"

    # ----- changing --------------------------------------------------------------------------
    def add_candidate(self, model: str, entry: dict) -> dict:
        first = {"at": now(), "event": "trained", "reason": entry.get("reason")}
        entry = {**entry, "status": "candidate", "created": now(), "history": [first]}
        self.versions(model).append(entry)
        self.save()
        return entry

    def _mark(self, entry: dict, status: str, event: str, by: str | None) -> None:
        entry["status"] = status
        entry["history"].append({"at": now(), "event": event, "by": by})

    def promote(self, model: str, version: str, by: str | None = None) -> dict:
        entry = self.get(model, version)
        if entry["status"] == "rejected":
            raise ValueError(f"{model} {version} failed its tests and cannot be promoted")
        old = self.production(model)
        if old is entry:
            return entry
        self._mark(old, "archived", f"replaced by {version}", by)
        self._mark(entry, "production", "promoted", by)
        self.data[model]["production"] = version
        self.save()
        return entry

    def reject(self, model: str, version: str, reason: str) -> None:
        entry = self.get(model, version)
        self._mark(entry, "rejected", f"rejected: {reason}", "gate")
        self.save()

    def rollback(self, model: str, by: str | None = None) -> dict:
        """Back to the most recent earlier version that was in production."""
        current = self.production(model)
        earlier = [
            v for v in self.versions(model)
            if v is not current and v["status"] == "archived"
        ]  # fmt: skip
        if not earlier:
            raise ValueError(f"{model}: no earlier production version to go back to")
        target = max(earlier, key=lambda v: int(v["version"][1:]))
        return self.promote(model, target["version"], by)
