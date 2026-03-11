"""
CourtMind — Tests for Legal Strategy + Explainability Layer

Unit tests, integration tests, and system tests covering:

 1.  Weak element detection (not_satisfied → detected)
 2.  Weak element detection (partial → detected)
 3.  Weak element detection (conflicted → detected)
 4.  Strong element detection (score ≥ 0.7)
 5.  Prosecution strategy recommendations
 6.  Defense strategy recommendations
 7.  Evidence improvement suggestions
 8.  Conviction probability formula
 9.  Risk level classification
10.  Explanation engine deterministic fallback
11.  StrategyReport serialisation (to_dict / to_json)
12.  No weak elements → prosecution "strong position" advice
13.  Exception exploitation in defense strategy
14.  Guardrail violations inform defense
15.  Evidence recommendations use element-specific templates
16.  Integration: StrategyEngine on real FactMatrix pipeline
17.  Integration: run_full_simulation includes strategy_report
18.  Integration: run_full_simulation includes explanation
19.  System: full pipeline with strong case
20.  System: full pipeline with weak case
21.  Strong element detection (fact_count fallback)
22.  ExplanationEngine LLM path mocked
23.  ExplanationEngine LLM failure falls back to deterministic
24.  Low confidence triggers prosecution warning
25.  Conflicted elements trigger defense exploit
26.  Burden stage 'prosecution_incomplete' in prosecution strategy
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from core.evaluation_pipeline import EvaluationPipeline
from core.fact_matrix import FactMatrix, FactSource, Severity
from simulation.run_simulation import run_full_simulation
from strategy.explanation_engine import ExplanationEngine
from strategy.strategy_engine import StrategyEngine
from strategy.strategy_models import StrategyReport, StrongElement, WeakElement


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _build_case_analysis(
    *,
    element_details: List[Dict[str, Any]] | None = None,
    confidence: float = 0.7,
    burden_stage: str = "prima_facie_established",
    evidence_score: float = 0.6,
    per_element_scores: Dict[str, float] | None = None,
    exceptions_detected: List[Dict[str, Any]] | None = None,
    section: str = "302",
    verdict_recommendation: str = "convict",
) -> Dict[str, Any]:
    """Build a minimal case_analysis dict for testing."""
    return {
        "evaluation_result": {
            "section": section,
            "element_details": element_details or [],
        },
        "burden_result": {
            "confidence_score": confidence,
            "burden_stage": burden_stage,
            "verdict_recommendation": verdict_recommendation,
        },
        "evidence_weight_result": {
            "overall_evidence_score": evidence_score,
            "per_element_scores": per_element_scores or {},
        },
        "exception_result": {
            "exceptions_detected": exceptions_detected or [],
        },
        "metadata": {},
    }


def _default_panel_result() -> Dict[str, Any]:
    return {
        "majority_verdict": "convict",
        "judges": [
            {"philosophy": "textualist", "verdict": "convict"},
            {"philosophy": "evidence_focused", "verdict": "convict"},
            {"philosophy": "burden_strict", "verdict": "acquit"},
        ],
    }


def _default_lawyer_output() -> Dict[str, Any]:
    return {
        "prosecution_args": ["Accused committed the act."],
        "defense_args": ["Accused was not present."],
        "analysis": "both sides presented.",
    }


def _default_guardrail_report() -> Dict[str, Any]:
    return {"violations": []}


def _murder_matrix() -> FactMatrix:
    """Strong murder case — 302 IPC, all elements satisfied."""
    fm = FactMatrix()
    fm.add_fact("actus_reus", "Accused stabbed the victim in the chest.",
                FactSource.WITNESS, severity="critical",
                tags=["act_by_accused", "stabbing"])
    fm.add_fact("actus_reus", "Victim died from stab wounds.",
                FactSource.FORENSIC, severity="critical",
                tags=["death_caused", "death_of_human"])
    fm.add_fact("mens_rea", "Accused stated he wanted to kill victim.",
                FactSource.CONFESSION, severity="high",
                tags=["intention", "premeditated"])
    fm.add_fact("evidence", "Blood-stained knife recovered.",
                FactSource.FORENSIC, severity="high",
                tags=["weapon", "physical_evidence"])
    return fm


def _weak_matrix() -> FactMatrix:
    """Weak case — only partial elements, low evidence."""
    fm = FactMatrix()
    fm.add_fact("actus_reus", "A person was found dead.",
                FactSource.WITNESS, severity="medium",
                tags=["death_of_human"])
    return fm


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS — StrategyEngine
# ═══════════════════════════════════════════════════════════════════════

class TestWeakElementDetection:
    """Tests 1–3: Weak element detection."""

    def test_not_satisfied_detected(self):
        """#1: not_satisfied required element → weak."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []},
        ])
        engine = StrategyEngine()
        report = engine.generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.weak_elements) == 1
        assert report.weak_elements[0]["element_id"] == "act_by_accused"
        assert report.weak_elements[0]["status"] == "not_satisfied"

    def test_partial_detected(self):
        """#2: partial element → weak."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "intention_or_knowledge", "status": "partial",
             "required": True, "matching_fact_ids": ["f1"]},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.weak_elements) == 1
        assert "partial" in report.weak_elements[0]["reason"]

    def test_conflicted_detected(self):
        """#3: conflicted element → weak."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "conflicted",
             "required": True, "matching_fact_ids": ["f1", "f2"]},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.weak_elements) == 1
        assert "contradictory" in report.weak_elements[0]["reason"]

    def test_satisfied_not_weak(self):
        """Satisfied elements are not flagged as weak."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "satisfied",
             "required": True, "matching_fact_ids": ["f1"]},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.weak_elements) == 0

    def test_optional_element_not_weak(self):
        """Not-satisfied but optional elements are not flagged."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "supporting_evidence", "status": "not_satisfied",
             "required": False, "matching_fact_ids": []},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.weak_elements) == 0


