"""
CourtMind — Strategy Layer: Strategy Engine

Deterministic legal strategy analysis derived from CaseAnalysis,
panel results, lawyer output, and guardrail reports.

**Strict rules**

*   Pure deterministic — no LLM.
*   Does NOT modify CaseAnalysis or any evaluation result.
*   Read-only consumer of existing structured outputs.

Usage
-----
    from strategy.strategy_engine import StrategyEngine

    engine = StrategyEngine()
    report = engine.generate(case_analysis, panel_result, lawyer_output, guardrail_report)
"""

from __future__ import annotations

from typing import Any, Dict, List

from strategy.strategy_models import (
    StrategyReport,
    StrongElement,
    WeakElement,
)


# ---------------------------------------------------------------------------
# Burden-stage multipliers (reuse same weights as SectionAutoDetector)
# ---------------------------------------------------------------------------

_BURDEN_MULTIPLIERS: Dict[str, float] = {
    "prima_facie_established": 0.8,
    "defense_rebuttal_required": 0.5,
    "exception_established": 0.4,
    "reasonable_doubt": 0.3,
    "manual_review_required": 0.3,
    "prosecution_incomplete": 0.2,
    "acquittal_recommended": 0.1,
}

_WEAK_STATUSES = frozenset({"not_satisfied", "partial", "conflicted"})


# ---------------------------------------------------------------------------
# Evidence recommendation templates
# ---------------------------------------------------------------------------

_EVIDENCE_SUGGESTIONS: Dict[str, List[str]] = {
    "act_by_accused": [
        "Obtain eyewitness testimony placing accused at the scene",
        "Request CCTV footage from the incident location",
    ],
    "death_of_human": [
        "Secure post-mortem / autopsy report",
        "Obtain death certificate from competent authority",
    ],
    "intention_or_knowledge": [
        "Introduce motive evidence or planning indicators",
        "Obtain digital records (messages, search history) showing intent",
    ],
    "knowledge_element": [
        "Present evidence of accused's awareness of likely consequences",
    ],
    "deception_element": [
        "Collect documentary proof of false representations",
        "Obtain financial records showing fraudulent transactions",
    ],
    "inducement_element": [
        "Gather witness statements proving inducement",
    ],
    "gain_loss_element": [
        "Present bank statements or financial records showing gain/loss",
    ],
    "hurt_element": [
        "Secure medical injury report from victim",
        "Obtain forensic evidence of physical harm",
    ],
    "supporting_evidence": [
        "Add corroborating forensic or witness evidence",
    ],
}

_GENERIC_EVIDENCE = [
    "Collect additional forensic evidence",
    "Obtain witness testimony for unsupported elements",
    "Request digital records (CCTV, phone records, documents)",
]


# ---------------------------------------------------------------------------
# Strategy Engine
# ---------------------------------------------------------------------------

