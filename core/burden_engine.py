"""
CourtMind - Deterministic Burden of Proof Engine

Evaluates the prosecution's burden of proof against a StatuteEvaluator result
and the underlying FactMatrix.  Pure rule-based — no LLM, no narrative text,
no side effects.

Usage
-----
    from core.fact_matrix import FactMatrix, FactCategory, Severity
    from core.statute_engine import IPC302Evaluator
    from core.burden_engine import BurdenEngine

    matrix = FactMatrix()
    # … populate facts …

    evaluator = IPC302Evaluator()
    eval_result = evaluator.evaluate(matrix)

    burden = BurdenEngine()
    verdict = burden.evaluate(eval_result, matrix)
    print(verdict.to_json())
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Tuple

from core.fact_matrix import (
    FactCategory,
    FactMatrix,
    Severity,
)
from core.statute_engine import (
    ElementStatus,
    EvaluationResult,
)

# Late import to avoid circular dependency.  Resolved at first use.
_ExceptionResult = None

def _get_exception_result_class():
    global _ExceptionResult
    if _ExceptionResult is None:
        from core.exception_engine import ExceptionResult as _ER
        _ExceptionResult = _ER
    return _ExceptionResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class BurdenStage(str, Enum):
    """Possible burden-of-proof stages (ordered by severity)."""

    PROSECUTION_INCOMPLETE = "prosecution_incomplete"
    PRIMA_FACIE_ESTABLISHED = "prima_facie_established"
    REASONABLE_DOUBT = "reasonable_doubt"
    DEFENSE_REBUTTAL_REQUIRED = "defense_rebuttal_required"
    EXCEPTION_ESTABLISHED = "exception_established"
    ACQUITTAL_RECOMMENDED = "acquittal_recommended"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


# Severity ranking for internal comparisons
_SEVERITY_RANK: Dict[str, int] = {
    Severity.LOW.value: 0,
    Severity.MEDIUM.value: 1,
    Severity.HIGH.value: 2,
    Severity.CRITICAL.value: 3,
}


# Tags on exception facts that can negate specific required elements
_EXCEPTION_NEGATION_MAP: Dict[str, Tuple[str, ...]] = {
    # exception tag  →  element_ids it can negate
    "self-defense": ("intention_or_knowledge",),
    "self_defense": ("intention_or_knowledge",),
    "insanity": ("intention_or_knowledge",),
    "accident": ("intention_or_knowledge", "act_by_accused"),
    "provocation": ("intention_or_knowledge",),
    "duress": ("intention_or_knowledge",),
    "alibi": ("act_by_accused",),
    "mistaken_identity": ("act_by_accused",),
    "consent": ("act_by_accused",),
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class BurdenResult:
    """Output of the burden-of-proof evaluation."""

    burden_stage: str
    confidence_score: float
    required_elements_satisfied: int
    required_elements_total: int
    conflicted_elements: int
    exceptions_claimed: List[str]
    exceptions_supported: List[str]
    reasoning_flags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Burden Engine
# ---------------------------------------------------------------------------

class BurdenEngine:
    """
    Deterministic burden-of-proof evaluator.

    Call :meth:`evaluate` with the output of a ``StatuteEvaluator`` and the
    ``FactMatrix`` it was built from.  Returns a :class:`BurdenResult` with
    a machine-readable ``burden_stage``, ``confidence_score``, and structured
    ``reasoning_flags``.

    Zero LLM.  Zero side effects.  Fully testable.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        evaluation_result: EvaluationResult,
        fact_matrix: FactMatrix,
        exception_result=None,
    ) -> BurdenResult:
        """
        Run the deterministic rule table against *evaluation_result* and
        *fact_matrix*.

        Parameters
        ----------
        evaluation_result
            Output of ``StatuteEvaluator.evaluate()``.
        fact_matrix
            The same ``FactMatrix`` that was passed to the statute evaluator.
        exception_result : ExceptionResult, optional
            If provided the engine reads exception data from this structured
            result instead of scanning the FactMatrix directly.  This is the
            preferred path when the ``EvaluationPipeline`` is driving the
            evaluation.

        Returns
        -------
        BurdenResult
        """
        flags: List[str] = []

        # ------ gather element-level counts ---------------------------------
        required_total, required_satisfied, conflicted_count, partial_count, \
            failed_ids, conflicted_ids, partial_ids, satisfied_ids = \
            self._count_required_elements(evaluation_result)

        # ------ analyse exceptions ------------------------------------------
        if exception_result is not None:
            # Preferred path — use pre-computed ExceptionResult.
            exceptions_claimed = [
                d.get("statement", "") for d in exception_result.exceptions_detected
            ]
            exceptions_supported = list(exception_result.exceptions_supported)
            negated_elements = list(exception_result.negated_elements)
        else:
            # Legacy / standalone path — scan FactMatrix directly.
            exception_facts = fact_matrix.get_facts(FactCategory.EXCEPTIONS_CLAIMED.value)
            exceptions_claimed = [f.statement for f in exception_facts]
            exceptions_supported = self._get_supported_exceptions(
                exception_facts, fact_matrix
            )
            negated_elements = self._get_negated_elements(exception_facts)

        # ------ confidence score --------------------------------------------
        confidence = self._compute_confidence(
            conflicted_count, partial_count, len(exceptions_claimed)
        )

        # Low-severity intent check
        if self._has_low_severity_intent(evaluation_result, fact_matrix):
            confidence = max(0.0, confidence - 0.10)
            flags.append("LOW_SEVERITY_INTENT")

        # ------ rule table (order matters) ----------------------------------
        stage = self._apply_rules(
            required_total=required_total,
            required_satisfied=required_satisfied,
            conflicted_count=conflicted_count,
            partial_count=partial_count,
            failed_ids=failed_ids,
            conflicted_ids=conflicted_ids,
            exceptions_claimed=exceptions_claimed,
            exceptions_supported=exceptions_supported,
            negated_elements=negated_elements,
            satisfied_ids=satisfied_ids,
            flags=flags,
        )

        return BurdenResult(
            burden_stage=stage.value,
            confidence_score=round(confidence, 2),
            required_elements_satisfied=required_satisfied,
            required_elements_total=required_total,
            conflicted_elements=conflicted_count,
            exceptions_claimed=exceptions_claimed,
            exceptions_supported=exceptions_supported,
            reasoning_flags=flags,
        )

    # ------------------------------------------------------------------
    # Internals — element counting
    # ------------------------------------------------------------------

    @staticmethod
    def _count_required_elements(
        er: EvaluationResult,
    ) -> Tuple[int, int, int, int, List[str], List[str], List[str], List[str]]:
        """
        Walk ``element_details`` and return counts + id lists for required
        elements only.

        Returns
        -------
        (required_total, required_satisfied, conflicted, partial,
         failed_ids, conflicted_ids, partial_ids, satisfied_ids)
        """
        # Only count elements flagged as required.
        total = 0
        satisfied = 0
        conflicted = 0
        partial = 0
        failed_ids: List[str] = []
        conflicted_ids: List[str] = []
        partial_ids: List[str] = []
        satisfied_ids: List[str] = []

        for detail in er.element_details:
            if not detail.get("required", True):
                continue
            total += 1
            status = detail.get("status", "")
            eid = detail.get("element_id", "")
            if status == ElementStatus.SATISFIED.value:
                satisfied += 1
                satisfied_ids.append(eid)
            elif status == ElementStatus.CONFLICTED.value:
                conflicted += 1
                conflicted_ids.append(eid)
            elif status == ElementStatus.PARTIAL.value:
                partial += 1
                partial_ids.append(eid)
            else:
                failed_ids.append(eid)

        return (
            total, satisfied, conflicted, partial,
            failed_ids, conflicted_ids, partial_ids, satisfied_ids,
        )

    # ------------------------------------------------------------------
    # Internals — exception analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _get_supported_exceptions(
        exception_facts: list,
        matrix: FactMatrix,
    ) -> List[str]:
        """
        An exception is *supported* when its severity >= MEDIUM and it is
        not itself involved in a conflict.
        """
        conflict_ids = set()
        for c in matrix.get_conflicts():
            conflict_ids.add(c.fact_a_id)
            conflict_ids.add(c.fact_b_id)

        supported: List[str] = []
        for f in exception_facts:
            if f.id in conflict_ids:
                continue
            if _SEVERITY_RANK.get(f.severity, 0) >= _SEVERITY_RANK[Severity.MEDIUM.value]:
                supported.append(f.statement)
        return supported

    @staticmethod
    def _get_negated_elements(exception_facts: list) -> List[str]:
        """
        Return element_ids that are negated by supported exception tags.
        """
        negated: set = set()
        for f in exception_facts:
            for tag in f.tags:
                tag_lower = tag.lower()
                if tag_lower in _EXCEPTION_NEGATION_MAP:
                    negated.update(_EXCEPTION_NEGATION_MAP[tag_lower])
        return sorted(negated)

    # ------------------------------------------------------------------
    # Internals — confidence
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_confidence(
        conflicted: int,
        partial: int,
        exceptions_claimed_count: int,
    ) -> float:
        score = 1.0
        score -= 0.25 * conflicted
        score -= 0.15 * partial
        if exceptions_claimed_count > 0:
            score -= 0.10
        return max(0.0, min(1.0, score))

    @staticmethod
    def _has_low_severity_intent(
        er: EvaluationResult,
        matrix: FactMatrix,
    ) -> bool:
        """
        Check if the intent/knowledge element is satisfied only by
        LOW-severity facts.
        """
        for detail in er.element_details:
            eid = detail.get("element_id", "")
            if "intention" not in eid and "knowledge" not in eid:
                continue
            if detail.get("status") != ElementStatus.SATISFIED.value:
                continue
            # All matching facts must be LOW for this to trigger
            fact_ids = detail.get("matching_fact_ids", [])
            if not fact_ids:
                continue
            all_low = all(
                _SEVERITY_RANK.get(
                    (matrix.get_fact_by_id(fid) or type("_", (), {"severity": "low"})()).severity,
                    0,
                ) <= _SEVERITY_RANK[Severity.LOW.value]
                for fid in fact_ids
            )
            if all_low:
                return True
        return False

    # ------------------------------------------------------------------
    # Internals — rule table
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_rules(
        *,
        required_total: int,
        required_satisfied: int,
        conflicted_count: int,
        partial_count: int,
        failed_ids: List[str],
        conflicted_ids: List[str],
        exceptions_claimed: List[str],
        exceptions_supported: List[str],
        negated_elements: List[str],
        satisfied_ids: List[str],
        flags: List[str],
    ) -> BurdenStage:
        """Apply the deterministic rule table.  Order of rules matters."""

        # Rule 6 — acquittal (checked early so it takes priority when applicable)
        # Exception established AND it negates a required element that was
        # the prosecution's only path.
        if exceptions_supported and negated_elements:
            # Does the negation target an element that IS satisfied?
            # If so, the exception undermines the prosecution's case.
            negated_and_satisfied = [
                eid for eid in negated_elements if eid in satisfied_ids
            ]
            if negated_and_satisfied:
                flags.append("EXCEPTION_NEGATES_REQUIRED_ELEMENT")
                flags.append("ACQUITTAL_RECOMMENDED")
                return BurdenStage.ACQUITTAL_RECOMMENDED

        # Rule 5 — exception established (supported but does NOT negate)
        if exceptions_supported and not negated_elements:
            flags.append("EXCEPTION_ESTABLISHED_NO_NEGATION")
            return BurdenStage.EXCEPTION_ESTABLISHED

        # Rule 1 — any required element conflicted
        if conflicted_count > 0:
            flags.append("REQUIRED_ELEMENT_CONFLICTED")
            return BurdenStage.REASONABLE_DOUBT

        # Rule 2 — any required element not satisfied (and not partial)
        if failed_ids:
            flags.append("REQUIRED_ELEMENT_MISSING")
            return BurdenStage.PROSECUTION_INCOMPLETE

        # Rule 2b — partial counts as not fully met
        if partial_count > 0 and required_satisfied < required_total:
            flags.append("REQUIRED_ELEMENT_PARTIAL")
            return BurdenStage.PROSECUTION_INCOMPLETE

        # Rule 3 — all required satisfied, no conflicts
        if required_satisfied == required_total and conflicted_count == 0:
            # Rule 4 — but exceptions exist (claimed, not yet supported)
            if exceptions_claimed and not exceptions_supported:
                flags.append("EXCEPTION_CLAIMED_UNRESOLVED")
                return BurdenStage.DEFENSE_REBUTTAL_REQUIRED

            flags.append("ALL_REQUIRED_ELEMENTS_MET")
            return BurdenStage.PRIMA_FACIE_ESTABLISHED

        # Fallback
        flags.append("NO_RULE_MATCHED")
        return BurdenStage.MANUAL_REVIEW_REQUIRED
