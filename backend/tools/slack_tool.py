"""Slack notification for the HITL gate (Pillar 4 support).

Posts a Block Kit review card when content is ready for review (image, score,
and a "Review in app" deep link to /?thread=<id>). Approve/reject happens in
the web studio — Slack is notify-only.

Two posting modes:
  * Bot token (SLACK_BOT_TOKEN + SLACK_CHANNEL): posts via chat.postMessage and
    remembers the message ts, so when the run is decided in the studio we can
    chat.update that exact card into an "Approved by … / Download image" result.
  * Webhook fallback (SLACK_WEBHOOK_URL): posts the card but can't edit it later
    (incoming webhooks return no message handle).
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "")
APP_URL = os.getenv("APP_URL", "http://localhost:3000")

# thread_id -> Slack message ts, so a studio decision can update the right card.
_ts_by_thread: dict[str, str] = {}
# thread_id -> last approved-card context, so "Posted to X" can rebuild the card.
_card_ctx: dict[str, dict] = {}


def get_ts(thread_id: str) -> str:
    """The Slack message ts for a run (empty if unknown) — for persistence."""
    return _ts_by_thread.get(thread_id, "")


def restore(thread_id: str, ts: str, image: str, score: int, brief: str, reviewer: str) -> None:
    """Re-seed the in-memory card state after a backend restart (from R2)."""
    if ts:
        _ts_by_thread[thread_id] = ts
    _card_ctx[thread_id] = {"image": image, "score": score, "brief": brief, "reviewer": reviewer}


def _score_badge(score: int) -> str:
    if score >= 8:
        return f"🟢 {score}/10"
    if score >= 5:
        return f"🟡 {score}/10"
    return f"🔴 {score}/10"


def _review_blocks(image_url: str, score: int, brief: str, iteration: int, thread_id: str) -> list:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🎨 Content ready for review"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Brief:* {brief}"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Quality score*\n{_score_badge(score)}"},
                {"type": "mrkdwn", "text": f"*Iteration*\n{iteration}"},
            ],
        },
        {"type": "image", "image_url": image_url, "alt_text": "generated image"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "open_app",
                    "text": {"type": "plain_text", "text": "Review in app ↗"},
                    "style": "primary",
                    "url": f"{APP_URL.rstrip('/')}/?thread={thread_id}",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Open the studio to review and approve — Slack is notify-only."}
            ],
        },
    ]


def send_approval_request(
    image_url: str, score: int, brief: str, iteration: int, thread_id: str = ""
) -> bool:
    """Post the review card. Returns True on success.

    With a bot token, also remembers the message ts (keyed by thread_id) so the
    card can later be updated into a decision result.
    """
    blocks = _review_blocks(image_url, score, brief, iteration, thread_id)
    fallback = "Content ready for review"

    if SLACK_BOT_TOKEN and SLACK_CHANNEL:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            json={"channel": SLACK_CHANNEL, "blocks": blocks, "text": fallback},
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack chat.postMessage failed: {data.get('error')}")
        if thread_id and data.get("ts"):
            _ts_by_thread[thread_id] = data["ts"]
        return True

    if SLACK_WEBHOOK_URL:
        r = requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks, "text": fallback}, timeout=10)
        r.raise_for_status()
        return r.text == "ok"

    raise RuntimeError("no Slack destination configured (SLACK_BOT_TOKEN+SLACK_CHANNEL or SLACK_WEBHOOK_URL)")


def _approved_blocks(
    thread_id: str, image_url: str, score: int, brief: str, reviewer: str, tweet_url: str = ""
) -> list:
    """Approved result card. Adds 'Posted to X' state when tweet_url is set."""
    headline = f"✅ *Approved by {reviewer}*  ·  {_score_badge(score)}\n_{brief}_"
    if tweet_url:
        headline += "\n🐦 *Posted to X*"
    elements = [
        {
            "type": "button",
            "action_id": "download",
            "text": {"type": "plain_text", "text": "⬇️  Download image"},
            "style": "primary",
            "url": image_url,
        },
        {
            "type": "button",
            "action_id": "view_in_studio",
            "text": {"type": "plain_text", "text": "View in studio ↗"},
            "url": f"{APP_URL.rstrip('/')}/?thread={thread_id}",
        },
    ]
    # Posting to X happens in the studio (not from Slack). After it's posted,
    # the card shows a "View tweet" link.
    if tweet_url:
        elements.append({
            "type": "button",
            "action_id": "view_tweet",
            "text": {"type": "plain_text", "text": "View tweet ↗"},
            "url": tweet_url,
        })
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": headline}},
        {"type": "image", "image_url": image_url, "alt_text": "approved image"},
        {"type": "actions", "elements": elements},
    ]


def _chat_update(thread_id: str, blocks: list, fallback: str) -> bool:
    ts = _ts_by_thread.get(thread_id)
    if not (SLACK_BOT_TOKEN and SLACK_CHANNEL and ts):
        return False
    resp = requests.post(
        "https://slack.com/api/chat.update",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": SLACK_CHANNEL, "ts": ts, "blocks": blocks, "text": fallback},
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        logger.warning("slack chat.update failed: %s", data.get("error"))
        return False
    return True


def update_on_decision(
    thread_id: str, status: str, image_url: str, score: int, brief: str, reviewer: str
) -> bool:
    """Replace the review card with the decision result (bot token only).

    Approve → "✅ Approved by … " + Download / View in studio / Post to X.
    Reject/regenerate → a short status line. No-op when on webhook or no ts.
    """
    if not (SLACK_BOT_TOKEN and SLACK_CHANNEL and _ts_by_thread.get(thread_id)):
        return False

    if status == "approved":
        _card_ctx[thread_id] = {
            "image": image_url, "score": score, "brief": brief, "reviewer": reviewer,
        }
        blocks = _approved_blocks(thread_id, image_url, score, brief, reviewer)
        return _chat_update(thread_id, blocks, f"Approved by {reviewer}")

    label = {"rejected": "❌ *Rejected*", "regenerated": "🔁 *Regenerated*"}.get(
        status, f"*{status}*"
    )
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{label} by {reviewer}  ·  {_score_badge(score)}\n_{brief}_"},
        }
    ]
    ok = _chat_update(thread_id, blocks, f"{status} by {reviewer}")
    _ts_by_thread.pop(thread_id, None)  # terminal, won't be updated again
    return ok


def delete_card(thread_id: str, ts: str = "") -> bool:
    """Delete the Slack card for a run (bot token only) — used when a run is
    deleted from the studio. `ts` lets the caller pass the persisted message ts
    so it works after a restart (when _ts_by_thread is empty)."""
    ts = ts or _ts_by_thread.get(thread_id, "")
    _ts_by_thread.pop(thread_id, None)
    _card_ctx.pop(thread_id, None)
    if not (SLACK_BOT_TOKEN and SLACK_CHANNEL and ts):
        return False
    resp = requests.post(
        "https://slack.com/api/chat.delete",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": SLACK_CHANNEL, "ts": ts},
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        logger.warning("slack chat.delete failed: %s", data.get("error"))
        return False
    return True


def mark_posted_to_x(thread_id: str, tweet_url: str) -> bool:
    """Rebuild the approved card to show 'Posted to X' + a View tweet button."""
    ctx = _card_ctx.get(thread_id)
    if not ctx:
        return False
    blocks = _approved_blocks(
        thread_id, ctx["image"], ctx["score"], ctx["brief"], ctx["reviewer"], tweet_url
    )
    return _chat_update(thread_id, blocks, f"Posted to X — {tweet_url}")
