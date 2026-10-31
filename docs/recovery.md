# Recovery, backups and failover

Backlog PR-17. Code:

* [`app/services/recovery.py`](../apps/backend/app/services/recovery.py): state snapshots.
* [`app/services/leader.py`](../apps/backend/app/services/leader.py): active/standby.
* [`scripts/backup_db.py`](../scripts/backup_db.py): database backups.
* [`docker-compose.ha.yml`](../docker-compose.ha.yml) and
  [`docker/nginx-ha.conf`](../docker/nginx-ha.conf): two backends behind a load balancer.

The platform keeps two kinds of state, and each is protected differently:

| State | Where | Protected by |
|---|---|---|
| The live warehouse: robots, orders, stock, WMS, safety, alert incidents, ERP outbox, event sequence | Memory of the active backend | Signed snapshots in `STATE_DIR`, restored at start-up |
| Users, refresh tokens, recorded runs, predictions, safety log, incidents | PostgreSQL | `pg_dump` backups with a restore test |

## Restart recovery

The active backend saves the whole warehouse every `SNAPSHOT_SECONDS` (30) while it changes, every
10 minutes while it stands still, and once more on a clean shutdown. `POST
/api/v1/simulation/snapshot` saves it on demand, for example before maintenance.

At start-up the newest snapshot is restored **paused**: an operator checks the floor before the
robots move again. Each snapshot holds:

* The simulation engine: robots, tasks, orders, WMS stock and documents, safety state, and the
  random generator, so a restored run continues exactly as it would have.
* Alert-centre incidents.
* The ERP connector's imports and outbox, and the mock ERP's own books.
* The platform-event sequence and replay buffer, so a subscriber's `after=` stays valid.

`GET /api/v1/simulation/recovery` shows the last save, what start-up restored, and this
instance's role.

* **How it is written:** the file is `MAGIC`, then an HMAC-SHA256, then a zlib-compressed pickle.
  The key is derived from `JWT_SECRET`. A file whose signature does not match is **never
  unpickled**, because unpickling can run code. A tampered or foreign file is renamed
  `.rejected` and the previous good one (`.prev`) is used. Without a fixed `JWT_SECRET`,
  recovery is off.
* **Safe writes:** writes go to a temporary file followed by a rename, so a crash mid-write leaves
  the last good file.
* **Cost:** taking the snapshot costs the event loop about 70 ms on the large layout (40 robots).
  Compressing and writing (about 400 KB) happen in a worker thread.
* **Recorded runs:** a restored backend opens a new recorded run in the database, starting at the
  restored tick.

**Measured:** the dev backend ran to tick 96 and was killed. After the restart it was at tick 89
(the last periodic save), paused, with its orders and robots in place.

## Database backups

```
python scripts/backup_db.py                      # backups/warehouse_ai_<time>.dump + .json
python scripts/backup_db.py --verify latest      # restore test
python scripts/backup_db.py --restore FILE --yes # back into DATABASE_URL (backend stopped)
```

* **Backup:** a backup is a `pg_dump` custom-format file plus a manifest. The manifest records the
  row count of every table, the Alembic version, the size and the SHA-256. The counts are read in
  the **same database snapshot** as the dump (`pg_export_snapshot`), so they describe exactly
  what is in the file, even while the platform keeps writing. The newest 14 backups are kept
  (`--keep`).
* **Restore test:** it checks the checksum, then starts a **temporary PostgreSQL server** (from
  the same installation, on localhost only), restores into it, and requires every table's row
  count and the Alembic version to match the manifest. Then it stops the server and deletes it.
  That means it needs no `CREATE DATABASE` right on the real server, and it rehearses what a
  real recovery does: restore onto another machine. `RESTORE_CHECK_URL` points it at a server
  instead.
* **Password:** it reaches the PostgreSQL tools only through `PGPASSWORD`. It is never printed or
  written to the manifest.
* **Schedule:** run both commands nightly, with cron or Windows Task Scheduler, and copy `backups/`
  to another machine or bucket. A backup that sits on the same disk does not protect against
  that disk failing.

**Measured:** 656,414 rows in 26 tables gave a 6.7 MB backup in 5.7 s. The restore test passed,
with every table identical, at Alembic 007, in 38 s.

## Active/standby behind a load balancer

The live warehouse is one simulation in one process, so two backends must never both run it.
With `HA_MODE=active-standby`:

* Every instance tries to take a **PostgreSQL advisory lock**. The holder is **active**: it
  restores the latest snapshot from the shared `STATE_DIR` and runs the loop.
* Every other instance is **standby**. It answers 503 to everything except `/health`, `/ready` and
  `/metrics`, closes live streams with code 1013, and retries the lock every 2 s.
* The lock belongs to a database session. When the active process dies or loses its database
  connection, PostgreSQL releases the lock and a standby takes over. An active instance that can
  no longer see its lock **steps down** immediately, without saving, so two instances never
  write at the same time.
* nginx (`docker/nginx-ha.conf`) sends each request on to the other backend when it gets a 503.
  A standby refuses before doing anything, so retrying a POST there is safe.

```
docker compose -f docker-compose.yml -f docker-compose.ha.yml up    # API on :8080
```

Logins work on either instance: tokens are signed with the shared `JWT_SECRET`, and refresh
tokens and users are stored in PostgreSQL.

**Failover drill** (two real backends, ports 8001 and 8002, shared state directory):

1. A became active and B became standby. B's API answered 503.
2. The warehouse ran on A, then A was killed outright, like a crash.
3. **B became active 1.7 s later.** It restored tick 14 (A had reached tick 16, so 1 s of
   simulated time was lost), paused, with all 12 robots.

## Metrics and alerts

`warehouse_instance_active`, `warehouse_state_snapshot_age_seconds`, `_bytes`,
`_capture_seconds`, `_failures_total`. `/ready` adds the `role` check (required) and the
`state_snapshot` check (reported only).

New alert rules: `StateSnapshotStale` (no save for 15 min on the active instance) and
`StateSnapshotFailing`.

## Tests

`apps/backend/tests/test_recovery.py` covers:

* A run with an incident, ERP imports and events is saved and restored. Engine state, KPIs,
  incidents, event sequence and ERP imports are identical, and the restored engine continues
  exactly like an untouched copy.
* A one-byte change is refused and the previous file is used.
* A file signed with another secret is not loaded.
* The snapshot API and its metrics.
* A standby answers 503.
* The leader lock against the real PostgreSQL: one holder; when that holder's session dies it
  steps down and the other takes over.
* The backup manifest check refuses a damaged file, and old backups are pruned.

## Not yet

* Snapshots go to one directory; copying them off-site (with the database backups) is up to the
  site.
* Docker was not available here, so the compose and nginx files have not run as containers. The
  failover drill ran the same code as two local processes.
* Running the warehouse across several active backends (sharding by zone or site) is a larger
  change (PR-06 scale, PR-33 multi-site).
