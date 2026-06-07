"""Replicate (FLUX dev) image-generation wrapper (Pillar 2: tool layer).

Calls Replicate's hosted FLUX.1 [dev] — no local GPU, so the live demo runs
anywhere. FLUX is chosen over SDXL for markedly better prompt adherence and
hands/text rendering (the exact weaknesses the Vision scorer flags on SDXL).
Returns {url, prompt_used, model, latency_ms} and retries with exponential
backoff on transient API errors. The Replicate client reads REPLICATE_API_TOKEN
from the environment automatically.
"""
from __future__ import annotations

import logging
import time

import replicate

logger = logging.getLogger(__name__)

# Replicate "official model" — referenced by name, no version hash needed.
FLUX_MODEL = "black-forest-labs/flux-dev"
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
                FLUX_MODEL,
                input={
                    # FLUX has no negative_prompt; it uses aspect_ratio, not w/h.
                    "prompt": full_prompt,
                    "aspect_ratio": "1:1",
                    "num_outputs": 1,
                    "output_format": "png",
                    "num_inference_steps": 28,
                    "guidance": 3.5,
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
                "model": FLUX_MODEL,
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
