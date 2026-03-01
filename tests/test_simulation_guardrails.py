"""
Tests for core.simulation_guardrails — SimulationGuardrails.

10 test categories:

 1. Valid lawyer output passes.
 2. Lawyer changing section fails.
 3. Lawyer inventing element fails.
 4. Risk mismatch flagged.
 5. Judge contradicting burden fails.
 6. Judge contradicting negation fails.
 7. Valid judge output passes.
 8. Judgment missing section fails.
 9. Judgment contradicting acquittal fails.
10. Clean full flow passes.

Run:  python -m pytest tests/test_simulation_guardrails.py -v
"""

import pytest

from core.simulation_guardrails import SimulationGuardrails


# ── fixtures ────────────────────────────────────────────────────────────

@pytest.fixture()
def guardrails() -> SimulationGuardrails:
    return SimulationGuardrails()


def _base_case_analysis(
    *,
    section: str = "302 IPC",
    burden_stage: str = "prima_facie_established",
    confidence_score: float = 0.85,
    fully_negated: bool = False,
    detected_sections: list | None = None,
) -> dict:
    """Return a minimal but valid CaseAnalysis dict."""
    return {
        "evaluation_result": {
            "section": section,
            "section_title": "Murder",
            "element_details": [
                {
                    "element_id": "death_caused",
                    "status": "satisfied",
                    "required": True,
                    "matching_fact_ids": ["f1"],
                    "confidence_notes": [],
                },
                {
                    "element_id": "act_by_accused",
                    "status": "satisfied",
                    "required": True,
                    "matching_fact_ids": ["f2"],
                    "confidence_notes": [],
                },
                {
                    "element_id": "intention",
                    "status": "satisfied",
                    "required": True,
                    "matching_fact_ids": ["f3"],
                    "confidence_notes": [],
                },
            ],
            "elements_satisfied": 3,
            "elements_failed": 0,
            "elements_required": 3,
            "verdict_recommendation": "prima_facie_met",
        },
        "burden_result": {
            "burden_stage": burden_stage,
            "confidence_score": confidence_score,
            "required_elements_satisfied": 3,
            "required_elements_total": 3,
            "conflicted_elements": 0,
            "exceptions_claimed": [],
            "exceptions_supported": [],
            "reasoning_flags": [],
        },
        "metadata": {
            "pipeline_version": "1.0.0",
            "section_evaluated": section,
            "section_title": "Murder",
            "evaluated_at": "2026-03-01T00:00:00+00:00",
            "detected_sections": detected_sections or [],
        },
        "evidence_weight_result": {
            "overall_evidence_score": 0.9,
            "element_scores": {
                "death_caused": 0.95,
                "act_by_accused": 0.9,
                "intention": 0.85,
            },
        },
        "exception_result": {
            "exceptions_detected": [],
            "fully_negated": fully_negated,
            "requires_manual_review": False,
            "negated_elements": [],
            "exceptions_supported": [],
        },
    }


def _valid_lawyer_output(section: str = "302 IPC") -> dict:
    return {
        "confirmed_section": section,
        "alternate_sections": [],
        "prosecution_arguments": [
            "Element 'death_caused' is satisfied with 1 supporting fact(s).",
            "Element 'act_by_accused' is satisfied with 1 supporting fact(s).",
            "Element 'intention' is satisfied with 1 supporting fact(s).",
        ],
        "defense_arguments": [
            "No strong defense arguments identified.",
        ],
        "identified_weaknesses": [],
        "risk_level": "low",
    }


def _valid_judge_output(verdict: str = "convict") -> dict:
    return {
        "judge_type": "textualist",
        "agreement_with_lawyer": True,
        "key_reasoning_points": [
            "Element 'death_caused' is textually satisfied.",
            "Element 'act_by_accused' is textually satisfied.",
            "Element 'intention' is textually satisfied.",
        ],
        "concerns": [],
        "provisional_verdict": verdict,
    }


def _valid_judgment_text() -> str:
    return (
        "JUDGMENT — 302 IPC (Murder)\n"
        "==================================================\n"
        "Evaluation Date: 2026-03-01\n\n"
        "BURDEN OF PROOF ANALYSIS\n"
        "  Stage: prima_facie_established\n"
        "  Confidence: 0.85\n\n"
        "FINAL VERDICT\n"
        "==================================================\n"
        "  Majority Verdict: CONVICT\n"
        "  The panel finds that the prosecution has met the burden. "
        "We proceed to convict."
    )


# ── 1. Valid lawyer output passes ───────────────────────────────────────

