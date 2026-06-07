"""Claude Vision quality scorer. Implemented on Day 2.

Uses claude-opus-4-8 with structured outputs (output_config.format) so the score
is always a schema-valid object — no "ask for JSON ONLY / fallback to 5" parsing.
"""
from __future__ import annotations

VISION_MODEL = "claude-opus-4-8"

# The JSON schema the model is constrained to (used on Day 2).
SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "composition": {"type": "string"},
        "style_match": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "suggested_fix": {"type": "string"},
    },
    "required": ["score", "composition", "style_match", "issues", "suggested_fix"],
    "additionalProperties": False,
}


def score_image(image_url: str, original_brief: str) -> dict:
    """TODO(day2): client.messages.create(model=VISION_MODEL,
    thinking={"type": "adaptive"},
    output_config={"format": {"type": "json_schema", "schema": SCORE_SCHEMA}}, ...)
    with the image passed as a vision content block."""
    raise NotImplementedError("Implemented on Day 2")
