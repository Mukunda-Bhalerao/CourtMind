"""
CourtMind — Strategy Layer: Data Models

Structured output types for the strategy and explainability layer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class WeakElement:
    """An element that is not fully satisfied."""

    element_id: str
    status: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StrongElement:
    """An element with strong evidential support."""

    element_id: str
    evidence_score: float
    supporting_fact_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyReport:
    """
    Unified output from the StrategyEngine.

    All fields are derived deterministically from the CaseAnalysis
    and simulation outputs — no LLM involvement.
    """

    weak_elements: List[Dict[str, Any]] = field(default_factory=list)
    strong_elements: List[Dict[str, Any]] = field(default_factory=list)
    prosecution_strategy: List[str] = field(default_factory=list)
    defense_strategy: List[str] = field(default_factory=list)
    evidence_recommendations: List[str] = field(default_factory=list)
    risk_level: str = "unknown"
    conviction_probability_estimate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
