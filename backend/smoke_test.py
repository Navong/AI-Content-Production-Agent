"""Day 3 end-to-end smoke test.

Runs the full graph with a REAL brief — prompt engineering, image generation,
quality scoring, and the HITL interrupt/resume cycle. Every call lands in
LangSmith under the `content-production-agent` project.

Run: python smoke_test.py
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from langgraph.types import Command

from graph import graph
from state import initial_state

# Deliberately specific brief — should score well and trigger the happy path.
BRIEF = "a cute robot barista in a Seoul cafe with hangul signage, watercolor style"


def main() -> None:
    cfg = {"configurable": {"thread_id": "smoke-day3"}}

    print(f"\nBrief: {BRIEF!r}\n{'-'*60}")
    result = graph.invoke(initial_state(BRIEF), cfg)

    assert "__interrupt__" in result, "expected HITL gate to interrupt"
    payload = result["__interrupt__"][0].value
    print(f"\n{'-'*60}")
    print(f"PAUSED → score {payload['score']}/10, iteration {payload['iteration']}")
    print(f"image : {payload['image_url']}")

    # Approve and resume
    final = graph.invoke(Command(resume={"action": "approve"}), cfg)
    print(f"\nFINAL status  : {final['status']}")
    print(f"iterations    : {final['iteration']}")
    print(f"history entries: {len(final['history'])}")
    for h in final["history"]:
        print(f"  iter {h['iteration']}: score n/a → {h['url'][:60]}...")
    assert final["status"] == "approved"
    print("\nOK: full graph ran end-to-end with real APIs.")


if __name__ == "__main__":
    main()
