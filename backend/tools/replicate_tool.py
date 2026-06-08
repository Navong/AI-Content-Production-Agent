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
# Product-ad model: FLUX Kontext (Pruna-accelerated) — instruction-based image
# editing that restages the product into a new scene while preserving the
# product itself. ~5s/image and more faithful than inpaint compositing.
AD_MODEL = "prunaai/flux-kontext-fast:6efb57153457f8c51fb813c6d15f45d896f1916dd7d732af49d6a4b09488e2a6"
# Faithful enhancer for the uploaded product photo (upscale + detail/HDR) — low
# creativity + high resemblance keep the product itself unchanged.
ENHANCE_MODEL = "philz1337x/clarity-upscaler:dfad41707589d68ecdccd1dfa600d55a208f9310748e44bfe35b4a6291453d5e"
MAX_ATTEMPTS = 3


def enhance_image(image_url: str) -> str:
    """Upscale + enhance a product photo, staying faithful to the original.

    Returns the enhanced image URL, or the original URL on any failure (so a
    flaky enhancer never blocks ad production).
    """
    try:
        start = time.monotonic()
        out = replicate.run(
            ENHANCE_MODEL,
            input={
                "image": image_url,
                "scale_factor": 2,
                "creativity": 0.2,   # low → minimal hallucination
                "resemblance": 1.0,  # high → stay true to the product
                "dynamic": 6,
                "sharpen": 1,
                "num_inference_steps": 18,
                "output_format": "png",
            },
        )
        url = _extract_url(out)
        logger.info("enhance ok (%dms): %s", int((time.monotonic() - start) * 1000), url)
        return url or image_url
    except Exception as e:  # noqa: BLE001
        logger.warning("enhance failed, using original product image: %s", e)
        return image_url


def _extract_url(output) -> str:
    """replicate.run may return a FileOutput, a str, or a list of either."""
    item = output[0] if isinstance(output, (list, tuple)) else output
    return getattr(item, "url", None) or str(item)


def generate_ad(product_image_url: str, scene_prompt: str) -> dict:
    """Stage a product image into an advertising scene (FLUX Kontext).

    Kontext edits the input image per an instruction while preserving the
    product, so we phrase `scene_prompt` as a "place the product here, keep it
    unchanged" instruction. Returns {url, prompt_used, model, latency_ms}.
    """
    instruction = (
        "Place the product into this setting, keeping the product itself exactly "
        f"as shown and unchanged. {scene_prompt}"
    )
    last_err: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        start = time.monotonic()
        try:
            output = replicate.run(
                AD_MODEL,
                input={
                    "img_cond_path": product_image_url,
                    "prompt": instruction,
                    "aspect_ratio": "1:1",
                    "output_format": "png",
                },
            )
            url = _extract_url(output)
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.info("flux-kontext ok (attempt %d, %dms): %s", attempt, latency_ms, url)
            return {
                "url": url,
                "prompt_used": instruction,
                "model": AD_MODEL.split(":")[0],
                "latency_ms": latency_ms,
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
            backoff = 2 ** attempt
            logger.warning("flux-kontext attempt %d failed: %s (retry in %ds)", attempt, e, backoff)
            if attempt < MAX_ATTEMPTS:
                time.sleep(backoff)
    raise RuntimeError(f"flux-kontext failed after {MAX_ATTEMPTS} attempts: {last_err}")


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
