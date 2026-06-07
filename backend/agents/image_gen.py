"""ImageGen node — turns the refined prompt into an image (Pillar 2: tool layer).

Day 2/3 will delegate to tools.replicate_tool.generate_image(). For now it
returns a placeholder URL and logs the attempt to `history`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from state import GraphState


def image_gen(state: GraphState) -> dict:
    # TODO(day2/day3): url = generate_image(state["refined_prompt"], state["style_tags"])["url"]
    url = "https://placehold.co/1024x1024/png?text=stub+render"

    entry = {
        "iteration": state.get("iteration", 0),
        "prompt": state.get("refined_prompt", ""),
        "url": url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # history has an additive reducer, so returning [entry] appends one row.
    return {"generated_url": url, "history": [entry]}
