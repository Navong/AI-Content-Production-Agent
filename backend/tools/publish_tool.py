"""Social publishing tool (Pillar 2: tool layer) — Facebook Page.

Closes the loop from generation → approval → distribution. Two capabilities:

  * generate_caption(brief): Claude writes an engaging caption from the brief.
  * publish(image_url, caption): posts the approved image (its public R2 URL) +
    caption to a Facebook Page via the Graph API. Facebook fetches the image
    from the URL, so there's no separate upload step.

Free for a Page you own/admin: a Meta app in development mode can post to the
admin's own Page with pages_manage_posts — no App Review needed.

Config (env):
  FACEBOOK_PAGE_ID            — the numeric Page ID
  FACEBOOK_PAGE_ACCESS_TOKEN  — a Page access token (ideally long-lived)
"""
from __future__ import annotations

import logging
import os

import anthropic
import requests

logger = logging.getLogger(__name__)

PLATFORM = "Facebook"
GRAPH = "https://graph.facebook.com/v21.0"

CAPTION_MODEL = "claude-sonnet-4-6"
CAPTION_SYSTEM = (
    "You are a social media copywriter for a creative studio. Write ONE Facebook "
    "caption for an AI-generated image described by the brief. Keep it engaging "
    "and natural (not salesy), 1-3 short sentences, with 2-4 relevant hashtags at "
    "the end. Output ONLY the caption text — no quotes, no preamble, no markdown."
)

_anthropic: anthropic.Anthropic | None = None


def _client() -> anthropic.Anthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = anthropic.Anthropic()
    return _anthropic


def publish_configured() -> bool:
    """True when the Facebook Page id and access token are both present."""
    return bool(os.getenv("FACEBOOK_PAGE_ID") and os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN"))


def generate_caption(brief: str) -> str:
    """Claude-written social caption for the given brief (best-effort)."""
    try:
        resp = _client().messages.create(
            model=CAPTION_MODEL,
            max_tokens=220,
            system=CAPTION_SYSTEM,
            messages=[{"role": "user", "content": f"Brief: {brief}"}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = text.strip('"').strip()
        return text or f"{brief} #AIart"
    except Exception as e:  # noqa: BLE001
        logger.warning("caption generation failed, using brief: %s", e)
        return f"{brief} #AIart"


def publish(image_url: str, caption: str) -> dict:
    """Post `caption` + the image at `image_url` to the Facebook Page.

    Returns {id, url}. Raises RuntimeError on missing config or a Graph error.
    """
    page_id = os.getenv("FACEBOOK_PAGE_ID", "")
    token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    if not (page_id and token):
        raise RuntimeError("Facebook not configured (FACEBOOK_PAGE_ID / FACEBOOK_PAGE_ACCESS_TOKEN)")

    resp = requests.post(
        f"{GRAPH}/{page_id}/photos",
        data={"url": image_url, "caption": caption, "access_token": token},
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))

    post_id = data.get("post_id") or data.get("id", "")
    return {"id": post_id, "url": f"https://www.facebook.com/{post_id}"}
