"""Slack notification for the HITL gate. Implemented on Day 2.

NOTE: an incoming webhook URL can POST a Block Kit card, but interactive button
clicks require a configured Slack app with an interactivity Request URL. Default
posture: Slack is notify-only; the approve/reject decision happens in the Next.js
UI (which calls /api/approve -> Command(resume=...)).
"""
from __future__ import annotations

import os

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


def send_approval_request(image_url: str, score: int, brief: str, iteration: int) -> bool:
    """TODO(day2): build Block Kit blocks (image preview, score badge, brief,
    iteration) and POST to SLACK_WEBHOOK_URL. Returns True on success."""
    raise NotImplementedError("Implemented on Day 2")
