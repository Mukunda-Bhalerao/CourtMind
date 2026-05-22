"""
CourtMind — Simulation Layer: Panel Engine

Simulates a 3-judge panel deliberation.

1. Each judge produces independent reasoning.
2. Majority-rule verdict applied.
3. Tie-breaking: highest ``confidence_score`` bias.
4. Final structured verdict returned.

Usage
-----
    from simulation.panel_engine import PanelEngine
    from simulation.judge_agent import JudgeAgent

    judges = [
        JudgeAgent("textualist"),
        JudgeAgent("evidence_focused"),
        JudgeAgent("burden_strict"),
    ]
    panel = PanelEngine(judges)
    result = panel.conduct_panel(case_analysis_dict, lawyer_output)
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from simulation.judge_agent import JudgeAgent


# ---------------------------------------------------------------------------
# Panel Engine
# ---------------------------------------------------------------------------

class PanelEngine:
    """
    Conducts a multi-judge panel deliberation.

    Parameters
    ----------
    judges : list[JudgeAgent]
        Typically three judges with distinct reasoning styles.
    """

    def __init__(self, judges: Optional[List[JudgeAgent]] = None) -> None:
        if judges is None:
            judges = [
                JudgeAgent("textualist"),
                JudgeAgent("evidence_focused"),
                JudgeAgent("burden_strict"),
            ]
        if not judges:
            raise ValueError("Panel requires at least one judge.")
        self._judges = judges

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def conduct_panel(
        self,
        case_analysis: dict,
        lawyer_output: dict,
    ) -> Dict[str, Any]:
        """
        Run the panel deliberation.

        Parameters
        ----------
        case_analysis : dict
            Output of ``CaseAnalysis.to_dict()``.
        lawyer_output : dict
            Output of ``LawyerAgent.generate()``.

        Returns
        -------
        dict
            Panel verdict with majority ruling, vote split, per-judge
            outputs, and confidence level.
        """
        judge_outputs: List[Dict[str, Any]] = []
        for judge in self._judges:
            output = judge.deliberate(case_analysis, lawyer_output)
            judge_outputs.append(output)

        verdicts = [j["provisional_verdict"] for j in judge_outputs]
        majority = self._majority_verdict(verdicts, case_analysis)
        split = self._vote_split(verdicts)
        confidence_level = self._confidence_level(case_analysis, majority)

        return {
            "majority_verdict": majority,
            "vote_split": split,
            "judges": judge_outputs,
            "confidence_level": confidence_level,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _majority_verdict(verdicts: List[str], case_analysis: dict) -> str:
        """
        Determine the majority verdict.

        If a clear majority exists, return it.  On a full three-way tie
        (or no single majority), break the tie by favouring the verdict
        implied by the highest ``confidence_score``:

        *   confidence ≥ 0.7 → ``"convict"``
        *   confidence ≥ 0.4 → ``"review"``
        *   else → ``"acquit"``
        """
        counts = Counter(verdicts)
        if not counts:
            return "review"

        top_count = counts.most_common(1)[0][1]
        leaders = [v for v, c in counts.items() if c == top_count]

        if len(leaders) == 1:
            return leaders[0]

        # Full three-way split (each judge voted differently) —
        # maximum disagreement means the case needs further review.
        if len(counts) >= 3:
            return "review"

        # Two-way tie — break using confidence score.
        confidence = case_analysis.get("burden_result", {}).get(
            "confidence_score", 0.0
        )

        # If exceptions are supported, lean away from conviction.
        exception_result = case_analysis.get("exception_result", {})
        if exception_result.get("exceptions_supported"):
            if "acquit" in leaders:
                return "acquit"
            return "review"

        if confidence >= 0.7:
            return "convict"
        if confidence >= 0.4:
            return "review"
        return "acquit"

    @staticmethod
    def _vote_split(verdicts: List[str]) -> str:
        """Format vote split as e.g. ``"2-1"`` or ``"3-0"``."""
        counts = Counter(verdicts)
        parts = sorted(counts.values(), reverse=True)
        return "-".join(str(p) for p in parts)

    @staticmethod
    def _confidence_level(case_analysis: dict, majority: str) -> str:
        """
        Map the panel outcome to a human-readable confidence label.
        """
        confidence = case_analysis.get("burden_result", {}).get(
            "confidence_score", 0.0
        )
        if majority == "convict" and confidence >= 0.8:
            return "high"
        if majority == "acquit":
            return "high" if confidence < 0.4 else "medium"
        if majority == "review":
            return "low"
        return "medium"
