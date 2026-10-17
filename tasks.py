"""Cross-platform task runner (works on Windows, macOS and Linux).

Usage:  python tasks.py <task>
Tasks:  up, down, backend, frontend, test, lint, migrate, seed, data, experiments
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "apps" / "backend"
FRONTEND = ROOT / "apps" / "frontend"
PY = sys.executable
NPM = "npm.cmd" if sys.platform == "win32" else "npm"

TASKS: dict[str, tuple[list[str], Path]] = {
    "up": (["docker", "compose", "up", "--build"], ROOT),
    "down": (["docker", "compose", "down"], ROOT),
    "backend": ([PY, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], BACKEND),
    "frontend": ([NPM, "run", "dev"], FRONTEND),
    "test": ([PY, "-m", "pytest", "-q"], ROOT),
    "lint": ([PY, "-m", "ruff", "check", "."], ROOT),
    "migrate": ([PY, "-m", "alembic", "upgrade", "head"], BACKEND),
    "seed": ([PY, "scripts/seed.py"], ROOT),  # layout from configs/simulation.yaml (large)
    "data": ([PY, "scripts/generate_data.py", "--runs", "50"], ROOT),
    "experiments": ([PY, "scripts/run_experiments.py"], ROOT),  # all Phase 4 experiments
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        raise SystemExit(1)
    cmd, cwd = TASKS[sys.argv[1]]
    raise SystemExit(subprocess.call(cmd, cwd=cwd))


if __name__ == "__main__":
    main()
