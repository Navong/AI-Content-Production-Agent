"""QualityEval node — scores the generated image (Pillar 2: tool layer).

Day 2/3 will delegate to tools.claude_vision_tool.score_image(), which uses
claude-opus-4-8 with structured outputs so the score is always a valid object
(no fragile "ask for JSON / fallback to 5" parsing). For now it returns a
passing score so the happy path reaches the HITL gate.
"""
from __future__ import annotations

from state import GraphState


def quality_eval(state: GraphState) -> dict:
    # TODO(day2/day3): result = score_image(state["generated_url"], state["brief"])
    score = 9
    feedback = ""
    print(f"[quality_eval] iteration {state.get('iteration', 0)}: score {score}/10")
    return {"quality_score": score, "quality_feedback": feedback}
