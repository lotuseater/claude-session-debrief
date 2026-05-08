"""session_debrief — read a Claude Code transcript, write a markdown retro."""

from .parser import Session, parse, ToolUse, UserPrompt, AssistantTurn
from .heuristics import (
    Debrief,
    debrief,
    goal_outcome,
    reading_economy,
    flow_report,
    decision_points,
    best_span,
    thinking_profile,
)
from .renderer import render
from .locator import (
    TranscriptInfo,
    list_transcripts,
    most_recent,
    recent,
    transcripts_root,
    format_menu,
)
from .multi import MultiDebrief, aggregate

__version__ = "0.1.0"

__all__ = [
    "Session",
    "ToolUse",
    "UserPrompt",
    "AssistantTurn",
    "parse",
    "Debrief",
    "debrief",
    "goal_outcome",
    "reading_economy",
    "flow_report",
    "decision_points",
    "best_span",
    "thinking_profile",
    "render",
    "TranscriptInfo",
    "list_transcripts",
    "most_recent",
    "recent",
    "transcripts_root",
    "format_menu",
    "MultiDebrief",
    "aggregate",
    "__version__",
]
