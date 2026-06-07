"""PromptEngineer node — refines the brief into an image-gen prompt.

On a retry (quality_feedback is set), this node:
  1. increments the iteration counter, and
  2. clears generated_url + quality_score
so the supervisor re-routes through image_gen and quality_eval. Keeping this
bookkeeping in the node (not the router) is what lets `route` stay pure.
"""
from __future__ import annotations

from state import GraphState

# Day 3 will call this model to actually rewrite the prompt.
PROMPT_MODEL = "claude-sonnet-4-6"  # cheap/fast; good enough for prompt rewriting


def prompt_engineer(state: GraphState) -> dict:
    is_retry = bool(state.get("quality_feedback"))
    iteration = state.get("iteration", 0) + (1 if is_retry else 0)

    # TODO(day3): client.messages.create(model=PROMPT_MODEL, ...) to turn
    # state["brief"] (+ state["quality_feedback"] on retry) into a real prompt.
    refined = f"[stub] {state['brief']}, cinematic lighting, highly detailed, 8k"

    return {
        "refined_prompt": refined,
        "style_tags": ["stub", "cinematic", "detailed"],
        "iteration": iteration,
        # clear downstream so the supervisor re-runs gen + eval on retries
        "generated_url": "",
        "quality_score": 0,
    }
