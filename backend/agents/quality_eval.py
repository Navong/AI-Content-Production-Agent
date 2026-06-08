"""QualityEval node — scores the generated image via Claude Vision.

Calls claude_vision_tool.score_image(), which uses claude-opus-4-8 with
structured outputs to return a schema-valid critique. The `suggested_fix` field
is stored as quality_feedback so the PromptEngineer can fold it in on retry.
"""
from __future__ import annotations

from state import GraphState
from tools.claude_vision_tool import score_image


def quality_eval(state: GraphState) -> dict:
    result = score_image(
        state["generated_url"], state["brief"], mode=state.get("mode", "text")
    )

    score = result["score"]
    # Combine issues + suggested_fix into the feedback the retry loop acts on.
    issues_txt = "; ".join(result.get("issues", []))
    feedback = f"{issues_txt}\n\nSuggested fix: {result.get('suggested_fix', '')}"

    print(
        f"[quality_eval] iteration {state.get('iteration', 0)}: "
        f"score {score}/10 — {result.get('issues', [''])[0][:80]}"
    )
    return {"quality_score": score, "quality_feedback": feedback}
