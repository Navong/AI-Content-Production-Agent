"""Supervisor node + router (Pillar 1: the orchestrator).

`route` is a PURE function used by the conditional edge — it only reads state and
returns the next node name. It must never mutate state; all state changes happen
inside worker nodes via their returned dicts. Retry bookkeeping (incrementing the
iteration counter, clearing the stale image/score) lives in `prompt_engineer`.
"""
from __future__ import annotations

from state import GraphState

QUALITY_THRESHOLD = 8
MAX_ITERATIONS = 3


def supervisor(state: GraphState) -> dict:
    """Hub node. No-op by design — it exists so the graph has a single routing
    hub and the LangSmith trace shows every hop through the supervisor."""
    return {}


def route(state: GraphState) -> str:
    """Decide the next node from current state. Pure: read-only."""
    if not state.get("refined_prompt"):
        return "prompt_engineer"
    if not state.get("generated_url"):
        return "image_gen"
    if state.get("quality_score", 0) == 0:
        return "quality_eval"
    if state["quality_score"] >= QUALITY_THRESHOLD:
        return "hitl_gate"
    if state.get("iteration", 0) < MAX_ITERATIONS:
        return "prompt_engineer"  # retry, folding in quality_feedback
    return "hitl_gate"  # max iterations -> force a human decision
