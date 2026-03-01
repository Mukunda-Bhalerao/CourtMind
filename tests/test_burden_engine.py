"""
Unit tests for BurdenEngine

Test scenarios
--------------
 1. All required elements satisfied            → prima_facie_established
 2. One required element missing               → prosecution_incomplete
 3. One required element conflicted            → reasonable_doubt
 4. Exception claimed but unsupported          → defense_rebuttal_required
 5. Exception supported with evidence          → exception_established
 6. Exception negates element                  → acquittal_recommended
 7. Partial element lowers confidence score
 8. Multiple conflicts reduce confidence correctly
 9. Confidence bounded between 0.0 and 1.0
10. Output schema matches exact specification

Run:  python -m pytest tests/test_burden_engine.py -v
"""

import json
import pytest

from core.fact_matrix import (
    FactCategory,
    FactMatrix,
    FactSource,
    Severity,
)
from core.statute_engine import IPC302Evaluator
from core.burden_engine import BurdenEngine, BurdenResult, BurdenStage


# ── helpers ───────────────────────────────────────────────────────────────

_evaluator = IPC302Evaluator()
_engine = BurdenEngine()


def _run(matrix: FactMatrix) -> BurdenResult:
    """Evaluate fact matrix through the full pipeline → BurdenResult."""
    return _engine.evaluate(_evaluator.evaluate(matrix), matrix)


# ── shared fixtures ───────────────────────────────────────────────────────

