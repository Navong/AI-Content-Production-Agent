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
# Set to "true" only if the bot also has the groups:read scope — lets channel
# auto-detect include private channels (else Slack errors with missing_scope).
SLACK_GROUPS_READ = os.getenv("SLACK_GROUPS_READ", "").lower() in ("1", "true", "yes")
APP_URL = os.getenv("APP_URL", "http://localhost:3000")

# thread_id -> Slack message ts / channel, so a studio decision can update the
# right card (the channel can differ from SLACK_CHANNEL when auto-detected).
_ts_by_thread: dict[str, str] = {}
_chan_by_thread: dict[str, str] = {}
# thread_id -> last approved-card context, so "Posted to X" can rebuild the card.
_card_ctx: dict[str, dict] = {}

# Cached posting channel + the Slack errors that mean "this channel is unusable".
_resolved_channel: str = ""
_CHANNEL_ERRORS = {"channel_not_found", "is_archived", "not_in_channel", "channel_is_archived"}


def _auto_channel() -> str:
    """The most recently created channel the bot is a member of — used when
    SLACK_CHANNEL is unset or stale (e.g. the old channel was deleted and the bot
    was invited to a new one). Newest-first matches the "just add the bot to a new
    channel" workflow. Needs the channels:read / groups:read scope; "" if absent."""
    if not SLACK_BOT_TOKEN:
        return ""
    # Public channels need channels:read; including private_channel would also
    # require groups:read or Slack rejects the whole call with missing_scope. We
    # request only what channels:read covers, then add private channels when the
    # extra scope is present.
    types = "public_channel"
    if SLACK_GROUPS_READ:
        types += ",private_channel"
    try:
        resp = requests.get(
            "https://slack.com/api/users.conversations",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            params={"types": types, "exclude_archived": "true", "limit": 200},
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Slack auto-channel lookup error: %s", data.get("error"))
            return ""
        chans = data.get("channels", [])
        if not chans:
            return ""
        chans.sort(key=lambda c: c.get("created", 0), reverse=True)
        return chans[0]["id"]
    except Exception as e:  # noqa: BLE001
        logger.warning("Slack auto-channel lookup failed: %s", e)
        return ""


def _target_channel(refresh: bool = False) -> str:
    """Channel to post into: the configured SLACK_CHANNEL, else a channel the bot
    is in. `refresh=True` ignores the (stale) configured id and finds a live one,
    so cards keep working after the bot is moved to a new channel."""
    global _resolved_channel
    if refresh:
        _resolved_channel = _auto_channel()
    elif not _resolved_channel:
        _resolved_channel = SLACK_CHANNEL or _auto_channel()
    return _resolved_channel


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

    if SLACK_BOT_TOKEN:
        channel = _target_channel()
        if not channel:
            raise RuntimeError(
                "no Slack channel — set SLACK_CHANNEL or invite the bot to a channel"
            )
        data = _post_message(channel, blocks, fallback)
        # If the configured channel is gone/inaccessible, find a live one and retry.
        if not data.get("ok") and data.get("error") in _CHANNEL_ERRORS:
            channel = _target_channel(refresh=True)
            if channel:
                data = _post_message(channel, blocks, fallback)
        if not data.get("ok"):
            raise RuntimeError(f"slack chat.postMessage failed: {data.get('error')}")
        if thread_id and data.get("ts"):
            _ts_by_thread[thread_id] = data["ts"]
            _chan_by_thread[thread_id] = channel
        return True

    if SLACK_WEBHOOK_URL:
        r = requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks, "text": fallback}, timeout=10)
        r.raise_for_status()
        return r.text == "ok"

    raise RuntimeError("no Slack destination configured (SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL)")


def _post_message(channel: str, blocks: list, fallback: str) -> dict:
    """POST chat.postMessage; returns the parsed Slack response (ok / error)."""
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": channel, "blocks": blocks, "text": fallback},
        timeout=10,
    )
    return resp.json()


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
    channel = _chan_by_thread.get(thread_id) or _target_channel()
    if not (SLACK_BOT_TOKEN and channel and ts):
        return False
    resp = requests.post(
        "https://slack.com/api/chat.update",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": channel, "ts": ts, "blocks": blocks, "text": fallback},
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
    if not (SLACK_BOT_TOKEN and _ts_by_thread.get(thread_id)):
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
    channel = _chan_by_thread.pop(thread_id, "") or _target_channel()
    _ts_by_thread.pop(thread_id, None)
    _card_ctx.pop(thread_id, None)
    if not (SLACK_BOT_TOKEN and channel and ts):
        return False
    resp = requests.post(
        "https://slack.com/api/chat.delete",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": channel, "ts": ts},
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
