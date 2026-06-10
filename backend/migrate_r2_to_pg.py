"""One-time backfill: copy old R2 run snapshots into the Postgres `runs` table.

The dashboard reads Postgres-first (R2 only when Postgres is empty), so runs
created before Postgres existed are orphaned in R2. This idempotently upserts
each R2 snapshot into Postgres — safe to re-run (ON CONFLICT updates in place).

Usage (from backend/, with .env loaded and DATABASE_URL pointing at the target):
    python migrate_r2_to_pg.py
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("migrate")


def main() -> None:
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is not set — point it at the target Postgres.")

    import db as run_store
    from tools.r2_tool import list_runs

    run_store.init_runs_table()

    snaps = list_runs(limit=1000)
    if not snaps:
        log.info("No R2 snapshots found — nothing to migrate.")
        return

    migrated, skipped = 0, 0
    for snap in snaps:
        thread_id = snap.get("thread_id")
        if not thread_id:
            skipped += 1
            continue
        run_store.upsert_run(thread_id, snap)
        migrated += 1
        log.info("  ✓ %s  (%s)", thread_id, snap.get("status", "?"))

    log.info("Done — migrated %d run(s), skipped %d.", migrated, skipped)


if __name__ == "__main__":
    main()
