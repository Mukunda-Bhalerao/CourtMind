"""
CourtMind — Multi-Hearing Courtroom Simulation Manager

Orchestrates iterative hearing rounds where judges may request
additional information before rendering a final verdict.

Eight feedback loops:

1. **Evidence Expansion** — weak evidence triggers request for more.
2. **Clarification** — partially satisfied elements need clarification.
3. **Exception Validation** — claimed but unsupported exceptions.
4. **Section Re-evaluation** — new facts may change legal classification.
5. **Conflict Resolution** — unresolved contradictions in the FactMatrix.
6. **Argument Refinement** — judges identify lawyer argument weaknesses.
7. **Precedent / Research** — legal ambiguity warrants case law lookup.
8. **Sentencing Phase** — conviction triggers sentencing recommendation.

**Strict rules**

*   Does NOT modify deterministic engine logic.
*   FactMatrix is the single source of truth.
*   All new behaviour is optional and backward-compatible.
*   Previous hearing results are never mutated.

Usage
-----
    from simulation.hearing_manager import HearingManager
    from core.fact_matrix import FactMatrix, FactSource

    fm = FactMatrix()
    # … populate …

    manager = HearingManager()
    result = manager.run_hearing_cycle(fm)
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.evaluation_pipeline import CaseAnalysis, EvaluationPipeline
from core.fact_matrix import FactMatrix
from core.simulation_guardrails import SimulationGuardrails
from research.research_aggregator import ResearchAggregator
from simulation.judge_agent import JudgeAgent
from simulation.judgment_writer import JudgmentWriter
from simulation.lawyer_agent import LawyerAgent
from simulation.panel_engine import PanelEngine


# ---------------------------------------------------------------------------
# Feedback type enum
# ---------------------------------------------------------------------------

class FeedbackType(str, Enum):
    """Possible judge feedback types that can trigger a new hearing."""

    EVIDENCE_REQUEST = "evidence_request"
    CLARIFICATION_REQUEST = "clarification_request"
    EXCEPTION_VALIDATION = "exception_validation"
    SECTION_REVIEW = "section_review"
    CONFLICT_RESOLUTION = "conflict_resolution"
    ARGUMENT_REFINEMENT = "argument_refinement"
    PRECEDENT_REQUEST = "precedent_request"
    SENTENCING_PHASE = "sentencing_phase"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HearingFeedback:
    """A single piece of judge feedback requesting further action."""

    type: str
    message: str
    requested_element: str = ""
    severity: str = "medium"
    requires_update: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HearingRound:
    """Record of one hearing iteration."""

    hearing_number: int
    case_analysis: Dict[str, Any] = field(default_factory=dict)
    lawyer_output: Dict[str, Any] = field(default_factory=dict)
    panel_result: Dict[str, Any] = field(default_factory=dict)
    final_judgment: str = ""
    feedback: List[Dict[str, Any]] = field(default_factory=list)
    updates_applied: List[str] = field(default_factory=list)
    research_data: Dict[str, Any] = field(default_factory=dict)
    guardrail_report: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Sentencing helper
# ---------------------------------------------------------------------------

_SEVERITY_TO_YEARS: Dict[str, str] = {
    "critical": "life imprisonment or 14–20 years rigorous imprisonment",
    "high": "7–14 years rigorous imprisonment",
    "medium": "3–7 years imprisonment",
    "low": "up to 3 years imprisonment or fine",
}


def _compute_sentencing(
    case_analysis: Dict[str, Any],
    fact_matrix: FactMatrix,
) -> Dict[str, Any]:
    """
    Deterministic sentencing recommendation based on evaluation results
    and fact severity.
    """
    eval_result = case_analysis.get("evaluation_result", {})
    burden_result = case_analysis.get("burden_result", {})
    evidence_weight = case_analysis.get("evidence_weight_result", {})

    section = eval_result.get("section", "unknown")
    confidence = float(burden_result.get("confidence_score", 0.0))
    evidence_score = float(evidence_weight.get("overall_evidence_score", 0.0))

    # Determine max severity from actus_reus facts
    severity_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    all_actus = fact_matrix.get_facts("actus_reus")
    max_severity = all_actus[0].severity if all_actus else "medium"
    for fact in all_actus:
        if severity_rank.get(fact.severity, 0) > severity_rank.get(max_severity, 0):
            max_severity = fact.severity

    # Aggravating: high confidence + high evidence
    aggravating: List[str] = []
    if confidence >= 0.8:
        aggravating.append("High confidence in prosecution case")
    if evidence_score >= 0.8:
        aggravating.append("Strong corroborating evidence")
    for fact in fact_matrix.get_facts("mens_rea"):
        if "premeditated" in [t.lower() for t in fact.tags]:
            aggravating.append("Premeditated act")
            break

    # Mitigating: exceptions claimed, low severity
    mitigating: List[str] = []
    exception_result = case_analysis.get("exception_result", {})
    for exc in exception_result.get("exceptions_detected", []):
        if exc.get("supported"):
            mitigating.append(f"Supported exception: {exc.get('tag', 'unknown')}")
    if max_severity in ("low", "medium"):
        mitigating.append(f"Fact severity is {max_severity}")

    recommendation = _SEVERITY_TO_YEARS.get(max_severity, "as per court discretion")

    return {
        "section": section,
        "max_fact_severity": max_severity,
        "aggravating_factors": aggravating,
        "mitigating_factors": mitigating,
        "sentence_recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Hearing Manager
# ---------------------------------------------------------------------------

class HearingManager:
    """
    Orchestrates iterative multi-hearing courtroom simulation.

    Runs up to *max_hearings* rounds.  At each round:
    1. Run ``EvaluationPipeline`` + ``run_full_simulation`` equivalent.
    2. Collect judge feedback.
    3. If feedback requires updates and a ``fact_updater`` callback is
       provided, apply updates to the FactMatrix.
    4. Re-run if verdict is unstable or feedback pending.
    5. Stop when verdict stabilises or *max_hearings* reached.

    Parameters
    ----------
    max_hearings : int
        Upper bound on hearing rounds (default 5).
    auto_detect : bool
        Passed through to ``EvaluationPipeline``.
    research_aggregator : ResearchAggregator | None
        Optional research enrichment.
    """

    def __init__(
        self,
        *,
        max_hearings: int = 5,
        auto_detect: bool = True,
        research_aggregator: Optional[ResearchAggregator] = None,
    ) -> None:
        if max_hearings < 1:
            raise ValueError("max_hearings must be at least 1.")
        self._max_hearings = max_hearings
        self._auto_detect = auto_detect
        self._aggregator = research_aggregator or ResearchAggregator()

    @property
    def max_hearings(self) -> int:
        return self._max_hearings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_hearing_cycle(
        self,
        fact_matrix: FactMatrix,
        *,
        fact_updater: Optional[Callable[[FactMatrix, List[HearingFeedback]], List[str]]] = None,
    ) -> Dict[str, Any]:
        """
        Run the iterative hearing cycle.

        Parameters
        ----------
        fact_matrix : FactMatrix
            The case fact matrix (will be mutated if *fact_updater* is
            provided and feedback requests updates).
        fact_updater : callable, optional
            ``fn(fact_matrix, feedbacks) -> list[str]``
            Called when feedback requests updates.  Returns list of
            human-readable descriptions of updates applied.  If ``None``,
            the loop still runs but no external facts are added — only
            internal loops (argument refinement, research, sentencing)
            can act.

        Returns
        -------
        dict
            Keys: ``hearings``, ``final_result``, ``total_hearings``,
            ``verdict_stable``, ``sentencing`` (if applicable).
        """
        hearings: List[Dict[str, Any]] = []
        previous_verdict: Optional[str] = None
        verdict_stable = False
        sentencing: Optional[Dict[str, Any]] = None
        last_result: Dict[str, Any] = {}

        for hearing_num in range(1, self._max_hearings + 1):
            # 1. Run full simulation for this hearing
            round_result = self._run_single_hearing(fact_matrix)
            case_analysis = round_result["case_analysis"]
            panel_result = round_result["panel_result"]
            current_verdict = panel_result.get("majority_verdict", "review")

            # 2. Collect judge feedback
            feedbacks = self.collect_judge_feedback(
                case_analysis, panel_result, round_result, fact_matrix,
            )

            # 3. Determine updates
            updates_applied: List[str] = []

            # 3a. Internal loops that don't need user input
            internal_updates = self._apply_internal_feedback(
                feedbacks, case_analysis, round_result, fact_matrix,
            )
            updates_applied.extend(internal_updates)

            # 3b. External updates via callback
            external_feedbacks = [
                fb for fb in feedbacks if fb.requires_update and fb.type not in (
                    FeedbackType.ARGUMENT_REFINEMENT.value,
                    FeedbackType.PRECEDENT_REQUEST.value,
                    FeedbackType.SENTENCING_PHASE.value,
                )
            ]
            if external_feedbacks and fact_updater is not None:
                ext_updates = fact_updater(fact_matrix, external_feedbacks)
                updates_applied.extend(ext_updates)

            # 4. Build hearing round record
            hearing_round = HearingRound(
                hearing_number=hearing_num,
                case_analysis=case_analysis,
                lawyer_output=round_result["lawyer_output"],
                panel_result=panel_result,
                final_judgment=round_result["final_judgment"],
                feedback=[fb.to_dict() for fb in feedbacks],
                updates_applied=updates_applied,
                research_data=round_result["research_data"],
                guardrail_report=round_result["guardrail_report"],
            )
            hearings.append(hearing_round.to_dict())
            last_result = round_result

            # 5. Check verdict stability
            if previous_verdict is not None and current_verdict == previous_verdict:
                verdict_stable = True

            # 6. Sentencing phase (loop 8)
            sentencing_fb = [
                fb for fb in feedbacks
                if fb.type == FeedbackType.SENTENCING_PHASE.value
            ]
            if sentencing_fb:
                sentencing = _compute_sentencing(case_analysis, fact_matrix)

            # 7. Stop conditions
            if verdict_stable:
                break
            if not any(fb.requires_update for fb in feedbacks):
                verdict_stable = True
                break

            previous_verdict = current_verdict

        final = {
            "hearings": hearings,
            "final_result": last_result,
            "total_hearings": len(hearings),
            "verdict_stable": verdict_stable,
        }
        if sentencing is not None:
            final["sentencing"] = sentencing

        return final

    # ------------------------------------------------------------------
    # Feedback collection
    # ------------------------------------------------------------------

    def collect_judge_feedback(
        self,
        case_analysis: Dict[str, Any],
        panel_result: Dict[str, Any],
        simulation_result: Dict[str, Any],
        fact_matrix: FactMatrix,
    ) -> List[HearingFeedback]:
        """
        Analyse the simulation result and produce structured feedback
        items that may trigger further hearings.
        """
        feedbacks: List[HearingFeedback] = []

        eval_result = case_analysis.get("evaluation_result", {})
        burden_result = case_analysis.get("burden_result", {})
        evidence_weight = case_analysis.get("evidence_weight_result", {})
        exception_result = case_analysis.get("exception_result", {})
        metadata = case_analysis.get("metadata", {})

        evidence_score = float(evidence_weight.get("overall_evidence_score", 0.0))
        burden_stage = burden_result.get("burden_stage", "unknown")
        confidence = float(burden_result.get("confidence_score", 0.0))
        majority_verdict = panel_result.get("majority_verdict", "review")

        element_details = eval_result.get("element_details", [])

        # --- Loop 1: Evidence Expansion ---
        if evidence_score <= 0.6:
            weak_elements = [
                e.get("element_id", "?") for e in element_details
                if e.get("status") != "satisfied"
            ]
            feedbacks.append(HearingFeedback(
                type=FeedbackType.EVIDENCE_REQUEST.value,
                message=(
                    f"Evidence score ({evidence_score:.2f}) is below threshold. "
                    f"Additional evidence requested for: {', '.join(weak_elements) or 'general strengthening'}."
                ),
                requested_element=", ".join(weak_elements),
                severity="high" if evidence_score < 0.3 else "medium",
                requires_update=True,
            ))

        # --- Loop 2: Clarification ---
        partial_elements = [
            e for e in element_details
            if e.get("status") in ("partial", "not_satisfied")
            and e.get("required", True)
        ]
        for elem in partial_elements:
            eid = elem.get("element_id", "?")
            feedbacks.append(HearingFeedback(
                type=FeedbackType.CLARIFICATION_REQUEST.value,
                message=f"Element '{eid}' is {elem.get('status')} — clarification needed.",
                requested_element=eid,
                severity="medium",
                requires_update=True,
            ))

        # --- Loop 3: Exception Validation ---
        for exc in exception_result.get("exceptions_detected", []):
            if not exc.get("supported", False):
                tag = exc.get("tag", "unknown")
                feedbacks.append(HearingFeedback(
                    type=FeedbackType.EXCEPTION_VALIDATION.value,
                    message=f"Exception '{tag}' claimed but lacks supporting evidence.",
                    requested_element=tag,
                    severity="medium",
                    requires_update=True,
                ))

        # --- Loop 4: Section Re-evaluation ---
        detected = metadata.get("detected_sections", [])
        current_section = eval_result.get("section", "")
        if detected and len(detected) > 1:
            top = detected[0]
            if isinstance(top, dict):
                top_section = top.get("section", "")
            else:
                top_section = str(top)
            if top_section and top_section != current_section:
                feedbacks.append(HearingFeedback(
                    type=FeedbackType.SECTION_REVIEW.value,
                    message=(
                        f"Section auto-detector suggests '{top_section}' "
                        f"may be more appropriate than '{current_section}'."
                    ),
                    requested_element=top_section,
                    severity="high",
                    requires_update=True,
                ))

        # --- Loop 5: Conflict Resolution ---
        conflicts = fact_matrix.get_conflicts()
        if conflicts:
            conflict_desc = "; ".join(c.reason for c in conflicts[:3])
            feedbacks.append(HearingFeedback(
                type=FeedbackType.CONFLICT_RESOLUTION.value,
                message=f"Unresolved conflicts in fact matrix: {conflict_desc}.",
                requested_element="conflicts",
                severity="high",
                requires_update=True,
            ))

        # --- Loop 6: Argument Refinement ---
        guardrail_report = simulation_result.get("guardrail_report", {})
        violations = guardrail_report.get("violations", [])
        if violations:
            feedbacks.append(HearingFeedback(
                type=FeedbackType.ARGUMENT_REFINEMENT.value,
                message=(
                    f"Guardrail violations detected ({len(violations)}). "
                    "Lawyer arguments should be refined."
                ),
                requested_element="arguments",
                severity="medium",
                requires_update=True,
            ))

        # --- Loop 7: Precedent / Research ---
        if confidence < 0.5 or burden_stage in (
            "reasonable_doubt", "manual_review_required", "prosecution_incomplete",
        ):
            feedbacks.append(HearingFeedback(
                type=FeedbackType.PRECEDENT_REQUEST.value,
                message="Legal ambiguity detected — requesting case precedents.",
                requested_element="precedents",
                severity="medium",
                requires_update=True,
            ))

        # --- Loop 8: Sentencing Phase ---
        if majority_verdict == "convict":
            feedbacks.append(HearingFeedback(
                type=FeedbackType.SENTENCING_PHASE.value,
                message="Verdict is 'convict' — sentencing phase triggered.",
                requested_element="sentencing",
                severity="high",
                requires_update=False,
            ))

        return feedbacks

    # ------------------------------------------------------------------
    # Fact matrix updates
    # ------------------------------------------------------------------

    @staticmethod
    def update_fact_matrix(
        fact_matrix: FactMatrix,
        feedbacks: List[HearingFeedback],
        fact_updater: Callable[[FactMatrix, List[HearingFeedback]], List[str]],
    ) -> List[str]:
        """
        Apply external updates to the FactMatrix based on feedback.

        Delegates to the *fact_updater* callback.
        """
        return fact_updater(fact_matrix, feedbacks)

    # ------------------------------------------------------------------
    # Internal feedback application
    # ------------------------------------------------------------------

    def _apply_internal_feedback(
        self,
        feedbacks: List[HearingFeedback],
        case_analysis: Dict[str, Any],
        simulation_result: Dict[str, Any],
        fact_matrix: FactMatrix,
    ) -> List[str]:
        """
        Handle feedback types that can be resolved without user input:
        argument refinement, precedent requests, sentencing.
        """
        updates: List[str] = []

        for fb in feedbacks:
            if fb.type == FeedbackType.ARGUMENT_REFINEMENT.value:
                # Re-run lawyer with current analysis (already done in next loop)
                updates.append("Lawyer arguments will be regenerated in next hearing.")
                fb.requires_update = False

            elif fb.type == FeedbackType.PRECEDENT_REQUEST.value:
                research_data = self._aggregator.enrich(case_analysis)
                if research_data.get("precedents") or research_data.get("recent_context"):
                    updates.append(
                        f"Research enrichment applied: "
                        f"{len(research_data.get('precedents', []))} precedents, "
                        f"{len(research_data.get('recent_context', []))} context items."
                    )
                fb.requires_update = False

            elif fb.type == FeedbackType.SENTENCING_PHASE.value:
                # Sentencing is computed in the main loop
                fb.requires_update = False

        return updates

    # ------------------------------------------------------------------
    # Single hearing execution
    # ------------------------------------------------------------------

    def _run_single_hearing(
        self,
        fact_matrix: FactMatrix,
    ) -> Dict[str, Any]:
        """
        Execute one full hearing round (equivalent to run_full_simulation).

        Returns the same dict shape as ``run_full_simulation()``.
        """
        guardrails = SimulationGuardrails()
        all_violations: List[str] = []

        # 1. Deterministic analysis
        pipeline = EvaluationPipeline(auto_detect=self._auto_detect)
        analysis: CaseAnalysis = pipeline.run(fact_matrix)
        case_dict: Dict[str, Any] = analysis.to_dict()

        # 2. Research enrichment
        research_data: Dict[str, Any] = self._aggregator.enrich(case_dict)

        # 3. Lawyer review + guardrail
        lawyer = LawyerAgent()
        lawyer_output: Dict[str, Any] = lawyer.generate(case_dict)

        lawyer_report = guardrails.validate_lawyer_output(case_dict, lawyer_output)
        all_violations.extend(lawyer_report["violations"])

        # 4. Panel deliberation + per-judge guardrails
        judges = [
            JudgeAgent("textualist"),
            JudgeAgent("evidence_focused"),
            JudgeAgent("burden_strict"),
        ]
        panel = PanelEngine(judges)
        panel_result: Dict[str, Any] = panel.conduct_panel(case_dict, lawyer_output)

        judge_validations: List[bool] = []
        for judge_out in panel_result.get("judges", []):
            jr = guardrails.validate_judge_output(case_dict, judge_out)
            judge_validations.append(jr["valid"])
            all_violations.extend(jr["violations"])

        # 5. Judgment narrative + guardrail
        writer = JudgmentWriter()
        final_judgment: str = writer.compose(case_dict, panel_result)

        judgment_report = guardrails.validate_final_judgment(
            case_dict, final_judgment,
        )
        all_violations.extend(judgment_report["violations"])

        # 6. Citation guardrail
        simulation_output = {
            "lawyer_output": lawyer_output,
            "panel_result": panel_result,
            "final_judgment": final_judgment,
        }
        citation_report = guardrails.validate_citations(
            case_dict, simulation_output, research_data,
        )
        all_violations.extend(citation_report["violations"])

        result: Dict[str, Any] = {
            "case_analysis": case_dict,
            "lawyer_output": lawyer_output,
            "panel_result": panel_result,
            "final_judgment": final_judgment,
            "research_data": research_data,
            "guardrail_report": {
                "lawyer_valid": lawyer_report["valid"],
                "judge_validations": judge_validations,
                "judgment_valid": judgment_report["valid"],
                "citation_valid": citation_report["valid"],
                "violations": all_violations,
            },
        }

        if all_violations:
            result["simulation_drift_detected"] = True

        return result
