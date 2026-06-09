"""FastAPI entrypoint — SSE streaming + HITL approval + run logging.

Endpoints:
  GET  /health
  GET  /api/runs            → last N completed runs (from runs.jsonl)
  POST /api/generate        → streams node events as SSE; pauses at HITL gate
  POST /api/approve         → resumes paused graph, streams done event
  POST /slack/actions       → signature-verified Slack button callback; resumes
                              the paused graph (approve/reject) or starts a fresh
                              run (regenerate) in the background

Each run is logged to runs.jsonl on completion so the /dashboard page has
persistent history. LangSmith receives metadata tags (brief_length, project,
iterations_used, final_score) on every run for the observability pillar.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.types import Command
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from contextlib import asynccontextmanager

from graph import build_graph, graph as _default_graph
from state import initial_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

# Swapped to a Postgres-backed graph (durable checkpointer) at startup; falls back
# to the in-memory graph if DATABASE_URL is missing or setup fails.
GRAPH = _default_graph
DB_READY = False
_pg_pool = None


@asynccontextmanager
async def lifespan(_app: "FastAPI"):
    global GRAPH, DB_READY, _pg_pool
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            import db as run_store

            _pg_pool = AsyncConnectionPool(
                conninfo=db_url,
                min_size=1,
                max_size=10,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            )
            await _pg_pool.open()
            saver = AsyncPostgresSaver(_pg_pool)
            await saver.setup()
            GRAPH = build_graph(saver)
            run_store.init_runs_table()
            DB_READY = True
            logger.info("Postgres durable checkpointer + run store ready")
        except Exception as e:  # noqa: BLE001
            logger.warning("Postgres setup failed; using in-memory + R2: %s", e)
    else:
        logger.info("DATABASE_URL not set — using in-memory checkpointer + R2 snapshots")
    yield
    if _pg_pool is not None:
        try:
            await _pg_pool.close()
        except Exception:  # noqa: BLE001
            pass


app = FastAPI(title="AI Content Production Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session registry: thread_id -> {status, config, brief, started_at}
sessions: dict[str, dict] = {}

RUNS_FILE = Path(__file__).parent / "runs.jsonl"


# ---------------------------------------------------------------------------
# Run log helpers (Pillar 5: observability)
# ---------------------------------------------------------------------------

def _log_run(thread_id: str, status: str, final_score: int, iterations: int) -> None:
    """Append one completed-run record to runs.jsonl."""
    session = sessions.get(thread_id, {})
    record = {
        "thread_id": thread_id,
        "brief": session.get("brief", ""),
        "brief_length": len(session.get("brief", "")),
        "final_score": final_score,
        "iterations_used": iterations,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with RUNS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _read_runs(limit: int = 50) -> list[dict]:
    if not RUNS_FILE.exists():
        return []
    lines = RUNS_FILE.read_text(encoding="utf-8").strip().splitlines()
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return list(reversed(records))[:limit]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    brief: str  # text brief, or the product description in ad mode
    mode: str = "text"  # "text" | "ad"
    product_image_url: str = ""  # uploaded product photo (ad mode)


class ApproveRequest(BaseModel):
    thread_id: str
    action: str  # "approve" | "reject" | "regenerate"
    reviewer: str = "Studio"  # shown on the updated Slack card
    # The iteration the reviewer actually picked in the studio (may not be the
    # last one the agent generated). Overrides what the approved card shows.
    image: str = ""
    score: int | None = None


class CaptionRequest(BaseModel):
    thread_id: str


class PublishRequest(BaseModel):
    thread_id: str
    image: str = ""
    caption: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(payload: dict) -> dict:
    return {"data": json.dumps(payload)}


def _make_config(thread_id: str, brief: str) -> dict:
    """Build the LangGraph run config with LangSmith metadata (Pillar 5)."""
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": "content-production-run",
        "metadata": {
            "project": "content-production-agent",
            "brief_length": len(brief),
        },
        "tags": ["production", "content-agent"],
    }


# --- Durable run snapshots (R2) ---------------------------------------------
# sessions + the LangGraph checkpointer are in-memory, so a backend restart
# (incl. every auto-deploy) wipes paused runs. We persist a JSON snapshot per
# run to R2 so the review deep link and approval survive restarts. After a
# restart the graph itself can't be resumed, so approve/reject is finalized
# directly (see /api/approve).

_SNAPSHOT_KEYS = (
    "status", "brief", "mode", "product_image_url",
    "image_at_pause", "score_at_pause", "iteration_at_pause", "feedback_at_pause",
    "reviewer", "published_url", "published_caption", "started_at",
)


def _persist_session(thread_id: str) -> None:
    s = sessions.get(thread_id)
    if not s:
        return
    try:
        from tools.slack_tool import get_ts
        snap = {k: s.get(k) for k in _SNAPSHOT_KEYS}
        snap["slack_ts"] = get_ts(thread_id)
        import db as run_store
        if run_store.db_configured():
            run_store.upsert_run(thread_id, snap)
        else:
            from tools.r2_tool import put_json
            put_json(f"sessions/{thread_id}.json", snap)
    except Exception as e:  # noqa: BLE001
        logger.warning("persist session failed (non-fatal): %s", e)


def _get_session(thread_id: str) -> dict | None:
    """In-memory session, or rehydrate it from the durable store after a restart."""
    s = sessions.get(thread_id)
    if s:
        return s
    snap = None
    try:
        import db as run_store
        if run_store.db_configured():
            snap = run_store.get_run(thread_id)
        else:
            from tools.r2_tool import get_json
            snap = get_json(f"sessions/{thread_id}.json")
    except Exception:  # noqa: BLE001
        snap = None
    if not snap:
        return None
    snap["_restored"] = True  # graph state is gone — can't resume, finalize directly
    sessions[thread_id] = snap
    try:
        from tools.slack_tool import restore
        restore(
            thread_id, snap.get("slack_ts", ""), snap.get("image_at_pause", ""),
            snap.get("score_at_pause", 0), snap.get("brief", ""),
            snap.get("reviewer", "Studio"),
        )
    except Exception:  # noqa: BLE001
        pass
    return snap


async def _stream_graph(inputs, cfg: dict, session_id: str):
    """Yield SSE dicts for every graph update chunk."""
    score_at_pause = 0
    iteration_at_pause = 0

    async for chunk in GRAPH.astream(inputs, cfg, stream_mode="updates"):

        # ── HITL interrupt ────────────────────────────────────────────────
        if "__interrupt__" in chunk:
            p = chunk["__interrupt__"][0].value
            score_at_pause = p.get("score", 0)
            iteration_at_pause = p.get("iteration", 0)
            sessions[session_id]["status"] = "awaiting_approval"
            sessions[session_id]["score_at_pause"] = score_at_pause
            sessions[session_id]["iteration_at_pause"] = iteration_at_pause
            sessions[session_id]["image_at_pause"] = p.get("image_url", "")
            _persist_session(session_id)  # durable snapshot (survives restarts)
            yield _sse({
                "event": "awaiting_approval",
                "image_url": p.get("image_url", ""),
                "score": score_at_pause,
                "brief": p.get("brief", ""),
                "iteration": iteration_at_pause,
            })
            return

        # ── Worker node updates ───────────────────────────────────────────
        for node_name, updates in chunk.items():
            if not isinstance(updates, dict):
                continue

            if node_name == "prompt_engineer":
                yield _sse({
                    "event": "node_done",
                    "node": "prompt_engineer",
                    "prompt": updates.get("refined_prompt", ""),
                    "iteration": updates.get("iteration", 0),
                })

            elif node_name == "image_gen" and updates.get("generated_url"):
                yield _sse({
                    "event": "image_ready",
                    "url": updates["generated_url"],
                })

            elif node_name == "quality_eval":
                sessions[session_id]["feedback_at_pause"] = updates.get(
                    "quality_feedback", ""
                )
                yield _sse({
                    "event": "score_ready",
                    "score": updates.get("quality_score", 0),
                    "feedback": updates.get("quality_feedback", ""),
                })

            elif node_name == "hitl_gate" and updates.get("status"):
                status = updates["status"]
                sessions[session_id]["status"] = status
                # Log the completed run
                _log_run(
                    thread_id=session_id,
                    status=status,
                    final_score=sessions[session_id].get("score_at_pause", 0),
                    iterations=sessions[session_id].get("iteration_at_pause", 0),
                )
                _persist_session(session_id)  # snapshot the terminal state
                # Update the Slack card in place (bot-token mode only).
                if status in ("approved", "rejected", "regenerated"):
                    try:
                        from tools.slack_tool import update_on_decision
                        update_on_decision(
                            thread_id=session_id,
                            status=status,
                            image_url=sessions[session_id].get("image_at_pause", ""),
                            score=sessions[session_id].get("score_at_pause", 0),
                            brief=sessions[session_id].get("brief", ""),
                            reviewer=sessions[session_id].get("reviewer", "Studio"),
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Slack card update failed (non-fatal): %s", e)
                yield _sse({"event": "done", "status": status})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def api_config():
    """Feature flags the studio reads on load (e.g. show 'Post to X' only when configured)."""
    from tools.x_tool import x_configured
    return {"x_enabled": x_configured(), "durable": DB_READY}


@app.get("/api/runs")
def get_runs(limit: int = 48):
    """Durable run history for the dashboard (Postgres → R2 → local jsonl)."""
    import db as run_store
    if run_store.db_configured():
        rows = run_store.list_runs(limit)
        if rows:
            return rows
    from tools.r2_tool import list_runs
    snaps = list_runs(limit)
    if snaps:
        return [
            {
                "thread_id": s.get("thread_id", ""),
                "brief": s.get("brief", ""),
                "mode": s.get("mode", "text"),
                "status": s.get("status", ""),
                "score": s.get("score_at_pause", 0),
                "iterations": s.get("iteration_at_pause", 0),
                "image": s.get("image_at_pause", ""),
                "published_url": s.get("published_url", ""),
                "timestamp": s.get("started_at", ""),
            }
            for s in snaps
        ]
    return _read_runs(limit)


@app.get("/api/session/{thread_id}")
def get_session(thread_id: str):
    """Snapshot of one run, used by the 'Review in app' deep link from Slack.

    Rehydrated from the R2 snapshot if it's no longer in memory (e.g. after a
    backend restart), so review deep links survive restarts.
    """
    s = _get_session(thread_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "thread_id": thread_id,
        "status": s.get("status", ""),
        "brief": s.get("brief", ""),
        "image": s.get("image_at_pause", ""),
        "score": s.get("score_at_pause", 0),
        "iteration": s.get("iteration_at_pause", 0),
        "feedback": s.get("feedback_at_pause", ""),
        "published_url": s.get("published_url", ""),
    }


@app.post("/api/upload")
async def upload_product(file: UploadFile = File(...)):
    """Store an uploaded product photo in R2 and return its public URL (ad mode)."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image too large (max 12MB)")
    from tools.r2_tool import upload_bytes
    url = upload_bytes(
        data,
        file.content_type or "image/png",
        thread_id="uploads",
        label=str(uuid4())[:8],
    )
    if not url:
        raise HTTPException(status_code=400, detail="R2 storage is not configured")
    return {"url": url}


