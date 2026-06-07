"""Slack notification + interactive approval for the HITL gate (Pillar 4).

Posts a Block Kit card to an incoming webhook when content is ready for review.
The card carries three interactive buttons — Approve / Regenerate / Reject —
whose action payloads are delivered to the backend's POST /slack/actions endpoint
(requires the owning Slack app to have Interactivity enabled with that Request
URL). The handler verifies the Slack signature and resumes the paused graph via
Command(resume=...), so a reviewer can drive the whole loop from Slack. A plain
"Open in app" URL button is kept as a fallback that works even without
interactivity configured.
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
            "block_id": "hitl_decision",
            "elements": [
                {
                    "type": "button",
                    "action_id": "approve",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "style": "primary",
                    "value": thread_id,
                },
                {
                    "type": "button",
                    "action_id": "regenerate",
                    "text": {"type": "plain_text", "text": "🔁 Regenerate"},
                    "value": thread_id,
                },
                {
                    "type": "button",
                    "action_id": "reject",
                    "text": {"type": "plain_text", "text": "❌ Reject"},
                    "style": "danger",
                    "value": thread_id,
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Reject this draft?"},
                        "text": {"type": "mrkdwn", "text": "This ends the run without approving."},
                        "confirm": {"type": "plain_text", "text": "Reject"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
                {
                    "type": "button",
                    "action_id": "open_app",
                    "text": {"type": "plain_text", "text": "Open in app ↗"},
                    "url": APP_URL,
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Approve, regenerate, or reject right here — decisions resume the agent run.",
                }
            ],
        },
    ]

    resp = requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks}, timeout=10)
    resp.raise_for_status()
    return resp.text == "ok"
