"""
CourtMind — Strategy Layer: Explanation Engine

Generates human-readable explanations of case analysis and strategy.

Two modes:
*   **Deterministic fallback** — always available, rule-based narrative.
*   **LLM-assisted** — optional Ollama integration for richer prose.

The deterministic fallback is guaranteed; the LLM path is best-effort.

Usage
-----
    from strategy.explanation_engine import ExplanationEngine

    engine = ExplanationEngine()
    explanation = engine.generate_case_explanation(
        case_analysis, panel_result, strategy_report,
    )
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


class ExplanationEngine:
    """
    Produces human-readable case explanations.

    *   Uses Ollama if the ``OLLAMA_MODEL`` environment variable is set
        and the service is reachable.
    *   Falls back to a deterministic template otherwise.
    *   **Never** modifies any analysis output.
    """

    def __init__(self, *, ollama_model: Optional[str] = None) -> None:
        self._ollama_model = ollama_model or os.environ.get("OLLAMA_MODEL")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_case_explanation(
        self,
        case_analysis: Dict[str, Any],
        panel_result: Dict[str, Any],
        strategy_report: Dict[str, Any],
    ) -> str:
        """
        Produce a narrative explanation of the case.

        Parameters
        ----------
        case_analysis : dict
            Output of ``CaseAnalysis.to_dict()``.
        panel_result : dict
            ``PanelEngine.conduct_panel()`` output.
        strategy_report : dict
            ``StrategyReport.to_dict()`` output.

        Returns
        -------
        str
            Multi-paragraph explanation.
        """
        # Attempt LLM-assisted explanation
        if self._ollama_model:
            try:
                return self._llm_explanation(
                    case_analysis, panel_result, strategy_report,
                )
            except Exception:
                pass  # Fall through to deterministic path

        return self._deterministic_explanation(
            case_analysis, panel_result, strategy_report,
        )

    # ------------------------------------------------------------------
    # Deterministic explanation
    # ------------------------------------------------------------------

    @staticmethod
    def _deterministic_explanation(
        case_analysis: Dict[str, Any],
        panel_result: Dict[str, Any],
        strategy_report: Dict[str, Any],
    ) -> str:
        eval_result = case_analysis.get("evaluation_result", {})
        burden_result = case_analysis.get("burden_result", {})
        evidence_weight = case_analysis.get("evidence_weight_result", {})

        section = eval_result.get("section", "Unknown")
        verdict_rec = burden_result.get("verdict_recommendation", "review")
        confidence = float(burden_result.get("confidence_score", 0.0))
        burden_stage = burden_result.get("burden_stage", "unknown")
        evidence_score = float(evidence_weight.get("overall_evidence_score", 0.0))

        majority_verdict = panel_result.get("majority_verdict", "review")
        judges = panel_result.get("judges", [])

        weak = strategy_report.get("weak_elements", [])
        strong = strategy_report.get("strong_elements", [])
        risk = strategy_report.get("risk_level", "unknown")
        prob = strategy_report.get("conviction_probability_estimate", 0.0)

        lines = []

        # --- Section and overview ---
        lines.append(f"## Case Analysis — IPC Section {section}")
        lines.append("")
        lines.append(
            f"The evaluation pipeline identified IPC Section **{section}** "
            f"as the applicable offence.  The burden analysis reached stage "
            f"**{burden_stage}** with a confidence score of **{confidence:.2f}**."
        )
        lines.append("")

        # --- Evidence overview ---
        lines.append("### Evidence Assessment")
        lines.append("")
        lines.append(
            f"The overall evidence score is **{evidence_score:.2f}**.  "
            f"This has been weighted across all statutory elements."
        )
        lines.append("")

        # --- Elements ---
        if strong:
            lines.append("**Strongest Elements:**")
            for s in strong:
                eid = s.get("element_id", "?")
                score = s.get("evidence_score", 0.0)
                lines.append(f"- {eid} (evidence score: {score:.2f})")
            lines.append("")

        if weak:
            lines.append("**Weakest Elements:**")
            for w in weak:
                eid = w.get("element_id", "?")
                reason = w.get("reason", "")
                lines.append(f"- {eid}: {reason}")
            lines.append("")

        # --- Panel ---
        lines.append("### Judicial Panel")
        lines.append("")
        lines.append(
            f"The panel reached a majority verdict of **{majority_verdict}**.  "
            f"{len(judges)} judge(s) participated."
        )
        lines.append("")

        for j in judges:
            philosophy = j.get("philosophy") or j.get("judge_type", "?")
            j_verdict = j.get("verdict") or j.get("provisional_verdict", "?")
            lines.append(f"- **{philosophy}** judge: {j_verdict}")
        lines.append("")

        # --- Risk and probability ---
        lines.append("### Risk Analysis")
        lines.append("")
        lines.append(
            f"Conviction probability estimate: **{prob:.2%}** "
            f"(risk level: **{risk}**)."
        )
        lines.append("")

        # --- Strategy summary ---
        prosecution = strategy_report.get("prosecution_strategy", [])
        defense = strategy_report.get("defense_strategy", [])

        if prosecution:
            lines.append("### Prosecution Strategy Recommendations")
            lines.append("")
            for s in prosecution:
                lines.append(f"- {s}")
            lines.append("")

        if defense:
            lines.append("### Defense Strategy Recommendations")
            lines.append("")
            for s in defense:
                lines.append(f"- {s}")
            lines.append("")

        # --- Evidence recs ---
        evidence_recs = strategy_report.get("evidence_recommendations", [])
        if evidence_recs:
            lines.append("### Evidence Improvement Suggestions")
            lines.append("")
            for r in evidence_recs:
                lines.append(f"- {r}")
            lines.append("")

        # --- Verdict ---
        lines.append("### Verdict Recommendation")
        lines.append("")
        lines.append(f"Based on the deterministic analysis: **{verdict_rec}**.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # LLM-assisted explanation
    # ------------------------------------------------------------------

    def _llm_explanation(
        self,
        case_analysis: Dict[str, Any],
        panel_result: Dict[str, Any],
        strategy_report: Dict[str, Any],
    ) -> str:
        """
        Call Ollama to produce a richer narrative.

        Raises on any network / parse error — caller catches and falls
        back to deterministic path.
        """
        import json
        import urllib.request

        prompt = self._build_prompt(case_analysis, panel_result, strategy_report)

        payload = json.dumps({
            "model": self._ollama_model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            text = body.get("response", "").strip()
            if not text:
                raise ValueError("Empty LLM response")
            return text

    # ------------------------------------------------------------------
    # Prompt builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        case_analysis: Dict[str, Any],
        panel_result: Dict[str, Any],
        strategy_report: Dict[str, Any],
    ) -> str:
        eval_result = case_analysis.get("evaluation_result", {})
        burden_result = case_analysis.get("burden_result", {})
        evidence_weight = case_analysis.get("evidence_weight_result", {})

        section = eval_result.get("section", "Unknown")
        verdict_rec = burden_result.get("verdict_recommendation", "review")
        confidence = burden_result.get("confidence_score", 0.0)
        burden_stage = burden_result.get("burden_stage", "unknown")
        evidence_score = evidence_weight.get("overall_evidence_score", 0.0)
        majority_verdict = panel_result.get("majority_verdict", "review")
        weak = strategy_report.get("weak_elements", [])
        strong = strategy_report.get("strong_elements", [])
        risk = strategy_report.get("risk_level", "unknown")
        prob = strategy_report.get("conviction_probability_estimate", 0.0)

        prompt_lines = [
            "You are a legal analyst for an Indian criminal court case.",
            "Based on the following structured analysis, produce a clear,",
            "professional explanation of the case findings and strategy.",
            "",
            f"IPC Section: {section}",
            f"Burden Stage: {burden_stage}",
            f"Confidence Score: {confidence}",
            f"Evidence Score: {evidence_score}",
            f"Majority Verdict: {majority_verdict}",
            f"Verdict Recommendation: {verdict_rec}",
            f"Risk Level: {risk}",
            f"Conviction Probability: {prob:.2%}",
            "",
            f"Strong Elements: {len(strong)}",
            f"Weak Elements: {len(weak)}",
        ]

        if weak:
            prompt_lines.append("")
            prompt_lines.append("Weak Elements:")
            for w in weak:
                prompt_lines.append(f"  - {w.get('element_id')}: {w.get('reason')}")

        prosecution = strategy_report.get("prosecution_strategy", [])
        defense = strategy_report.get("defense_strategy", [])

        if prosecution:
            prompt_lines.append("")
            prompt_lines.append("Prosecution Strategies:")
            for s in prosecution:
                prompt_lines.append(f"  - {s}")

        if defense:
            prompt_lines.append("")
            prompt_lines.append("Defense Strategies:")
            for s in defense:
                prompt_lines.append(f"  - {s}")

        prompt_lines.append("")
        prompt_lines.append(
            "Write a 3-5 paragraph professional case summary covering: "
            "the applicable section, strength of evidence, panel verdict, "
            "key risks, and strategic recommendations for both sides."
        )

        return "\n".join(prompt_lines)
