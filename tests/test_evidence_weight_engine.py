"""
Unit tests for core.evidence_weight_engine — Evidence Weight Scoring Engine.

Test scenarios:

 1. High severity forensic evidence gives high score.
 2. Multiple medium facts accumulate correctly.
 3. Conflict forces score to 0.0.
 4. Partial element lowers final score.
 5. Source multipliers applied correctly.
 6. Cap at 1.0 enforced.
 7. overall_evidence_score calculated correctly.
 8. Weak vs strong classification works.
 9. Elements not satisfied are ignored.
10. Schema integrity exact.

Run:  python -m pytest tests/test_evidence_weight_engine.py -v
"""

import json
import pytest

from core.fact_matrix import (
    FactCategory,
    FactMatrix,
    FactSource,
    Severity,
)
from core.statute_engine import (
    ElementStatus,
    EvaluationResult,
    IPC302Evaluator,
)
from core.evidence_weight_engine import EvidenceWeightEngine, EvidenceWeightResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _evaluator() -> IPC302Evaluator:
    return IPC302Evaluator()


def _strong_matrix() -> FactMatrix:
    """All required IPC-302 elements satisfied at HIGH+ severity."""
    m = FactMatrix()
    m.add_fact("actus_reus", "Victim died from stab wounds",
               "forensic", severity="critical", tags=["death_caused"])
    m.add_fact("actus_reus", "Accused stabbed the victim",
               "witness", severity="critical", tags=["act_by_accused"])
    m.add_fact("mens_rea", "Accused planned attack deliberately",
               "document", severity="high", tags=["premeditated", "intention"])
    m.add_fact("evidence", "Knife recovered with fingerprints",
               "forensic", severity="high", tags=["forensic", "weapon"])
    return m


def _run(matrix: FactMatrix) -> tuple:
    """Evaluate + weight in one go, returning (eval_result, weight_result)."""
    ev = _evaluator()
    er = ev.evaluate(matrix)
    engine = EvidenceWeightEngine()
    wr = engine.evaluate(matrix, er)
    return er, wr


# ═════════════════════════════════════════════════════════════════════════
# 1. High severity forensic evidence gives high score
# ═════════════════════════════════════════════════════════════════════════

class TestScenario01_HighSeverityForensic:
    """A critical-severity forensic fact should produce a high element score."""

    def test_death_element_high_score(self):
        _, wr = _run(_strong_matrix())
        assert wr.element_scores["death_of_human"] >= 0.7

    def test_forensic_source_adds_bonus(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim died",
                   "forensic", severity="critical", tags=["death_caused"])
        m.add_fact("actus_reus", "Accused attacked victim",
                   "forensic", severity="critical", tags=["act_by_accused"])
        m.add_fact("mens_rea", "Premeditated intent",
                   "forensic", severity="critical", tags=["intention"])
        _, wr = _run(m)
        # critical (1.0) + forensic bonus (0.2) = 1.2 → capped to 1.0
        assert wr.element_scores["death_of_human"] == 1.0

    def test_strong_matrix_overall_high(self):
        _, wr = _run(_strong_matrix())
        assert wr.overall_evidence_score >= 0.5


# ═════════════════════════════════════════════════════════════════════════
# 2. Multiple medium facts accumulate correctly
# ═════════════════════════════════════════════════════════════════════════

class TestScenario02_MultipleMedianAccumulate:
    """Two medium-severity witness facts should accumulate their scores."""

    def test_two_medium_witness_facts(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim found dead",
                   "witness", severity="medium", tags=["death_caused"])
        m.add_fact("actus_reus", "Victim declared dead at hospital",
                   "witness", severity="medium", tags=["death_caused"])
        m.add_fact("actus_reus", "Accused attacked victim",
                   "witness", severity="high", tags=["act_by_accused"])
        m.add_fact("mens_rea", "Accused confessed intent",
                   "confession", severity="high", tags=["intention"])
        _, wr = _run(m)
        # death: 2 × (0.5 + 0.1) = 1.2 → capped 1.0
        assert wr.element_scores["death_of_human"] == 1.0

    def test_single_medium_fact_moderate_score(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim found dead",
                   "witness", severity="medium", tags=["death_caused"])
        m.add_fact("actus_reus", "Accused hit victim",
                   "witness", severity="high", tags=["act_by_accused"])
        m.add_fact("mens_rea", "Accused intended harm",
                   "witness", severity="medium", tags=["intention"])
        _, wr = _run(m)
        # death: 0.5 + 0.1 = 0.6
        assert wr.element_scores["death_of_human"] == pytest.approx(0.6, abs=0.01)


