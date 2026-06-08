"""PromptEngineer / Creative Director node.

Two modes:
  * text — turns a creative brief into an SDXL text-to-image prompt + style tags.
  * ad   — acts as a creative director: turns a PRODUCT description into an
           advertising SCENE prompt (the setting around the product) for the
           ad-inpaint model. The product itself is supplied as an image, so the
           prompt describes only the environment, lighting, props, and mood.

On retry, the previous critique (suggested_fix) is folded in verbatim.
Uses claude-sonnet-4-6. Retry bookkeeping lives here so the router stays pure.
"""
from __future__ import annotations

import time

import anthropic

from state import GraphState

PROMPT_MODEL = "claude-sonnet-4-6"
MAX_ATTEMPTS = 3

SYSTEM_TEXT = (
    "You are an expert prompt engineer for SDXL image models. "
    "Convert user creative briefs into precise, detailed generation prompts. "
    "Output ONLY a JSON object with two keys:\n"
    '  "prompt": string — the full SDXL generation prompt (≤200 words)\n'
    '  "style_tags": array of 5 strings — key style keywords extracted from the prompt\n'
    "No extra text, no markdown fences. On retry, incorporate the quality feedback "
    "to specifically fix the issues noted."
)

SYSTEM_AD = (
    "You are a creative director at an advertising studio. You are given a PRODUCT "
    "description. The product photo itself is supplied separately, so DO NOT "
    "describe the product — describe the advertising SCENE to place it in: the "
    "setting/surface, lighting, props, mood, and color palette for a premium, "
    "photorealistic product ad. Keep the product the hero; avoid text, logos, or "
    "people unless essential.\n"
    "Output ONLY a JSON object with two keys:\n"
    '  "prompt": string — the scene/setting description (≤60 words), ending with '
    '"photorealistic product advertisement"\n'
    '  "style_tags": array of 5 strings — mood/style keywords for the ad\n'
    "No extra text, no markdown fences. On retry, incorporate the quality feedback."
)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def prompt_engineer(state: GraphState) -> dict:
    is_retry = bool(state.get("quality_feedback"))
    iteration = state.get("iteration", 0) + (1 if is_retry else 0)
    is_ad = state.get("mode") == "ad"
    system = SYSTEM_AD if is_ad else SYSTEM_TEXT

    label = "Product description" if is_ad else "Creative brief"
    user_content = f"{label}: {state['brief']}"
    if is_retry:
        user_content += (
            f"\n\nPrevious prompt attempt:\n{state.get('refined_prompt', '')}"
            f"\n\nQuality score: {state.get('quality_score', 0)}/10"
            f"\n\nCritique / suggested fix:\n{state['quality_feedback']}"
            f"\n\nRevise the prompt to directly address the critique."
        )

    last_err: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = _get_client().messages.create(
                model=PROMPT_MODEL,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            break
        except anthropic.APIStatusError as e:
            last_err = e
            if e.status_code == 529 and attempt < MAX_ATTEMPTS:
                time.sleep(2 ** (attempt - 1))
                continue
            raise
    else:
        raise RuntimeError(f"prompt_engineer failed after {MAX_ATTEMPTS} attempts: {last_err}")

    import json
    text = resp.content[0].text.strip()
    # Strip accidental markdown fences
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text)

    refined = parsed["prompt"]
    tags = parsed.get("style_tags", [])[:5]

    print(
        f"[prompt_engineer] iteration {iteration}: "
        f"{'RETRY — ' + state.get('quality_feedback','')[:60] + '...' if is_retry else 'first pass'}"
    )

    return {
        "refined_prompt": refined,
        "style_tags": tags,
        "iteration": iteration,
        # Clear downstream so supervisor re-routes through image_gen + quality_eval
        "generated_url": "",
        "quality_score": 0,
        "quality_feedback": "",
    }
