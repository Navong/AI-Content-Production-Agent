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

import requests
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.types import Command
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from graph import graph
from state import initial_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

app = FastAPI(title="AI Content Production Agent")
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
    brief: str


class ApproveRequest(BaseModel):
    thread_id: str
    action: str  # "approve" | "reject" | "regenerate"


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


async def _stream_graph(inputs, cfg: dict, session_id: str):
    """Yield SSE dicts for every graph update chunk."""
    score_at_pause = 0
    iteration_at_pause = 0

    async for chunk in graph.astream(inputs, cfg, stream_mode="updates"):

        # ── HITL interrupt ────────────────────────────────────────────────
        if "__interrupt__" in chunk:
            p = chunk["__interrupt__"][0].value
            score_at_pause = p.get("score", 0)
            iteration_at_pause = p.get("iteration", 0)
            sessions[session_id]["status"] = "awaiting_approval"
            sessions[session_id]["score_at_pause"] = score_at_pause
            sessions[session_id]["iteration_at_pause"] = iteration_at_pause
            sessions[session_id]["image_at_pause"] = p.get("image_url", "")
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
                yield _sse({"event": "done", "status": status})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/runs")
def get_runs(limit: int = 50):
    return _read_runs(limit)


@app.get("/api/session/{thread_id}")
def get_session(thread_id: str):
    """Snapshot of one run, used by the 'Review in app' deep link from Slack.

    Sessions are in-memory, so this 404s if the backend restarted since the run
    paused (same constraint as the LangGraph checkpointer here).
    """
    s = sessions.get(thread_id)
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
    }


