"""HITL gate node (Pillar 4: human-in-the-loop).

Fires a Slack notification card, then pauses the graph via LangGraph's native
interrupt(). The run resumes when the caller invokes the graph again with
Command(resume={"action": "approve" | "reject" | "regenerate"}) on the same
thread_id.
"""
from __future__ import annotations

import os

from langgraph.types import interrupt

from state import GraphState

_slack_enabled = bool(os.getenv("SLACK_WEBHOOK_URL"))


def hitl_gate(state: GraphState) -> dict:
    # Fire the Slack notification (best-effort — don't let a Slack error
    # block the approval flow).
    if _slack_enabled:
        try:
            from tools.slack_tool import send_approval_request
            send_approval_request(
                state.get("generated_url", ""),
                state.get("quality_score", 0),
                state.get("brief", ""),
                state.get("iteration", 0),
            )
            print(
                f"[hitl_gate] Slack card sent — score {state.get('quality_score')}/10, "
                f"iteration {state.get('iteration', 0)}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"[hitl_gate] Slack notify failed (non-fatal): {e}")

    decision = interrupt(
        {
            "kind": "approval",
            "image_url": state.get("generated_url"),
            "score": state.get("quality_score"),
            "brief": state.get("brief"),
            "iteration": state.get("iteration", 0),
        }
    )

    action = (decision or {}).get("action", "approved")
    status = "approved" if action in ("approve", "approved") else action
    return {"status": status}
