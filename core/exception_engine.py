"""
CourtMind — Deterministic Exception Negation Engine

Scans the FactMatrix for claimed exceptions (self-defence, insanity, alibi,
etc.), determines which are *supported* (severity ≥ MEDIUM, no conflict),
maps each to the statutory element-ids it negates via the ontology, and
reports whether the full set of required elements has been negated.

The BurdenEngine reads the structured output of this engine rather than
scanning the FactMatrix for exceptions itself.

No LLM.  No side effects.  Fully testable.

Usage
-----
    from core.fact_matrix import FactMatrix
    from core.statute_engine import IPC302Evaluator
    from core.exception_engine import ExceptionEngine

    matrix = FactMatrix()
    # … populate facts (including EXCEPTIONS_CLAIMED) …

    evaluator = IPC302Evaluator()
    eval_result = evaluator.evaluate(matrix)

    engine = ExceptionEngine()
    exc_result = engine.evaluate(matrix, eval_result)
    print(exc_result.to_json())
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, FrozenSet, List, Set, Tuple

from core.fact_matrix import (
    FactCategory,
    FactMatrix,
    Severity,
)
from core.ontology import (
    EXCEPTION_NEGATION_MAP,
    LegalTag,
    resolve_tag,
    validate_tag,
)
from core.statute_engine import (
    ElementStatus,
    EvaluationResult,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEVERITY_RANK: Dict[str, int] = {
    Severity.LOW.value: 0,
    Severity.MEDIUM.value: 1,
    Severity.HIGH.value: 2,
    Severity.CRITICAL.value: 3,
}

# Tags (LegalTag values) that are recognised as exception tags.
_EXCEPTION_TAG_VALUES: FrozenSet[str] = frozenset(
    tag.value for tag in EXCEPTION_NEGATION_MAP
)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ExceptionDetail:
    """Per-exception structured detail."""

    tag: str
    fact_id: str
    statement: str
    severity: str
    supported: bool
    conflicted: bool
    negates_elements: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Convert tuple to list for JSON serialisation.
        d["negates_elements"] = list(d["negates_elements"])
        return d


@dataclass
class ExceptionResult:
    """Structured output of the ExceptionEngine."""

    exceptions_detected: List[Dict[str, Any]] = field(default_factory=list)
    exceptions_supported: List[str] = field(default_factory=list)
    negated_elements: List[str] = field(default_factory=list)
    fully_negated: bool = False
    requires_manual_review: bool = False

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Exception Engine
# ---------------------------------------------------------------------------

class ExceptionEngine:
    """
    Deterministic exception-negation evaluator.

    1. Detects exception facts from ``FactCategory.EXCEPTIONS_CLAIMED``.
    2. Determines support: severity ≥ MEDIUM **and** not in a conflict.
    3. Maps supported exceptions to the element-ids they negate via the
       ontology ``EXCEPTION_NEGATION_MAP``.
    4. Reports whether *all* required elements are negated
       (``fully_negated``).
    5. Flags ``requires_manual_review`` when an exception is present but
       conflicted.

    Zero LLM.  Zero side effects.  Fully testable.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        fact_matrix: FactMatrix,
        evaluation_result: EvaluationResult,
    ) -> ExceptionResult:
        """
        Run the exception-negation analysis.

        Parameters
        ----------
        fact_matrix
            The populated ``FactMatrix`` (must contain exception facts in
            ``FactCategory.EXCEPTIONS_CLAIMED``).
        evaluation_result
            Output of ``StatuteEvaluator.evaluate()``.

        Returns
        -------
        ExceptionResult
        """
        exception_facts = fact_matrix.get_facts(
            FactCategory.EXCEPTIONS_CLAIMED.value
        )

        if not exception_facts:
            return ExceptionResult()

        # Gather conflict fact-ids for quick lookup.
        conflict_ids: Set[str] = set()
        for c in fact_matrix.get_conflicts():
            conflict_ids.add(c.fact_a_id)
            conflict_ids.add(c.fact_b_id)

        # Gather required element-ids from evaluation_result.
        required_element_ids: List[str] = [
            d["element_id"]
            for d in evaluation_result.element_details
            if d.get("required", True)
        ]

        # Walk exception facts.
        details: List[ExceptionDetail] = []
        supported_statements: List[str] = []
        negated_set: Set[str] = set()
        needs_review = False

        for fact in exception_facts:
            # Match exception tags on the fact.
            matched_tags = self._extract_exception_tags(fact.tags)

            for tag_value in matched_tags:
                is_conflicted = fact.id in conflict_ids
                sev_rank = _SEVERITY_RANK.get(fact.severity, 0)
                is_supported = (
                    sev_rank >= _SEVERITY_RANK[Severity.MEDIUM.value]
                    and not is_conflicted
                )

                # Look up negated elements from ontology.
                legal_tag = resolve_tag(tag_value)
                negates = EXCEPTION_NEGATION_MAP.get(legal_tag, ())

                detail = ExceptionDetail(
                    tag=tag_value,
                    fact_id=fact.id,
                    statement=fact.statement,
                    severity=fact.severity,
                    supported=is_supported,
                    conflicted=is_conflicted,
                    negates_elements=negates,
                )
                details.append(detail)

                if is_supported:
                    supported_statements.append(fact.statement)
                    negated_set.update(negates)

                if is_conflicted:
                    needs_review = True

        # Determine fully_negated: every required element is negated.
        fully_negated = (
            bool(required_element_ids)
            and bool(negated_set)
            and all(eid in negated_set for eid in required_element_ids)
        )

        return ExceptionResult(
            exceptions_detected=[d.to_dict() for d in details],
            exceptions_supported=sorted(set(supported_statements)),
            negated_elements=sorted(negated_set),
            fully_negated=fully_negated,
            requires_manual_review=needs_review,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_exception_tags(tags: List[str]) -> List[str]:
        """
        Return tag values from *tags* that are recognised exception tags
        in the ontology ``EXCEPTION_NEGATION_MAP``.
        """
        result: List[str] = []
        for t in tags:
            if t in _EXCEPTION_TAG_VALUES:
                result.append(t)
            else:
                # Try lowercase normalisation.
                low = t.lower()
                if low in _EXCEPTION_TAG_VALUES:
                    result.append(low)
        return result