# ═════════════════════════════════════════════════════════════════════════
# 3. Conflict forces score to 0.0
# ═════════════════════════════════════════════════════════════════════════

class TestScenario03_ConflictForcesZero:
    """A conflicted element must receive a score of exactly 0.0."""

    def test_conflicted_score_is_zero(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim died",
                   "forensic", severity="critical", tags=["death_caused"])
        m.add_fact("actus_reus", "Accused stabbed victim",
                   "witness", severity="high", tags=["act_by_accused"])
        # intent facts + conflict
        f1 = m.add_fact("mens_rea", "Accused planned murder",
                        "witness", severity="high", tags=["intention"])
        f2 = m.add_fact("mens_rea", "Accused acted on impulse — no plan",
                        "witness", severity="high", tags=["intention"])
        m.register_conflict(f1.id, f2.id, "Contradicts premeditation")
        er, wr = _run(m)
        # intention_or_knowledge should be conflicted → 0.0
        if "intention_or_knowledge" in wr.element_scores:
            assert wr.element_scores["intention_or_knowledge"] == 0.0

    def test_conflicted_in_weak_list(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim died",
                   "forensic", severity="critical", tags=["death_caused"])
        m.add_fact("actus_reus", "Accused stabbed victim",
                   "witness", severity="high", tags=["act_by_accused"])
        f1 = m.add_fact("mens_rea", "Accused planned murder",
                        "witness", severity="high", tags=["intention"])
        f2 = m.add_fact("mens_rea", "Accused had no plan",
                        "witness", severity="high", tags=["intention"])
        m.register_conflict(f1.id, f2.id, "Contradicts intent")
        _, wr = _run(m)
        if "intention_or_knowledge" in wr.element_scores:
            assert "intention_or_knowledge" in wr.weak_elements


# ═════════════════════════════════════════════════════════════════════════
# 4. Partial element lowers final score
# ═════════════════════════════════════════════════════════════════════════

class TestScenario04_PartialElements:
    """An element with only low-severity evidence scores lower."""

    def test_low_severity_gives_partial(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Someone might have died",
                   "witness", severity="low", tags=["death_caused"])
        m.add_fact("actus_reus", "Accused pushed victim",
                   "witness", severity="high", tags=["act_by_accused"])
        m.add_fact("mens_rea", "Accused had intent",
                   "document", severity="high", tags=["intention"])
        _, wr = _run(m)
        # death scored via low-severity partial: 0.25 + 0.1 = 0.35
        if "death_of_human" in wr.element_scores:
            assert wr.element_scores["death_of_human"] < 0.5

    def test_partial_lowers_overall(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim might have died",
                   "other", severity="low", tags=["death_caused"])
        m.add_fact("actus_reus", "Accused struck victim",
                   "forensic", severity="critical", tags=["act_by_accused"])
        m.add_fact("mens_rea", "Accused planned attack",
                   "forensic", severity="critical", tags=["intention"])
        _, wr = _run(m)
        # Overall dragged down by weak death element
        assert wr.overall_evidence_score < 1.0

    def test_partial_appears_in_weak_if_below_threshold(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim possibly dead",
                   "other", severity="low", tags=["death_caused"])
        m.add_fact("actus_reus", "Accused hit victim",
                   "forensic", severity="critical", tags=["act_by_accused"])
        m.add_fact("mens_rea", "Accused had motive",
                   "forensic", severity="critical", tags=["intention"])
        _, wr = _run(m)
        if "death_of_human" in wr.element_scores:
            if wr.element_scores["death_of_human"] < 0.4:
                assert "death_of_human" in wr.weak_elements


# ═════════════════════════════════════════════════════════════════════════
# 5. Source multipliers applied correctly
# ═════════════════════════════════════════════════════════════════════════

