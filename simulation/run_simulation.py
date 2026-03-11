"""
CourtMind — Simulation Layer: Full Simulation Entry Point

Orchestrates the complete courtroom simulation:

1. Run ``EvaluationPipeline`` (with optional auto-detect).
2. Convert ``CaseAnalysis`` to dict.
3. Run ``LawyerAgent``.
4. Instantiate 3 ``JudgeAgent`` instances (textualist, evidence_focused,
   burden_strict).
5. Run ``PanelEngine``.
6. Run ``JudgmentWriter``.
7. Return unified result dict.

**Does NOT modify the deterministic engine.**

Usage
-----
    from core.fact_matrix import FactMatrix, FactCategory, FactSource, Severity
    from simulation.run_simulation import run_full_simulation

    matrix = FactMatrix()
    # … populate facts …

    result = run_full_simulation(matrix, auto_detect=True)
    print(result["final_judgment"])
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.evaluation_pipeline import CaseAnalysis, EvaluationPipeline
from core.fact_matrix import FactMatrix
from core.simulation_guardrails import SimulationGuardrails
from research.research_aggregator import ResearchAggregator
from simulation.judge_agent import JudgeAgent
from simulation.judgment_writer import JudgmentWriter
from simulation.lawyer_agent import LawyerAgent
from simulation.panel_engine import PanelEngine


def run_full_simulation(
    fact_matrix: FactMatrix,
    *,
    auto_detect: bool = True,
    research_aggregator: Optional[ResearchAggregator] = None,
    iterative: bool = False,
    max_hearings: int = 5,
    fact_updater: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Execute the full CourtMind simulation pipeline.

    Parameters
    ----------
    fact_matrix : FactMatrix
        The populated fact matrix.
    auto_detect : bool
        Passed through to ``EvaluationPipeline``.
    research_aggregator : ResearchAggregator | None
        If provided, runs precedent + context enrichment.  A default
        no-key (no-op) aggregator is used when ``None``.
    iterative : bool
        If ``True``, delegates to ``HearingManager`` for multi-hearing
        simulation.  Default ``False`` preserves original single-pass
        behaviour.
    max_hearings : int
        Maximum hearing rounds when *iterative* is ``True``.
    fact_updater : callable | None
        ``fn(fact_matrix, feedbacks) -> list[str]`` — callback for
        supplying new facts between hearings (iterative mode only).

    Returns
    -------
    dict
        Single-pass: ``case_analysis``, ``lawyer_output``, ``panel_result``,
        ``final_judgment``, ``research_data``, ``guardrail_report``.
        Iterative: ``hearings``, ``final_result``, ``total_hearings``,
        ``verdict_stable``, optionally ``sentencing``.
        If any critical violation is detected, ``simulation_drift_detected``
        is also set to ``True``.
    """
    # ── Iterative mode: delegate to HearingManager ──────────────
    if iterative:
        from simulation.hearing_manager import HearingManager
        manager = HearingManager(
            max_hearings=max_hearings,
            auto_detect=auto_detect,
            research_aggregator=research_aggregator,
        )
        return manager.run_hearing_cycle(
            fact_matrix,
            fact_updater=fact_updater,
        )

    # ── Single-pass mode (original behaviour) ───────────────────
    guardrails = SimulationGuardrails()
    all_violations: List[str] = []

    # 1. Deterministic analysis
    pipeline = EvaluationPipeline(auto_detect=auto_detect)
    analysis: CaseAnalysis = pipeline.run(fact_matrix)
    case_dict: Dict[str, Any] = analysis.to_dict()

    # 2. Research enrichment (safe no-op when keys absent)
    aggregator = research_aggregator or ResearchAggregator()
    research_data: Dict[str, Any] = aggregator.enrich(case_dict)

    # 3. Lawyer review + guardrail
    lawyer = LawyerAgent()
    lawyer_output: Dict[str, Any] = lawyer.generate(case_dict)

    lawyer_report = guardrails.validate_lawyer_output(case_dict, lawyer_output)
    lawyer_valid: bool = lawyer_report["valid"]
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

    judgment_report = guardrails.validate_final_judgment(case_dict, final_judgment)
    judgment_valid: bool = judgment_report["valid"]
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
    citation_valid: bool = citation_report["valid"]
    all_violations.extend(citation_report["violations"])

    # 7. Assemble result
    result: Dict[str, Any] = {
        "case_analysis": case_dict,
        "lawyer_output": lawyer_output,
        "panel_result": panel_result,
        "final_judgment": final_judgment,
        "research_data": research_data,
        "guardrail_report": {
            "lawyer_valid": lawyer_valid,
            "judge_validations": judge_validations,
            "judgment_valid": judgment_valid,
            "citation_valid": citation_valid,
            "violations": all_violations,
        },
    }

    # 8. Flag simulation drift
    if all_violations:
        result["simulation_drift_detected"] = True

    return result
