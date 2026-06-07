"""FastAPI entrypoint — SSE streaming + HITL approval + run logging.

Endpoints:
  GET  /health
  GET  /api/runs            → last N completed runs (from runs.jsonl)
  POST /api/generate        → streams node events as SSE; pauses at HITL gate
  POST /api/approve         → resumes paused graph, streams done event

Each run is logged to runs.jsonl on completion so the /dashboard page has
persistent history. LangSmith receives metadata tags (brief_length, project,
iterations_used, final_score) on every run for the observability pillar.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from graph import graph
from state import initial_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


@app.post("/api/generate")
async def generate(body: GenerateRequest):
    thread_id = str(uuid4())
    cfg = {
        "configurable": {"thread_id": thread_id},
        # LangSmith metadata (Pillar 5: observability)
        "run_name": "content-production-run",
        "metadata": {
            "project": "content-production-agent",
            "brief_length": len(body.brief),
        },
        "tags": ["production", "content-agent"],
    }
    sessions[thread_id] = {
        "status": "running",
        "config": cfg,
        "brief": body.brief,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    async def stream():
        yield _sse({"event": "session", "thread_id": thread_id})
        try:
            async for evt in _stream_graph(initial_state(body.brief), cfg, thread_id):
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