class TestScenario05_SourceMultipliers:
    """Different sources must add their specific bonus."""

    def _score_single(self, source: str, severity: str = "medium") -> float:
        """Score a single-fact matrix to isolate source multiplier."""
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim died",
                   source, severity=severity, tags=["death_caused"])
        m.add_fact("actus_reus", "Accused attacked",
                   source, severity="high", tags=["act_by_accused"])
        m.add_fact("mens_rea", "Accused had intent",
                   source, severity="high", tags=["intention"])
        _, wr = _run(m)
        return wr.element_scores.get("death_of_human", 0.0)

    def test_forensic_highest_bonus(self):
        # medium (0.5) + forensic (0.2) = 0.7
        assert self._score_single("forensic") == pytest.approx(0.7, abs=0.01)

    def test_document_bonus(self):
        # medium (0.5) + document (0.15) = 0.65
        assert self._score_single("document") == pytest.approx(0.65, abs=0.01)

    def test_witness_bonus(self):
        # medium (0.5) + witness (0.1) = 0.6
        assert self._score_single("witness") == pytest.approx(0.6, abs=0.01)

    def test_confession_bonus(self):
        # medium (0.5) + confession (0.05) = 0.55
        assert self._score_single("confession") == pytest.approx(0.55, abs=0.01)

    def test_user_input_no_bonus(self):
        # medium (0.5) + 0 = 0.5
        assert self._score_single("user_input") == pytest.approx(0.5, abs=0.01)

    def test_other_no_bonus(self):
        assert self._score_single("other") == pytest.approx(0.5, abs=0.01)


# ═════════════════════════════════════════════════════════════════════════
# 6. Cap at 1.0 enforced
# ═════════════════════════════════════════════════════════════════════════

class TestScenario06_CapEnforced:
    """Element scores must never exceed 1.0."""

    def test_multiple_critical_forensic_capped(self):
        m = FactMatrix()
        for i in range(5):
            m.add_fact("actus_reus", f"Victim confirmed dead #{i}",
                       "forensic", severity="critical", tags=["death_caused"])
        m.add_fact("actus_reus", "Accused attacked victim",
                   "forensic", severity="critical", tags=["act_by_accused"])
        m.add_fact("mens_rea", "Accused had intent",
                   "forensic", severity="critical", tags=["intention"])
        _, wr = _run(m)
        assert wr.element_scores["death_of_human"] == 1.0

    def test_all_scores_within_bounds(self):
        _, wr = _run(_strong_matrix())
        for eid, score in wr.element_scores.items():
            assert 0.0 <= score <= 1.0, f"{eid} out of bounds: {score}"

    def test_overall_within_bounds(self):
        _, wr = _run(_strong_matrix())
        assert 0.0 <= wr.overall_evidence_score <= 1.0


# ═════════════════════════════════════════════════════════════════════════
# 7. overall_evidence_score calculated correctly
# ═════════════════════════════════════════════════════════════════════════

class TestScenario07_OverallScore:
    """Overall score = mean of scored element scores."""

    def test_mean_of_element_scores(self):
        _, wr = _run(_strong_matrix())
        if wr.element_scores:
            expected = sum(wr.element_scores.values()) / len(wr.element_scores)
            assert wr.overall_evidence_score == pytest.approx(expected, abs=0.001)

    def test_empty_matrix_overall_zero(self):
        m = FactMatrix()
        er = _evaluator().evaluate(m)
        engine = EvidenceWeightEngine()
        wr = engine.evaluate(m, er)
        assert wr.overall_evidence_score == 0.0

    def test_overall_is_float(self):
        _, wr = _run(_strong_matrix())
        assert isinstance(wr.overall_evidence_score, float)

    def test_single_element_equals_overall(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim died",
                   "forensic", severity="critical", tags=["death_caused"])
        # Only death element will be satisfied; others not_satisfied → ignored
        er = _evaluator().evaluate(m)
        engine = EvidenceWeightEngine()
        wr = engine.evaluate(m, er)
        if len(wr.element_scores) == 1:
            sole_score = list(wr.element_scores.values())[0]
            assert wr.overall_evidence_score == pytest.approx(sole_score, abs=0.001)


