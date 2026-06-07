"""FastAPI entrypoint — SSE streaming + HITL approval.

Endpoints:
  GET  /health
  POST /api/generate  → streams node events as SSE while the graph runs;
                        pauses at HITL gate and sends `awaiting_approval`
  POST /api/approve   → resumes the paused graph via Command(resume=...)
                        and streams the final `done` event

Sessions are kept in an in-memory dict keyed by thread_id (MemorySaver
backs the graph checkpoints; swap to SqliteSaver for cross-restart durability).
"""
from __future__ import annotations

import json
import logging
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

# In-memory session registry: thread_id -> {"status": str, "config": dict}
sessions: dict[str, dict] = {}


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


async def _stream_graph(inputs, cfg: dict):
    """Async generator: yield SSE dicts for every graph update chunk."""
    async for chunk in graph.astream(inputs, cfg, stream_mode="updates"):

        # ── HITL interrupt ────────────────────────────────────────────────
        if "__interrupt__" in chunk:
            p = chunk["__interrupt__"][0].value
            sessions[cfg["configurable"]["thread_id"]]["status"] = "awaiting_approval"
            yield _sse({
                "event": "awaiting_approval",
                "image_url": p.get("image_url", ""),
                "score": p.get("score", 0),
                "brief": p.get("brief", ""),
                "iteration": p.get("iteration", 0),
            })
            return  # graph is paused; /api/approve resumes it

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
                # Resume leg of hitl_gate (after Command(resume=...))
                status = updates["status"]
                sessions[cfg["configurable"]["thread_id"]]["status"] = status
                yield _sse({"event": "done", "status": status})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/generate")
async def generate(body: GenerateRequest):
    thread_id = str(uuid4())
    cfg = {"configurable": {"thread_id": thread_id}}
    sessions[thread_id] = {"status": "running", "config": cfg}

    async def stream():
        # First event: send thread_id so the frontend can reference it for approval.
        yield _sse({"event": "session", "thread_id": thread_id})
        try:
            async for evt in _stream_graph(initial_state(body.brief), cfg):
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
            async for evt in _stream_graph(Command(resume={"action": body.action}), cfg):
                yield evt
        except Exception as exc:
            logger.exception("resume error")
            yield _sse({"event": "error", "message": str(exc)})

    return EventSourceResponse(stream())
