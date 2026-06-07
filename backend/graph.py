"""LangGraph StateGraph for the AI Content Production Agent.

Supervisor pattern (Pillar 1): a pure router (`route`) inspects shared state and
decides which worker runs next. Workers mutate state by returning dicts; the
router never mutates. HITL (Pillar 4) uses LangGraph's native `interrupt()` plus
a checkpointer, so the pause is durable and resumable by `thread_id` — no
hand-rolled session dict.

Routing:
    no refined_prompt            -> prompt_engineer
    no generated_url             -> image_gen
    quality_score == 0           -> quality_eval
    quality_score >= THRESHOLD   -> hitl_gate -> END
    quality_score < THRESHOLD
        and iteration < MAX      -> prompt_engineer (retry with feedback)
    iteration >= MAX             -> hitl_gate (force human decision)
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.hitl import hitl_gate
from agents.image_gen import image_gen
from agents.prompt_engineer import prompt_engineer
from agents.quality_eval import quality_eval
from agents.supervisor import route, supervisor
from state import GraphState


def build_graph():
    g = StateGraph(GraphState)

    g.add_node("supervisor", supervisor)
    g.add_node("prompt_engineer", prompt_engineer)
    g.add_node("image_gen", image_gen)
    g.add_node("quality_eval", quality_eval)
    g.add_node("hitl_gate", hitl_gate)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        route,
        {
            "prompt_engineer": "prompt_engineer",
            "image_gen": "image_gen",
            "quality_eval": "quality_eval",
            "hitl_gate": "hitl_gate",
        },
    )
    # Workers return to the supervisor for the next routing decision.
    g.add_edge("prompt_engineer", "supervisor")
    g.add_edge("image_gen", "supervisor")
    g.add_edge("quality_eval", "supervisor")
    g.add_edge("hitl_gate", END)

    # MemorySaver is fine for dev; swap for SqliteSaver to persist across restarts.
    return g.compile(checkpointer=MemorySaver())


# Module-level singleton the API and smoke test import.
graph = build_graph()