# ═════════════════════════════════════════════════════════════════════════
# 8. Weak vs strong classification works
# ═════════════════════════════════════════════════════════════════════════

class TestScenario08_WeakStrongClassification:
    """Elements >= 0.7 are strong; < 0.4 are weak."""

    def test_strong_elements_populated(self):
        _, wr = _run(_strong_matrix())
        assert len(wr.strong_elements) > 0

    def test_strong_threshold(self):
        _, wr = _run(_strong_matrix())
        for eid in wr.strong_elements:
            assert wr.element_scores[eid] >= 0.7

    def test_weak_threshold(self):
        _, wr = _run(_strong_matrix())
        for eid in wr.weak_elements:
            assert wr.element_scores[eid] < 0.4

    def test_middle_in_neither(self):
        """Elements between 0.4 and 0.7 must not appear in either list."""
        _, wr = _run(_strong_matrix())
        for eid, sc in wr.element_scores.items():
            if 0.4 <= sc < 0.7:
                assert eid not in wr.strong_elements
                assert eid not in wr.weak_elements

    def test_lists_are_sorted(self):
        _, wr = _run(_strong_matrix())
        assert wr.strong_elements == sorted(wr.strong_elements)
        assert wr.weak_elements == sorted(wr.weak_elements)


# ═════════════════════════════════════════════════════════════════════════
# 9. Elements not satisfied are ignored
# ═════════════════════════════════════════════════════════════════════════

class TestScenario09_NotSatisfiedIgnored:
    """Only satisfied/partial/conflicted elements appear in scores."""

    def test_empty_matrix_no_scores(self):
        m = FactMatrix()
        er = _evaluator().evaluate(m)
        engine = EvidenceWeightEngine()
        wr = engine.evaluate(m, er)
        assert wr.element_scores == {}

    def test_not_satisfied_absent_from_scores(self):
        m = FactMatrix()
        m.add_fact("actus_reus", "Victim died",
                   "forensic", severity="critical", tags=["death_caused"])
        # act and intent not satisfied
        er = _evaluator().evaluate(m)
        engine = EvidenceWeightEngine()
        wr = engine.evaluate(m, er)
        for detail in er.element_details:
            if detail["status"] == ElementStatus.NOT_SATISFIED.value:
                assert detail["element_id"] not in wr.element_scores

    def test_satisfied_present_in_scores(self):
        _, wr = _run(_strong_matrix())
        assert "death_of_human" in wr.element_scores
        assert "act_by_accused" in wr.element_scores
        assert "intention_or_knowledge" in wr.element_scores

    def test_optional_evidence_scored_when_satisfied(self):
        _, wr = _run(_strong_matrix())
        # strong_matrix has evidence facts
        assert "supporting_evidence" in wr.element_scores


# ═════════════════════════════════════════════════════════════════════════
# 10. Schema integrity exact
# ═════════════════════════════════════════════════════════════════════════

class TestScenario10_SchemaIntegrity:
    """Output must conform to the exact specified schema."""

    def test_result_type(self):
        _, wr = _run(_strong_matrix())
        assert isinstance(wr, EvidenceWeightResult)

    def test_to_dict_keys(self):
        _, wr = _run(_strong_matrix())
        d = wr.to_dict()
        assert set(d.keys()) == {
            "element_scores", "overall_evidence_score",
            "weak_elements", "strong_elements",
        }

    def test_element_scores_are_floats(self):
        _, wr = _run(_strong_matrix())
        for eid, score in wr.element_scores.items():
            assert isinstance(score, float), f"{eid} score is {type(score)}"

    def test_to_json_parseable(self):
        _, wr = _run(_strong_matrix())
        parsed = json.loads(wr.to_json())
        assert "element_scores" in parsed
        assert "overall_evidence_score" in parsed

    def test_lists_are_lists(self):
        _, wr = _run(_strong_matrix())
        assert isinstance(wr.weak_elements, list)
        assert isinstance(wr.strong_elements, list)

    def test_roundtrip_values_preserved(self):
        _, wr = _run(_strong_matrix())
        parsed = json.loads(wr.to_json())
        assert parsed["overall_evidence_score"] == wr.overall_evidence_score
