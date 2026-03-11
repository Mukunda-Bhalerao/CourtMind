"""
CourtMind — Simulation Event Models

Structured event types and data models that drive the animated
courtroom UI.  Every event captures *who* spoke, *what* happened,
and optional metadata for rich rendering.

**Pure data — no logic here.**
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict


class EventType(str, Enum):
    """All possible courtroom simulation event types."""

    CASE_START = "case_start"
    VICTIM_STATEMENT = "victim_statement"
    ACCUSED_STATEMENT = "accused_statement"
    PROSECUTOR_ARGUMENT = "prosecutor_argument"
    DEFENSE_ARGUMENT = "defense_argument"
    EVIDENCE_PRESENTED = "evidence_presented"
    JUDGE_QUESTION = "judge_question"
    JUDGE_THINKING = "judge_thinking"
    PANEL_DELIBERATION = "panel_deliberation"
    JUDGE_VOTE = "judge_vote"
    VERDICT_DELIVERED = "verdict_delivered"
    STRATEGY_PRESENTED = "strategy_presented"
    EXPLANATION_DISPLAYED = "explanation_displayed"
    HEARING_FEEDBACK = "hearing_feedback"
    HEARING_UPDATE = "hearing_update"


# Canonical ordering used by the generator to lay out events in
# courtroom-natural sequence.  Types not listed here are appended at
# the end in encounter order.
EVENT_ORDER: list[EventType] = [
    EventType.CASE_START,
    EventType.VICTIM_STATEMENT,
    EventType.ACCUSED_STATEMENT,
    EventType.PROSECUTOR_ARGUMENT,
    EventType.DEFENSE_ARGUMENT,
    EventType.EVIDENCE_PRESENTED,
    EventType.JUDGE_THINKING,
    EventType.PANEL_DELIBERATION,
    EventType.JUDGE_VOTE,
    EventType.VERDICT_DELIVERED,
    EventType.STRATEGY_PRESENTED,
    EventType.EXPLANATION_DISPLAYED,
    EventType.HEARING_FEEDBACK,
    EventType.HEARING_UPDATE,
]


@dataclass
class Event:
    """A single courtroom simulation event."""

    event_id: str
    event_type: str          # EventType.value
    actor: str               # e.g. "prosecutor", "textualist_judge"
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0   # relative seconds from simulation start

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


@dataclass
class EventTimeline:
    """Container returned by the event generator."""

    events: list[Dict[str, Any]] = field(default_factory=list)
    total_events: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