@pytest.fixture()
def strong_matrix() -> FactMatrix:
    """All three required IPC-302 elements satisfied at HIGH+ severity."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim died from stab wounds",
        FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused stabbed the victim repeatedly",
        FactSource.WITNESS, severity=Severity.CRITICAL, tags=["act_by_accused"],
    )
    m.add_fact(
        FactCategory.MENS_REA, "Accused planned the attack deliberately",
        FactSource.DOCUMENT, severity=Severity.HIGH, tags=["premeditated", "intention"],
    )
    return m


# ═════════════════════════════════════════════════════════════════════════
# 1. All required elements satisfied → prima_facie_established
# ═════════════════════════════════════════════════════════════════════════

class TestScenario01_PrimaFacie:
    """When every required element is SATISFIED and no exceptions are
    claimed, the engine must return prima_facie_established."""

    def test_stage(self, strong_matrix):
        r = _run(strong_matrix)
        assert r.burden_stage == BurdenStage.PRIMA_FACIE_ESTABLISHED.value

    def test_flag(self, strong_matrix):
        r = _run(strong_matrix)
        assert "ALL_REQUIRED_ELEMENTS_MET" in r.reasoning_flags

    def test_all_required_counted(self, strong_matrix):
        r = _run(strong_matrix)
        assert r.required_elements_total == 3
        assert r.required_elements_satisfied == 3

    def test_no_conflicts(self, strong_matrix):
        r = _run(strong_matrix)
        assert r.conflicted_elements == 0

    def test_no_exceptions(self, strong_matrix):
        r = _run(strong_matrix)
        assert r.exceptions_claimed == []
        assert r.exceptions_supported == []

    def test_perfect_confidence(self, strong_matrix):
        r = _run(strong_matrix)
        assert r.confidence_score == 1.0


# ═════════════════════════════════════════════════════════════════════════
# 2. One required element missing → prosecution_incomplete
# ═════════════════════════════════════════════════════════════════════════

class TestScenario02_ProsecutionIncomplete:
    """When at least one required element has no supporting facts at all,
    the engine must return prosecution_incomplete."""

    @pytest.fixture()
    def matrix_no_intent(self) -> FactMatrix:
        """Death + act present, NO mens-rea facts at all."""
        m = FactMatrix()
        m.add_fact(
            FactCategory.ACTUS_REUS, "Victim was found dead",
            FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
        )
        m.add_fact(
            FactCategory.ACTUS_REUS, "Accused pushed the victim",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["act_by_accused"],
        )
        return m

    def test_stage(self, matrix_no_intent):
        r = _run(matrix_no_intent)
        assert r.burden_stage == BurdenStage.PROSECUTION_INCOMPLETE.value

    def test_flag(self, matrix_no_intent):
        r = _run(matrix_no_intent)
        assert "REQUIRED_ELEMENT_MISSING" in r.reasoning_flags

    def test_satisfied_less_than_total(self, matrix_no_intent):
        r = _run(matrix_no_intent)
        assert r.required_elements_total == 3
        assert r.required_elements_satisfied == 2

    def test_empty_matrix_also_incomplete(self):
        r = _run(FactMatrix())
        assert r.burden_stage == BurdenStage.PROSECUTION_INCOMPLETE.value


# ═════════════════════════════════════════════════════════════════════════
# 3. One required element conflicted → reasonable_doubt
# ═════════════════════════════════════════════════════════════════════════

class TestScenario03_ReasonableDoubt:
    """When a required element's supporting facts are contradicted by a
    registered conflict the engine must return reasonable_doubt."""

    @pytest.fixture()
    def conflicted_matrix(self) -> FactMatrix:
        m = FactMatrix()
        f1 = m.add_fact(
            FactCategory.ACTUS_REUS, "Accused killed the victim",
            FactSource.WITNESS, severity=Severity.HIGH,
            tags=["death_caused", "act_by_accused"],
        )
        f2 = m.add_fact(
            FactCategory.ACTUS_REUS, "Accused was in another city",
            FactSource.DOCUMENT, severity=Severity.HIGH, tags=["absent"],
        )
        m.register_conflict(f1.id, f2.id, "Location contradiction")
        m.add_fact(
            FactCategory.MENS_REA, "Accused had motive",
            FactSource.DOCUMENT, severity=Severity.HIGH, tags=["motive"],
        )
        return m

    def test_stage(self, conflicted_matrix):
        r = _run(conflicted_matrix)
        assert r.burden_stage == BurdenStage.REASONABLE_DOUBT.value

    def test_flag(self, conflicted_matrix):
        r = _run(conflicted_matrix)
        assert "REQUIRED_ELEMENT_CONFLICTED" in r.reasoning_flags

    def test_conflicted_count(self, conflicted_matrix):
        r = _run(conflicted_matrix)
        assert r.conflicted_elements >= 1


# ═════════════════════════════════════════════════════════════════════════
# 4. Exception claimed but unsupported → defense_rebuttal_required
# ═════════════════════════════════════════════════════════════════════════

class TestScenario04_DefenseRebuttal:
    """When all required elements are met BUT an exception is claimed at
    LOW severity (unsupported), the engine must return
    defense_rebuttal_required."""

    @pytest.fixture()
    def matrix_weak_exception(self) -> FactMatrix:
        m = FactMatrix()
        m.add_fact(
            FactCategory.ACTUS_REUS, "Victim died",
            FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
        )
        m.add_fact(
            FactCategory.ACTUS_REUS, "Accused struck victim",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["act_by_accused"],
        )
        m.add_fact(
            FactCategory.MENS_REA, "Accused acted intentionally",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["intentional"],
        )
        # LOW severity → unsupported
        m.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED, "Vague claim of self-defense",
            FactSource.USER_INPUT, severity=Severity.LOW, tags=["self-defense"],
        )
        return m

    def test_stage(self, matrix_weak_exception):
        r = _run(matrix_weak_exception)
        assert r.burden_stage == BurdenStage.DEFENSE_REBUTTAL_REQUIRED.value

    def test_flag(self, matrix_weak_exception):
        r = _run(matrix_weak_exception)
        assert "EXCEPTION_CLAIMED_UNRESOLVED" in r.reasoning_flags

    def test_claimed_not_supported(self, matrix_weak_exception):
        r = _run(matrix_weak_exception)
        assert len(r.exceptions_claimed) == 1
        assert len(r.exceptions_supported) == 0


# ═════════════════════════════════════════════════════════════════════════
# 5. Exception supported with evidence → exception_established
# ═════════════════════════════════════════════════════════════════════════

class TestScenario05_ExceptionEstablished:
    """When an exception fact is HIGH+ severity (supported) with a tag that
    does NOT appear in the negation map, the engine must return
    exception_established."""

    @pytest.fixture()
    def matrix_supported_no_negation(self) -> FactMatrix:
        m = FactMatrix()
        m.add_fact(
            FactCategory.ACTUS_REUS, "Victim died from injuries",
            FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
        )
        m.add_fact(
            FactCategory.ACTUS_REUS, "Accused hit victim",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["act_by_accused"],
        )
        m.add_fact(
            FactCategory.MENS_REA, "Accused intended the attack",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["intention"],
        )
        # Tag NOT in _EXCEPTION_NEGATION_MAP → no element negated
        m.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Defense claims diminished responsibility",
            FactSource.CASE_FILE, severity=Severity.HIGH,
            tags=["diminished_responsibility"],
        )
        return m

    def test_stage(self, matrix_supported_no_negation):
        r = _run(matrix_supported_no_negation)
        assert r.burden_stage == BurdenStage.EXCEPTION_ESTABLISHED.value

    def test_flag(self, matrix_supported_no_negation):
        r = _run(matrix_supported_no_negation)
        assert "EXCEPTION_ESTABLISHED_NO_NEGATION" in r.reasoning_flags

    def test_supported_list(self, matrix_supported_no_negation):
        r = _run(matrix_supported_no_negation)
        assert len(r.exceptions_supported) == 1


# ═════════════════════════════════════════════════════════════════════════
# 6. Exception negates element → acquittal_recommended
# ═════════════════════════════════════════════════════════════════════════

class TestScenario06_AcquittalRecommended:
    """When a supported exception carries a negation-map tag that targets a
    satisfied required element, the engine must return
    acquittal_recommended."""

    @pytest.fixture()
    def matrix_self_defense(self) -> FactMatrix:
        m = FactMatrix()
        m.add_fact(
            FactCategory.ACTUS_REUS, "Victim died from injuries",
            FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
        )
        m.add_fact(
            FactCategory.ACTUS_REUS, "Accused struck victim",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["act_by_accused"],
        )
        m.add_fact(
            FactCategory.MENS_REA, "Accused acted with intention",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["intention"],
        )
        # "self-defense" → negates intention_or_knowledge
        m.add_fact(
            FactCategory.EXCEPTIONS_CLAIMED,
            "Three witnesses confirm victim attacked first",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["self-defense"],
        )
        return m

    def test_stage(self, matrix_self_defense):
        r = _run(matrix_self_defense)
        assert r.burden_stage == BurdenStage.ACQUITTAL_RECOMMENDED.value

    def test_flags(self, matrix_self_defense):
        r = _run(matrix_self_defense)
        assert "EXCEPTION_NEGATES_REQUIRED_ELEMENT" in r.reasoning_flags
        assert "ACQUITTAL_RECOMMENDED" in r.reasoning_flags

    def test_supported_list(self, matrix_self_defense):
        r = _run(matrix_self_defense)
        assert len(r.exceptions_supported) == 1


# ═════════════════════════════════════════════════════════════════════════
# 7. Partial element lowers confidence score
# ═════════════════════════════════════════════════════════════════════════

class TestScenario07_PartialConfidence:
    """When a required element is PARTIAL (facts exist but below the
    severity threshold), the confidence score must drop by 0.15 per
    partial element."""

    @pytest.fixture()
    def matrix_partial_intent(self) -> FactMatrix:
        """Death + act at CRITICAL; intent at LOW → PARTIAL."""
        m = FactMatrix()
        m.add_fact(
            FactCategory.ACTUS_REUS, "Victim died",
            FactSource.FORENSIC, severity=Severity.CRITICAL, tags=["death_caused"],
        )
        m.add_fact(
            FactCategory.ACTUS_REUS, "Accused hit victim",
            FactSource.WITNESS, severity=Severity.CRITICAL, tags=["act_by_accused"],
        )
        # LOW severity for intent → below IPC302's min_severity=MEDIUM
        m.add_fact(
            FactCategory.MENS_REA, "Possibly intentional",
            FactSource.OTHER, severity=Severity.LOW, tags=["intention"],
        )
        return m

    def test_stage_is_incomplete(self, matrix_partial_intent):
        """Partial element counts as not fully satisfied → incomplete."""
        r = _run(matrix_partial_intent)
        assert r.burden_stage == BurdenStage.PROSECUTION_INCOMPLETE.value

    def test_confidence_reduced_by_partial(self, matrix_partial_intent):
        """1.0 − 0.15 (one partial) = 0.85, then may also get
        −0.10 for LOW_SEVERITY_INTENT → 0.75."""
        r = _run(matrix_partial_intent)
        assert r.confidence_score < 1.0
        assert r.confidence_score <= 0.85

    def test_flag_present(self, matrix_partial_intent):
        r = _run(matrix_partial_intent)
        has_partial_or_low = (
            "REQUIRED_ELEMENT_PARTIAL" in r.reasoning_flags
            or "LOW_SEVERITY_INTENT" in r.reasoning_flags
        )
        assert has_partial_or_low


# ═════════════════════════════════════════════════════════════════════════
# 8. Multiple conflicts reduce confidence correctly
# ═════════════════════════════════════════════════════════════════════════

class TestScenario08_MultipleConflicts:
    """Each conflicted required element deducts 0.25 from confidence.
    Two conflicts → 1.0 − 0.50 = 0.50."""

    @pytest.fixture()
    def matrix_two_conflicts(self) -> FactMatrix:
        m = FactMatrix()
        # Death — conflicted
        f1 = m.add_fact(
            FactCategory.ACTUS_REUS, "Victim died",
            FactSource.FORENSIC, severity=Severity.HIGH, tags=["death_caused"],
        )
        f2 = m.add_fact(
            FactCategory.ACTUS_REUS, "Victim is alive",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["alive"],
        )
        m.register_conflict(f1.id, f2.id, "alive vs dead")
        # Act — conflicted
        f3 = m.add_fact(
            FactCategory.ACTUS_REUS, "Accused attacked",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["act_by_accused"],
        )
        f4 = m.add_fact(
            FactCategory.ACTUS_REUS, "Accused was absent",
            FactSource.DOCUMENT, severity=Severity.HIGH, tags=["absent"],
        )
        m.register_conflict(f3.id, f4.id, "present vs absent")
        # Intent — satisfied, no conflict
        m.add_fact(
            FactCategory.MENS_REA, "Accused intended",
            FactSource.WITNESS, severity=Severity.HIGH, tags=["intention"],
        )
        return m

    def test_stage(self, matrix_two_conflicts):
        r = _run(matrix_two_conflicts)
        assert r.burden_stage == BurdenStage.REASONABLE_DOUBT.value

    def test_conflicted_count(self, matrix_two_conflicts):
        r = _run(matrix_two_conflicts)
        assert r.conflicted_elements == 2

    def test_confidence_exact(self, matrix_two_conflicts):
        """1.0 − 2×0.25 = 0.50"""
        r = _run(matrix_two_conflicts)
        assert r.confidence_score == 0.50

    def test_three_conflicts_drops_to_quarter(self):
        """Three conflicts → 1.0 − 3×0.25 = 0.25."""
        m = FactMatrix()
        f1 = m.add_fact(FactCategory.ACTUS_REUS, "Victim died",
                        FactSource.FORENSIC, severity=Severity.HIGH,
                        tags=["death_caused"])
        f2 = m.add_fact(FactCategory.ACTUS_REUS, "Victim alive",
                        FactSource.WITNESS, severity=Severity.HIGH,
                        tags=["alive"])
        m.register_conflict(f1.id, f2.id, "death conflict")

        f3 = m.add_fact(FactCategory.ACTUS_REUS, "Accused attacked",
                        FactSource.WITNESS, severity=Severity.HIGH,
                        tags=["act_by_accused"])
        f4 = m.add_fact(FactCategory.ACTUS_REUS, "Accused elsewhere",
                        FactSource.DOCUMENT, severity=Severity.HIGH,
                        tags=["absent"])
        m.register_conflict(f3.id, f4.id, "act conflict")

        f5 = m.add_fact(FactCategory.MENS_REA, "Accused intended",
                        FactSource.WITNESS, severity=Severity.HIGH,
                        tags=["intention"])
        f6 = m.add_fact(FactCategory.MENS_REA, "No motive at all",
                        FactSource.DOCUMENT, severity=Severity.HIGH,
                        tags=["no_motive"])
        m.register_conflict(f5.id, f6.id, "intent conflict")

        r = _run(m)
        assert r.confidence_score == 0.25


# ═════════════════════════════════════════════════════════════════════════
# 9. Confidence bounded between 0.0 and 1.0
# ═════════════════════════════════════════════════════════════════════════

class TestScenario09_ConfidenceBounds:
    """No matter how extreme the inputs, confidence must be in [0.0, 1.0]."""

    def test_upper_bound(self, strong_matrix):
        r = _run(strong_matrix)
        assert r.confidence_score <= 1.0

    def test_lower_bound_extreme_conflicts(self):
        """Even with max penalties the score never goes below 0.0."""
        m = FactMatrix()
        f1 = m.add_fact(FactCategory.ACTUS_REUS, "Victim died",
                        FactSource.FORENSIC, severity=Severity.HIGH,
                        tags=["death_caused"])
        f2 = m.add_fact(FactCategory.ACTUS_REUS, "Victim alive",
                        FactSource.WITNESS, severity=Severity.HIGH,
                        tags=["alive"])
        m.register_conflict(f1.id, f2.id, "c1")

        f3 = m.add_fact(FactCategory.ACTUS_REUS, "Accused attacked",
                        FactSource.WITNESS, severity=Severity.HIGH,
                        tags=["act_by_accused"])
        f4 = m.add_fact(FactCategory.ACTUS_REUS, "Accused absent",
                        FactSource.DOCUMENT, severity=Severity.HIGH,
                        tags=["absent"])
        m.register_conflict(f3.id, f4.id, "c2")

        f5 = m.add_fact(FactCategory.MENS_REA, "Accused intended",
                        FactSource.WITNESS, severity=Severity.HIGH,
                        tags=["intention"])
        f6 = m.add_fact(FactCategory.MENS_REA, "No motive",
                        FactSource.DOCUMENT, severity=Severity.HIGH,
                        tags=["no_motive"])
        m.register_conflict(f5.id, f6.id, "c3")

        # Also add an exception for extra penalty
        m.add_fact(FactCategory.EXCEPTIONS_CLAIMED, "Self-defense",
                   FactSource.USER_INPUT, severity=Severity.LOW,
                   tags=["self-defense"])

        r = _run(m)
        assert 0.0 <= r.confidence_score <= 1.0

    def test_score_is_float(self, strong_matrix):
        r = _run(strong_matrix)
        assert isinstance(r.confidence_score, float)


# ═════════════════════════════════════════════════════════════════════════
# 10. Output schema matches exact specification
# ═════════════════════════════════════════════════════════════════════════

class TestScenario10_OutputSchema:
    """BurdenResult must expose exactly the specified fields and
    serialise correctly to dict / JSON."""

    EXPECTED_KEYS = {
        "burden_stage",
        "confidence_score",
        "required_elements_satisfied",
        "required_elements_total",
        "conflicted_elements",
        "exceptions_claimed",
        "exceptions_supported",
        "reasoning_flags",
    }

    def test_to_dict_keys(self, strong_matrix):
        d = _run(strong_matrix).to_dict()
        assert set(d.keys()) == self.EXPECTED_KEYS

    def test_to_dict_no_extra_keys(self, strong_matrix):
        d = _run(strong_matrix).to_dict()
        assert not set(d.keys()) - self.EXPECTED_KEYS

    def test_to_json_roundtrip(self, strong_matrix):
        r = _run(strong_matrix)
        parsed = json.loads(r.to_json())
        assert parsed["burden_stage"] == BurdenStage.PRIMA_FACIE_ESTABLISHED.value
        assert parsed["confidence_score"] == 1.0
        assert parsed["required_elements_satisfied"] == 3
        assert parsed["required_elements_total"] == 3

    def test_reasoning_flags_type(self, strong_matrix):
        r = _run(strong_matrix)
        assert isinstance(r.reasoning_flags, list)
        assert all(isinstance(f, str) for f in r.reasoning_flags)

    def test_exceptions_are_lists(self, strong_matrix):
        r = _run(strong_matrix)
        assert isinstance(r.exceptions_claimed, list)
        assert isinstance(r.exceptions_supported, list)

    def test_burden_stage_is_valid_enum(self, strong_matrix):
        r = _run(strong_matrix)
        valid_stages = {s.value for s in BurdenStage}
        assert r.burden_stage in valid_stages
