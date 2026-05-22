"""
CourtMind — Multi-Section Auto Detection + Ranking System

Automatically detects applicable IPC sections based on a ``FactMatrix`` and
ranks them by legal strength using deterministic scoring.

*   No LLM usage.
*   Uses ``SectionRegistry`` for section discovery.
*   Does **not** mutate the ``FactMatrix``.
*   Evaluates every registered section independently via ``EvaluationPipeline``.
*   Deterministic ranking only.

Usage
-----
    from core.fact_matrix import FactMatrix
    from core.section_auto_detector import SectionAutoDetector

    matrix = FactMatrix()
    # … populate facts …

    detector = SectionAutoDetector()
    result = detector.detect(matrix)
    print(result)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.burden_engine import BurdenEngine
from core.evidence_weight_engine import EvidenceWeightEngine
from core.exception_engine import ExceptionEngine
from core.fact_matrix import FactMatrix
from core.section_registry import SectionRegistry, registry as _default_registry
from core.statute_engine import StatuteEvaluator


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BURDEN_MULTIPLIER: Dict[str, float] = {
    "prosecution_incomplete": 0.2,
    "reasonable_doubt": 0.3,
    "defense_rebuttal_required": 0.5,
    "prima_facie_established": 0.8,
    "exception_established": 0.4,
    "acquittal_recommended": 0.1,
    "manual_review_required": 0.3,
}

_COMBINED_SCORE_THRESHOLD: float = 0.25

# Sections that cover non-lethal offences.  If death-related facts are
# present in the FactMatrix, these sections receive a score penalty so
# they do not outrank lethal-offence sections like 302/304 IPC.
_NON_LETHAL_SECTIONS: frozenset = frozenset({"323 IPC", "420 IPC"})

# Severity ordering for tie-breaking: higher = more severe.
# On equal combined_score, prefer the less-severe charge.
_SECTION_SEVERITY: Dict[str, int] = {
    "302 IPC": 100,   # Murder — most severe
    "304 IPC": 80,    # Culpable Homicide not amounting to Murder
    "420 IPC": 40,    # Cheating
    "323 IPC": 20,    # Causing Hurt — least severe
}

_DEATH_TAGS: frozenset = frozenset({
    "death", "death_caused", "victim_dead", "died", "fatal", "homicide",
})


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class DetectedSection:
    """Structured detail for a single detected section."""

    section: str
    burden_stage: str
    confidence_score: float
    overall_evidence_score: float
    combined_score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DetectionResult:
    """Output of :meth:`SectionAutoDetector.detect`."""

    detected_sections: List[Dict[str, Any]] = field(default_factory=list)
    top_section: str = ""
    top_score: float = 0.0

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Auto Detector
# ---------------------------------------------------------------------------

class SectionAutoDetector:
    """
    Deterministic multi-section detector and ranker.

    For every registered section in the ``SectionRegistry``, runs the full
    ``EvaluationPipeline``, extracts ``burden_stage``, ``confidence_score``,
    and ``overall_evidence_score``, computes a ``combined_score``, and
    returns all qualifying sections sorted descending.

    Zero LLM.  Zero side effects.  Fully testable.
    """

    def __init__(
        self,
        registry: Optional[SectionRegistry] = None,
        *,
        burden_engine: Optional[BurdenEngine] = None,
        evidence_weight_engine: Optional[EvidenceWeightEngine] = None,
        exception_engine: Optional[ExceptionEngine] = None,
    ) -> None:
        self._registry = registry or _default_registry
        self._burden = burden_engine
        self._evidence_weight = evidence_weight_engine
        self._exception = exception_engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, fact_matrix: FactMatrix) -> DetectionResult:
        """
        Detect and rank all registered sections against *fact_matrix*.

        Parameters
        ----------
        fact_matrix : FactMatrix
            The populated fact matrix to evaluate. **Not mutated.**

        Returns
        -------
        DetectionResult
        """
        # Lazy import to avoid circular dependency at module level.
        from core.evaluation_pipeline import EvaluationPipeline

        sections = self._registry.list_registered_sections()
        scored: List[DetectedSection] = []

        for code in sections:
            evaluator = self._registry.get(code)
            pipeline = EvaluationPipeline(
                evaluator=evaluator,
                burden_engine=self._burden or BurdenEngine(),
                evidence_weight_engine=self._evidence_weight or EvidenceWeightEngine(),
                exception_engine=self._exception or ExceptionEngine(),
            )
            analysis = pipeline.run(fact_matrix)

            burden_stage = analysis.burden_stage
            confidence = analysis.confidence_score
            evidence = analysis.overall_evidence_score
            multiplier = _BURDEN_MULTIPLIER.get(burden_stage, 0.0)

            # Element satisfaction ratio — only count truly required elements
            element_details = analysis.evaluation_result.get("element_details", [])
            required_elements = [e for e in element_details if e.get("required", True)]
            n_required = len(required_elements)
            n_satisfied = sum(
                1 for e in required_elements if e.get("status") == "satisfied"
            )
            satisfaction_ratio = n_satisfied / n_required if n_required else 0.0

            combined = round(
                (confidence * 0.4)
                + (evidence * 0.2)
                + (satisfaction_ratio * 0.3)
                + (multiplier * 0.1),
                4,
            )

            scored.append(
                DetectedSection(
                    section=code,
                    burden_stage=burden_stage,
                    confidence_score=confidence,
                    overall_evidence_score=evidence,
                    combined_score=combined,
                )
            )

        # Exception penalty: if a section has required elements negated
        # by supported exceptions, penalise it.  E.g. self-defense negating
        # intention_or_knowledge should push 304 above 302.
        for s in scored:
            exc_data = self._get_exception_data(s.section, fact_matrix)
            negated = exc_data.get("negated_elements", [])
            supported = exc_data.get("exceptions_supported", [])
            if supported and negated:
                # Reduce score proportional to negated elements.
                penalty = 0.15 * len(negated)
                s.combined_score = round(
                    max(s.combined_score - penalty, 0.0), 4,
                )

        # Death-presence penalty: demote non-lethal sections when death
        # facts exist so they never outrank 302/304 IPC.
        if self._has_death_facts(fact_matrix):
            for s in scored:
                if s.section in _NON_LETHAL_SECTIONS:
                    s.combined_score = round(s.combined_score * 0.4, 4)

        # Sort descending by combined_score.  On equal scores prefer
        # the less-severe section (benefit of doubt to the accused).
        scored.sort(
            key=lambda s: (
                s.combined_score,
                -_SECTION_SEVERITY.get(s.section, 50),
            ),
            reverse=True,
        )

        # Apply threshold filter.
        qualifying = [s for s in scored if s.combined_score > _COMBINED_SCORE_THRESHOLD]

        if not qualifying:
            return DetectionResult()

        return DetectionResult(
            detected_sections=[s.to_dict() for s in qualifying],
            top_section=qualifying[0].section,
            top_score=qualifying[0].combined_score,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _has_death_facts(fact_matrix: FactMatrix) -> bool:
        """Return ``True`` if actus_reus facts contain death-related tags or keywords."""
        death_kw = {"died", "death", "killed", "dead", "deceased", "fatal", "homicide"}
        for fact in fact_matrix.get_facts("actus_reus"):
            tags_lower = {t.lower() for t in fact.tags}
            if tags_lower & _DEATH_TAGS:
                return True
            stmt_lower = fact.statement.lower()
            if any(kw in stmt_lower for kw in death_kw):
                return True
        return False

    def _get_exception_data(self, section_code: str, fact_matrix: FactMatrix) -> dict:
        """Run the exception engine for a section and return its result dict."""
        evaluator = self._registry.get(section_code)
        eval_result = evaluator.evaluate(fact_matrix)
        exc_engine = self._exception or ExceptionEngine()
        exc_result = exc_engine.evaluate(fact_matrix, eval_result)
        return exc_result.to_dict()
