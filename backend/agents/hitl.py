"""HITL gate node (Pillar 4: human-in-the-loop).

Uses LangGraph's native `interrupt()`: the graph pauses here and the call to
`graph.invoke(...)` returns with an `__interrupt__` payload. The run resumes when
the caller invokes the graph again with `Command(resume={"action": ...})` on the
same `thread_id`. This is durable (backed by the checkpointer) — no hand-rolled
in-memory session dict.

Slack is notify-only by default: an incoming webhook can POST a card, but
interactive button clicks need a configured Slack app with an interactivity
Request URL. The actual approve/reject decision flows through the Next.js UI,
which calls /api/approve -> Command(resume=...).
"""
from __future__ import annotations

from langgraph.types import interrupt

from state import GraphState

# from tools.slack_tool import send_approval_request  # wired on Day 2


def hitl_gate(state: GraphState) -> dict:
    # TODO(day2): send_approval_request(state["generated_url"], state["quality_score"],
    #             state["brief"], state.get("iteration", 0))  # notify-only

    decision = interrupt(
        {
            "kind": "approval",
            "image_url": state.get("generated_url"),
            "score": state.get("quality_score"),
            "brief": state.get("brief"),
            "iteration": state.get("iteration", 0),
        }
    )

    # `decision` is whatever the caller passed to Command(resume=...).
    action = (decision or {}).get("action", "approved")
    status = "approved" if action in ("approve", "approved") else action
    return {"status": status}
