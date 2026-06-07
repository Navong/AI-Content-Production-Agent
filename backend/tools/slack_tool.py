"""Slack notification for the HITL gate (Pillar 4 support).

Posts a Block Kit card to an incoming webhook when content is ready for review.
Notify-only by design: an incoming webhook can render a card and a *URL* button
(which just opens a link — no Slack app needed), but it cannot receive button
*actions*. Those require a configured Slack app with an interactivity Request URL.
So the card links back to the Next.js app, where approve/reject actually happens
(/api/approve -> Command(resume=...)).
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
    image_url: str, score: int, brief: str, iteration: int
) -> bool:
    """POST a review card to Slack. Returns True on success."""
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
                    "text": {"type": "plain_text", "text": "Review in app"},
                    "url": APP_URL,
                    "style": "primary",
                }
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Approve / reject in the app — Slack is notify-only.",
                }
            ],
        },
    ]

    resp = requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks}, timeout=10)
    resp.raise_for_status()
    return resp.text == "ok"
