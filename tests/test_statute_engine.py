"""
Tests for core.statute_engine — IPC 302 Evaluator.
Run:  python -m pytest tests/test_statute_engine.py -v
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
    Recommendation,
    StatuteEvaluator,
)


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def evaluator() -> IPC302Evaluator:
    return IPC302Evaluator()


@pytest.fixture
def empty_matrix() -> FactMatrix:
    return FactMatrix()


@pytest.fixture
def strong_murder_case() -> FactMatrix:
    """All three required elements clearly satisfied, plus evidence."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim was found dead at the scene",
        FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused stabbed the victim with a knife",
        FactSource.WITNESS, severity=Severity.CRITICAL, tags=["stabbing", "act_by_accused"],
    )
    m.add_fact(
        FactCategory.MENS_REA, "Accused purchased knife one day before and told friend he intended to kill victim",
        FactSource.WITNESS, severity=Severity.HIGH, tags=["premeditated", "intention"],
    )
    m.add_fact(
        FactCategory.EVIDENCE, "Autopsy report confirms stab wound as cause of death",
        FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["autopsy", "forensic"],
    )
    m.add_fact(
        FactCategory.EVIDENCE, "CCTV footage shows accused at the scene at time of death",
        FactSource.DOCUMENT, severity=Severity.HIGH, tags=["cctv"],
    )
    return m


@pytest.fixture
def no_intent_case() -> FactMatrix:
    """Death + act present, but no intention / knowledge facts."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim died after falling",
        FactSource.WITNESS, severity=Severity.HIGH, tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused pushed the victim during argument",
        FactSource.WITNESS, severity=Severity.HIGH, tags=["act_by_accused"],
    )
    # Deliberately no mens_rea
    return m


@pytest.fixture
def conflicted_case() -> FactMatrix:
    """One actus_reus fact is contradicted by another source."""
    m = FactMatrix()
    f1 = m.add_fact(
        FactCategory.ACTUS_REUS, "Victim was killed by accused",
        FactSource.WITNESS, severity=Severity.HIGH, tags=["death_caused", "act_by_accused"],
    )
    f2 = m.add_fact(
        FactCategory.ACTUS_REUS, "Accused was in a different city at the time",
        FactSource.DOCUMENT, severity=Severity.HIGH, tags=["absent"],
    )
    m.register_conflict(f1.id, f2.id, "Contradictory presence claims")
    m.add_fact(
        FactCategory.MENS_REA, "Accused had motive per insurance documents",
        FactSource.DOCUMENT, severity=Severity.HIGH, tags=["motive"],
    )
    return m


@pytest.fixture
def self_defense_case() -> FactMatrix:
    """All elements present but exception claimed."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim died from injuries caused by accused",
        FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused struck victim with heavy object",
        FactSource.WITNESS, severity=Severity.HIGH, tags=["act_by_accused", "violence"],
    )
    m.add_fact(
        FactCategory.MENS_REA, "Accused intentionally attacked victim",
        FactSource.WITNESS, severity=Severity.HIGH, tags=["intentional"],
    )
    m.add_fact(
        FactCategory.EXCEPTIONS_CLAIMED, "Defense claims the victim attacked first and accused acted in self-defense",
        FactSource.CASE_FILE, severity=Severity.HIGH, tags=["self-defense"],
    )
    return m


# ── basic structure ───────────────────────────────────────────────────────

class TestEvaluatorSetup:
    def test_section_info(self, evaluator: IPC302Evaluator):
        assert evaluator.SECTION == "302 IPC"
        assert evaluator.SECTION_TITLE == "Murder"

    def test_has_three_required_elements(self, evaluator: IPC302Evaluator):
        required = [e for e in evaluator.ELEMENTS if e.required]
        assert len(required) == 3

    def test_has_one_optional_element(self, evaluator: IPC302Evaluator):
        optional = [e for e in evaluator.ELEMENTS if not e.required]
        assert len(optional) == 1

    def test_is_subclass_of_base(self, evaluator: IPC302Evaluator):
        assert isinstance(evaluator, StatuteEvaluator)


# ── empty matrix → all fail ───────────────────────────────────────────────

class TestEmptyMatrix:
    def test_all_elements_fail(self, evaluator: IPC302Evaluator, empty_matrix: FactMatrix):
        result = evaluator.evaluate(empty_matrix)
        assert result.verdict_recommendation == Recommendation.INSUFFICIENT.value
        assert len(result.elements_satisfied) == 0
        assert len(result.elements_failed) >= 3

    def test_result_is_valid_json(self, evaluator: IPC302Evaluator, empty_matrix: FactMatrix):
        result = evaluator.evaluate(empty_matrix)
        parsed = json.loads(result.to_json())
        assert parsed["section"] == "302 IPC"


# ── strong case → Proceed ─────────────────────────────────────────────────

class TestStrongCase:
    def test_verdict_proceed(self, evaluator: IPC302Evaluator, strong_murder_case: FactMatrix):
        result = evaluator.evaluate(strong_murder_case)
        assert result.verdict_recommendation == Recommendation.PROCEED.value

    def test_all_required_satisfied(self, evaluator: IPC302Evaluator, strong_murder_case: FactMatrix):
        result = evaluator.evaluate(strong_murder_case)
        required_descs = {e.description for e in evaluator.ELEMENTS if e.required}
        assert required_descs == set(result.elements_satisfied) & required_descs

    def test_optional_evidence_satisfied(self, evaluator: IPC302Evaluator, strong_murder_case: FactMatrix):
        result = evaluator.evaluate(strong_murder_case)
        assert "Supporting physical or documentary evidence" in result.elements_satisfied

    def test_no_conflicts(self, evaluator: IPC302Evaluator, strong_murder_case: FactMatrix):
        result = evaluator.evaluate(strong_murder_case)
        assert result.conflicts_found == 0
        assert result.elements_conflicted == []

    def test_matching_fact_ids_present(self, evaluator: IPC302Evaluator, strong_murder_case: FactMatrix):
        result = evaluator.evaluate(strong_murder_case)
        for detail in result.element_details:
            if detail["status"] == ElementStatus.SATISFIED.value:
                assert len(detail["matching_fact_ids"]) > 0


