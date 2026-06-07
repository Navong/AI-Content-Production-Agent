# AI Content Production Agent

A LangGraph supervisor system that takes a creative brief and autonomously runs
**prompt engineering → image generation → quality evaluation → human approval**,
fully traced in LangSmith. Built as a working prototype of a generative-content
production pipeline.

> 스위트앤데이터의 이미지 생성 워크플로우에서 영감을 받아 만든 프로젝트입니다.
> LangGraph Supervisor 패턴으로 프롬프트 엔지니어링 → 이미지 생성 → 품질 평가 → 인간 승인까지
> 전 과정을 자율적으로 처리하는 에이전트 시스템입니다. LangSmith로 전체 실행 흐름을 추적합니다.

---

## Architecture

```
User brief
    │
    ▼
┌──────────────────────────────────────────────────────┐
│                  Agent system boundary               │
│                                                      │
│          Supervisor node (LangGraph)                 │
│      plans steps · routes · decides retry/done       │
│           │              │             │             │
│    ┌──────┘         ┌────┘        ┌────┘             │
│    ▼                ▼             ▼                  │
│ PromptEngineer   ImageGen    QualityEval             │
│ (sonnet-4-6)    (FLUX dev)   (opus-4-8)              │
│    └──────────────────────────────┘                  │
│                    │                                 │
│         TypedDict GraphState (memory)                │
│   brief · prompt · url · score · history             │
│                    │                                 │
│            HITL gate node                            │
│        interrupt() + checkpointer                    │
│       Slack notify + UI approve/reject               │
└──────────────────────────────────────────────────────┘
    │
    ▼
Approved image package
(URL · metadata · prompt log · score)
```

### Routing logic

```
quality_score >= 8              → hitl_gate → END
quality_score < 8, iteration < 3 → prompt_engineer (retry with feedback)
iteration >= 3                   → hitl_gate (force human decision)
```

---

## The 5 production-agent pillars

| Pillar | Component | What it does |
|---|---|---|
| **Orchestrator** | `supervisor.py` + `route()` | Pure router — LLM decides next node, never mutates state |
| **Tool layer** | `replicate_tool` · `claude_vision_tool` · `slack_tool` | 3 real API integrations with retry, structured outputs, error handling |
| **Memory** | `GraphState` TypedDict + additive `history` reducer | Full session state shared across all nodes; every iteration logged |
| **Human-in-the-loop** | `hitl_gate` + LangGraph `interrupt()` + `MemorySaver` | Durable pause; resumes via `Command(resume=...)` on `thread_id` |
| **Observability** | LangSmith tracing + `/dashboard` page | Full trace per run: node sequence, tool latency, cost, score history |

---

## Tech stack

| Layer | Tech | Why |
|---|---|---|
| Orchestration | LangGraph `StateGraph` | Supervisor pattern + conditional edges + native HITL |
| LLM (prompt) | `claude-sonnet-4-6` | Cheap/fast for prompt rewriting |
| LLM (vision) | `claude-opus-4-8` | Best-in-class vision + structured outputs for scoring |
| Image gen | FLUX dev (Replicate) | ~2.5s/image, excellent prompt adherence |
| HITL | LangGraph `interrupt()` + MemorySaver | Durable pause — no hand-rolled session dict |
| Slack | Incoming webhook (notify-only) | Card posts on quality threshold hit |
| Observability | LangSmith | Full trace + cost per run + metadata tags |
| API | FastAPI + SSE | Streaming agent progress to frontend |
| Frontend | Next.js 15 + Tailwind | Live progress UI, approve/reject, run dashboard |
| Deploy | Railway (backend) + Vercel (frontend) | Free tier, live demo URL |

---

## Key design decisions

1. **Current models.** `claude-opus-4-8` for Vision scoring, `claude-sonnet-4-6`
   for prompt rewriting. Using two models routes the expensive model only to the
   node that needs it — a real production-cost signal.

2. **Native HITL.** The approval pause uses LangGraph's `interrupt()` +
   `MemorySaver`. Resumes via `Command(resume={"action": ...})` on the same
   `thread_id`. Durable across restarts if you swap `MemorySaver` → `SqliteSaver`.

3. **Pure router.** `route()` only reads state and returns the next node name.
   All state changes (including the retry iteration bump) happen inside nodes.

4. **Base64 Vision.** The Vision scorer fetches the image bytes and sends them as
   base64 instead of a URL source — avoids robots.txt blocks and handles
   Replicate's signed/expiring delivery URLs.

5. **Slack notify-only.** Interactive button round-trips need a full Slack app
   with an interactivity Request URL. The card links back to the Next.js UI;
   approve/reject flows through `/api/approve → Command(resume=...)`.

---

## Project structure

