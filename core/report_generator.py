"""
CourtMind — Report Generator

Exports case analysis results as structured JSON or Markdown reports.

**Strict rules**

*   Read-only — does NOT modify simulation results.
*   Deterministic — same input always produces the same report.

Usage
-----
    from core.report_generator import ReportGenerator

    gen = ReportGenerator()
    md = gen.to_markdown(simulation_result)
    js = gen.to_json(simulation_result)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict


class ReportGenerator:
    """Generate human-readable and machine-readable case reports."""

    def to_json(self, result: Dict[str, Any]) -> str:
        """Serialize the full simulation result to indented JSON."""
        return json.dumps(result, indent=2, default=str, ensure_ascii=False)

    def to_markdown(self, result: Dict[str, Any]) -> str:
        """Produce a Markdown-formatted case report."""
        lines: list[str] = []
        _add = lines.append

        _add("# CourtMind Case Report")
        _add(f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n")

        # --- Section & Confidence ---
        ca = result.get("case_analysis", {})
        er = ca.get("evaluation_result", {})
        br = ca.get("burden_result", {})

        _add("## Detected Section")
        _add(f"**IPC Section:** {er.get('section', 'N/A')}")
        _add(f"**Confidence Score:** {er.get('confidence_score', br.get('confidence_score', 'N/A'))}")
        _add(f"**Burden Stage:** {br.get('burden_stage', 'N/A')}")
        _add(f"**Burden Met:** {'Yes' if br.get('burden_met') else 'No'}\n")

        # --- Element Status ---
        elements = er.get("element_details", [])
        if elements:
            _add("## Element Status")
            _add("| Element | Satisfied | Facts | Weight |")
            _add("|---------|-----------|-------|--------|")
            for el in elements:
                eid = (el.get("element_id") or "").replace("_", " ")
                sat = "Yes" if el.get("satisfied") else "No"
                facts = len(el.get("matching_fact_ids", []))
                weight = f"{el['weight']:.2f}" if "weight" in el else "N/A"
                _add(f"| {eid} | {sat} | {facts} | {weight} |")
            _add("")

        # --- Evidence Weight ---
        ew = ca.get("evidence_weight_result", {})
        if ew:
            _add("## Evidence Weight")
            _add(f"**Overall Score:** {ew.get('overall_evidence_score', 'N/A')}")
            per = ew.get("per_element_scores", {})
            if per:
                for k, v in per.items():
                    score = f"{v:.2f}" if isinstance(v, (int, float)) else str(v)
                    _add(f"- {k.replace('_', ' ')}: {score}")
            _add("")

        # --- Panel Result ---
        pr = result.get("panel_result", {})
        if pr:
            _add("## Panel Deliberation")
            _add(f"**Majority Verdict:** {pr.get('majority_verdict', 'N/A').upper()}")
            _add(f"**Vote Split:** {pr.get('vote_split', 'N/A')}")
            for j in pr.get("judges", []):
                _add(f"\n### {j.get('judge_type', 'Judge')}")
                _add(f"**Verdict:** {j.get('provisional_verdict', 'N/A')}")
                for pt in j.get("key_reasoning_points", []):
                    _add(f"- {pt}")
            _add("")

        # --- Strategy ---
        sr = result.get("strategy_report", {})
        if sr:
            _add("## Strategy Analysis")
            prob = sr.get("conviction_probability_estimate")
            if prob is not None:
                _add(f"**Conviction Probability:** {prob * 100:.1f}%")
            _add(f"**Risk Level:** {sr.get('risk_level', 'N/A')}")
            if sr.get("prosecution_strategy"):
                _add("\n**Prosecution:**")
                for s in sr["prosecution_strategy"]:
                    _add(f"- {s}")
            if sr.get("defense_strategy"):
                _add("\n**Defense:**")
                for s in sr["defense_strategy"]:
                    _add(f"- {s}")
            _add("")

        # --- Research ---
        rd = result.get("research_data", {})
        if rd:
            precs = rd.get("precedents", [])
            ctx = rd.get("recent_context", [])
            if precs or ctx:
                _add("## Research Results")
                if precs:
                    _add("### Precedent Cases")
                    for p in precs:
                        _add(f"- {p.get('title', 'Untitled')} ({p.get('year', '?')})")
                if ctx:
                    _add("### Recent Context")
                    for c in ctx:
                        _add(f"- {c.get('title', 'Untitled')}: {c.get('snippet', '')}")
                _add("")

        # --- Final Judgment ---
        fj = result.get("final_judgment", "")
        if fj:
            _add("## Final Judgment")
            _add(fj)
            _add("")

        # --- Explanation ---
        exp = result.get("explanation", "")
        if exp:
            _add("## Case Explanation")
            _add(exp if isinstance(exp, str) else json.dumps(exp, indent=2, default=str))
            _add("")

        # --- Guardrails ---
        gr = result.get("guardrail_report", {})
        if gr:
            violations = gr.get("violations", [])
            _add("## Guardrail Report")
            if violations:
                _add("**Violations:**")
                for v in violations:
                    _add(f"- {v}")
            else:
                _add("No guardrail violations detected.")
            _add("")

        return "\n".join(lines)
