"""
CourtMind - Deterministic IPC Statute Evaluation Engine

Rule-based evaluation of IPC sections against a populated FactMatrix.
No LLM. No hallucination. Pure structured logic.

Usage
-----
    from core.fact_matrix import FactMatrix
    from core.statute_engine import IPC302Evaluator

    matrix = FactMatrix()
    matrix.add_fact("actus_reus", "Accused stabbed victim", "witness", tags=["death_caused"])
    ...

    evaluator = IPC302Evaluator()
    result = evaluator.evaluate(matrix)
    print(result.to_json())
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from core.fact_matrix import (
    Fact,
    FactCategory,
    FactMatrix,
    Severity,
)
from core.ontology import get_section_element_tags as _get_section_element_tags


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ElementStatus(str, Enum):
    """Evaluation outcome for a single legal element."""

    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    PARTIAL = "partial"              # some supporting facts, but weak
    CONFLICTED = "conflicted"        # supporting facts exist but contradicted


class Recommendation(str, Enum):
    """Overall verdict recommendation."""

    PROCEED = "Proceed"
    INSUFFICIENT = "Insufficient Elements"
    CONFLICTED = "Conflicted — Manual Review Required"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ElementResult:
    """Evaluation outcome for one legal element."""

    element_id: str
    description: str
    status: str                             # ElementStatus value
    required: bool = True
    matching_fact_ids: List[str] = field(default_factory=list)
    confidence_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationResult:
    """Full evaluation output for a statute section."""

    section: str
    section_title: str
    elements_required: List[str]
    elements_satisfied: List[str]
    elements_failed: List[str]
    elements_partial: List[str]
    elements_conflicted: List[str]
    element_details: List[Dict[str, Any]]
    verdict_recommendation: str             # Recommendation value
    conflicts_found: int
    exceptions_claimed: List[str]
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Element Definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ElementSpec:
    """
    Declarative specification of one legal element to check.

    Parameters
    ----------
    element_id : str
        Unique key, e.g. ``"death_of_human"``.
    description : str
        Human-readable label.
    required_category : str
        Which FactCategory bucket to search.
    match_tags : tuple[str, ...]
        A fact is a *match* if it carries **any** of these tags.
    match_keywords : tuple[str, ...]
        A fact is a *match* if its statement contains **any** of these
        sub-strings (case-insensitive).
    min_severity : str
        Minimum severity to count as strong evidence.
    required : bool
        If ``True`` the element must be satisfied for the section to apply.
    """

    element_id: str
    description: str
    required_category: str
    match_tags: Tuple[str, ...] = ()
    match_keywords: Tuple[str, ...] = ()
    min_severity: str = Severity.LOW.value
    required: bool = True


# ---------------------------------------------------------------------------
# Severity ordering (for >= comparisons)
# ---------------------------------------------------------------------------

_SEVERITY_RANK: Dict[str, int] = {
    Severity.LOW.value: 0,
    Severity.MEDIUM.value: 1,
    Severity.HIGH.value: 2,
    Severity.CRITICAL.value: 3,
}


def _severity_gte(a: str, b: str) -> bool:
    """Return True if severity *a* >= severity *b*."""
    return _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0)


# ---------------------------------------------------------------------------
# Abstract Base Evaluator
# ---------------------------------------------------------------------------

class StatuteEvaluator(ABC):
    """
    Base class for all IPC section evaluators.

    Subclasses define :pyattr:`SECTION`, :pyattr:`SECTION_TITLE`, and
    :pyattr:`ELEMENTS`, then inherit the full evaluation pipeline for free.
    """

    SECTION: str = ""
    SECTION_TITLE: str = ""
    ELEMENTS: Tuple[ElementSpec, ...] = ()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, matrix: FactMatrix) -> EvaluationResult:
        """
        Evaluate the fact matrix against this statute section.

        Returns a fully populated :class:`EvaluationResult`.
        """
        element_results: List[ElementResult] = []
        satisfied: List[str] = []
        failed: List[str] = []
        partial: List[str] = []
        conflicted: List[str] = []

        for spec in self.ELEMENTS:
            result = self._evaluate_element(spec, matrix)
            element_results.append(result)

            if result.status == ElementStatus.SATISFIED.value:
                satisfied.append(spec.description)
            elif result.status == ElementStatus.PARTIAL.value:
                partial.append(spec.description)
            elif result.status == ElementStatus.CONFLICTED.value:
                conflicted.append(spec.description)
            else:
                failed.append(spec.description)

        recommendation = self._determine_recommendation(
            element_results, matrix
        )

        # Collect claimed exceptions
        exception_facts = matrix.get_facts(FactCategory.EXCEPTIONS_CLAIMED.value)
        exceptions_claimed = [f.statement for f in exception_facts]

        return EvaluationResult(
            section=self.SECTION,
            section_title=self.SECTION_TITLE,
            elements_required=[s.description for s in self.ELEMENTS],
            elements_satisfied=satisfied,
            elements_failed=failed,
            elements_partial=partial,
            elements_conflicted=conflicted,
            element_details=[r.to_dict() for r in element_results],
            verdict_recommendation=recommendation.value,
            conflicts_found=len(matrix.get_conflicts()),
            exceptions_claimed=exceptions_claimed,
        )

    # ------------------------------------------------------------------
    # Internals — element matching
    # ------------------------------------------------------------------

    def _evaluate_element(
        self, spec: ElementSpec, matrix: FactMatrix
    ) -> ElementResult:
        """
        Check whether a single element is supported by the fact matrix.

        Matching rules (OR logic — any hit counts):
        1. Fact is in the required category.
        2. AND (fact carries a matching tag OR statement contains a keyword).
        """
        candidates = matrix.get_facts(spec.required_category)
        matching_ids: List[str] = []
        notes: List[str] = []

        for fact in candidates:
            if self._fact_matches(fact, spec):
                matching_ids.append(fact.id)

        # Check if any matched fact is involved in a conflict
        conflict_ids = set()
        for c in matrix.get_conflicts():
            conflict_ids.add(c.fact_a_id)
            conflict_ids.add(c.fact_b_id)

        matched_and_conflicted = [
            fid for fid in matching_ids if fid in conflict_ids
        ]

        # Determine status
        if not matching_ids:
            status = ElementStatus.NOT_SATISFIED
            notes.append(
                f"No facts found in '{spec.required_category}' matching "
                f"tags {spec.match_tags} or keywords {spec.match_keywords}."
            )
        elif matched_and_conflicted and len(matched_and_conflicted) == len(matching_ids):
            # ALL matching facts are conflicted
            status = ElementStatus.CONFLICTED
            notes.append(
                f"All {len(matching_ids)} matching fact(s) are involved in conflicts."
            )
        elif matched_and_conflicted:
            # Some matched facts are conflicted but others are clean
            strong = [
                fid for fid in matching_ids
                if fid not in conflict_ids
                and _severity_gte(
                    matrix.get_fact_by_id(fid).severity, spec.min_severity  # type: ignore[union-attr]
                )
            ]
            if strong:
                status = ElementStatus.SATISFIED
                notes.append(
                    f"{len(strong)} clean fact(s) meet severity threshold; "
                    f"{len(matched_and_conflicted)} conflicted fact(s) noted."
                )
            else:
                status = ElementStatus.PARTIAL
                notes.append(
                    "Matching facts exist but only conflicted or below severity threshold."
                )
        else:
            # No conflicts — check severity
            strong = [
                fid for fid in matching_ids
                if _severity_gte(
                    matrix.get_fact_by_id(fid).severity, spec.min_severity  # type: ignore[union-attr]
                )
            ]
            if strong:
                status = ElementStatus.SATISFIED
                notes.append(f"{len(strong)} fact(s) meet severity threshold.")
            else:
                status = ElementStatus.PARTIAL
                notes.append(
                    "Facts exist but all below required severity threshold."
                )

        return ElementResult(
            element_id=spec.element_id,
            description=spec.description,
            status=status.value,
            required=spec.required,
            matching_fact_ids=matching_ids,
            confidence_notes=notes,
        )

    def _fact_matches(self, fact: Fact, spec: ElementSpec) -> bool:
        """Return ``True`` if *fact* matches at least one tag or keyword."""
        # If no tags AND no keywords defined, every fact in the category matches
        if not spec.match_tags and not spec.match_keywords:
            return True

        fact_tags_lower = {t.lower() for t in fact.tags}

        # Tag match (OR)
        for tag in spec.match_tags:
            if tag.lower() in fact_tags_lower:
                return True

        # Keyword match (OR, case-insensitive substring)
        stmt_lower = fact.statement.lower()
        for kw in spec.match_keywords:
            if kw.lower() in stmt_lower:
                return True

        return False

    # ------------------------------------------------------------------
    # Internals — recommendation
    # ------------------------------------------------------------------

    def _determine_recommendation(
        self,
        results: List[ElementResult],
        matrix: FactMatrix,
    ) -> Recommendation:
        """
        Derive overall recommendation from element results.

        Rules
        -----
        1. If any *required* element is CONFLICTED → ``CONFLICTED``.
        2. If all required elements SATISFIED → ``PROCEED``.
        3. Otherwise → ``INSUFFICIENT``.
        """
        required_specs = {s.element_id for s in self.ELEMENTS if s.required}

        has_conflict = False
        all_required_met = True

        for r in results:
            if r.element_id not in required_specs:
                continue
            if r.status == ElementStatus.CONFLICTED.value:
                has_conflict = True
            if r.status not in (
                ElementStatus.SATISFIED.value,
            ):
                all_required_met = False

        if has_conflict:
            return Recommendation.CONFLICTED
        if all_required_met:
            return Recommendation.PROCEED
        return Recommendation.INSUFFICIENT


# ---------------------------------------------------------------------------
# IPC Section 302 — Murder
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ontology tag extraction helper
# ---------------------------------------------------------------------------

def _ontology_tags(section: str, element_id: str) -> Tuple[str, ...]:
    """Pull the tag set for *element_id* from the ontology as a plain tuple."""
    return tuple(sorted(t.value for t in _get_section_element_tags(section)[element_id]))


class IPC302Evaluator(StatuteEvaluator):
    """
    Deterministic evaluator for **IPC Section 302 — Murder**.

    Required elements
    -----------------
    1. **Death of a human being** — an actus_reus fact confirming death.
    2. **Act by accused caused death** — an actus_reus fact linking the
       accused's conduct to the death.
    3. **Intention to cause death OR knowledge that the act is likely to
       cause death** — a mens_rea fact establishing intent or knowledge.

    Optional enrichment
    --------------------
    * Supporting evidence (evidence category).
    * Claimed exceptions (exceptions_claimed category).
    """

    SECTION = "302 IPC"
    SECTION_TITLE = "Murder"

    ELEMENTS = (
        ElementSpec(
            element_id="death_of_human",
            description="Death of a human being",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=_ontology_tags("302 IPC", "death_of_human"),
            match_keywords=("died", "death", "killed", "dead", "deceased", "fatal"),
            min_severity=Severity.HIGH.value,
            required=True,
        ),
        ElementSpec(
            element_id="act_by_accused",
            description="Act committed by the accused that caused death",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=_ontology_tags("302 IPC", "act_by_accused"),
            match_keywords=(
                "accused", "defendant", "struck", "stabbed", "shot",
                "poisoned", "strangled", "attacked", "assaulted", "hit",
                "beat", "pushed",
            ),
            min_severity=Severity.HIGH.value,
            required=True,
        ),
        ElementSpec(
            element_id="intention_or_knowledge",
            description="Intention to cause death OR knowledge that act is likely to cause death",
            required_category=FactCategory.MENS_REA.value,
            match_tags=_ontology_tags("302 IPC", "intention_or_knowledge"),
            match_keywords=(
                "intended", "premeditated", "planned", "deliberately",
                "willfully", "knowingly", "knew", "aware", "motive",
                "intention", "with intent",
            ),
            min_severity=Severity.MEDIUM.value,
            required=True,
        ),
        # Optional: supporting physical evidence
        ElementSpec(
            element_id="supporting_evidence",
            description="Supporting physical or documentary evidence",
            required_category=FactCategory.EVIDENCE.value,
            match_tags=_ontology_tags("302 IPC", "supporting_evidence"),
            match_keywords=(
                "forensic", "weapon", "blood", "dna", "cctv", "footage",
                "fingerprint", "autopsy", "post-mortem", "witness",
                "testimony", "report",
            ),
            min_severity=Severity.MEDIUM.value,
            required=False,  # strengthens case but not legally required
        ),
    )
