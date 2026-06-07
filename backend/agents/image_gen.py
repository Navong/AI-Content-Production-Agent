"""ImageGen node — calls the Replicate tool and logs to history.

Returns the image URL and appends one entry to the additive `history` list so
every iteration is preserved in shared state for the dashboard and LangSmith.
"""
from __future__ import annotations

from datetime import datetime, timezone

from state import GraphState
from tools.replicate_tool import generate_image


def image_gen(state: GraphState) -> dict:
    result = generate_image(state["refined_prompt"], state.get("style_tags"))

    entry = {
        "iteration": state.get("iteration", 0),
        "prompt": result["prompt_used"],
        "url": result["url"],
        "model": result["model"],
        "latency_ms": result["latency_ms"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    print(
        f"[image_gen] iteration {state.get('iteration', 0)}: "
        f"{result['model']} in {result['latency_ms']}ms -> {result['url']}"
    )
    # history has an additive reducer — returning [entry] appends one row.
    return {"generated_url": result["url"], "history": [entry]}