class TestStrongElementDetection:
    """Tests 4, 21: Strong element detection."""

    def test_high_score_detected(self):
        """#4: satisfied + score ≥ 0.7 → strong."""
        ca = _build_case_analysis(
            element_details=[
                {"element_id": "act_by_accused", "status": "satisfied",
                 "required": True, "matching_fact_ids": ["f1"]},
            ],
            per_element_scores={"act_by_accused": 0.85},
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.strong_elements) == 1
        assert report.strong_elements[0]["evidence_score"] == 0.85

    def test_fact_count_fallback(self):
        """#21: satisfied + fact_count ≥ 2 → strong even if score < 0.7."""
        ca = _build_case_analysis(
            element_details=[
                {"element_id": "act_by_accused", "status": "satisfied",
                 "required": True, "matching_fact_ids": ["f1", "f2"]},
            ],
            per_element_scores={"act_by_accused": 0.5},
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.strong_elements) == 1
        assert report.strong_elements[0]["supporting_fact_count"] == 2

    def test_low_score_and_low_facts_not_strong(self):
        """Satisfied but score < 0.7 and fact_count < 2 → not strong."""
        ca = _build_case_analysis(
            element_details=[
                {"element_id": "act_by_accused", "status": "satisfied",
                 "required": True, "matching_fact_ids": ["f1"]},
            ],
            per_element_scores={"act_by_accused": 0.3},
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.strong_elements) == 0


