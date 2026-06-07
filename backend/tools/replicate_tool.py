"""Replicate (SDXL/Flux) image-generation wrapper. Implemented on Day 2.

Returns a dict: {url, prompt_used, model, latency_ms}.
"""
from __future__ import annotations


def generate_image(prompt: str, style_tags: list[str] | None = None) -> dict:
    """TODO(day2): replicate.run("stability-ai/sdxl:...", input={prompt, ...})
    with 3-attempt exponential backoff and latency logging."""
    raise NotImplementedError("Implemented on Day 2")
