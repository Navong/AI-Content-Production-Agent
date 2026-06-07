"""Shared graph state for the AI Content Production Agent.

This TypedDict is the agent's memory (Pillar 3). Every node reads it and returns
a partial dict that LangGraph merges in. `history` uses an additive reducer so
each node can append its own entry without clobbering prior iterations.
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class GraphState(TypedDict):
    brief: str                                  # original user input
    refined_prompt: str                         # after PromptEngineer
    style_tags: list[str]                       # extracted style keywords
    generated_url: str                          # image URL from Replicate
    quality_score: int                          # 1-10 from Claude Vision (0 = not scored yet)
    quality_feedback: str                       # what to fix on retry
    iteration: int                              # retry counter (max 3)
    status: str                                 # running | awaiting_approval | approved | rejected | done
    history: Annotated[list[dict], operator.add]  # all iterations: {iteration, prompt, url, timestamp}


def initial_state(brief: str) -> GraphState:
    """Build a fresh state for a new run."""
    return {
        "brief": brief,
        "refined_prompt": "",
        "style_tags": [],
        "generated_url": "",
        "quality_score": 0,
        "quality_feedback": "",
        "iteration": 0,
        "status": "running",
        "history": [],
    }
