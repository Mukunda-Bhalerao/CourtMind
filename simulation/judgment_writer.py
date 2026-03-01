"""
CourtMind — Simulation Layer: Judgment Writer

Composes a final narrative judgment document from structured
deterministic analysis and panel deliberation results.

**Rules**

*   Must cite deterministic findings.
*   Must cite element statuses.
*   Must cite ``burden_stage``.
*   Must **not** contradict structured outputs.

Usage
-----
    from simulation.judgment_writer import JudgmentWriter

    writer = JudgmentWriter()
    text = writer.compose(case_analysis_dict, panel_result)
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Judgment Writer
# ---------------------------------------------------------------------------

class JudgmentWriter:
    """
    Produces a structured legal judgment narrative from ``CaseAnalysis``
    and ``PanelEngine`` output.

    All statements reference only fields present in the inputs — no facts
    are invented.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compose(
        self,
        case_analysis: dict,
        panel_result: dict,
    ) -> str:
        """
        Compose the final judgment text.

        Parameters
        ----------
        case_analysis : dict
            Output of ``CaseAnalysis.to_dict()``.
        panel_result : dict
            Output of ``PanelEngine.conduct_panel()``.

        Returns
        -------
        str
            Multi-paragraph judgment document.
        """
        sections: List[str] = [
            self._header(case_analysis),
            self._element_analysis(case_analysis),
            self._burden_analysis(case_analysis),
            self._evidence_summary(case_analysis),
            self._exception_analysis(case_analysis),
            self._panel_summary(panel_result),
            self._verdict(panel_result, case_analysis),
        ]
        return "\n\n".join(s for s in sections if s)

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    @staticmethod
    def _header(case_analysis: dict) -> str:
        eval_r = case_analysis.get("evaluation_result", {})
        meta = case_analysis.get("metadata", {})
        section = eval_r.get("section", "Unknown")
        title = eval_r.get("section_title", "")
        evaluated_at = meta.get("evaluated_at", "N/A")
        return (
            f"JUDGMENT — {section} ({title})\n"
            f"{'=' * 50}\n"
            f"Evaluation Date: {evaluated_at}"
        )

    @staticmethod
    def _element_analysis(case_analysis: dict) -> str:
        eval_r = case_analysis.get("evaluation_result", {})
        details = eval_r.get("element_details", [])
        if not details:
            return "ELEMENT ANALYSIS\nNo element details available."

        lines = ["ELEMENT ANALYSIS"]
        for elem in details:
            eid = elem.get("element_id", "?")
            status = elem.get("status", "unknown")
            required = "Required" if elem.get("required", True) else "Optional"
            n_facts = len(elem.get("matching_fact_ids", []))
            notes = "; ".join(elem.get("confidence_notes", []))
            lines.append(
                f"  - {eid} [{required}]: {status.upper()} "
                f"({n_facts} fact(s))"
            )
            if notes:
                lines.append(f"    Notes: {notes}")

        satisfied = eval_r.get("elements_satisfied", 0)
        required = eval_r.get("elements_required", 0)
        lines.append(f"\n  Elements satisfied: {satisfied}/{required}")
        return "\n".join(lines)

    @staticmethod
    def _burden_analysis(case_analysis: dict) -> str:
        burden = case_analysis.get("burden_result", {})
        stage = burden.get("burden_stage", "unknown")
        confidence = burden.get("confidence_score", 0.0)
        sat = burden.get("required_elements_satisfied", 0)
        total = burden.get("required_elements_total", 0)
        flags = burden.get("reasoning_flags", [])
        lines = [
            "BURDEN OF PROOF ANALYSIS",
            f"  Stage: {stage}",
            f"  Confidence: {confidence}",
            f"  Required elements met: {sat}/{total}",
        ]
        if flags:
            lines.append(f"  Reasoning flags: {', '.join(flags)}")
        return "\n".join(lines)

    @staticmethod
    def _evidence_summary(case_analysis: dict) -> str:
        ew = case_analysis.get("evidence_weight_result", {})
        overall = ew.get("overall_evidence_score", 0.0)
        per_element = ew.get("element_scores", {})
        lines = [
            "EVIDENCE WEIGHT SUMMARY",
            f"  Overall evidence score: {overall}",
        ]
        if per_element:
            for eid, score in per_element.items():
                lines.append(f"  - {eid}: {score}")
        return "\n".join(lines)

    @staticmethod
    def _exception_analysis(case_analysis: dict) -> str:
        exc = case_analysis.get("exception_result", {})
        detected = exc.get("exceptions_detected", [])
        if not detected:
            return "EXCEPTION ANALYSIS\n  No exceptions claimed."

        lines = ["EXCEPTION ANALYSIS"]
        for d in detected:
            tag = d.get("tag", "?")
            supported = "Supported" if d.get("supported") else "Not supported"
            negates = d.get("negates_elements", [])
            lines.append(f"  - {tag}: {supported}")
            if negates:
                lines.append(f"    Negates: {', '.join(negates)}")

        if exc.get("fully_negated"):
            lines.append("  ** All required elements negated by exceptions.")
        if exc.get("requires_manual_review"):
            lines.append("  ** Manual review required due to conflicts.")
        return "\n".join(lines)

    @staticmethod
    def _panel_summary(panel_result: dict) -> str:
        judges = panel_result.get("judges", [])
        split = panel_result.get("vote_split", "N/A")
        lines = [
            "PANEL DELIBERATION",
            f"  Vote split: {split}",
        ]
        for j in judges:
            jtype = j.get("judge_type", "?")
            verdict = j.get("provisional_verdict", "?")
            points = j.get("key_reasoning_points", [])
            concerns = j.get("concerns", [])
            lines.append(f"\n  Judge ({jtype}): {verdict.upper()}")
            for p in points:
                lines.append(f"    - {p}")
            if concerns:
                lines.append("    Concerns:")
                for c in concerns:
                    lines.append(f"      * {c}")
        return "\n".join(lines)

    @staticmethod
    def _verdict(panel_result: dict, case_analysis: dict) -> str:
        majority = panel_result.get("majority_verdict", "review")
        confidence = panel_result.get("confidence_level", "medium")
        burden_stage = case_analysis.get("burden_result", {}).get(
            "burden_stage", "unknown"
        )
        lines = [
            "FINAL VERDICT",
            f"{'=' * 50}",
            f"  Majority Verdict: {majority.upper()}",
            f"  Confidence Level: {confidence}",
            f"  Burden Stage: {burden_stage}",
        ]

        if majority == "convict":
            lines.append(
                "\n  The panel finds, based on the structured analysis, "
                "that the prosecution has discharged its burden of proof. "
                "All required statutory elements are satisfied."
            )
        elif majority == "acquit":
            lines.append(
                "\n  The panel finds that the prosecution has NOT fully "
                "discharged its burden. The accused is entitled to the "
                "benefit of doubt."
            )
        else:
            lines.append(
                "\n  The panel recommends further review. The evidence "
                "and element analysis do not provide sufficient clarity "
                "for a definitive verdict."
            )

        return "\n".join(lines)
