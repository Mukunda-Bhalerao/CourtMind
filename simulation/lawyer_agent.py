"""
CourtMind — Simulation Layer: Lawyer Agent

Simulates a lawyer reviewing a structured ``CaseAnalysis`` (dict form)
and producing prosecution/defense arguments, weakness identification,
and risk assessment.

**Strict rules**

*   Accepts only ``CaseAnalysis.to_dict()`` output.
*   Must **not** modify deterministic outputs.
*   Must cite only structured fields (elements_satisfied, elements_failed,
    burden_stage, confidence_score, overall_evidence_score).
*   No invention of facts — references only what the deterministic engine
    produced.
*   No new legal elements allowed.

Usage
-----
    from simulation.lawyer_agent import LawyerAgent

    lawyer = LawyerAgent()
    output = lawyer.generate(case_analysis_dict)
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Risk-level mapping
# ---------------------------------------------------------------------------

_RISK_LEVEL_MAP: Dict[str, str] = {
    "prosecution_incomplete": "high",
    "prima_facie_established": "low",
    "reasonable_doubt": "medium",
    "defense_rebuttal_required": "medium",
    "exception_established": "medium",
    "acquittal_recommended": "high",
    "manual_review_required": "medium",
}


# ---------------------------------------------------------------------------
# Lawyer Agent
# ---------------------------------------------------------------------------

class LawyerAgent:
    """
    Deterministic-first lawyer simulation.

    Analyses the structured ``CaseAnalysis`` dict and produces:

    *   ``confirmed_section`` — the section evaluated.
    *   ``alternate_sections`` — from auto-detection metadata if present.
    *   ``prosecution_arguments`` — strengths derived from satisfied elements.
    *   ``defense_arguments`` — weaknesses derived from failed/partial/
        conflicted elements and exceptions.
    *   ``identified_weaknesses`` — explicit list of prosecution gaps.
    *   ``risk_level`` — ``"low"`` / ``"medium"`` / ``"high"`` based on
        burden stage.

    All reasoning is derived **exclusively** from fields already present in
    the ``CaseAnalysis`` dict —  no facts are invented.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, case_analysis: dict) -> Dict[str, Any]:
        """
        Produce a structured lawyer review from *case_analysis*.

        Parameters
        ----------
        case_analysis : dict
            Output of ``CaseAnalysis.to_dict()``.

        Returns
        -------
        dict
            Structured lawyer output.
        """
        eval_result = case_analysis.get("evaluation_result", {})
        burden_result = case_analysis.get("burden_result", {})
        evidence_weight = case_analysis.get("evidence_weight_result", {})
        exception_result = case_analysis.get("exception_result", {})
        metadata = case_analysis.get("metadata", {})

        section = eval_result.get("section", "unknown")
        burden_stage = burden_result.get("burden_stage", "unknown")
        confidence = burden_result.get("confidence_score", 0.0)
        evidence_score = evidence_weight.get("overall_evidence_score", 0.0)

        element_details = eval_result.get("element_details", [])
        elements_satisfied = eval_result.get("elements_satisfied", 0)
        elements_failed = eval_result.get("elements_failed", 0)

        prosecution_args = self._build_prosecution_arguments(
            element_details, burden_stage, confidence, evidence_score,
        )
        defense_args = self._build_defense_arguments(
            element_details, burden_result, exception_result,
        )
        weaknesses = self._identify_weaknesses(
            element_details, burden_result, confidence,
        )
        alternate_sections = self._extract_alternate_sections(
            section, metadata,
        )
        risk = _RISK_LEVEL_MAP.get(burden_stage, "medium")

        return {
            "confirmed_section": section,
            "alternate_sections": alternate_sections,
            "prosecution_arguments": prosecution_args,
            "defense_arguments": defense_args,
            "identified_weaknesses": weaknesses,
            "risk_level": risk,
        }

    # ------------------------------------------------------------------
    # Internals — prosecution
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prosecution_arguments(
        element_details: List[dict],
        burden_stage: str,
        confidence: float,
        evidence_score: float,
    ) -> List[str]:
        args: List[str] = []

        satisfied = [
            d for d in element_details
            if d.get("status") == "satisfied" and d.get("required", True)
        ]
        for elem in satisfied:
            eid = elem.get("element_id", "?")
            n_facts = len(elem.get("matching_fact_ids", []))
            args.append(
                f"Element '{eid}' is satisfied with {n_facts} supporting fact(s)."
            )

        if burden_stage == "prima_facie_established":
            args.append(
                "Prima facie case established — all required elements met."
            )

        if confidence >= 0.8:
            args.append(
                f"High prosecution confidence ({confidence})."
            )

        if evidence_score >= 0.7:
            args.append(
                f"Strong overall evidence score ({evidence_score})."
            )

        if not args:
            args.append("No strong prosecution arguments identified.")

        return args

    # ------------------------------------------------------------------
    # Internals — defense
    # ------------------------------------------------------------------

    @staticmethod
    def _build_defense_arguments(
        element_details: List[dict],
        burden_result: dict,
        exception_result: dict,
    ) -> List[str]:
        args: List[str] = []

        failed = [
            d for d in element_details
            if d.get("status") == "not_satisfied" and d.get("required", True)
        ]
        for elem in failed:
            eid = elem.get("element_id", "?")
            args.append(
                f"Required element '{eid}' is not satisfied — prosecution gap."
            )

        conflicted = [
            d for d in element_details
            if d.get("status") == "conflicted" and d.get("required", True)
        ]
        for elem in conflicted:
            eid = elem.get("element_id", "?")
            args.append(
                f"Element '{eid}' has conflicting evidence — reasonable doubt."
            )

        partial = [
            d for d in element_details
            if d.get("status") == "partial" and d.get("required", True)
        ]
        for elem in partial:
            eid = elem.get("element_id", "?")
            args.append(
                f"Element '{eid}' only partially established — insufficient."
            )

        exceptions_supported = exception_result.get(
            "exceptions_supported", []
        )
        if exceptions_supported:
            args.append(
                f"Supported exception(s): {', '.join(exceptions_supported)}."
            )

        negated = exception_result.get("negated_elements", [])
        if negated:
            args.append(
                f"Exception negates element(s): {', '.join(negated)}."
            )

        if exception_result.get("fully_negated"):
            args.append(
                "All required elements negated by exceptions — "
                "strong acquittal argument."
            )

        flags = burden_result.get("reasoning_flags", [])
        if "LOW_SEVERITY_INTENT" in flags:
            args.append(
                "Intent element backed only by low-severity facts."
            )

        if not args:
            args.append("No strong defense arguments identified.")

        return args

    # ------------------------------------------------------------------
    # Internals — weaknesses
    # ------------------------------------------------------------------

    @staticmethod
    def _identify_weaknesses(
        element_details: List[dict],
        burden_result: dict,
        confidence: float,
    ) -> List[str]:
        weaknesses: List[str] = []

        for elem in element_details:
            if not elem.get("required", True):
                continue
            status = elem.get("status", "")
            eid = elem.get("element_id", "?")
            if status == "not_satisfied":
                weaknesses.append(f"Missing: element '{eid}'.")
            elif status == "partial":
                weaknesses.append(f"Weak: element '{eid}' only partial.")
            elif status == "conflicted":
                weaknesses.append(f"Disputed: element '{eid}' conflicted.")

        if confidence < 0.5:
            weaknesses.append(
                f"Low confidence score ({confidence}) — case is fragile."
            )

        conflicted_count = burden_result.get("conflicted_elements", 0)
        if conflicted_count > 0:
            weaknesses.append(
                f"{conflicted_count} element(s) in conflict."
            )

        return weaknesses

    # ------------------------------------------------------------------
    # Internals — alternate sections
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_alternate_sections(
        confirmed: str,
        metadata: dict,
    ) -> List[str]:
        detected = metadata.get("detected_sections", [])
        return [
            d["section"] for d in detected
            if isinstance(d, dict) and d.get("section") != confirmed
        ]
