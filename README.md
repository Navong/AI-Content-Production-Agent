# AI Content Production Agent

A LangGraph supervisor system that takes a creative brief and autonomously runs
prompt engineering → image generation → quality evaluation → human approval,
fully traced in LangSmith. Built as a working prototype of a generative-content
pipeline.

## The 5 production-agent pillars

| Pillar | Where |
|---|---|
| Orchestrator | `backend/agents/supervisor.py` — pure router over shared state |
| Tool layer | `backend/tools/` — Replicate (SDXL), Claude Vision, Slack |
| Memory | `backend/state.py` — `GraphState` TypedDict with an additive `history` |
| Human-in-the-loop | `backend/agents/hitl.py` — native LangGraph `interrupt()` + checkpointer |
| Observability | LangSmith tracing (env-driven, on from Day 1) |

## Key design decisions

1. **Current models.** Claude **Opus 4.8** (`claude-opus-4-8`) for Vision quality
   scoring, **Sonnet 4.6** (`claude-sonnet-4-6`) for prompt rewriting.
2. **Native HITL.** The approval pause uses LangGraph's `interrupt()` + a
   checkpointer and resumes via `Command(resume=...)` keyed by `thread_id` — not
   a hand-rolled session dict, so it survives restarts (swap MemorySaver →
   SqliteSaver).
3. **Pure router.** `route()` only reads state and returns the next node name;
   all state changes (including the retry iteration bump) happen inside nodes.
4. **Slack is notify-only.** Interactive button round-trips need a full Slack app
   with an interactivity Request URL; the approve/reject decision flows through
   the Next.js UI instead.

## Run it (Day 1)

### Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env          # then fill in keys (LangSmith optional for the smoke test)
python smoke_test.py            # runs the graph end-to-end with stubs
uvicorn main:app --reload       # serves /health
```

### Frontend
```bash
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

## Build plan

- **Day 1 (done):** scaffold — state, graph skeleton, stub nodes/tools, LangSmith wiring, smoke test, frontend shell.
- **Day 2:** implement the three tools (Replicate, Claude Vision w/ structured outputs, Slack notify).
- **Day 3:** real agent logic + retry loop.
- **Day 4:** FastAPI SSE + Next.js live progress + approve/reject.
- **Day 5:** observability dashboard, README polish, deploy.