class StrategyEngine:
    """
    Deterministic legal strategy analyser.

    Consumes structured simulation outputs and produces a
    :class:`StrategyReport` with prosecution/defense strategies,
    weak/strong element analysis, evidence recommendations, and
    risk classification.
    """

    def generate(
        self,
        case_analysis: Dict[str, Any],
        panel_result: Dict[str, Any],
        lawyer_output: Dict[str, Any],
        guardrail_report: Dict[str, Any],
    ) -> StrategyReport:
        """
        Produce a deterministic strategy report.

        Parameters
        ----------
        case_analysis : dict
            Output of ``CaseAnalysis.to_dict()``.
        panel_result : dict
            Output of ``PanelEngine.conduct_panel()``.
        lawyer_output : dict
            Output of ``LawyerAgent.generate()``.
        guardrail_report : dict
            Guardrail validation report.

        Returns
        -------
        StrategyReport
        """
        eval_result = case_analysis.get("evaluation_result", {})
        burden_result = case_analysis.get("burden_result", {})
        evidence_weight = case_analysis.get("evidence_weight_result", {})
        exception_result = case_analysis.get("exception_result", {})

        element_details = eval_result.get("element_details", [])
        confidence = float(burden_result.get("confidence_score", 0.0))
        evidence_score = float(evidence_weight.get("overall_evidence_score", 0.0))
        burden_stage = burden_result.get("burden_stage", "unknown")

        # 1. Weak / strong elements
        weak = self._detect_weak_elements(element_details)
        strong = self._detect_strong_elements(element_details, evidence_weight)

        # 2. Strategies
        prosecution = self._prosecution_strategy(
            element_details, weak, burden_stage, confidence,
        )
        defense = self._defense_strategy(
            element_details, weak, exception_result,
            evidence_score, guardrail_report,
        )

        # 3. Evidence recommendations
        evidence_recs = self._evidence_recommendations(weak, element_details)

        # 4. Conviction probability & risk
        probability = self._conviction_probability(
            confidence, evidence_score, burden_stage,
        )
        risk = self._risk_level(probability)

        return StrategyReport(
            weak_elements=[w.to_dict() for w in weak],
            strong_elements=[s.to_dict() for s in strong],
            prosecution_strategy=prosecution,
            defense_strategy=defense,
            evidence_recommendations=evidence_recs,
            risk_level=risk,
            conviction_probability_estimate=round(probability, 4),
        )

    # ------------------------------------------------------------------
    # Weak elements
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_weak_elements(
        element_details: List[Dict[str, Any]],
    ) -> List[WeakElement]:
        weak: List[WeakElement] = []
        for elem in element_details:
            status = elem.get("status", "")
            if status in _WEAK_STATUSES and elem.get("required", True):
                eid = elem.get("element_id", "?")
                reason = f"Element '{eid}' is {status}"
                if status == "not_satisfied":
                    reason += " — no supporting facts found"
                elif status == "partial":
                    reason += " — insufficient evidence for full satisfaction"
                elif status == "conflicted":
                    reason += " — contradictory evidence present"
                weak.append(WeakElement(
                    element_id=eid,
                    status=status,
                    reason=reason,
                ))
        return weak

    # ------------------------------------------------------------------
    # Strong elements
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_strong_elements(
        element_details: List[Dict[str, Any]],
        evidence_weight: Dict[str, Any],
    ) -> List[StrongElement]:
        strong: List[StrongElement] = []
        per_element = evidence_weight.get("per_element_scores", {})
        for elem in element_details:
            if elem.get("status") != "satisfied":
                continue
            eid = elem.get("element_id", "?")
            elem_score = float(per_element.get(eid, 0.0))
            fact_count = len(elem.get("matching_fact_ids", []))
            if elem_score >= 0.7 or fact_count >= 2:
                strong.append(StrongElement(
                    element_id=eid,
                    evidence_score=round(elem_score, 4),
                    supporting_fact_count=fact_count,
                ))
        return strong

    # ------------------------------------------------------------------
    # Prosecution strategy
    # ------------------------------------------------------------------

    @staticmethod
    def _prosecution_strategy(
        element_details: List[Dict[str, Any]],
        weak: List[WeakElement],
        burden_stage: str,
        confidence: float,
    ) -> List[str]:
        strategies: List[str] = []

        for w in weak:
            strategies.append(
                f"Strengthen evidence for element '{w.element_id}' "
                f"(currently {w.status})"
            )
            eid = w.element_id.lower()
            if "intention" in eid or "mens_rea" in eid or "knowledge" in eid:
                strategies.append(
                    "Introduce motive evidence or planning indicators "
                    f"to support '{w.element_id}'"
                )
            if "act_by_accused" in eid or "actus" in eid:
                strategies.append(
                    "Add witness testimony or forensic linkage "
                    f"to prove '{w.element_id}'"
                )

        if burden_stage == "prosecution_incomplete":
            strategies.append(
                "Address prosecution gaps to advance burden stage "
                "beyond 'prosecution_incomplete'"
            )
        if confidence < 0.5:
            strategies.append(
                "Overall confidence is low — prioritise satisfying "
                "all required elements before trial"
            )

        # If no weak elements, prosecution is in strong position
        if not weak:
            strategies.append(
                "All required elements satisfied — focus on "
                "rebutting potential defense arguments"
            )

        return strategies

    # ------------------------------------------------------------------
    # Defense strategy
    # ------------------------------------------------------------------

    @staticmethod
    def _defense_strategy(
        element_details: List[Dict[str, Any]],
        weak: List[WeakElement],
        exception_result: Dict[str, Any],
        evidence_score: float,
        guardrail_report: Dict[str, Any],
    ) -> List[str]:
        strategies: List[str] = []

        # Exploit weak elements
        for w in weak:
            strategies.append(
                f"Challenge prosecution on weak element '{w.element_id}' "
                f"({w.status})"
            )

        # Exceptions
        for exc in exception_result.get("exceptions_detected", []):
            tag = exc.get("tag", "unknown")
            if exc.get("supported"):
                strategies.append(
                    f"Strengthen exception defense for '{tag}' "
                    "with additional corroborating evidence"
                )
            else:
                strategies.append(
                    f"Exception '{tag}' is claimed but unsupported — "
                    "gather supporting witness or forensic evidence"
                )

        # Evidence score
        if evidence_score < 0.5:
            strategies.append(
                "Challenge reliability of prosecution evidence "
                f"(overall score: {evidence_score:.2f})"
            )

        # Conflicts
        conflicts = [
            elem for elem in element_details
            if elem.get("status") == "conflicted"
        ]
        if conflicts:
            strategies.append(
                "Exploit contradictions in prosecution evidence "
                f"({len(conflicts)} conflicted element(s))"
            )

        # Guardrail violations
        violations = guardrail_report.get("violations", [])
        if violations:
            strategies.append(
                f"Simulation flagged {len(violations)} guardrail violation(s) — "
                "potential inconsistencies in prosecution case"
            )

        if not strategies:
            strategies.append(
                "No obvious defense angles — consider procedural challenges"
            )

        return strategies

    # ------------------------------------------------------------------
    # Evidence recommendations
    # ------------------------------------------------------------------

    @staticmethod
    def _evidence_recommendations(
        weak: List[WeakElement],
        element_details: List[Dict[str, Any]],
    ) -> List[str]:
        recs: List[str] = []
        seen: set = set()

        for w in weak:
            eid = w.element_id
            suggestions = _EVIDENCE_SUGGESTIONS.get(eid, [])
            for s in suggestions:
                if s not in seen:
                    recs.append(s)
                    seen.add(s)

        # If no specific suggestions, add generic ones
        if not recs and weak:
            for g in _GENERIC_EVIDENCE:
                recs.append(g)

        return recs

    # ------------------------------------------------------------------
    # Conviction probability
    # ------------------------------------------------------------------

    @staticmethod
    def _conviction_probability(
        confidence: float,
        evidence_score: float,
        burden_stage: str,
    ) -> float:
        burden_mult = _BURDEN_MULTIPLIERS.get(burden_stage, 0.3)
        probability = (
            confidence * 0.5
            + evidence_score * 0.4
            + burden_mult * 0.1
        )
        return max(0.0, min(1.0, probability))

    # ------------------------------------------------------------------
    # Risk level
    # ------------------------------------------------------------------

    @staticmethod
    def _risk_level(probability: float) -> str:
        if probability >= 0.75:
            return "high"
        if probability >= 0.5:
            return "moderate"
        return "low"
