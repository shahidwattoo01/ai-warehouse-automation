"""PostgreSQL backups with a restore test (backlog PR-17; docs/recovery.md).

    python scripts/backup_db.py                     # back up to backups/ (keeps the last 14)
    python scripts/backup_db.py --verify latest     # restore the newest backup on a temporary
                                                    # PostgreSQL server, compare with its manifest
    python scripts/backup_db.py --restore FILE --yes   # put a backup back into DATABASE_URL

A backup is a `pg_dump` custom-format file plus a manifest: the row count of every table, the
Alembic version and the file's SHA-256. The counts are taken in the same database snapshot the
dump reads (pg_export_snapshot), so a restore test can demand exact equality even while the
platform keeps writing. A backup nobody has restored is only a hope: run --verify on a schedule.

The password comes from DATABASE_URL and is handed to the PostgreSQL tools through PGPASSWORD;
it is never printed or written to the manifest.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "backend"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

BACKUP_DIR = ROOT / "backups"
WINDOWS_BIN = Path("C:/Program Files/PostgreSQL")


def database_url() -> str:
    from app.core.config import get_settings

    return get_settings().database_url


def tool(name: str) -> str:
    """pg_dump / pg_restore from PATH, PG_BIN, or a standard Windows install."""
    if os.environ.get("PG_BIN"):
        return str(Path(os.environ["PG_BIN"]) / name)
    found = shutil.which(name)
    if found:
        return found
    for version in sorted(WINDOWS_BIN.glob("*"), reverse=True):
        exe = version / "bin" / f"{name}.exe"
        if exe.exists():
            return str(exe)
    raise SystemExit(f"{name} not found: install the PostgreSQL client tools or set PG_BIN")


def pg_args(url) -> tuple[list[str], dict]:
    args = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username]
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    return args, env


def tables(conn) -> list[str]:
    rows = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    )
    return [r[0] for r in rows]


def counts(conn) -> dict[str, int]:
    return {t: conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one() for t in tables(conn)}


def alembic_version(conn) -> str | None:
    try:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def backup(out_dir: Path, keep: int) -> Path:
    url = make_url(database_url())
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dump = out_dir / f"{url.database}_{stamp}.dump"
    args, env = pg_args(url)
    db = create_engine(url)
    began = time.perf_counter()
    with db.connect() as conn:
        # One snapshot for the counts and the dump: the manifest describes exactly the file.
        conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        snapshot = conn.execute(text("SELECT pg_export_snapshot()")).scalar_one()
        rows = counts(conn)
        version = alembic_version(conn)
        subprocess.run(
            [tool("pg_dump"), *args, "-d", url.database, "-Fc", "-Z", "6",
             f"--snapshot={snapshot}", "-f", str(dump)],
            env=env, check=True,
        )  # fmt: skip
        conn.rollback()
    manifest = {
        "database": url.database,
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "alembic_version": version,
        "tables": rows,
        "total_rows": sum(rows.values()),
        "bytes": dump.stat().st_size,
        "sha256": sha256(dump),
        "seconds": round(time.perf_counter() - began, 1),
    }
    dump.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        f"backup {dump.name}: {manifest['total_rows']:,} rows in {len(rows)} tables, "
        f"{manifest['bytes'] / 1e6:.1f} MB, {manifest['seconds']} s"
    )
    prune(out_dir, url.database, keep)
    return dump


def prune(out_dir: Path, name: str, keep: int) -> None:
    """Keep the newest `keep` backups of this database (dump and manifest together)."""
    dumps = sorted(out_dir.glob(f"{name}_*.dump"))
    for old in dumps[: max(0, len(dumps) - keep)]:
        old.unlink()
        old.with_suffix(".json").unlink(missing_ok=True)
        print(f"removed old backup {old.name}")


def latest(out_dir: Path) -> Path:
    dumps = sorted(out_dir.glob("*.dump"))
    if not dumps:
        raise SystemExit(f"no backups in {out_dir}")
    return dumps[-1]


def restore_into(dump: Path, url, create: bool) -> None:
    args, env = pg_args(url)
    if create:
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
        admin.dispose()
    subprocess.run(
        [tool("pg_restore"), *args, "-d", url.database, "--no-owner", "--no-privileges",
         "--exit-on-error",
         *([] if create else ["--clean", "--if-exists"]), str(dump)],
        env=env, check=True,
    )  # fmt: skip


class ScratchServer:
    """A throw-away PostgreSQL server for the restore test: a new cluster in a temporary
    directory, on localhost only, removed afterwards. Like a real recovery drill it restores onto
    a separate server, and it needs no CREATE DATABASE right on the production one."""

    def __init__(self, port: int = 55432) -> None:
        self.port = port
        self.dir = Path(tempfile.mkdtemp(prefix="wai_restore_"))
        self.data = self.dir / "data"

    def __enter__(self):
        quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        subprocess.run(
            [tool("initdb"), "-D", str(self.data), "-U", "postgres", "-A", "trust",
             "-E", "UTF8", "--no-instructions"],
            check=True, **quiet,
        )  # fmt: skip
        opts = f"-p {self.port} -c listen_addresses=localhost"
        subprocess.run(
            [tool("pg_ctl"), "-D", str(self.data), "-o", opts, "-l", str(self.dir / "log.txt"),
             "-w", "start"],
            check=True, **quiet,
        )  # fmt: skip
        return make_url(f"postgresql+psycopg://postgres@localhost:{self.port}/restore_check")

    def __exit__(self, *exc) -> None:
        subprocess.run(
            [tool("pg_ctl"), "-D", str(self.data), "-m", "fast", "-w", "stop"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        shutil.rmtree(self.dir, ignore_errors=True)


def verify(dump: Path) -> bool:
    """Restore into a scratch server (or RESTORE_CHECK_URL), compare with the manifest."""
    manifest = json.loads(dump.with_suffix(".json").read_text(encoding="utf-8"))
    problems = []
    if sha256(dump) != manifest["sha256"]:
        problems.append("file checksum differs from the manifest (damaged or changed)")
    began = time.perf_counter()
    if not problems:
        given = os.environ.get("RESTORE_CHECK_URL")
        with contextlib.nullcontext(make_url(given)) if given else ScratchServer() as scratch:
            restore_into(dump, scratch, create=True)
            db = create_engine(scratch)
            with db.connect() as conn:
                got, version = counts(conn), alembic_version(conn)
            db.dispose()
        if version != manifest["alembic_version"]:
            problems.append(f"alembic {version} != {manifest['alembic_version']}")
        for table, n in manifest["tables"].items():
            if got.get(table) != n:
                problems.append(f"{table}: {got.get(table)} rows restored, {n} backed up")
    seconds = round(time.perf_counter() - began, 1)
    if problems:
        print(f"RESTORE TEST FAILED for {dump.name}:")
        for p in problems:
            print(f"  - {p}")
        return False
    print(
        f"restore test passed for {dump.name}: {len(manifest['tables'])} tables, "
        f"{manifest['total_rows']:,} rows identical, alembic {manifest['alembic_version']}, "
        f"restored in {seconds} s"
    )
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=BACKUP_DIR)
    ap.add_argument("--keep", type=int, default=14, help="backups to keep (default 14)")
    ap.add_argument("--verify", metavar="FILE", help="restore test of FILE or 'latest'")
    ap.add_argument("--restore", metavar="FILE", help="restore FILE into DATABASE_URL")
    ap.add_argument("--yes", action="store_true", help="confirm --restore (replaces the data)")
    a = ap.parse_args()
    if a.verify:
        dump = latest(a.dir) if a.verify == "latest" else Path(a.verify)
        sys.exit(0 if verify(dump) else 1)
    if a.restore:
        if not a.yes:
            raise SystemExit("--restore replaces the database's data: stop the backend, add --yes")
        dump = latest(a.dir) if a.restore == "latest" else Path(a.restore)
        restore_into(dump, make_url(database_url()), create=False)
        print(f"restored {dump.name}; start the backend again")
        return
    backup(a.dir, a.keep)


if __name__ == "__main__":
    main()
