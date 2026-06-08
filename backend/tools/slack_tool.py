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


def update_on_decision(
    thread_id: str, status: str, image_url: str, score: int, brief: str, reviewer: str
) -> bool:
    """Replace the review card with the decision result (bot token only).

    On approve the card becomes "✅ Approved by … " + a Download image button;
    on reject it becomes a short "❌ Rejected by …". No-op (returns False) when
    posting via webhook, or if we never captured this run's message ts.
    """
    ts = _ts_by_thread.get(thread_id)
    if not (SLACK_BOT_TOKEN and SLACK_CHANNEL and ts):
        return False

    if status == "approved":
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Approved by {reviewer}*  ·  {_score_badge(score)}\n_{brief}_",
                },
            },
            {"type": "image", "image_url": image_url, "alt_text": "approved image"},
            {
                "type": "actions",
                "elements": [
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
                ],
            },
        ]
        fallback = f"Approved by {reviewer}"
    else:
        label = {
            "rejected": "❌ *Rejected*",
            "regenerated": "🔁 *Regenerated*",
        }.get(status, f"*{status}*")
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{label} by {reviewer}  ·  {_score_badge(score)}\n_{brief}_",
                },
            }
        ]
        fallback = f"{status} by {reviewer}"

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
    _ts_by_thread.pop(thread_id, None)
    return True
