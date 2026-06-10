"""Replicate image-generation wrapper (Pillar 2: tool layer).

Calls Replicate's hosted Black Forest Labs FLUX.1 [schnell] — a fast 4-step
distilled FLUX that renders in ~1-2s, keeping the live demo and the retry loop
snappy. No local GPU, runs anywhere. Returns {url, prompt_used, model,
latency_ms} and retries with exponential backoff on transient API errors. The
Replicate client reads REPLICATE_API_TOKEN from the environment automatically.
"""
from __future__ import annotations

import logging
import time

import replicate

logger = logging.getLogger(__name__)

# Official Replicate model — referenced by name, no version hash needed.
IMAGE_MODEL = "black-forest-labs/flux-schnell"
# Product-ad model: FLUX 2 Pro — high-quality generation+editing with reference
# images. Takes the product as a reference and restages it into a scene while
# keeping it faithful; renders hero-ingredient props (rice, milk, citrus…)
# crisply. Higher fidelity + quality than Kontext (a "pro" tier model).
AD_MODEL = "black-forest-labs/flux-2-pro"
MAX_ATTEMPTS = 3


def _extract_url(output) -> str:
    """replicate.run may return a FileOutput, a str, or a list of either."""
    item = output[0] if isinstance(output, (list, tuple)) else output
    return getattr(item, "url", None) or str(item)


def generate_ad(product_image_url: str, scene_prompt: str) -> dict:
    """Stage a product image into an advertising scene (FLUX 2 Pro).

    The product is passed as a reference image; the instruction asks the model
    to place it into the scene while keeping it faithful. Returns
    {url, prompt_used, model, latency_ms}.
    """
    instruction = (
        "Edit this image into a finished advertisement. Keep the product's exact "
        "shape, color, design and label from the source image — do NOT add or alter "
        "any text, label, or logo, and show only this ONE product (no duplicates). "
        "You MAY add a single person — the model — naturally using or presenting the "
        "product as described, with realistic, healthy skin. Render photorealistic, "
        "high-resolution professional advertising photography with clean lighting. "
        f"{scene_prompt}"
    )
    last_err: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        start = time.monotonic()
        try:
            output = replicate.run(
                AD_MODEL,
                input={
                    "prompt": instruction,
                    "input_images": [product_image_url],
                    "aspect_ratio": "1:1",
                    "output_format": "png",
                },
            )
            url = _extract_url(output)
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.info("flux-2-pro ok (attempt %d, %dms): %s", attempt, latency_ms, url)
            return {
                "url": url,
                "prompt_used": instruction,
                "model": AD_MODEL.split(":")[0],
                "latency_ms": latency_ms,
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
            backoff = 2 ** attempt
            logger.warning("flux-2-pro attempt %d failed: %s (retry in %ds)", attempt, e, backoff)
            if attempt < MAX_ATTEMPTS:
                time.sleep(backoff)
    raise RuntimeError(f"flux-2-pro failed after {MAX_ATTEMPTS} attempts: {last_err}")


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
                    "aspect_ratio": "1:1",
                    "num_inference_steps": 4,  # schnell is distilled to <=4 steps
                    "output_format": "png",
                    "num_outputs": 1,
                    "go_fast": True,
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
