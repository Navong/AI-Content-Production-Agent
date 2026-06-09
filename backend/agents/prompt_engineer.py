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

import json
import re
import time

import anthropic


def _extract_json(text: str) -> dict:
    """Parse the model's JSON output, tolerating fences or surrounding prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    return json.loads(text)

from state import GraphState

PROMPT_MODEL = "claude-sonnet-4-6"
MAX_ATTEMPTS = 3

# Ad mode generates one ad per visual TREATMENT (distinct looks for the human to
# pick from), instead of a retry-until-good loop. These are mood/treatment levers
# the creative director applies to a product-appropriate scene — not fixed
# settings — so e.g. "dramatic" for sunscreen becomes golden-hour beach, not dark
# velvet.
AD_STYLES = [
    "clean and minimal — simple, bright, lots of negative space, product clearly in focus",
    "premium and dramatic — rich directional lighting and an elevated, high-end mood that suits the product",
    "authentic lifestyle — the product in a real, relatable in-use setting that fits how it's actually used",
]

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
    "You are a creative director making a clean, premium product ad. The product "
    "photo is supplied separately, so DO NOT describe the product — describe a "
    "simple, uncluttered SCENE around it.\n"
    "STEP 1 — Understand the product: its category, ONE hero ingredient/feature, "
    "and its benefit. If the description is not in English (e.g. Korean), "
    "translate it to English first.\n"
    "STEP 2 — Write a SHORT, focused scene. Pick just ONE or TWO subtle ingredient "
    "cues (e.g. rice toner → a few rice grains and a soft milky pool; sunscreen → "
    "warm sunlight). Do NOT pile on many props, effects, or adjectives. Keep it "
    "clean, minimal and uncluttered, with the product as the clear hero and plenty "
    "of breathing room. Give a surface/setting, soft lighting, and a fitting color "
    "palette — nothing more. Apply the requested treatment lightly. No people, no "
    "duplicate products, no text.\n"
    "Output ONLY a JSON object with two keys:\n"
    '  "prompt": a concise scene description in English (about 25-40 words, natural '
    'language — not keyword spam), ending with "photorealistic product advertisement"\n'
    '  "style_tags": array of 5 short mood/palette keywords\n'
    "No extra text, no markdown fences."
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

    if is_ad:
        # Ad mode produces a set of distinct STYLE variations (no retry loop);
        # each iteration takes the next style direction so the human can pick.
        style = AD_STYLES[iteration % len(AD_STYLES)]
        user_content = (
            f"Product description: {state['brief']}\n\n"
            "Infer the product's category and natural usage context (translate the "
            "description to English first if it isn't already), then design an ad "
            "scene that genuinely fits the product's purpose — apply this visual "
            f"treatment: {style}\n"
            "Keep the product the hero and make this variation visually distinct."
        )
    else:
        user_content = f"Creative brief: {state['brief']}"
        if is_retry:
            user_content += (
                f"\n\nPrevious prompt attempt:\n{state.get('refined_prompt', '')}"
                f"\n\nQuality score: {state.get('quality_score', 0)}/10"
                f"\n\nCritique / suggested fix:\n{state['quality_feedback']}"
                f"\n\nRevise the prompt to directly address the critique."
            )

    last_err: Exception | None = None
    parsed: dict | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = _get_client().messages.create(
                model=PROMPT_MODEL,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            parsed = _extract_json(text)
            break
        except anthropic.APIStatusError as e:
            last_err = e
            if e.status_code == 529 and attempt < MAX_ATTEMPTS:
                time.sleep(2 ** (attempt - 1))
                continue
            raise
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last_err = e
            if attempt < MAX_ATTEMPTS:
                continue  # model returned non-JSON — retry
            raise RuntimeError(f"prompt_engineer JSON parse failed: {e}")
    if parsed is None:
        raise RuntimeError(f"prompt_engineer failed after {MAX_ATTEMPTS} attempts: {last_err}")

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
