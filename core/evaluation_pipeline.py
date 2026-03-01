"""
CourtMind — Evaluation Pipeline

Single entry-point that chains FactMatrix → StatuteEvaluator → BurdenEngine
and returns a unified :class:`CaseAnalysis` result.

*   Does **not** modify the ``EvaluationResult`` or ``BurdenResult`` schemas.
*   Backward-compatible — callers that only need EvaluationResult can still
    use ``StatuteEvaluator.evaluate()`` directly.
*   No LLM.  No side effects.  Fully testable.

Usage
-----
    from core.fact_matrix import FactMatrix, FactCategory, FactSource, Severity
    from core.evaluation_pipeline import EvaluationPipeline, CaseAnalysis

    matrix = FactMatrix()
    # … populate facts …

    pipeline = EvaluationPipeline()          # uses IPC302 by default
    analysis: CaseAnalysis = pipeline.run(matrix)

    print(analysis.to_json())
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.burden_engine import BurdenEngine, BurdenResult
from core.evidence_weight_engine import EvidenceWeightEngine, EvidenceWeightResult
from core.exception_engine import ExceptionEngine, ExceptionResult
from core.fact_matrix import FactMatrix
from core.section_auto_detector import SectionAutoDetector
from core.section_registry import registry as _registry
from core.statute_engine import (
    EvaluationResult,
    StatuteEvaluator,
)


# ---------------------------------------------------------------------------
# Unified Output
# ---------------------------------------------------------------------------

@dataclass
class CaseAnalysis:
    """
    Unified structured output that bundles a statute evaluation with
    a burden-of-proof assessment.

    Fields
    ------
    evaluation_result : dict
        Serialised ``EvaluationResult`` — schema untouched.
    burden_result : dict
        Serialised ``BurdenResult`` — schema untouched.
    metadata : dict
        Pipeline-level metadata (timestamp, evaluator section, etc.).
    """

    evaluation_result: Dict[str, Any]
    burden_result: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    evidence_weight_result: Dict[str, Any] = field(default_factory=dict)
    exception_result: Dict[str, Any] = field(default_factory=dict)

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    # -- convenience accessors -----------------------------------------------

    @property
    def burden_stage(self) -> str:
        """Shortcut into ``burden_result["burden_stage"]``."""
        return self.burden_result.get("burden_stage", "")

    @property
    def confidence_score(self) -> float:
        """Shortcut into ``burden_result["confidence_score"]``."""
        return float(self.burden_result.get("confidence_score", 0.0))

    @property
    def verdict_recommendation(self) -> str:
        """Shortcut into ``evaluation_result["verdict_recommendation"]``."""
        return self.evaluation_result.get("verdict_recommendation", "")

    @property
    def overall_evidence_score(self) -> float:
        """Shortcut into ``evidence_weight_result["overall_evidence_score"]``."""
        return float(self.evidence_weight_result.get("overall_evidence_score", 0.0))

    @property
    def fully_negated(self) -> bool:
        """Shortcut into ``exception_result["fully_negated"]``."""
        return bool(self.exception_result.get("fully_negated", False))

    @property
    def detected_sections(self) -> list:
        """Shortcut into ``metadata["detected_sections"]``.

        Returns an empty list when auto-detection was not used."""
        return self.metadata.get("detected_sections", [])


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class EvaluationPipeline:
    """
    Chains ``StatuteEvaluator`` → ``ExceptionEngine`` → ``BurdenEngine``
    → ``EvidenceWeightEngine`` in a single ``.run()`` call.

    Parameters
    ----------
    evaluator : StatuteEvaluator, optional
        If provided, used directly (dependency-injection).  Otherwise
        resolved from the :class:`SectionRegistry` via *section_code*.
    section_code : str
        IPC section code passed to the registry when *evaluator* is
        ``None``.  Defaults to ``"302 IPC"``.
    burden_engine : BurdenEngine, optional
        Defaults to ``BurdenEngine()``.
    exception_engine : ExceptionEngine, optional
        Defaults to ``ExceptionEngine()``.
    auto_detect : bool
        If ``True``, run :class:`SectionAutoDetector` before evaluator
        resolution and override *section_code* with the detected top
        section.  A manual *evaluator* override still takes priority.
    """

    def __init__(
        self,
        evaluator: Optional[StatuteEvaluator] = None,
        burden_engine: Optional[BurdenEngine] = None,
        *,
        section_code: str = "302 IPC",
        evidence_weight_engine: Optional[EvidenceWeightEngine] = None,
        exception_engine: Optional[ExceptionEngine] = None,
        auto_detect: bool = False,
    ) -> None:
        self._manual_evaluator = evaluator
        self._section_code = section_code
        self._auto_detect = auto_detect
        self._evaluator = evaluator or _registry.get(section_code)
        self._burden = burden_engine or BurdenEngine()
        self._evidence_weight = evidence_weight_engine or EvidenceWeightEngine()
        self._exception = exception_engine or ExceptionEngine()

    # -- public API ----------------------------------------------------------

    def run(self, fact_matrix: FactMatrix) -> CaseAnalysis:
        """
        Execute the full evaluation pipeline.

        1. (Optional) ``SectionAutoDetector.detect(fact_matrix)`` — override
           evaluator with the top-ranked section.
        2. ``StatuteEvaluator.evaluate(fact_matrix)`` → ``EvaluationResult``
        3. ``ExceptionEngine.evaluate(fact_matrix, eval_result)`` → ``ExceptionResult``
        4. ``BurdenEngine.evaluate(eval_result, fact_matrix, exception_result)`` → ``BurdenResult``
        5. ``EvidenceWeightEngine.evaluate(fact_matrix, eval_result)`` → ``EvidenceWeightResult``
        6. Package all into a ``CaseAnalysis``.

        Parameters
        ----------
        fact_matrix : FactMatrix
            The populated fact matrix to evaluate.

        Returns
        -------
        CaseAnalysis
        """
        detection_sections: list = []
        evaluator = self._evaluator

        # Auto-detect: override evaluator unless a manual one was injected.
        if self._auto_detect and self._manual_evaluator is None:
            detector = SectionAutoDetector(
                burden_engine=self._burden,
                evidence_weight_engine=self._evidence_weight,
                exception_engine=self._exception,
            )
            detection = detector.detect(fact_matrix)
            detection_sections = detection.detected_sections
            if detection.top_section:
                evaluator = _registry.get(detection.top_section)

        eval_result: EvaluationResult = evaluator.evaluate(fact_matrix)
        exc_result: ExceptionResult = self._exception.evaluate(
            fact_matrix, eval_result
        )
        burden_result: BurdenResult = self._burden.evaluate(
            eval_result, fact_matrix, exception_result=exc_result
        )
        weight_result: EvidenceWeightResult = self._evidence_weight.evaluate(
            fact_matrix, eval_result
        )

        metadata = self._build_metadata(eval_result)
        if detection_sections:
            metadata["detected_sections"] = detection_sections

        return CaseAnalysis(
            evaluation_result=eval_result.to_dict(),
            burden_result=burden_result.to_dict(),
            metadata=metadata,
            evidence_weight_result=weight_result.to_dict(),
            exception_result=exc_result.to_dict(),
        )

    # -- convenience ---------------------------------------------------------

    @property
    def evaluator(self) -> StatuteEvaluator:
        """Currently configured statute evaluator."""
        return self._evaluator

    @property
    def burden_engine(self) -> BurdenEngine:
        """Currently configured burden engine."""
        return self._burden

    @property
    def evidence_weight_engine(self) -> EvidenceWeightEngine:
        """Currently configured evidence weight engine."""
        return self._evidence_weight

    @property
    def exception_engine(self) -> ExceptionEngine:
        """Currently configured exception engine."""
        return self._exception

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _build_metadata(eval_result: EvaluationResult) -> Dict[str, Any]:
        return {
            "pipeline_version": "1.0.0",
            "section_evaluated": eval_result.section,
            "section_title": eval_result.section_title,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