# ── missing intent → Insufficient ─────────────────────────────────────────

class TestNoIntentCase:
    def test_verdict_insufficient(self, evaluator: IPC302Evaluator, no_intent_case: FactMatrix):
        result = evaluator.evaluate(no_intent_case)
        assert result.verdict_recommendation == Recommendation.INSUFFICIENT.value

    def test_intent_element_failed(self, evaluator: IPC302Evaluator, no_intent_case: FactMatrix):
        result = evaluator.evaluate(no_intent_case)
        assert any("Intention" in desc for desc in result.elements_failed)

    def test_death_and_act_satisfied(self, evaluator: IPC302Evaluator, no_intent_case: FactMatrix):
        result = evaluator.evaluate(no_intent_case)
        assert any("Death" in desc for desc in result.elements_satisfied)
        assert any("Act" in desc for desc in result.elements_satisfied)


# ── conflicted case → Conflicted recommendation ──────────────────────────

class TestConflictedCase:
    def test_verdict_conflicted(self, evaluator: IPC302Evaluator, conflicted_case: FactMatrix):
        result = evaluator.evaluate(conflicted_case)
        # The death_of_human fact is the one in conflict, so that required
        # element should be CONFLICTED → overall should flag conflict
        assert result.verdict_recommendation == Recommendation.CONFLICTED.value

    def test_conflicts_count(self, evaluator: IPC302Evaluator, conflicted_case: FactMatrix):
        result = evaluator.evaluate(conflicted_case)
        assert result.conflicts_found == 1


# ── exceptions surface ────────────────────────────────────────────────────

class TestExceptions:
    def test_exceptions_listed(self, evaluator: IPC302Evaluator, self_defense_case: FactMatrix):
        result = evaluator.evaluate(self_defense_case)
        assert len(result.exceptions_claimed) == 1
        assert "self-defense" in result.exceptions_claimed[0].lower()

    def test_verdict_still_proceed_when_elements_met(
        self, evaluator: IPC302Evaluator, self_defense_case: FactMatrix
    ):
        # Exceptions don't block the section match — they're surfaced for review
        result = evaluator.evaluate(self_defense_case)
        assert result.verdict_recommendation == Recommendation.PROCEED.value


# ── export format ─────────────────────────────────────────────────────────

class TestExport:
    def test_to_dict_keys(self, evaluator: IPC302Evaluator, strong_murder_case: FactMatrix):
        result = evaluator.evaluate(strong_murder_case)
        d = result.to_dict()
        expected_keys = {
            "section", "section_title", "elements_required",
            "elements_satisfied", "elements_failed", "elements_partial",
            "elements_conflicted", "element_details",
            "verdict_recommendation", "conflicts_found",
            "exceptions_claimed", "evaluated_at",
        }
        assert expected_keys == set(d.keys())

    def test_to_json_roundtrip_parseable(self, evaluator: IPC302Evaluator, strong_murder_case: FactMatrix):
        result = evaluator.evaluate(strong_murder_case)
        parsed = json.loads(result.to_json())
        assert parsed["section"] == "302 IPC"
        assert isinstance(parsed["element_details"], list)


# ── severity threshold ────────────────────────────────────────────────────

class TestSeverityThreshold:
    def test_low_severity_facts_give_partial(self, evaluator: IPC302Evaluator):
        """Facts exist but below the element's min_severity → PARTIAL."""
        m = FactMatrix()
        m.add_fact(
            FactCategory.ACTUS_REUS, "Someone may have died",
            FactSource.OTHER, severity=Severity.LOW, tags=["death_caused"],
        )
        m.add_fact(
            FactCategory.ACTUS_REUS, "Accused might have been involved",
            FactSource.OTHER, severity=Severity.LOW, tags=["act_by_accused"],
        )
        m.add_fact(
            FactCategory.MENS_REA, "Possibly intentional",
            FactSource.OTHER, severity=Severity.LOW, tags=["intention"],
        )
        result = evaluator.evaluate(m)
        # All three required elements have matches but below HIGH threshold
        assert result.verdict_recommendation == Recommendation.INSUFFICIENT.value
        assert len(result.elements_partial) >= 2  # death + act need HIGH


# ── keyword-only match (no tags) ──────────────────────────────────────────

class TestKeywordMatch:
    def test_keyword_match_without_tags(self, evaluator: IPC302Evaluator):
        m = FactMatrix()
        m.add_fact(
            FactCategory.ACTUS_REUS,
            "The deceased was found dead in the apartment",
            FactSource.FORENSIC, severity=Severity.CRITICAL,
            # no tags — relying on keyword "dead"/"deceased"
        )
        m.add_fact(
            FactCategory.ACTUS_REUS,
            "The accused stabbed the victim repeatedly",
            FactSource.WITNESS, severity=Severity.CRITICAL,
        )
        m.add_fact(
            FactCategory.MENS_REA,
            "Accused deliberately planned the attack",
            FactSource.DOCUMENT, severity=Severity.HIGH,
        )
        result = evaluator.evaluate(m)
        assert result.verdict_recommendation == Recommendation.PROCEED.value