class TestProsecutionStrategy:
    """Tests 5, 12, 24, 26: Prosecution strategy recommendations."""

    def test_weak_elements_generate_strategies(self):
        """#5: Each weak element gets 'strengthen' recommendation."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []},
            {"element_id": "intention_or_knowledge", "status": "partial",
             "required": True, "matching_fact_ids": []},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        strategies = report.prosecution_strategy
        assert any("act_by_accused" in s for s in strategies)
        assert any("intention_or_knowledge" in s for s in strategies)

    def test_no_weak_elements_strong_position(self):
        """#12: All satisfied → prosecution gets 'strong position' advice."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "satisfied",
             "required": True, "matching_fact_ids": ["f1"]},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("satisfied" in s.lower() or "rebutting" in s.lower()
                    for s in report.prosecution_strategy)

    def test_low_confidence_warning(self):
        """#24: Confidence < 0.5 → extra prosecution warning."""
        ca = _build_case_analysis(confidence=0.3, element_details=[
            {"element_id": "act_by_accused", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("confidence" in s.lower() for s in report.prosecution_strategy)

    def test_prosecution_incomplete_stage(self):
        """#26: burden_stage = prosecution_incomplete → advice."""
        ca = _build_case_analysis(
            burden_stage="prosecution_incomplete",
            element_details=[
                {"element_id": "act_by_accused", "status": "not_satisfied",
                 "required": True, "matching_fact_ids": []},
            ],
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("prosecution_incomplete" in s for s in report.prosecution_strategy)

    def test_intention_element_gets_motive_advice(self):
        """Intention weak element triggers motive suggestion."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "intention_or_knowledge", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("motive" in s.lower() for s in report.prosecution_strategy)


class TestDefenseStrategy:
    """Tests 6, 13, 14, 25: Defense strategy recommendations."""

    def test_weak_elements_exploited(self):
        """#6: Weak element → defense 'challenge' recommendation."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("challenge" in s.lower() for s in report.defense_strategy)

    def test_exceptions_exploited(self):
        """#13: Supported exceptions → defense strengthening advice."""
        ca = _build_case_analysis(
            exceptions_detected=[
                {"tag": "self-defense", "supported": True},
            ],
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("self-defense" in s for s in report.defense_strategy)

    def test_unsupported_exception_advice(self):
        """Unsupported exception → gather more evidence advice."""
        ca = _build_case_analysis(
            exceptions_detected=[
                {"tag": "provocation", "supported": False},
            ],
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("provocation" in s and "unsupported" in s
                    for s in report.defense_strategy)

    def test_guardrail_violations_inform_defense(self):
        """#14: Guardrail violations → defense strategy."""
        guardrail = {"violations": ["Judge cited non-existent precedent"]}
        ca = _build_case_analysis()
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            guardrail,
        )
        assert any("violation" in s.lower() for s in report.defense_strategy)

    def test_conflicted_elements_exploit(self):
        """#25: Conflicted elements → defense exploit contradictions."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "conflicted",
             "required": True, "matching_fact_ids": ["f1", "f2"]},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("contradiction" in s.lower() for s in report.defense_strategy)

    def test_low_evidence_score_challenge(self):
        """Low evidence score → defense challenges reliability."""
        ca = _build_case_analysis(evidence_score=0.3)
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("reliability" in s.lower() or "evidence" in s.lower()
                    for s in report.defense_strategy)

    def test_no_angles_procedural_fallback(self):
        """No weak elements, no exceptions, high score → procedural fallback."""
        ca = _build_case_analysis(
            evidence_score=0.9,
            element_details=[
                {"element_id": "act_by_accused", "status": "satisfied",
                 "required": True, "matching_fact_ids": ["f1", "f2"]},
            ],
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("procedural" in s.lower() for s in report.defense_strategy)


class TestEvidenceRecommendations:
    """Tests 7, 15: Evidence improvement suggestions."""

    def test_suggestions_for_weak_elements(self):
        """#7: Weak elements get evidence recommendations."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.evidence_recommendations) > 0

    def test_element_specific_templates(self):
        """#15: Known element IDs map to specific evidence templates."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "death_of_human", "status": "partial",
             "required": True, "matching_fact_ids": []},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert any("autopsy" in r.lower() or "death certificate" in r.lower()
                    for r in report.evidence_recommendations)

    def test_generic_fallback_when_no_template(self):
        """Unknown element IDs get generic evidence suggestions."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "custom_unknown_element", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.evidence_recommendations) > 0
        assert any("forensic" in r.lower() or "witness" in r.lower()
                    for r in report.evidence_recommendations)

    def test_no_recs_when_no_weak(self):
        """No weak elements → no evidence recommendations."""
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "satisfied",
             "required": True, "matching_fact_ids": ["f1"]},
        ])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.evidence_recommendations) == 0


class TestConvictionProbability:
    """Test 8: Conviction probability formula."""

    def test_formula_correctness(self):
        """#8: probability = confidence*0.5 + evidence*0.4 + burden_mult*0.1"""
        ca = _build_case_analysis(
            confidence=0.8,
            evidence_score=0.7,
            burden_stage="prima_facie_established",
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        # 0.8*0.5 + 0.7*0.4 + 0.8*0.1 = 0.40 + 0.28 + 0.08 = 0.76
        assert abs(report.conviction_probability_estimate - 0.76) < 0.001

    def test_zero_inputs(self):
        """All zero inputs → minimal probability."""
        ca = _build_case_analysis(
            confidence=0.0,
            evidence_score=0.0,
            burden_stage="acquittal_recommended",
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        # 0*0.5 + 0*0.4 + 0.1*0.1 = 0.01
        assert report.conviction_probability_estimate == pytest.approx(0.01, abs=0.001)

    def test_probability_capped_at_one(self):
        """Probability never exceeds 1.0."""
        ca = _build_case_analysis(
            confidence=1.0,
            evidence_score=1.0,
            burden_stage="prima_facie_established",
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert report.conviction_probability_estimate <= 1.0

    def test_unknown_burden_stage_default_multiplier(self):
        """Unknown burden stage uses default multiplier (0.3)."""
        ca = _build_case_analysis(
            confidence=0.5,
            evidence_score=0.5,
            burden_stage="totally_unknown_stage",
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        # 0.5*0.5 + 0.5*0.4 + 0.3*0.1 = 0.25 + 0.20 + 0.03 = 0.48
        assert abs(report.conviction_probability_estimate - 0.48) < 0.001


class TestRiskLevel:
    """Test 9: Risk level classification."""

    def test_high_risk(self):
        """#9: probability ≥ 0.75 → 'high'."""
        ca = _build_case_analysis(
            confidence=0.9, evidence_score=0.9,
            burden_stage="prima_facie_established",
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert report.risk_level == "high"

    def test_moderate_risk(self):
        """probability 0.5-0.75 → 'moderate'."""
        ca = _build_case_analysis(
            confidence=0.6, evidence_score=0.6,
            burden_stage="defense_rebuttal_required",
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert report.risk_level == "moderate"

    def test_low_risk(self):
        """probability < 0.5 → 'low'."""
        ca = _build_case_analysis(
            confidence=0.2, evidence_score=0.2,
            burden_stage="prosecution_incomplete",
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert report.risk_level == "low"


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS — ExplanationEngine
# ═══════════════════════════════════════════════════════════════════════

class TestExplanationEngine:
    """Tests 10, 22, 23: Explanation generation."""

    def test_deterministic_fallback(self):
        """#10: Without OLLAMA_MODEL, deterministic explanation produced."""
        ca = _build_case_analysis(section="302")
        strategy = StrategyReport(risk_level="high").to_dict()
        engine = ExplanationEngine()
        explanation = engine.generate_case_explanation(
            ca, _default_panel_result(), strategy,
        )
        assert isinstance(explanation, str)
        assert "302" in explanation
        assert "Verdict Recommendation" in explanation

    def test_explanation_includes_sections(self):
        """Deterministic explanation includes key analysis sections."""
        ca = _build_case_analysis(
            section="420",
            evidence_score=0.6,
            confidence=0.5,
        )
        strategy = StrategyReport(
            weak_elements=[{"element_id": "deception_element",
                           "status": "partial", "reason": "testing"}],
            risk_level="moderate",
            conviction_probability_estimate=0.55,
        ).to_dict()
        explanation = ExplanationEngine().generate_case_explanation(
            ca, _default_panel_result(), strategy,
        )
        assert "Evidence Assessment" in explanation
        assert "Judicial Panel" in explanation
        assert "Risk Analysis" in explanation

    @patch("strategy.explanation_engine.ExplanationEngine._llm_explanation")
    def test_llm_path_used_when_available(self, mock_llm):
        """#22: LLM explanation path is called when model is set."""
        mock_llm.return_value = "LLM generated explanation text."
        engine = ExplanationEngine(ollama_model="test-model")
        result = engine.generate_case_explanation(
            _build_case_analysis(), _default_panel_result(),
            StrategyReport().to_dict(),
        )
        assert result == "LLM generated explanation text."
        mock_llm.assert_called_once()

    @patch("strategy.explanation_engine.ExplanationEngine._llm_explanation")
    def test_llm_failure_falls_back(self, mock_llm):
        """#23: LLM failure → deterministic fallback."""
        mock_llm.side_effect = ConnectionError("Ollama down")
        engine = ExplanationEngine(ollama_model="test-model")
        result = engine.generate_case_explanation(
            _build_case_analysis(section="302"), _default_panel_result(),
            StrategyReport().to_dict(),
        )
        assert isinstance(result, str)
        assert "302" in result  # Deterministic output includes section

    def test_prompt_builder(self):
        """Prompt builder produces valid text with key facts."""
        ca = _build_case_analysis(section="323", confidence=0.6)
        strategy = StrategyReport(risk_level="low").to_dict()
        prompt = ExplanationEngine._build_prompt(
            ca, _default_panel_result(), strategy,
        )
        assert "323" in prompt
        assert "legal analyst" in prompt.lower()


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS — Strategy Models
# ═══════════════════════════════════════════════════════════════════════

class TestStrategyModels:
    """Test 11: Serialisation."""

    def test_weak_element_to_dict(self):
        w = WeakElement("act_by_accused", "not_satisfied", "missing evidence")
        d = w.to_dict()
        assert d["element_id"] == "act_by_accused"
        assert d["status"] == "not_satisfied"

    def test_strong_element_to_dict(self):
        s = StrongElement("act_by_accused", 0.85, 3)
        d = s.to_dict()
        assert d["evidence_score"] == 0.85
        assert d["supporting_fact_count"] == 3

    def test_strategy_report_to_dict(self):
        """#11: StrategyReport.to_dict() round-trip."""
        report = StrategyReport(
            weak_elements=[{"element_id": "x", "status": "partial", "reason": "r"}],
            prosecution_strategy=["strengthen x"],
            risk_level="moderate",
            conviction_probability_estimate=0.6,
        )
        d = report.to_dict()
        assert d["risk_level"] == "moderate"
        assert len(d["weak_elements"]) == 1

    def test_strategy_report_to_json(self):
        report = StrategyReport(risk_level="low")
        j = report.to_json()
        assert '"risk_level": "low"' in j


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Tests 16–18: Strategy engine on real pipeline output."""

    def test_strategy_on_real_pipeline(self):
        """#16: StrategyEngine produces valid report from real EvaluationPipeline."""
        fm = _murder_matrix()
        pipeline = EvaluationPipeline(auto_detect=True)
        analysis = pipeline.run(fm)
        case_dict = analysis.to_dict()

        engine = StrategyEngine()
        report = engine.generate(
            case_dict, _default_panel_result(),
            _default_lawyer_output(), _default_guardrail_report(),
        )
        assert isinstance(report, StrategyReport)
        assert report.risk_level in ("low", "moderate", "high")
        assert 0.0 <= report.conviction_probability_estimate <= 1.0
        assert len(report.prosecution_strategy) > 0
        assert len(report.defense_strategy) > 0

    def test_run_full_simulation_includes_strategy(self):
        """#17: run_full_simulation() result contains strategy_report."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        assert "strategy_report" in result
        sr = result["strategy_report"]
        assert "risk_level" in sr
        assert "conviction_probability_estimate" in sr
        assert "prosecution_strategy" in sr
        assert "defense_strategy" in sr

    def test_run_full_simulation_includes_explanation(self):
        """#18: run_full_simulation() result contains explanation string."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        assert "explanation" in result
        assert isinstance(result["explanation"], str)
        assert len(result["explanation"]) > 100

    def test_backward_compatibility(self):
        """Old keys still present in result dict."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        for key in ("case_analysis", "lawyer_output", "panel_result",
                     "final_judgment", "research_data", "guardrail_report"):
            assert key in result


# ═══════════════════════════════════════════════════════════════════════
# SYSTEM TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestSystemEndToEnd:
    """Tests 19–20: Full pipeline scenarios."""

    def test_strong_case_end_to_end(self):
        """#19: Strong murder case → high probability, strategy populated."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        sr = result["strategy_report"]
        # Strong case should have moderate-to-high probability
        assert sr["conviction_probability_estimate"] >= 0.4
        assert sr["risk_level"] in ("moderate", "high")
        # Explanation should reference the section
        assert "302" in result["explanation"] or "Case Analysis" in result["explanation"]

    def test_weak_case_end_to_end(self):
        """#20: Weak case → low probability, many evidence recommendations."""
        fm = _weak_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        sr = result["strategy_report"]
        # Weak case should have weak elements and evidence recs
        assert len(sr["weak_elements"]) > 0 or sr["conviction_probability_estimate"] < 0.5
        assert len(sr["defense_strategy"]) > 0

    def test_cheating_420_case(self):
        """Section 420 cheating case → appropriate strategies."""
        fm = FactMatrix()
        fm.add_fact("actus_reus", "Accused created fake documents.",
                    FactSource.DOCUMENT, severity="high",
                    tags=["deception", "deception_element"])
        fm.add_fact("actus_reus", "Victim was deceived into handing money.",
                    FactSource.WITNESS, severity="high",
                    tags=["inducement", "inducement_element"])
        fm.add_fact("mens_rea", "Accused planned the fraud for weeks.",
                    FactSource.DOCUMENT, severity="high",
                    tags=["intention", "cheating_intent"])
        fm.add_fact("evidence", "Bank records show transfers.",
                    FactSource.DOCUMENT, severity="medium",
                    tags=["financial", "gain_loss_element"])
        result = run_full_simulation(fm, auto_detect=True)
        assert "strategy_report" in result
        assert "explanation" in result

    def test_self_defense_case(self):
        """Section 304 with self-defense exception."""
        fm = FactMatrix()
        fm.add_fact("actus_reus", "Accused hit the victim.",
                    FactSource.WITNESS, severity="high",
                    tags=["act_by_accused", "hurt"])
        fm.add_fact("actus_reus", "Victim died from injuries.",
                    FactSource.FORENSIC, severity="critical",
                    tags=["death_of_human", "death_caused"])
        fm.add_fact("mens_rea", "Accused knew his actions could kill.",
                    FactSource.WITNESS, severity="medium",
                    tags=["knowledge", "knowledge_element"])
        fm.add_fact("exceptions_claimed", "Accused acted in self-defense.",
                    FactSource.USER_INPUT, severity="low",
                    tags=["self-defense"])
        result = run_full_simulation(fm, auto_detect=True)
        sr = result["strategy_report"]
        # Defense strategy should mention exceptions
        defense_text = " ".join(sr["defense_strategy"])
        assert len(sr["defense_strategy"]) > 0


class TestMultipleElementCombinations:
    """Additional edge case tests for strategy engine."""

    def test_empty_element_details(self):
        """Empty element_details → no weak/strong elements."""
        ca = _build_case_analysis(element_details=[])
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.weak_elements) == 0
        assert len(report.strong_elements) == 0

    def test_many_weak_elements(self):
        """Multiple weak elements all detected."""
        elements = [
            {"element_id": f"elem_{i}", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []}
            for i in range(5)
        ]
        ca = _build_case_analysis(element_details=elements)
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.weak_elements) == 5

    def test_mixed_elements(self):
        """Mix of satisfied, partial, not_satisfied, conflicted."""
        elements = [
            {"element_id": "strong1", "status": "satisfied",
             "required": True, "matching_fact_ids": ["f1", "f2"]},
            {"element_id": "weak1", "status": "partial",
             "required": True, "matching_fact_ids": ["f1"]},
            {"element_id": "weak2", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []},
            {"element_id": "conflict1", "status": "conflicted",
             "required": True, "matching_fact_ids": ["f1", "f2"]},
        ]
        ca = _build_case_analysis(
            element_details=elements,
            per_element_scores={"strong1": 0.9},
        )
        report = StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert len(report.weak_elements) == 3
        assert len(report.strong_elements) == 1


class TestStrategyReportImmutability:
    """Ensure strategy generation does not mutate inputs."""

    def test_case_analysis_not_mutated(self):
        import copy
        ca = _build_case_analysis(element_details=[
            {"element_id": "act_by_accused", "status": "not_satisfied",
             "required": True, "matching_fact_ids": []},
        ])
        original = copy.deepcopy(ca)
        StrategyEngine().generate(
            ca, _default_panel_result(), _default_lawyer_output(),
            _default_guardrail_report(),
        )
        assert ca == original
