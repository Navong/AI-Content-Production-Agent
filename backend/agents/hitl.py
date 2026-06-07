"""HITL gate node (Pillar 4: human-in-the-loop).

Fires a Slack notification card, then pauses the graph via LangGraph's native
interrupt(). The run resumes when the caller invokes the graph again with
Command(resume={"action": "approve" | "reject" | "regenerate"}) on the same
thread_id.

IMPORTANT — LangGraph re-runs the entire node on resume: every line *before*
interrupt() executes a second time when the graph is resumed. To avoid posting a
duplicate Slack card on every approve/reject, the notification is de-duplicated
per (thread_id, iteration) via `_notified`.
"""
from __future__ import annotations

import os

from langgraph.types import interrupt

from state import GraphState

_slack_enabled = bool(os.getenv("SLACK_WEBHOOK_URL"))

# Tracks which (thread_id, iteration) pauses have already sent a Slack card, so
# the resume re-run of this node doesn't post a second one.
_notified: set[str] = set()


def hitl_gate(state: GraphState) -> dict:
    thread_id = state.get("thread_id", "")
    iteration = state.get("iteration", 0)
    notify_key = f"{thread_id}:{iteration}"

    # Fire the Slack notification once per pause (best-effort — don't let a Slack
    # error block approval, and don't re-send on the resume re-run of this node).
    if _slack_enabled and notify_key not in _notified:
        try:
            from tools.slack_tool import send_approval_request
            send_approval_request(
                state.get("generated_url", ""),
                state.get("quality_score", 0),
                state.get("brief", ""),
                iteration,
                thread_id,
            )
            _notified.add(notify_key)
            print(
                f"[hitl_gate] Slack card sent — score {state.get('quality_score')}/10, "
                f"iteration {iteration}"
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
