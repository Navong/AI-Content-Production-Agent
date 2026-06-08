"""X (Twitter) publishing tool (Pillar 2: tool layer).

Closes the loop from generation → approval → distribution. Two capabilities:

  * generate_caption(brief): Claude writes a punchy, on-brand tweet caption
    (<=270 chars, a couple of hashtags) from the creative brief.
  * post_tweet(image_url, caption): downloads the approved image (from R2) and
    posts it to X via OAuth 1.0a — media upload on the v1.1 endpoint, tweet
    creation on v2 — returning the public tweet URL.

Credentials (OAuth 1.0a user context, app with Read+Write) are read from env:
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
If they're missing, post_tweet raises a clear error so callers can fall back to
a dry-run / preview.
"""
from __future__ import annotations

import io
import logging
import os

import anthropic
import requests

logger = logging.getLogger(__name__)

CAPTION_MODEL = "claude-sonnet-4-6"

CAPTION_SYSTEM = (
    "You are a social media copywriter for a creative studio. Write ONE tweet "
    "(X post) to accompany an AI-generated image described by the brief. "
    "Constraints: at most 260 characters, natural and engaging (not salesy), "
    "1-3 relevant hashtags at the end. Output ONLY the tweet text — no quotes, "
    "no preamble, no markdown."
)

_anthropic: anthropic.Anthropic | None = None


def _client() -> anthropic.Anthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = anthropic.Anthropic()
    return _anthropic


def x_configured() -> bool:
    """True when all four OAuth 1.0a credentials are present."""
    return all(
        os.getenv(k)
        for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
    )


def generate_caption(brief: str) -> str:
    """Claude-written tweet caption for the given brief (best-effort)."""
    try:
        resp = _client().messages.create(
            model=CAPTION_MODEL,
            max_tokens=180,
            system=CAPTION_SYSTEM,
            messages=[{"role": "user", "content": f"Brief: {brief}"}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        # Strip accidental surrounding quotes.
        text = text.strip('"').strip()
        return text[:280] if text else f"{brief} #AIart"
    except Exception as e:  # noqa: BLE001
        logger.warning("caption generation failed, using brief: %s", e)
        return f"{brief[:240]} #AIart"


def post_tweet(image_url: str, caption: str) -> dict:
    """Post `caption` + the image at `image_url` to X. Returns {url, tweet_id}.

    Raises RuntimeError if credentials are missing or the API call fails.
    """
    if not x_configured():
        raise RuntimeError("X credentials not configured (X_API_KEY/SECRET, X_ACCESS_TOKEN/SECRET)")

    import tweepy  # imported lazily so the app runs without the dep until used

    api_key = os.getenv("X_API_KEY", "")
    api_secret = os.getenv("X_API_SECRET", "")
    access_token = os.getenv("X_ACCESS_TOKEN", "")
    access_secret = os.getenv("X_ACCESS_SECRET", "")

    # Download the approved image (R2 public URL) into memory.
    r = requests.get(image_url, timeout=30)
    r.raise_for_status()

    # v1.1 media upload (OAuth 1.0a).
    auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
    media = tweepy.API(auth).media_upload(
        filename="content.png", file=io.BytesIO(r.content)
    )

    # v2 tweet creation.
    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret,
    )
    resp = client.create_tweet(text=caption[:280], media_ids=[media.media_id])
    tweet_id = str(resp.data["id"])
    return {"tweet_id": tweet_id, "url": f"https://x.com/i/web/status/{tweet_id}"}
