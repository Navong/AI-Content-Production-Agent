"""FastAPI entrypoint.

Day 1: health check + graph wiring only. The SSE streaming endpoint
(/api/generate) and the approve endpoint (/api/approve -> Command(resume=...))
land on Day 4.

Run: uvicorn main:app --reload
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()  # loads ANTHROPIC_API_KEY, LANGSMITH_*, etc. before graph import

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI Content Production Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# TODO(day4): POST /api/generate -> stream node events as SSE (sse-starlette)
# TODO(day4): POST /api/approve  -> graph.invoke(Command(resume={"action": ...}),
#             {"configurable": {"thread_id": session_id}})
