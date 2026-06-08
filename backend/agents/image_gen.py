"""ImageGen node — generates an image and uploads it to R2 for permanent storage.

Flow:
  1. Call Replicate (FLUX dev) → get a temporary signed delivery URL (~24 h expiry)
  2. Upload to Cloudflare R2 → get a permanent public URL
  3. Store the permanent URL in state (falls back to Replicate URL if R2 is
     not configured, so the app works without R2 credentials)
  4. Append one entry to the additive `history` list
"""
from __future__ import annotations

from datetime import datetime, timezone

from state import GraphState
from tools.r2_tool import upload_image
from tools.replicate_tool import generate_ad, generate_image


def image_gen(state: GraphState) -> dict:
    thread_id = state.get("thread_id", "unknown")
    iteration = state.get("iteration", 0)

    if state.get("mode") == "ad" and state.get("product_image_url"):
        # Stage the uploaded product into an advertising scene.
        result = generate_ad(state["product_image_url"], state["refined_prompt"])
    else:
        result = generate_image(state["refined_prompt"], state.get("style_tags"))
    replicate_url = result["url"]

    # Upload to R2 for permanent storage; fall back to Replicate URL if not configured.
    permanent_url = upload_image(replicate_url, thread_id, iteration) or replicate_url

    entry = {
        "iteration": iteration,
        "prompt": result["prompt_used"],
        "replicate_url": replicate_url,
        "url": permanent_url,           # permanent R2 URL (or Replicate URL as fallback)
        "model": result["model"],
        "latency_ms": result["latency_ms"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    print(
        f"[image_gen] iteration {iteration}: "
        f"{result['model']} in {result['latency_ms']}ms -> {permanent_url}"
    )
    return {"generated_url": permanent_url, "history": [entry]}