class TestValidLawyerPasses:
    def test_clean_lawyer_output(self, guardrails: SimulationGuardrails):
        ca = _base_case_analysis()
        lo = _valid_lawyer_output()
        result = guardrails.validate_lawyer_output(ca, lo)
        assert result["valid"] is True
        assert result["violations"] == []

    def test_with_alternate_sections_in_detected(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(
            detected_sections=[
                {"section": "302 IPC", "score": 0.9},
                {"section": "304 IPC", "score": 0.6},
            ],
        )
        lo = _valid_lawyer_output()
        lo["alternate_sections"] = ["304 IPC"]
        result = guardrails.validate_lawyer_output(ca, lo)
        assert result["valid"] is True
        assert result["violations"] == []


# ── 2. Lawyer changing section fails ────────────────────────────────────

class TestLawyerChangingSection:
    def test_wrong_section_flagged(self, guardrails: SimulationGuardrails):
        ca = _base_case_analysis(section="302 IPC")
        lo = _valid_lawyer_output(section="304 IPC")
        result = guardrails.validate_lawyer_output(ca, lo)
        assert result["valid"] is False
        assert any("confirmed_section" in v for v in result["violations"])

    def test_alternate_not_in_detected(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(detected_sections=[])
        lo = _valid_lawyer_output()
        lo["alternate_sections"] = ["999 IPC"]
        result = guardrails.validate_lawyer_output(ca, lo)
        assert result["valid"] is False
        assert any("alternate_section" in v for v in result["violations"])


# ── 3. Lawyer inventing element fails ──────────────────────────────────

class TestLawyerInventingElement:
    def test_prosecution_references_unknown_element(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis()
        lo = _valid_lawyer_output()
        lo["prosecution_arguments"].append(
            "Element 'fabricated_element' is satisfied with 5 supporting fact(s)."
        )
        result = guardrails.validate_lawyer_output(ca, lo)
        assert result["valid"] is False
        assert any("fabricated_element" in v for v in result["violations"])

    def test_defense_references_unknown_element(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis()
        lo = _valid_lawyer_output()
        lo["defense_arguments"] = [
            "Element 'invented_gap' is not satisfied — prosecution gap."
        ]
        result = guardrails.validate_lawyer_output(ca, lo)
        assert result["valid"] is False
        assert any("invented_gap" in v for v in result["violations"])


# ── 4. Risk mismatch flagged ───────────────────────────────────────────

class TestRiskMismatch:
    def test_high_confidence_with_high_risk(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(confidence_score=0.9)
        lo = _valid_lawyer_output()
        lo["risk_level"] = "high"
        result = guardrails.validate_lawyer_output(ca, lo)
        assert result["valid"] is False
        assert any("risk_level" in v for v in result["violations"])

    def test_low_confidence_with_low_risk(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(confidence_score=0.2)
        lo = _valid_lawyer_output()
        lo["risk_level"] = "low"
        result = guardrails.validate_lawyer_output(ca, lo)
        assert result["valid"] is False
        assert any("risk_level" in v for v in result["violations"])

    def test_medium_confidence_medium_risk_passes(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(confidence_score=0.55)
        lo = _valid_lawyer_output()
        lo["risk_level"] = "medium"
        result = guardrails.validate_lawyer_output(ca, lo)
        # No risk violation (section/prosecution refs may still pass)
        assert not any("risk_level" in v for v in result["violations"])


# ── 5. Judge contradicting burden fails ─────────────────────────────────

class TestJudgeContradictsBurden:
    def test_convict_on_prosecution_incomplete(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(burden_stage="prosecution_incomplete")
        jo = _valid_judge_output(verdict="convict")
        result = guardrails.validate_judge_output(ca, jo)
        assert result["valid"] is False
        assert any("prosecution_incomplete" in v for v in result["violations"])

    def test_convict_on_acquittal_recommended(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(burden_stage="acquittal_recommended")
        jo = _valid_judge_output(verdict="convict")
        result = guardrails.validate_judge_output(ca, jo)
        assert result["valid"] is False
        assert any("acquittal_recommended" in v for v in result["violations"])

    def test_review_on_acquittal_recommended(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(burden_stage="acquittal_recommended")
        jo = _valid_judge_output(verdict="review")
        result = guardrails.validate_judge_output(ca, jo)
        assert result["valid"] is False
        assert any("acquittal_recommended" in v for v in result["violations"])


# ── 6. Judge contradicting negation fails ───────────────────────────────

class TestJudgeContradictsNegation:
    def test_convict_while_fully_negated(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(fully_negated=True)
        jo = _valid_judge_output(verdict="convict")
        result = guardrails.validate_judge_output(ca, jo)
        assert result["valid"] is False
        assert any("fully_negated" in v for v in result["violations"])

    def test_review_while_fully_negated(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(fully_negated=True)
        jo = _valid_judge_output(verdict="review")
        result = guardrails.validate_judge_output(ca, jo)
        assert result["valid"] is False
        assert any("fully_negated" in v for v in result["violations"])


# ── 7. Valid judge output passes ────────────────────────────────────────

class TestValidJudgePasses:
    def test_clean_convict(self, guardrails: SimulationGuardrails):
        ca = _base_case_analysis(burden_stage="prima_facie_established")
        jo = _valid_judge_output(verdict="convict")
        result = guardrails.validate_judge_output(ca, jo)
        assert result["valid"] is True
        assert result["violations"] == []

    def test_acquit_on_acquittal_stage(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(burden_stage="acquittal_recommended")
        jo = _valid_judge_output(verdict="acquit")
        result = guardrails.validate_judge_output(ca, jo)
        assert result["valid"] is True

    def test_acquit_when_fully_negated(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(fully_negated=True)
        jo = _valid_judge_output(verdict="acquit")
        result = guardrails.validate_judge_output(ca, jo)
        assert result["valid"] is True

    def test_unknown_element_in_reasoning_flagged(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis()
        jo = _valid_judge_output(verdict="convict")
        jo["key_reasoning_points"].append(
            "Element 'phantom_element' is textually satisfied."
        )
        result = guardrails.validate_judge_output(ca, jo)
        assert result["valid"] is False
        assert any("phantom_element" in v for v in result["violations"])


# ── 8. Judgment missing section fails ───────────────────────────────────

class TestJudgmentMissingSection:
    def test_section_absent(self, guardrails: SimulationGuardrails):
        ca = _base_case_analysis(section="302 IPC")
        text = "JUDGMENT — REDACTED\nSome analysis with prima_facie_established."
        result = guardrails.validate_final_judgment(ca, text)
        assert result["valid"] is False
        assert any("section" in v.lower() for v in result["violations"])

    def test_burden_stage_absent(self, guardrails: SimulationGuardrails):
        ca = _base_case_analysis(burden_stage="prima_facie_established")
        text = (
            "JUDGMENT — 302 IPC (Murder)\n"
            "The case was analysed but burden stage was omitted.\n"
            "Majority Verdict: CONVICT\n"
            "We proceed to convict."
        )
        result = guardrails.validate_final_judgment(ca, text)
        assert result["valid"] is False
        assert any("burden_stage" in v for v in result["violations"])


# ── 9. Judgment contradicting acquittal fails ───────────────────────────

class TestJudgmentContradictsAcquittal:
    def test_acquittal_stage_but_no_acquit_word(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(burden_stage="acquittal_recommended")
        text = (
            "JUDGMENT — 302 IPC (Murder)\n"
            "Stage: acquittal_recommended\n"
            "Majority Verdict: REVIEW\n"
            "The panel recommends further analysis."
        )
        result = guardrails.validate_final_judgment(ca, text)
        assert result["valid"] is False
        assert any("acquit" in v for v in result["violations"])

    def test_prima_facie_but_no_convict_or_proceed(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(burden_stage="prima_facie_established")
        text = (
            "JUDGMENT — 302 IPC (Murder)\n"
            "Stage: prima_facie_established\n"
            "Majority Verdict: REVIEW\n"
            "The panel is undecided."
        )
        result = guardrails.validate_final_judgment(ca, text)
        assert result["valid"] is False
        assert any("prima_facie_established" in v for v in result["violations"])

    def test_fully_negated_but_claims_convict(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis(fully_negated=True)
        text = (
            "JUDGMENT — 302 IPC (Murder)\n"
            "Stage: prima_facie_established\n"
            "Majority Verdict: CONVICT\n"
            "The panel finds all requirements met."
        )
        result = guardrails.validate_final_judgment(ca, text)
        assert result["valid"] is False
        assert any("fully_negated" in v.lower() or "CONVICT" in v for v in result["violations"])


# ── 10. Clean full flow passes ──────────────────────────────────────────

class TestCleanFullFlow:
    def test_all_three_valid(self, guardrails: SimulationGuardrails):
        ca = _base_case_analysis()
        lo = _valid_lawyer_output()
        jo = _valid_judge_output()
        jt = _valid_judgment_text()

        r1 = guardrails.validate_lawyer_output(ca, lo)
        r2 = guardrails.validate_judge_output(ca, jo)
        r3 = guardrails.validate_final_judgment(ca, jt)

        assert r1["valid"] is True, r1["violations"]
        assert r2["valid"] is True, r2["violations"]
        assert r3["valid"] is True, r3["violations"]

    def test_all_violations_collected(
        self, guardrails: SimulationGuardrails,
    ):
        """Multiple violations across all validators are reported."""
        ca = _base_case_analysis(
            burden_stage="acquittal_recommended",
            confidence_score=0.2,
            fully_negated=True,
        )
        lo = _valid_lawyer_output(section="999 IPC")
        lo["risk_level"] = "low"
        lo["prosecution_arguments"].append(
            "Element 'ghost' is satisfied with 1 supporting fact(s)."
        )

        jo = _valid_judge_output(verdict="convict")

        jt = "Some text with no section, no stage, Majority Verdict: CONVICT"

        r1 = guardrails.validate_lawyer_output(ca, lo)
        r2 = guardrails.validate_judge_output(ca, jo)
        r3 = guardrails.validate_final_judgment(ca, jt)

        assert r1["valid"] is False
        assert r2["valid"] is False
        assert r3["valid"] is False

        # Expect at least: section mismatch, ghost element, risk mismatch
        assert len(r1["violations"]) >= 3
        # Expect at least: fully_negated + acquittal contradiction
        assert len(r2["violations"]) >= 2
        # Expect at least: section missing + burden missing + acquit word
        assert len(r3["violations"]) >= 2