@app.post("/api/generate")
async def generate(body: GenerateRequest):
    thread_id = str(uuid4())
    cfg = _make_config(thread_id, body.brief)
    sessions[thread_id] = {
        "status": "running",
        "config": cfg,
        "brief": body.brief,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    async def stream():
        yield _sse({"event": "session", "thread_id": thread_id})
        try:
            async for evt in _stream_graph(initial_state(body.brief, thread_id), cfg, thread_id):
                yield evt
        except Exception as exc:
            logger.exception("graph error")
            yield _sse({"event": "error", "message": str(exc)})

    return EventSourceResponse(stream())


@app.post("/api/approve")
async def approve(body: ApproveRequest):
    session = sessions.get(body.thread_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    cfg = session["config"]

    async def stream():
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
# Slack interactive approval (Pillar 4: human-in-the-loop, from Slack)
# ---------------------------------------------------------------------------

def _verify_slack_signature(headers, body: bytes) -> bool:
    """Validate Slack's v0 request signature (HMAC-SHA256 over the raw body).

    https://api.slack.com/authentication/verifying-requests-from-slack
    """
    if not SLACK_SIGNING_SECRET:
        logger.warning("SLACK_SIGNING_SECRET not set — rejecting Slack action")
        return False
    ts = headers.get("x-slack-request-timestamp", "")
    sig = headers.get("x-slack-signature", "")
    if not ts or not sig:
        return False
    # Reject stale requests (replay-attack guard).
    try:
        if abs(time.time() - int(ts)) > 60 * 5:
            return False
    except ValueError:
        return False
    base = f"v0:{ts}:{body.decode('utf-8')}".encode("utf-8")
    digest = "v0=" + hmac.new(SLACK_SIGNING_SECRET.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig)


async def _drive_graph(inputs, cfg: dict, thread_id: str) -> str | None:
    """Run the graph until it pauses at the HITL gate or finishes.

    Returns the terminal status (e.g. "approved" / "reject") when the run ends,
    or None if it paused again (hitl_gate already posted a fresh Slack card).
    Mirrors _stream_graph's bookkeeping without the SSE plumbing.
    """
    async for chunk in graph.astream(inputs, cfg, stream_mode="updates"):
        if "__interrupt__" in chunk:
            p = chunk["__interrupt__"][0].value
            sessions[thread_id]["status"] = "awaiting_approval"
            sessions[thread_id]["score_at_pause"] = p.get("score", 0)
            sessions[thread_id]["iteration_at_pause"] = p.get("iteration", 0)
            sessions[thread_id]["image_at_pause"] = p.get("image_url", "")
            return None
        for node_name, updates in chunk.items():
            if node_name == "quality_eval" and isinstance(updates, dict):
                sessions[thread_id]["feedback_at_pause"] = updates.get(
                    "quality_feedback", ""
                )
            if (
                node_name == "hitl_gate"
                and isinstance(updates, dict)
                and updates.get("status")
            ):
                status = updates["status"]
                sessions[thread_id]["status"] = status
                _log_run(
                    thread_id=thread_id,
                    status=status,
                    final_score=sessions[thread_id].get("score_at_pause", 0),
                    iterations=sessions[thread_id].get("iteration_at_pause", 0),
                )
                return status
    return None


def _slack_update(response_url: str, text: str, blocks: list | None = None) -> None:
    """Replace the original Slack card with a result message (best-effort).

    `text` is always sent as the notification/fallback; `blocks` (when given)
    render the rich result card so the approved image stays visible.
    """
    if not response_url:
        return
    payload: dict = {"replace_original": True, "text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        requests.post(response_url, json=payload, timeout=10)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Slack response_url update failed: %s", exc)


def _result_card(summary: str, image_url: str = "") -> list:
    """A compact result card: a status line, optionally keeping the image."""
    blocks: list = [{"type": "section", "text": {"type": "mrkdwn", "text": summary}}]
    if image_url:
        blocks.append(
            {"type": "image", "image_url": image_url, "alt_text": "reviewed image"}
        )
    return blocks


async def _handle_slack_decision(
    thread_id: str, action: str, response_url: str, user: str
) -> None:
    """Resume (approve/reject) or kick off a fresh run (regenerate) for Slack."""
    try:
        if action == "regenerate":
            brief = sessions[thread_id]["brief"]
            new_tid = str(uuid4())
            new_cfg = _make_config(new_tid, brief)
            sessions[new_tid] = {
                "status": "running",
                "config": new_cfg,
                "brief": brief,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            status = await _drive_graph(initial_state(brief, new_tid), new_cfg, new_tid)
            if status is None:
                # New run paused at the gate → its own fresh card was just posted.
                summary = f"🔁 *Regenerated* (requested by @{user}) — see the new draft below."
            else:
                summary = f"🔁 Regenerate by @{user} — run ended with status *{status}*."
            _slack_update(response_url, summary, _result_card(summary))
            return

        cfg = sessions[thread_id]["config"]
        score = sessions[thread_id].get("score_at_pause", 0)
        image = sessions[thread_id].get("image_at_pause", "")
        status = await _drive_graph(Command(resume={"action": action}), cfg, thread_id)

        if action == "approve":
            summary = f"✅ *Approved* by @{user} — final score {score}/10."
            _slack_update(response_url, summary, _result_card(summary, image))
        elif action == "reject":
            summary = f"❌ *Rejected* by @{user} — score was {score}/10."
            _slack_update(response_url, summary, _result_card(summary))
        else:
            summary = f"*{action}* by @{user}. Run status: *{status}*."
            _slack_update(response_url, summary, _result_card(summary))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Slack decision error")
        _slack_update(response_url, f"⚠️ Couldn't process *{action}*: {exc}")


@app.post("/slack/actions")
async def slack_actions(request: Request):
    """Receive Block Kit button clicks, verify them, and drive the graph.

    Slack requires a response within 3s, so we acknowledge immediately (replacing
    the card) and finish the graph work in the background, updating the message
    via the payload's response_url when done.
    """
    raw = await request.body()
    if not _verify_slack_signature(request.headers, raw):
        raise HTTPException(status_code=403, detail="invalid Slack signature")

    form = parse_qs(raw.decode("utf-8"))
    payload_raw = form.get("payload", [None])[0]
    if not payload_raw:
        raise HTTPException(status_code=400, detail="missing payload")
    payload = json.loads(payload_raw)

    actions = payload.get("actions") or []
    if not actions:
        return JSONResponse({"text": "No action received."})

    action_id = actions[0].get("action_id", "")
    thread_id = actions[0].get("value", "")
    response_url = payload.get("response_url", "")
    user = (payload.get("user") or {}).get("username", "someone")

    # "open_app" is a URL button — Slack handles it client-side, no callback work.
    if action_id == "open_app":
        return JSONResponse({})

    if action_id not in ("approve", "reject", "regenerate"):
        return JSONResponse({"text": f"Unknown action: {action_id}"})

    if thread_id not in sessions:
        return JSONResponse(
            {
                "replace_original": True,
                "text": "⚠️ This run is no longer available (the server may have restarted).",
            }
        )

    # Acknowledge fast; do the graph work in the background.
    asyncio.create_task(
        _handle_slack_decision(thread_id, action_id, response_url, user)
    )

    pending = {
        "approve": "✅ Approving…",
        "reject": "❌ Rejecting…",
        "regenerate": "🔁 Regenerating…",
    }[action_id]
    return JSONResponse(
        {"replace_original": True, "text": f"{pending} (requested by @{user})"}
    )
