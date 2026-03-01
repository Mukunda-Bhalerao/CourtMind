"""
CourtMind — Evidence Weight Scoring Engine

Deterministic numeric scoring of how strongly the available evidence
supports each satisfied element in an :class:`EvaluationResult`.

**Design constraints**

*   No LLM.  No probabilistic ML.
*   Deterministic numeric scoring only.
*   Does **not** mutate :class:`FactMatrix`.
*   Does **not** modify the ``EvaluationResult`` schema.
*   Fully testable.

Scoring rules
-------------
1. Only elements marked ``"satisfied"`` or ``"partial"`` are scored.
   ``"conflicted"`` elements are forced to **0.0**.
   ``"not_satisfied"`` elements are **ignored entirely**.

2. Per-fact severity weight::

       low      = 0.25
       medium   = 0.50
       high     = 0.75
       critical = 1.00

3. Per-fact source multiplier (additive bonus)::

       forensic   = +0.20
       document   = +0.15
       witness    = +0.10
       confession = +0.05
       user_input =  0.00
       other      =  0.00

4. Element score = sum of (severity_weight + source_multiplier) for each
   matching fact, **capped at 1.0**.

5. ``overall_evidence_score`` = arithmetic mean of all element scores.
   (Elements not scored — ``not_satisfied`` — are excluded from the mean.)

6. Classification thresholds:
   * **strong** ≥ 0.7
   * **weak**   < 0.4

Usage
-----
    from core.evidence_weight_engine import EvidenceWeightEngine

    engine = EvidenceWeightEngine()
    result = engine.evaluate(fact_matrix, evaluation_result)
    print(result)   # EvidenceWeightResult dataclass
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from core.fact_matrix import FactMatrix, Severity, FactSource
from core.statute_engine import ElementStatus, EvaluationResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEVERITY_WEIGHT: Dict[str, float] = {
    Severity.LOW.value: 0.25,
    Severity.MEDIUM.value: 0.50,
    Severity.HIGH.value: 0.75,
    Severity.CRITICAL.value: 1.00,
}

_SOURCE_MULTIPLIER: Dict[str, float] = {
    FactSource.FORENSIC.value: 0.20,
    FactSource.DOCUMENT.value: 0.15,
    FactSource.WITNESS.value: 0.10,
    FactSource.CONFESSION.value: 0.05,
    FactSource.USER_INPUT.value: 0.00,
    FactSource.OTHER.value: 0.00,
    # Sources not listed explicitly default to 0.0
    FactSource.CASE_FILE.value: 0.00,
    FactSource.KANOON.value: 0.00,
}

_STRONG_THRESHOLD: float = 0.7
_WEAK_THRESHOLD: float = 0.4


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

@dataclass
class EvidenceWeightResult:
    """Structured output of the evidence-weight scoring pass."""

    element_scores: Dict[str, float]
    overall_evidence_score: float
    weak_elements: List[str]
    strong_elements: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class EvidenceWeightEngine:
    """
    Deterministic evidence-weight scorer.

    Call :meth:`evaluate` with a :class:`FactMatrix` and an
    :class:`EvaluationResult` to obtain an :class:`EvidenceWeightResult`.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        fact_matrix: FactMatrix,
        evaluation_result: EvaluationResult,
    ) -> EvidenceWeightResult:
        """
        Score each element's supporting evidence.

        Parameters
        ----------
        fact_matrix : FactMatrix
            The populated fact matrix (read-only).
        evaluation_result : EvaluationResult
            The statute evaluation whose element details drive scoring.

        Returns
        -------
        EvidenceWeightResult
        """
        element_scores: Dict[str, float] = {}

        for detail in evaluation_result.element_details:
            element_id: str = detail["element_id"]
            status: str = detail["status"]

            # Rule 1: skip not_satisfied
            if status == ElementStatus.NOT_SATISFIED.value:
                continue

            # Rule 1 (conflicted): force 0.0
            if status == ElementStatus.CONFLICTED.value:
                element_scores[element_id] = 0.0
                continue

            # Satisfied or partial — score the matching facts
            matching_ids: List[str] = detail.get("matching_fact_ids", [])
            score = self._score_facts(fact_matrix, matching_ids)
            element_scores[element_id] = min(score, 1.0)  # Rule 4: cap

        # Rule 6: classify
        strong: List[str] = []
        weak: List[str] = []
        for eid, sc in element_scores.items():
            if sc >= _STRONG_THRESHOLD:
                strong.append(eid)
            elif sc < _WEAK_THRESHOLD:
                weak.append(eid)

        # Rule 5: overall = mean (only scored elements)
        if element_scores:
            overall = sum(element_scores.values()) / len(element_scores)
        else:
            overall = 0.0

        return EvidenceWeightResult(
            element_scores=element_scores,
            overall_evidence_score=round(overall, 4),
            weak_elements=sorted(weak),
            strong_elements=sorted(strong),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _score_facts(
        fact_matrix: FactMatrix,
        fact_ids: List[str],
    ) -> float:
        """Sum severity_weight + source_multiplier for each matching fact."""
        total = 0.0
        for fid in fact_ids:
            fact = fact_matrix.get_fact_by_id(fid)
            if fact is None:
                continue
            severity = fact.severity
            source = fact.source
            total += _SEVERITY_WEIGHT.get(severity, 0.0)
            total += _SOURCE_MULTIPLIER.get(source, 0.0)
        return total
