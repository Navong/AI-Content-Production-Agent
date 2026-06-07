"""Day 1 smoke test: run the graph end-to-end with stubs.

Verifies the StateGraph wiring and the native HITL round-trip:
  brief -> prompt_engineer -> image_gen -> quality_eval -> hitl_gate (interrupt)
        -> resume(approve) -> END

If LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set, a trace appears in
LangSmith under the LANGSMITH_PROJECT. The graph runs locally either way.

Run: python smoke_test.py
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from langgraph.types import Command

from graph import graph
from state import initial_state


def main() -> None:
    cfg = {"configurable": {"thread_id": "smoke-1"}}

    result = graph.invoke(
        initial_state("a cute robot barista in a Seoul cafe, watercolor"),
        cfg,
    )

    assert "__interrupt__" in result, "expected the HITL gate to interrupt the run"
    payload = result["__interrupt__"][0].value
    print("PAUSED at HITL gate ->", payload)

    final = graph.invoke(Command(resume={"action": "approve"}), cfg)
    print("FINAL status:", final["status"])
    print("iterations:", final["iteration"], "| history entries:", len(final["history"]))
    assert final["status"] == "approved"
    assert len(final["history"]) == 1
    print("OK: graph ran end-to-end.")


if __name__ == "__main__":
    main()
