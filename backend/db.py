"""Postgres run/session store (durable history + rehydration).

Separate from the LangGraph checkpointer (which uses AsyncPostgresSaver for the
agent's graph state). This stores the per-run *snapshot* — status, brief, mode,
chosen image, score, published tweet, slack ts, etc. — so the dashboard,
"Review in app" deep links, and approve-after-restart all survive restarts.

Sync (psycopg) on its own small pool, so it can be called from both sync
endpoints and async stream handlers without await plumbing. Everything degrades
to a no-op when DATABASE_URL isn't set (the app then uses the R2 fallback).
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_pool = None


def db_configured() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        _pool = ConnectionPool(
            conninfo=os.environ["DATABASE_URL"],
            min_size=1,
            max_size=4,
            kwargs={"autocommit": True},
        )
    return _pool


def init_runs_table() -> None:
    if not db_configured():
        return
    with _get_pool().connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                thread_id     TEXT PRIMARY KEY,
                brief         TEXT,
                mode          TEXT,
                status        TEXT,
                score         INTEGER,
                iteration     INTEGER,
                image         TEXT,
                published_url TEXT,
                started_at    TIMESTAMPTZ DEFAULT now(),
                updated_at    TIMESTAMPTZ DEFAULT now(),
                data          JSONB
            )
            """
        )
    logger.info("runs table ready")


def upsert_run(thread_id: str, snap: dict) -> None:
    """Insert/update a run's snapshot. `snap` is the full session dict."""
    if not db_configured():
        return
    try:
        with _get_pool().connection() as conn:
            conn.execute(
                """
                INSERT INTO runs (thread_id, brief, mode, status, score, iteration,
                                  image, published_url, updated_at, data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
                ON CONFLICT (thread_id) DO UPDATE SET
                    brief = EXCLUDED.brief, mode = EXCLUDED.mode,
                    status = EXCLUDED.status, score = EXCLUDED.score,
                    iteration = EXCLUDED.iteration, image = EXCLUDED.image,
                    published_url = EXCLUDED.published_url,
                    updated_at = now(), data = EXCLUDED.data
                """,
                (
                    thread_id,
                    snap.get("brief", ""),
                    snap.get("mode", "text"),
                    snap.get("status", ""),
                    snap.get("score_at_pause", 0),
                    snap.get("iteration_at_pause", 0),
                    snap.get("image_at_pause", ""),
                    snap.get("published_url", ""),
                    json.dumps(snap),
                ),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("upsert_run failed (non-fatal): %s", e)


def get_run(thread_id: str) -> dict | None:
    """Return the full snapshot dict for a run, or None."""
    if not db_configured():
        return None
    try:
        with _get_pool().connection() as conn:
            row = conn.execute(
                "SELECT data FROM runs WHERE thread_id = %s", (thread_id,)
            ).fetchone()
            return row[0] if row else None  # JSONB → dict
    except Exception as e:  # noqa: BLE001
        logger.warning("get_run failed: %s", e)
        return None


def list_runs(limit: int = 60) -> list[dict]:
    """Most-recent runs for the dashboard (one indexed query)."""
    if not db_configured():
        return []
    try:
        with _get_pool().connection() as conn:
            rows = conn.execute(
                """
                SELECT thread_id, brief, mode, status, score, iteration,
                       image, published_url, started_at
                FROM runs ORDER BY updated_at DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "thread_id": r[0],
                "brief": r[1] or "",
                "mode": r[2] or "text",
                "status": r[3] or "",
                "score": r[4] or 0,
                "iterations": r[5] or 0,
                "image": r[6] or "",
                "published_url": r[7] or "",
                "timestamp": r[8].isoformat() if r[8] else "",
            }
            for r in rows
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("list_runs failed: %s", e)
        return []
