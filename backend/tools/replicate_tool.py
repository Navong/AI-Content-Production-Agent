"""Replicate image-generation wrapper (Pillar 2: tool layer).

Calls Replicate's hosted ByteDance SDXL-Lightning (4-step) — a distilled SDXL
that renders in ~1-2s, so the live demo (and the retry loop) stays snappy. No
local GPU, runs anywhere. Returns {url, prompt_used, model, latency_ms} and
retries with exponential backoff on transient API errors. The Replicate client
reads REPLICATE_API_TOKEN from the environment automatically.
"""
from __future__ import annotations

import logging
import time

import replicate

logger = logging.getLogger(__name__)

# Pinned to an exact version hash (SDXL-Lightning is a community model, so a
# version is required). Distilled to 4 steps with guidance_scale 0.
IMAGE_MODEL = "bytedance/sdxl-lightning-4step:6f7a773af6fc3e8de9d5a3c00be77c17308914bf67772726aff83496ba1e3bbe"
MAX_ATTEMPTS = 3


def _extract_url(output) -> str:
    """replicate.run may return a FileOutput, a str, or a list of either."""
    item = output[0] if isinstance(output, (list, tuple)) else output
    return getattr(item, "url", None) or str(item)


def generate_image(prompt: str, style_tags: list[str] | None = None) -> dict:
    """Generate one image and return {url, prompt_used, model, latency_ms}.

    Raises RuntimeError if all retry attempts fail.
    """
    full_prompt = f"{prompt}, {', '.join(style_tags)}" if style_tags else prompt

    last_err: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        start = time.monotonic()
        try:
            output = replicate.run(
                IMAGE_MODEL,
                input={
                    "prompt": full_prompt,
                    "negative_prompt": "worst quality, low quality, blurry, distorted",
                    "width": 1024,
                    "height": 1024,
                    "scheduler": "K_EULER",
                    "num_inference_steps": 4,  # Lightning is distilled to 4 steps
                    "guidance_scale": 0,       # 0 is recommended for Lightning
                    "num_outputs": 1,
                },
            )
            url = _extract_url(output)
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "replicate ok (attempt %d, %dms): %s", attempt, latency_ms, url
            )
            return {
                "url": url,
                "prompt_used": full_prompt,
                "model": IMAGE_MODEL,
                "latency_ms": latency_ms,
            }
        except Exception as e:  # noqa: BLE001 - retry any API/transport error
            last_err = e
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "replicate attempt %d failed: %s (retry in %ds)", attempt, e, backoff
            )
            if attempt < MAX_ATTEMPTS:
                time.sleep(backoff)

    raise RuntimeError(f"replicate failed after {MAX_ATTEMPTS} attempts: {last_err}")
