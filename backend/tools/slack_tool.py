"""Slack notification for the HITL gate (Pillar 4 support).

Notify-only by design. Posts a Block Kit card to an incoming webhook when
content is ready for review, with the image, score, and a single "Review in
app" button that deep-links to that run's review screen
(/?thread=<thread_id>). The actual approve/reject happens in the web studio —
Slack is the async "tap on the shoulder" that reaches a reviewer wherever they
are, not a second control surface.
"""
from __future__ import annotations

import os

import requests

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
APP_URL = os.getenv("APP_URL", "http://localhost:3000")


def _score_badge(score: int) -> str:
    if score >= 8:
        return f"🟢 {score}/10"
    if score >= 5:
        return f"🟡 {score}/10"
    return f"🔴 {score}/10"


def send_approval_request(
    image_url: str, score: int, brief: str, iteration: int, thread_id: str = ""
) -> bool:
    """POST a review card to Slack. Returns True on success.

    `thread_id` is embedded in each button's `value` so POST /slack/actions knows
    which paused run to resume.
    """
    if not SLACK_WEBHOOK_URL:
        raise RuntimeError("SLACK_WEBHOOK_URL is not set")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🎨 Content ready for review"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Brief:* {brief}"},
        },
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
                    # Deep-link straight to this paused run's review screen.
                    "url": f"{APP_URL.rstrip('/')}/?thread={thread_id}",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Open the studio to review and approve — Slack is notify-only.",
                }
            ],
        },
    ]

    resp = requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks}, timeout=10)
    resp.raise_for_status()
    return resp.text == "ok"