```
content-production-agent/
├── backend/
│   ├── main.py                   # FastAPI: /health, /api/generate, /api/approve, /api/runs
│   ├── graph.py                  # LangGraph StateGraph + MemorySaver
│   ├── state.py                  # TypedDict GraphState + initial_state()
│   ├── smoke_test.py             # End-to-end CLI test (real APIs)
│   ├── test_tools.py             # Isolated tool tests
│   ├── runs.jsonl                # Persistent run log (appended on completion)
│   ├── requirements.txt
│   ├── Procfile                  # Railway deploy
│   ├── railway.toml
│   ├── runtime.txt
│   ├── .env.example
│   ├── agents/
│   │   ├── supervisor.py         # Pure router (route function)
│   │   ├── prompt_engineer.py    # brief → SDXL/FLUX prompt (claude-sonnet-4-6)
│   │   ├── image_gen.py          # Calls replicate_tool, appends history
│   │   ├── quality_eval.py       # Scores via claude_vision_tool (claude-opus-4-8)
│   │   └── hitl.py               # interrupt() + Slack notify
│   └── tools/
│       ├── replicate_tool.py     # FLUX dev via Replicate API + retry
│       ├── claude_vision_tool.py # Claude Vision + structured outputs + base64 fetch
│       └── slack_tool.py         # Slack Block Kit webhook (notify-only)
├── frontend/
│   └── app/
│       ├── page.tsx              # Brief input + live SSE progress + HITL controls
│       └── dashboard/page.tsx    # Run history + score distribution + stats
├── vercel.json                   # Vercel monorepo config
└── README.md
```

---

## Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- API keys: Anthropic, Replicate, LangSmith (free tier)
- Optional: Slack incoming webhook URL

### Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # fill in your keys

# Verify everything works (real API calls, ~30s)
python smoke_test.py

# Start the server
uvicorn main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

### Frontend

```bash
cd frontend
npm install
# Set backend URL (already done — NEXT_PUBLIC_API_URL=http://localhost:8000)
npm run dev
# → http://localhost:3000
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | claude-sonnet-4-6 + claude-opus-4-8 |
| `REPLICATE_API_TOKEN` | Yes | FLUX dev image generation |
| `LANGSMITH_API_KEY` | Yes | Run tracing + dashboard |
| `LANGSMITH_TRACING` | Yes | Set to `true` |
| `LANGSMITH_PROJECT` | Yes | e.g. `content-production-agent` |
| `SLACK_WEBHOOK_URL` | No | Incoming webhook for HITL notify card |
| `APP_URL` | No | Your deployed app URL (in Slack card link) |

---

## How it works

1. **Submit a brief** — the frontend POSTs to `/api/generate` and opens an SSE stream.
2. **PromptEngineer** — `claude-sonnet-4-6` converts the brief into a precise FLUX
   generation prompt with style tags. On retry, the previous quality critique is
   folded in.
3. **ImageGen** — calls Replicate (FLUX dev) in ~2.5s. Result URL + metadata
   appended to `history[]`.
4. **QualityEval** — `claude-opus-4-8` fetches the image (base64), scores it 1–10
   with structured output: composition, style match, issues, suggested fix.
5. **Route** — score ≥ 8 → HITL gate; score < 8 and iteration < 3 → retry with
   the `suggested_fix`; iteration ≥ 3 → force HITL.
6. **HITL gate** — `interrupt()` pauses the graph. Slack card fires (if configured).
   The frontend shows Approve / Regenerate / Reject.
7. **Resume** — clicking Approve POSTs `{"action": "approve"}` to `/api/approve`,
   which calls `Command(resume=...)` on the `thread_id`. The graph completes.
8. **Run logged** — score, iterations, status, timestamp appended to `runs.jsonl`
   and visible at `/dashboard`.

---

## Demo briefs

| Brief | Expected path |
|---|---|
| `K-pop idol portrait, dreamy pastel background, ultra-detailed, studio lighting` | Score 8+ first try → clean happy path |
| `something cool for a fashion brand` | Score low → 1-2 retries → improves |
| `make a good picture` | Max 3 iterations → force HITL regardless of score |

---

## Deploy

### Backend → Railway

1. Push repo to GitHub
2. New Railway project → "Deploy from GitHub repo"
3. Set root directory: `backend/`
4. Add all env vars from `.env.example`
5. Railway auto-detects `Procfile` and starts `uvicorn`

### Frontend → Vercel

1. New Vercel project → import same GitHub repo
2. Set root directory: `frontend/`
3. Add `NEXT_PUBLIC_API_URL` = your Railway backend URL
4. Deploy — Vercel auto-detects Next.js

If deploying as a monorepo from the root, update the `rewrites` URL in
`vercel.json` with your Railway backend URL.

---

## LangSmith observability

Every run is traced end-to-end under the `content-production-agent` project.
Each trace shows:
- Full node sequence (supervisor → prompt_engineer → image_gen → quality_eval
  → hitl_gate interrupted → hitl_gate resumed)
- Per-node input/output
- Tool call latency
- Total token cost
- Metadata tags: `brief_length`, `iterations_used`, `final_score`

Screenshot your LangSmith trace dashboard — it's the single strongest proof
of production-level thinking in the project.