@app.post("/api/generate")
async def generate(body: GenerateRequest):
    thread_id = str(uuid4())
    cfg = _make_config(thread_id, body.brief)
    mode = "ad" if (body.mode == "ad" and body.product_image_url) else "text"
    sessions[thread_id] = {
        "status": "running",
        "config": cfg,
        "brief": body.brief,
        "mode": mode,
        "product_image_url": body.product_image_url,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    async def stream():
        yield _sse({"event": "session", "thread_id": thread_id})
        try:
            state = initial_state(body.brief, thread_id, mode, body.product_image_url)
            async for evt in _stream_graph(state, cfg, thread_id):
                yield evt
        except Exception as exc:
            logger.exception("graph error")
            yield _sse({"event": "error", "message": str(exc)})

    return EventSourceResponse(stream())


def _finalize_decision(thread_id: str, action: str) -> str:
    """Finalize a decision without resuming the graph (used when the run was
    rehydrated from R2 after a restart, so the checkpointer state is gone)."""
    status = (
        "approved" if action in ("approve", "approved")
        else "regenerated" if action == "regenerate"
        else "rejected"
    )
    s = sessions[thread_id]
    s["status"] = status
    _log_run(thread_id, status, s.get("score_at_pause", 0), s.get("iteration_at_pause", 0))
    _persist_session(thread_id)
    try:
        from tools.slack_tool import update_on_decision
        update_on_decision(
            thread_id, status, s.get("image_at_pause", ""), s.get("score_at_pause", 0),
            s.get("brief", ""), s.get("reviewer", "Studio"),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Slack card update failed (non-fatal): %s", e)
    return status


@app.post("/api/approve")
async def approve(body: ApproveRequest):
    session = _get_session(body.thread_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    session["reviewer"] = body.reviewer or "Studio"
    # Honor the reviewer's chosen iteration for the approved Slack card / log.
    if body.image:
        session["image_at_pause"] = body.image
    if body.score is not None:
        session["score_at_pause"] = body.score

    async def stream():
        # Idempotency: already decided elsewhere → just report it.
        if session.get("status") in ("approved", "rejected", "regenerated"):
            yield _sse({"event": "done", "status": session["status"]})
            return
        # With a durable checkpointer (Postgres) the paused graph survives restarts,
        # so we can truly resume even a rehydrated run. Without it, a rehydrated run
        # has no graph state → finalize the decision directly.
        if not DB_READY and (session.get("_restored") or not session.get("config")):
            yield _sse({"event": "done", "status": _finalize_decision(body.thread_id, body.action)})
            return
        cfg = session.get("config") or _make_config(body.thread_id, session.get("brief", ""))
        try:
            async for evt in _stream_graph(
                Command(resume={"action": body.action}), cfg, body.thread_id
            ):
                yield evt
        except Exception as exc:
            logger.exception("resume error")
            yield _sse({"event": "error", "message": str(exc)})

    return EventSourceResponse(stream())


# ---------------------------------------------------------------------------
# Publish to X (Pillar 2: another tool — distribution)
# ---------------------------------------------------------------------------

def _publish_to_x(thread_id: str, image: str = "", caption: str = "") -> dict:
    """Post the approved image + caption to X; idempotent per run.

    Falls back to the paused image and a Claude-generated caption when those
    aren't supplied. Records the tweet URL on the session and (best-effort)
    updates the Slack card.
    """
    from tools.x_tool import generate_caption, post_tweet

    s = _get_session(thread_id) or {}
    if s.get("published_url"):
        return {"url": s["published_url"], "tweet_id": "", "already": True}

    img = image or s.get("image_at_pause", "")
    cap = caption or generate_caption(s.get("brief", ""))
    result = post_tweet(img, cap)

    s["published_url"] = result["url"]
    s["published_caption"] = cap
    _persist_session(thread_id)
    try:
        from tools.slack_tool import mark_posted_to_x
        mark_posted_to_x(thread_id, result["url"])
    except Exception as e:  # noqa: BLE001
        logger.warning("Slack posted-update failed (non-fatal): %s", e)
    return result


@app.post("/api/caption")
def api_caption(body: CaptionRequest):
    """Return a Claude-generated tweet caption for this run's brief."""
    s = _get_session(body.thread_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    from tools.x_tool import generate_caption
    return {"caption": generate_caption(s.get("brief", ""))}


@app.post("/api/publish")
def api_publish(body: PublishRequest):
    """Post the approved image + caption to X. Returns {url}."""
    s = _get_session(body.thread_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    from tools.x_tool import x_configured
    if not x_configured():
        raise HTTPException(status_code=400, detail="X is not configured on the server")
    try:
        return _publish_to_x(body.thread_id, body.image, body.caption)
    except Exception as exc:  # noqa: BLE001
        logger.exception("publish error")
        raise HTTPException(status_code=502, detail=f"X post failed: {exc}")


# ---------------------------------------------------------------------------
# Slack interactivity — only the "Post to X" button does work (Pillar 4 + 2)
# ---------------------------------------------------------------------------

def _verify_slack_signature(headers, body: bytes) -> bool:
    """Validate Slack's v0 request signature (HMAC-SHA256 over the raw body)."""
    if not SLACK_SIGNING_SECRET:
        logger.warning("SLACK_SIGNING_SECRET not set — rejecting Slack action")
        return False
    ts = headers.get("x-slack-request-timestamp", "")
    sig = headers.get("x-slack-signature", "")
    if not ts or not sig:
        return False
    try:
        if abs(time.time() - int(ts)) > 60 * 5:
            return False
    except ValueError:
        return False
    base = f"v0:{ts}:{body.decode('utf-8')}".encode("utf-8")
    digest = "v0=" + hmac.new(SLACK_SIGNING_SECRET.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig)


async def _slack_post_to_x(thread_id: str, response_url: str, user: str) -> None:
    """Background: publish to X for a Slack 'Post to X' click, then report."""
    import requests as _rq
    try:
        result = await asyncio.to_thread(_publish_to_x, thread_id)
        text = f"🐦 Posted to X by @{user} — {result['url']}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Slack post-to-x error")
        text = f"⚠️ Couldn't post to X: {exc}"
    try:
        _rq.post(response_url, json={"text": text, "replace_original": False}, timeout=10)
    except Exception:  # noqa: BLE001
        pass


@app.post("/slack/actions")
async def slack_actions(request: Request):
    """Handle Block Kit button clicks.

    Only "post_to_x" does work (verified via signature → publish in background).
    URL buttons (open_app / download / view_in_studio) just ACK with 200.
    """
    raw = await request.body()
    form = parse_qs(raw.decode("utf-8"))
    payload_raw = form.get("payload", [None])[0]
    if not payload_raw:
        return JSONResponse({})  # not an interaction we handle

    if not _verify_slack_signature(request.headers, raw):
        raise HTTPException(status_code=403, detail="invalid Slack signature")

    payload = json.loads(payload_raw)
    actions = payload.get("actions") or []
    if not actions:
        return JSONResponse({})
    action_id = actions[0].get("action_id", "")
    thread_id = actions[0].get("value", "")
    response_url = payload.get("response_url", "")
    user = (payload.get("user") or {}).get("username", "someone")

    if action_id != "post_to_x":
        return JSONResponse({})  # URL buttons — nothing to do

    if _get_session(thread_id) is None:
        return JSONResponse(
            {"replace_original": False, "text": "⚠️ This run is no longer available."}
        )

    from tools.x_tool import x_configured
    if not x_configured():
        return JSONResponse(
            {"replace_original": False, "text": "⚠️ X publishing isn't configured on the server."}
        )

    asyncio.create_task(_slack_post_to_x(thread_id, response_url, user))
    return JSONResponse({"replace_original": False, "text": f"🐦 Posting to X… (requested by @{user})"})
