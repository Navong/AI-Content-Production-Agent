"""Day 2: exercise each tool in isolation.

  python test_tools.py            # run every tool whose credentials are present
  python test_tools.py replicate  # run a single tool (replicate | vision | slack)

Needs the relevant keys in .env:
  replicate -> REPLICATE_API_TOKEN
  vision    -> ANTHROPIC_API_KEY
  slack     -> SLACK_WEBHOOK_URL
When run with no args, replicate's output URL is fed into the vision + slack
tests so they score/post a real generated image.
"""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

BRIEF = "a cute robot barista in a Seoul cafe, watercolor"
PLACEHOLDER = "https://placehold.co/1024x1024/png?text=test"


def test_replicate() -> str | None:
    from tools.replicate_tool import generate_image

    out = generate_image(BRIEF, ["watercolor", "soft pastel", "studio lighting"])
    print("[replicate]", json.dumps(out, indent=2))
    return out["url"]


def test_vision(image_url: str | None = None) -> None:
    from tools.claude_vision_tool import score_image

    out = score_image(image_url or PLACEHOLDER, BRIEF)
    print("[vision]", json.dumps(out, indent=2))


def test_slack(image_url: str | None = None) -> None:
    from tools.slack_tool import send_approval_request

    ok = send_approval_request(image_url or PLACEHOLDER, 9, BRIEF, 0)
    print("[slack] posted:", ok)


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else None

    if which == "replicate":
        test_replicate()
        return
    if which == "vision":
        test_vision()
        return
    if which == "slack":
        test_slack()
        return

    # No arg: run whatever has credentials, chaining replicate's URL forward.
    image_url: str | None = None
    if os.getenv("REPLICATE_API_TOKEN"):
        image_url = test_replicate()
    else:
        print("[replicate] skipped (REPLICATE_API_TOKEN not set)")

    if os.getenv("ANTHROPIC_API_KEY"):
        test_vision(image_url)
    else:
        print("[vision] skipped (ANTHROPIC_API_KEY not set)")

    if os.getenv("SLACK_WEBHOOK_URL"):
        test_slack(image_url)
    else:
        print("[slack] skipped (SLACK_WEBHOOK_URL not set)")


if __name__ == "__main__":
    main()
