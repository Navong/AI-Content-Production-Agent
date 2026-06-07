"""Replicate (SDXL) image-generation wrapper (Pillar 2: tool layer).

Calls Replicate's hosted SDXL — no local GPU, so the live demo runs anywhere.
Returns {url, prompt_used, model, latency_ms} and retries with exponential
backoff on transient API errors. The Replicate client reads REPLICATE_API_TOKEN
from the environment automatically.
"""
from __future__ import annotations

import logging
import time

import replicate

logger = logging.getLogger(__name__)

# Pinned SDXL version for reproducible output across runs.
SDXL_MODEL = (
    "stability-ai/sdxl:"
    "7762fd07cf82c948538e41f63f77d685e02b063e37e496e96eefd46c929f9bdc"
)
NEGATIVE_PROMPT = (
    "lowres, blurry, watermark, text, signature, deformed, extra limbs, "
    "bad anatomy, jpeg artifacts"
)
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
                SDXL_MODEL,
                input={
                    "prompt": full_prompt,
                    "negative_prompt": NEGATIVE_PROMPT,
                    "width": 1024,
                    "height": 1024,
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
                "model": SDXL_MODEL.split(":")[0],
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
