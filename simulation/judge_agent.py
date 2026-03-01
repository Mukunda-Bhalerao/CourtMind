"""
CourtMind — Simulation Layer: Judge Agent

Simulates individual judge reasoning styles:

*   **textualist** — focuses on literal element satisfaction.
*   **evidence_focused** — weighs evidence scores most heavily.
*   **burden_strict** — insists on full burden-of-proof discharge.

Each judge accepts a ``CaseAnalysis`` dict and the ``LawyerAgent`` output,
then produces structured reasoning.  No facts are invented; all reasoning
is derived from the structured inputs.

Usage
-----
    from simulation.judge_agent import JudgeAgent

    judge = JudgeAgent("textualist")
    output = judge.deliberate(case_analysis_dict, lawyer_output)
"""

from __future__ import annotations

from typing import Any, Dict, List

_VALID_JUDGE_TYPES = frozenset({"textualist", "evidence_focused", "burden_strict"})


# ---------------------------------------------------------------------------
# Judge Agent
# ---------------------------------------------------------------------------

class JudgeAgent:
    """
    Simulates a single judge with a defined reasoning style.

    Parameters
    ----------
    judge_type : str
        One of ``"textualist"``, ``"evidence_focused"``, ``"burden_strict"``.
    """

    def __init__(self, judge_type: str) -> None:
        if judge_type not in _VALID_JUDGE_TYPES:
            raise ValueError(
                f"Unknown judge_type {judge_type!r}. "
                f"Must be one of {sorted(_VALID_JUDGE_TYPES)}."
            )
        self._judge_type = judge_type

    @property
    def judge_type(self) -> str:
        return self._judge_type

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deliberate(
        self,
        case_analysis: dict,
        lawyer_output: dict,
    ) -> Dict[str, Any]:
        """
        Produce structured judicial reasoning.

        Parameters
        ----------
        case_analysis : dict
            Output of ``CaseAnalysis.to_dict()``.
        lawyer_output : dict
            Output of ``LawyerAgent.generate()``.

        Returns
        -------
        dict
        """
        eval_result = case_analysis.get("evaluation_result", {})
        burden_result = case_analysis.get("burden_result", {})
        evidence_weight = case_analysis.get("evidence_weight_result", {})
        exception_result = case_analysis.get("exception_result", {})

        burden_stage = burden_result.get("burden_stage", "unknown")
        confidence = burden_result.get("confidence_score", 0.0)
        evidence_score = evidence_weight.get("overall_evidence_score", 0.0)
        elements_satisfied = eval_result.get("elements_satisfied", 0)
        elements_required = eval_result.get("elements_required", 0)

        handler = {
            "textualist": self._textualist_reasoning,
            "evidence_focused": self._evidence_focused_reasoning,
            "burden_strict": self._burden_strict_reasoning,
        }[self._judge_type]

        reasoning, concerns, verdict = handler(
            eval_result=eval_result,
            burden_result=burden_result,
            evidence_score=evidence_score,
            exception_result=exception_result,
            lawyer_output=lawyer_output,
        )

        return {
            "judge_type": self._judge_type,
            "agreement_with_lawyer": self._agrees_with_lawyer(
                verdict, lawyer_output,
            ),
            "key_reasoning_points": reasoning,
            "concerns": concerns,
            "provisional_verdict": verdict,
        }

    # ------------------------------------------------------------------
    # Textualist
    # ------------------------------------------------------------------

    @staticmethod
    def _textualist_reasoning(
        *,
        eval_result: dict,
        burden_result: dict,
        evidence_score: float,
        exception_result: dict,
        lawyer_output: dict,
    ) -> tuple:
        """Strict literal reading: every required element must be satisfied."""
        reasoning: List[str] = []
        concerns: List[str] = []

        element_details = eval_result.get("element_details", [])
        all_required_met = True

        for elem in element_details:
            if not elem.get("required", True):
                continue
            eid = elem.get("element_id", "?")
            status = elem.get("status", "")
            if status == "satisfied":
                reasoning.append(
                    f"Element '{eid}' is textually satisfied."
                )
            else:
                all_required_met = False
                concerns.append(
                    f"Element '{eid}' status is '{status}' — "
                    f"textual requirement not met."
                )

        if exception_result.get("fully_negated"):
            concerns.append("Exceptions fully negate required elements.")

        if all_required_met and not exception_result.get("fully_negated"):
            verdict = "convict"
            reasoning.append("All textual requirements fulfilled.")
        elif exception_result.get("fully_negated"):
            verdict = "acquit"
            reasoning.append("Exception negation overrides satisfied elements.")
        else:
            verdict = "acquit"
            reasoning.append("Textual requirements not fully met — acquit.")

        return reasoning, concerns, verdict

    # ------------------------------------------------------------------
    # Evidence-focused
    # ------------------------------------------------------------------

    @staticmethod
    def _evidence_focused_reasoning(
        *,
        eval_result: dict,
        burden_result: dict,
        evidence_score: float,
        exception_result: dict,
        lawyer_output: dict,
    ) -> tuple:
        """Weighs overall evidence strength most heavily."""
        reasoning: List[str] = []
        concerns: List[str] = []

        reasoning.append(
            f"Overall evidence score: {evidence_score}."
        )

        confidence = burden_result.get("confidence_score", 0.0)
        reasoning.append(
            f"Confidence score: {confidence}."
        )

        if evidence_score >= 0.7:
            reasoning.append("Evidence strongly supports prosecution.")
        elif evidence_score >= 0.4:
            reasoning.append("Evidence is moderate — case is arguable.")
        else:
            reasoning.append("Evidence is weak.")

        conflicted = burden_result.get("conflicted_elements", 0)
        if conflicted > 0:
            concerns.append(
                f"{conflicted} element(s) have conflicting evidence."
            )

        weaknesses = lawyer_output.get("identified_weaknesses", [])
        if weaknesses:
            concerns.append(
                f"Lawyer identified {len(weaknesses)} weakness(es)."
            )

        if exception_result.get("fully_negated"):
            concerns.append("Exceptions fully negate required elements.")
            verdict = "acquit"
        elif evidence_score >= 0.6 and confidence >= 0.6:
            verdict = "convict"
        elif evidence_score >= 0.4:
            verdict = "review"
        else:
            verdict = "acquit"

        return reasoning, concerns, verdict

    # ------------------------------------------------------------------
    # Burden-strict
    # ------------------------------------------------------------------

    @staticmethod
    def _burden_strict_reasoning(
        *,
        eval_result: dict,
        burden_result: dict,
        evidence_score: float,
        exception_result: dict,
        lawyer_output: dict,
    ) -> tuple:
        """Demands full burden discharge; any gap → acquit."""
        reasoning: List[str] = []
        concerns: List[str] = []

        burden_stage = burden_result.get("burden_stage", "unknown")
        reasoning.append(f"Burden stage: {burden_stage}.")

        flags = burden_result.get("reasoning_flags", [])
        if flags:
            reasoning.append(f"Reasoning flags: {', '.join(flags)}.")

        satisfied = burden_result.get("required_elements_satisfied", 0)
        total = burden_result.get("required_elements_total", 0)
        reasoning.append(
            f"Required elements satisfied: {satisfied}/{total}."
        )

        if burden_stage != "prima_facie_established":
            concerns.append(
                f"Burden not fully discharged (stage: {burden_stage})."
            )

        exceptions_supported = burden_result.get("exceptions_supported", [])
        if exceptions_supported:
            concerns.append(
                f"Supported exception(s): {', '.join(exceptions_supported)}."
            )

        if exception_result.get("fully_negated"):
            concerns.append("Exceptions fully negate required elements.")
            verdict = "acquit"
        elif burden_stage == "prima_facie_established":
            verdict = "convict"
        elif burden_stage in (
            "reasonable_doubt", "exception_established",
            "acquittal_recommended",
        ):
            verdict = "acquit"
        else:
            verdict = "review"

        return reasoning, concerns, verdict

    # ------------------------------------------------------------------
    # Agreement check
    # ------------------------------------------------------------------

    @staticmethod
    def _agrees_with_lawyer(verdict: str, lawyer_output: dict) -> bool:
        """
        Simple heuristic: if lawyer risk_level is 'high' and judge convicts,
        or risk_level is 'low' and judge acquits, they agree.
        """
        risk = lawyer_output.get("risk_level", "medium")
        if risk == "high" and verdict == "convict":
            return True
        if risk == "low" and verdict == "acquit":
            return True
        if risk == "medium" and verdict == "review":
            return True
        return False
