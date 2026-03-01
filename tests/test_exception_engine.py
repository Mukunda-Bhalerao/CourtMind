"""
Tests for ``core.exception_engine`` — ExceptionEngine & ExceptionResult.

10 test categories:

 1. Exception detected correctly
 2. Unsupported exception ignored
 3. Supported exception negates correct elements
 4. Multiple exceptions aggregate
 5. Conflict forces manual review
 6. fully_negated = True
 7. Partial negation
 8. No exception — clean output
 9. Schema / serialisation integrity
10. Does not alter evaluation_result

Run:  python -m pytest tests/test_exception_engine.py -v
"""

import json
import pytest

from core.fact_matrix import (
    Fact,
    FactCategory,
    FactMatrix,
    FactSource,
    Severity,
)
from core.ontology import LegalTag
from core.statute_engine import IPC302Evaluator, EvaluationResult
from core.exception_engine import ExceptionEngine, ExceptionResult, ExceptionDetail


# ── helpers ───────────────────────────────────────────────────────────────

def _base_matrix() -> FactMatrix:
    """Strong prosecution: death + act + intent satisfied."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim died from stabbing",
        FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused stabbed the victim",
        FactSource.WITNESS, severity=Severity.CRITICAL, tags=["act_by_accused"],
    )
    m.add_fact(
        FactCategory.MENS_REA, "Accused planned the attack",
        FactSource.DOCUMENT, severity=Severity.HIGH, tags=["intention"],
    )
    return m


def _eval_result(matrix: FactMatrix) -> EvaluationResult:
    return IPC302Evaluator().evaluate(matrix)


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture()
def engine() -> ExceptionEngine:
    return ExceptionEngine()


@pytest.fixture()
def base() -> FactMatrix:
    return _base_matrix()


@pytest.fixture()
def base_er(base) -> EvaluationResult:
    return _eval_result(base)


# ═════════════════════════════════════════════════════════════════════════
# 1. Exception detected correctly
# ═════════════════════════════════════════════════════════════════════════

class TestExceptionDetected:
    def test_self_defense_detected(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused acted in self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        assert len(r.exceptions_detected) == 1
        assert r.exceptions_detected[0]["tag"] == LegalTag.SELF_DEFENSE.value

    def test_insanity_detected(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused was insane at time of act",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.INSANITY.value],
        )
        r = engine.evaluate(base, base_er)
        assert len(r.exceptions_detected) == 1
        assert r.exceptions_detected[0]["tag"] == LegalTag.INSANITY.value

    def test_alibi_detected(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused was in another city",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.ALIBI.value],
        )
        r = engine.evaluate(base, base_er)
        assert len(r.exceptions_detected) == 1
        assert r.exceptions_detected[0]["tag"] == LegalTag.ALIBI.value

    def test_fact_without_exception_tag_not_detected(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Some unrelated claim",
            FactSource.OTHER,
            severity=Severity.HIGH,
            tags=["random_tag"],
        )
        r = engine.evaluate(base, base_er)
        assert len(r.exceptions_detected) == 0


# ═════════════════════════════════════════════════════════════════════════
# 2. Unsupported exception ignored
# ═════════════════════════════════════════════════════════════════════════

class TestUnsupportedExceptionIgnored:
    def test_low_severity_not_supported(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Vague self-defense claim",
            FactSource.USER_INPUT,
            severity=Severity.LOW,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        assert len(r.exceptions_detected) == 1
        assert r.exceptions_detected[0]["supported"] is False
        assert r.exceptions_supported == []

    def test_low_severity_does_not_negate(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Vague insanity claim",
            FactSource.USER_INPUT,
            severity=Severity.LOW,
            tags=[LegalTag.INSANITY.value],
        )
        r = engine.evaluate(base, base_er)
        assert r.negated_elements == []
        assert r.fully_negated is False


# ═════════════════════════════════════════════════════════════════════════
# 3. Supported exception negates correct elements
# ═════════════════════════════════════════════════════════════════════════

class TestSupportedNegation:
    def test_self_defense_negates_intent(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused acted in self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        assert "intention_or_knowledge" in r.negated_elements

    def test_alibi_negates_act(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused was elsewhere with proof",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.ALIBI.value],
        )
        r = engine.evaluate(base, base_er)
        assert "act_by_accused" in r.negated_elements

    def test_accident_negates_both(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Death was accidental",
            FactSource.FORENSIC,
            severity=Severity.HIGH,
            tags=[LegalTag.ACCIDENT.value],
        )
        r = engine.evaluate(base, base_er)
        assert "intention_or_knowledge" in r.negated_elements
        assert "act_by_accused" in r.negated_elements

    def test_provocation_negates_intent(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused was severely provoked",
            FactSource.WITNESS,
            severity=Severity.MEDIUM,
            tags=[LegalTag.PROVOCATION.value],
        )
        r = engine.evaluate(base, base_er)
        assert "intention_or_knowledge" in r.negated_elements

    def test_consent_negates_act(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Victim consented",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.CONSENT.value],
        )
        r = engine.evaluate(base, base_er)
        assert "act_by_accused" in r.negated_elements

    def test_supported_statement_in_list(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused acted in self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        assert "Accused acted in self-defense" in r.exceptions_supported


# ═════════════════════════════════════════════════════════════════════════
# 4. Multiple exceptions aggregate
# ═════════════════════════════════════════════════════════════════════════

class TestMultipleExceptions:
    def test_two_exceptions_merge_negation(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Self-defense claimed",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused was elsewhere",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.ALIBI.value],
        )
        r = engine.evaluate(base, base_er)
        assert "intention_or_knowledge" in r.negated_elements
        assert "act_by_accused" in r.negated_elements
        assert len(r.exceptions_detected) == 2

    def test_multiple_supported(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Duress claimed",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.DURESS.value],
        )
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Provocation claimed",
            FactSource.WITNESS,
            severity=Severity.MEDIUM,
            tags=[LegalTag.PROVOCATION.value],
        )
        r = engine.evaluate(base, base_er)
        assert len(r.exceptions_supported) == 2

    def test_one_supported_one_not(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Strong alibi",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.ALIBI.value],
        )
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Vague insanity",
            FactSource.USER_INPUT,
            severity=Severity.LOW,
            tags=[LegalTag.INSANITY.value],
        )
        r = engine.evaluate(base, base_er)
        assert len(r.exceptions_detected) == 2
        assert len(r.exceptions_supported) == 1
        assert "Strong alibi" in r.exceptions_supported

    def test_fact_with_two_exception_tags(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accident in self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.ACCIDENT.value, LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        assert len(r.exceptions_detected) == 2


# ═════════════════════════════════════════════════════════════════════════
# 5. Conflict forces manual review
# ═════════════════════════════════════════════════════════════════════════

class TestConflictForcesReview:
    def test_conflicted_exception_triggers_review(self, engine):
        m = _base_matrix()
        exc_fact = m.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused claims self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        # Add a conflicting fact.
        other_fact = m.add_fact(
            FactCategory.EVIDENCE,
            "Accused was the aggressor",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=["aggressor"],
        )
        m.register_conflict(exc_fact.id, other_fact.id, "Contradicts self-defense")
        er = _eval_result(m)
        r = engine.evaluate(m, er)
        assert r.requires_manual_review is True

    def test_conflicted_exception_not_supported(self, engine):
        m = _base_matrix()
        exc_fact = m.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused claims self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        other_fact = m.add_fact(
            FactCategory.EVIDENCE,
            "Accused was the aggressor",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=["aggressor"],
        )
        m.register_conflict(exc_fact.id, other_fact.id, "Contradicts self-defense")
        er = _eval_result(m)
        r = engine.evaluate(m, er)
        assert r.exceptions_supported == []

    def test_conflicted_does_not_negate(self, engine):
        m = _base_matrix()
        exc_fact = m.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Insanity claim",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.INSANITY.value],
        )
        other_fact = m.add_fact(
            FactCategory.EVIDENCE,
            "Psychiatric report says sane",
            FactSource.FORENSIC,
            severity=Severity.HIGH,
            tags=["sane"],
        )
        m.register_conflict(exc_fact.id, other_fact.id, "Contradicts insanity claim")
        er = _eval_result(m)
        r = engine.evaluate(m, er)
        assert r.negated_elements == []

    def test_no_conflict_no_review(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Accused in self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        assert r.requires_manual_review is False


# ═════════════════════════════════════════════════════════════════════════
# 6. fully_negated = True
# ═════════════════════════════════════════════════════════════════════════

class TestFullyNegated:
    def test_accident_negates_all_required(self, engine):
        """ACCIDENT negates intention_or_knowledge + act_by_accused.
        IPC 302 has 3 required elements: death_of_human, act_by_accused,
        intention_or_knowledge.  We need to negate all three."""
        m = _base_matrix()
        # Accident negates act_by_accused + intention_or_knowledge (2 of 3).
        m.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "It was an accident",
            FactSource.FORENSIC,
            severity=Severity.HIGH,
            tags=[LegalTag.ACCIDENT.value],
        )
        # Mistaken identity negates act_by_accused (already covered),
        # but we need death_of_human negated too — currently no exception
        # in the ontology negates death_of_human, so fully_negated stays
        # False for IPC 302 with one exception alone.
        er = _eval_result(m)
        r = engine.evaluate(m, er)
        # ACCIDENT only negates act_by_accused + intention_or_knowledge,
        # NOT death_of_human — so fully_negated must be False.
        assert r.fully_negated is False

    def test_fully_negated_when_all_required_negated(self, engine):
        """Synthetic test: create an evaluator result where the only
        required elements are those negated by ACCIDENT."""
        m = FactMatrix()
        m.add_fact(
            FactCategory.ACTUS_REUS, "Act happened",
            FactSource.WITNESS, severity=Severity.HIGH,
            tags=["act_by_accused"],
        )
        m.add_fact(
            FactCategory.MENS_REA, "Intention present",
            FactSource.DOCUMENT, severity=Severity.HIGH,
            tags=["intention"],
        )
        m.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "It was an accident",
            FactSource.FORENSIC,
            severity=Severity.HIGH,
            tags=[LegalTag.ACCIDENT.value],
        )
        # Build a synthetic EvaluationResult with only 2 required elements.
        from core.statute_engine import EvaluationResult, Recommendation, ElementStatus
        er = EvaluationResult(
            section="302 IPC",
            section_title="Murder",
            elements_required=2,
            elements_satisfied=2,
            elements_failed=0,
            elements_partial=0,
            elements_conflicted=0,
            element_details=[
                {
                    "element_id": "act_by_accused",
                    "status": ElementStatus.SATISFIED.value,
                    "required": True,
                    "matching_fact_ids": [],
                    "confidence_notes": [],
                },
                {
                    "element_id": "intention_or_knowledge",
                    "status": ElementStatus.SATISFIED.value,
                    "required": True,
                    "matching_fact_ids": [],
                    "confidence_notes": [],
                },
            ],
            verdict_recommendation=Recommendation.PROCEED.value,
            conflicts_found=0,
            exceptions_claimed=1,
        )
        r = engine.evaluate(m, er)
        assert r.fully_negated is True


# ═════════════════════════════════════════════════════════════════════════
# 7. Partial negation
# ═════════════════════════════════════════════════════════════════════════

class TestPartialNegation:
    def test_self_defense_partial(self, engine, base, base_er):
        """Self-defense negates intention_or_knowledge (and possibly
        cross-section elements) — not death_of_human or act_by_accused."""
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        assert "intention_or_knowledge" in r.negated_elements
        assert "death_of_human" not in r.negated_elements
        assert "act_by_accused" not in r.negated_elements
        assert r.fully_negated is False

    def test_alibi_partial(self, engine, base, base_er):
        """Alibi only negates act_by_accused."""
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Alibi proven",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.ALIBI.value],
        )
        r = engine.evaluate(base, base_er)
        assert r.negated_elements == ["act_by_accused"]
        assert r.fully_negated is False

    def test_duress_partial(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Duress claim",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.DURESS.value],
        )
        r = engine.evaluate(base, base_er)
        assert "intention_or_knowledge" in r.negated_elements
        assert "death_of_human" not in r.negated_elements
        assert r.fully_negated is False


# ═════════════════════════════════════════════════════════════════════════
# 8. No exception — clean output
# ═════════════════════════════════════════════════════════════════════════

class TestNoException:
    def test_empty_result(self, engine, base, base_er):
        r = engine.evaluate(base, base_er)
        assert r.exceptions_detected == []
        assert r.exceptions_supported == []
        assert r.negated_elements == []
        assert r.fully_negated is False
        assert r.requires_manual_review is False

    def test_empty_matrix(self, engine):
        m = FactMatrix()
        from core.statute_engine import EvaluationResult, Recommendation
        er = EvaluationResult(
            section="302 IPC",
            section_title="Murder",
            elements_required=3,
            elements_satisfied=0,
            elements_failed=3,
            elements_partial=0,
            elements_conflicted=0,
            element_details=[],
            verdict_recommendation=Recommendation.INSUFFICIENT.value,
            conflicts_found=0,
            exceptions_claimed=0,
        )
        r = engine.evaluate(m, er)
        assert r.exceptions_detected == []

    def test_non_exception_facts_ignored(self, engine, base, base_er):
        """Facts in other categories with exception-like tags are ignored."""
        base.add_fact(
            FactCategory.EVIDENCE,
            "Some evidence mentioning self-defense tangentially",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        assert r.exceptions_detected == []


# ═════════════════════════════════════════════════════════════════════════
# 9. Schema / serialisation integrity
# ═════════════════════════════════════════════════════════════════════════

class TestSerialisation:
    EXPECTED_KEYS = {
        "exceptions_detected",
        "exceptions_supported",
        "negated_elements",
        "fully_negated",
        "requires_manual_review",
    }

    def test_to_dict_keys(self, engine, base, base_er):
        r = engine.evaluate(base, base_er)
        assert set(r.to_dict().keys()) == self.EXPECTED_KEYS

    def test_to_dict_keys_with_exception(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Alibi",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.ALIBI.value],
        )
        r = engine.evaluate(base, base_er)
        assert set(r.to_dict().keys()) == self.EXPECTED_KEYS

    def test_to_json_parseable(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        parsed = json.loads(r.to_json())
        assert parsed["fully_negated"] is False
        assert isinstance(parsed["exceptions_detected"], list)

    def test_detected_detail_keys(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        r = engine.evaluate(base, base_er)
        det = r.exceptions_detected[0]
        assert "tag" in det
        assert "fact_id" in det
        assert "statement" in det
        assert "severity" in det
        assert "supported" in det
        assert "conflicted" in det
        assert "negates_elements" in det

    def test_exception_detail_dataclass(self):
        d = ExceptionDetail(
            tag="self-defense",
            fact_id="f1",
            statement="claim",
            severity="high",
            supported=True,
            conflicted=False,
            negates_elements=("intention_or_knowledge",),
        )
        dd = d.to_dict()
        assert dd["negates_elements"] == ["intention_or_knowledge"]

    def test_empty_result_serialises(self):
        r = ExceptionResult()
        d = r.to_dict()
        assert d["fully_negated"] is False
        assert d["exceptions_detected"] == []
        parsed = json.loads(r.to_json())
        assert parsed == d


# ═════════════════════════════════════════════════════════════════════════
# 10. Does not alter evaluation_result
# ═════════════════════════════════════════════════════════════════════════

class TestNoMutation:
    def test_evaluation_result_unchanged(self, engine, base, base_er):
        before = base_er.to_dict()
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Self-defense",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.SELF_DEFENSE.value],
        )
        engine.evaluate(base, base_er)
        after = base_er.to_dict()
        assert before == after

    def test_fact_matrix_unchanged(self, engine, base, base_er):
        before_facts = len(base.get_facts(FactCategory.EXCEPTIONS_CLAIMED.value))
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Alibi",
            FactSource.DOCUMENT,
            severity=Severity.HIGH,
            tags=[LegalTag.ALIBI.value],
        )
        after_add = len(base.get_facts(FactCategory.EXCEPTIONS_CLAIMED.value))
        engine.evaluate(base, base_er)
        after_eval = len(base.get_facts(FactCategory.EXCEPTIONS_CLAIMED.value))
        assert after_add == after_eval

    def test_multiple_runs_idempotent(self, engine, base, base_er):
        base.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Duress",
            FactSource.WITNESS,
            severity=Severity.HIGH,
            tags=[LegalTag.DURESS.value],
        )
        r1 = engine.evaluate(base, base_er)
        r2 = engine.evaluate(base, base_er)
        assert r1.to_dict() == r2.to_dict()
