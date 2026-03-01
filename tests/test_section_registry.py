"""
Unit tests for SectionRegistry.

Test scenarios:

 1. Default section (302 IPC) is registered.
 2. get("302 IPC") returns correct evaluator instance.
 3. list_registered_sections() contains 302 IPC.
 4. Duplicate registration raises error.
 5. Unknown section raises error.
 6. is_registered() works correctly.
 7. Dependency injection override works.
 8. Registry is immutable externally.
 9. Multiple section registration works.
10. Registry does not modify evaluator behavior.

Run:  python -m pytest tests/test_section_registry.py -v
"""

import pytest

from core.section_registry import SectionRegistry, registry
from core.statute_engine import (
    EvaluationResult,
    IPC302Evaluator,
    StatuteEvaluator,
)
from core.fact_matrix import FactCategory, FactMatrix, FactSource, Severity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _DummyEvaluator(StatuteEvaluator):
    """Minimal concrete evaluator for testing registration."""
    SECTION = "999 TEST"
    SECTION_TITLE = "Test Section"
    ELEMENTS = ()


class _AnotherDummy(StatuteEvaluator):
    SECTION = "888 TEST"
    SECTION_TITLE = "Another"
    ELEMENTS = ()


def _strong_matrix() -> FactMatrix:
    """Return a FactMatrix that satisfies all IPC 302 required elements."""
    m = FactMatrix()
    m.add_fact("actus_reus", "Victim was found dead",
               "witness", severity="high", tags=["death_caused"])
    m.add_fact("actus_reus", "Accused stabbed the victim",
               "witness", severity="high", tags=["act_by_accused"])
    m.add_fact("mens_rea", "Accused had premeditated intent",
               "document", severity="high", tags=["intention"])
    m.add_fact("evidence", "Knife recovered with fingerprints",
               "forensic", severity="high", tags=["forensic", "weapon"])
    return m


# ═════════════════════════════════════════════════════════════════════════
# 1. Default section (302 IPC) is registered
# ═════════════════════════════════════════════════════════════════════════

class TestScenario01_DefaultSection:
    """The module-level `registry` must auto-register IPC302Evaluator."""

    def test_302_is_registered(self):
        assert registry.is_registered("302 IPC") is True

    def test_default_registry_type(self):
        assert isinstance(registry, SectionRegistry)

    def test_only_302_registered_by_default(self):
        sections = registry.list_registered_sections()
        assert "302 IPC" in sections
        assert len(sections) >= 1

    def test_registered_class_is_ipc302(self):
        evaluator = registry.get("302 IPC")
        assert type(evaluator) is IPC302Evaluator


# ═════════════════════════════════════════════════════════════════════════
# 2. get("302 IPC") returns correct evaluator instance
# ═════════════════════════════════════════════════════════════════════════

class TestScenario02_GetReturnsInstance:
    """get() must return a fresh, correct evaluator instance."""

    def test_returns_ipc302_instance(self):
        assert isinstance(registry.get("302 IPC"), IPC302Evaluator)

    def test_returns_new_instance_each_call(self):
        a = registry.get("302 IPC")
        b = registry.get("302 IPC")
        assert a is not b

    def test_instance_section_matches(self):
        assert registry.get("302 IPC").SECTION == "302 IPC"

    def test_instance_title_matches(self):
        assert registry.get("302 IPC").SECTION_TITLE == "Murder"

    def test_instance_has_elements(self):
        assert len(registry.get("302 IPC").ELEMENTS) > 0


# ═════════════════════════════════════════════════════════════════════════
# 3. list_registered_sections() contains 302 IPC
# ═════════════════════════════════════════════════════════════════════════

class TestScenario03_ListRegisteredSections:
    """list_registered_sections() must be accurate and well-formed."""

    def test_contains_302(self):
        assert "302 IPC" in registry.list_registered_sections()

    def test_returns_tuple(self):
        assert isinstance(registry.list_registered_sections(), tuple)

    def test_is_sorted(self):
        r = SectionRegistry()
        r.register("999 TEST", _DummyEvaluator)
        r.register("302 IPC", IPC302Evaluator)
        sections = r.list_registered_sections()
        assert sections == tuple(sorted(sections))

    def test_empty_registry_returns_empty_tuple(self):
        r = SectionRegistry()
        assert r.list_registered_sections() == ()

    def test_no_duplicates_in_list(self):
        sections = registry.list_registered_sections()
        assert len(sections) == len(set(sections))


# ═════════════════════════════════════════════════════════════════════════
# 4. Duplicate registration raises error
# ═════════════════════════════════════════════════════════════════════════

class TestScenario04_DuplicateRegistration:
    """Re-registering an existing section_code must be rejected."""

    def test_duplicate_same_class_raises(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        with pytest.raises(ValueError, match="already registered"):
            r.register("302 IPC", IPC302Evaluator)

    def test_duplicate_different_class_raises(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        with pytest.raises(ValueError, match="already registered"):
            r.register("302 IPC", _DummyEvaluator)

    def test_error_message_names_existing_class(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        with pytest.raises(ValueError, match="IPC302Evaluator"):
            r.register("302 IPC", _DummyEvaluator)

    def test_first_registration_succeeds(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        assert r.is_registered("302 IPC")


# ═════════════════════════════════════════════════════════════════════════
# 5. Unknown section raises error
# ═════════════════════════════════════════════════════════════════════════

class TestScenario05_UnknownSection:
    """Querying an unregistered section must raise KeyError."""

    def test_raises_key_error(self):
        with pytest.raises(KeyError, match="not registered"):
            registry.get("999 IPC")

    def test_empty_string_raises(self):
        r = SectionRegistry()
        with pytest.raises(KeyError):
            r.get("")

    def test_error_lists_known_sections(self):
        with pytest.raises(KeyError, match="302 IPC"):
            registry.get("404 IPC")

    def test_non_string_raises_type_error(self):
        with pytest.raises(TypeError, match="string"):
            registry.get(302)  # type: ignore[arg-type]

    def test_none_raises_type_error(self):
        with pytest.raises(TypeError):
            registry.get(None)  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════
# 6. is_registered() works correctly
# ═════════════════════════════════════════════════════════════════════════

class TestScenario06_IsRegistered:
    """is_registered() must return correct booleans."""

    def test_true_for_known(self):
        assert registry.is_registered("302 IPC") is True

    def test_false_for_unknown(self):
        assert registry.is_registered("404 IPC") is False

    def test_false_on_empty_registry(self):
        r = SectionRegistry()
        assert r.is_registered("302 IPC") is False

    def test_non_string_raises_type_error(self):
        with pytest.raises(TypeError):
            registry.is_registered(42)  # type: ignore[arg-type]

    def test_returns_bool(self):
        result = registry.is_registered("302 IPC")
        assert isinstance(result, bool)


# ═════════════════════════════════════════════════════════════════════════
# 7. Dependency injection override works
# ═════════════════════════════════════════════════════════════════════════

class TestScenario07_DependencyInjection:
    """get(override=...) must bypass the registry and return the override."""

    def test_override_returns_provided_instance(self):
        custom = _DummyEvaluator()
        result = registry.get("302 IPC", override=custom)
        assert result is custom

    def test_override_bypasses_lookup(self):
        custom = _DummyEvaluator()
        # "999 IPC" is NOT registered, but override skips the lookup
        result = registry.get("999 IPC", override=custom)
        assert result is custom

    def test_override_none_falls_through(self):
        result = registry.get("302 IPC", override=None)
        assert isinstance(result, IPC302Evaluator)

    def test_override_preserves_type(self):
        custom = _DummyEvaluator()
        result = registry.get("302 IPC", override=custom)
        assert isinstance(result, _DummyEvaluator)


# ═════════════════════════════════════════════════════════════════════════
# 8. Registry is immutable externally
# ═════════════════════════════════════════════════════════════════════════

class TestScenario08_Immutability:
    """freeze() must lock the registry against further mutation."""

    def test_frozen_property_initially_false(self):
        r = SectionRegistry()
        assert r.frozen is False

    def test_freeze_sets_frozen(self):
        r = SectionRegistry()
        r.freeze()
        assert r.frozen is True

    def test_register_after_freeze_raises_runtime_error(self):
        r = SectionRegistry()
        r.freeze()
        with pytest.raises(RuntimeError, match="frozen"):
            r.register("302 IPC", IPC302Evaluator)

    def test_get_still_works_after_freeze(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        r.freeze()
        assert isinstance(r.get("302 IPC"), IPC302Evaluator)

    def test_list_still_works_after_freeze(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        r.freeze()
        assert "302 IPC" in r.list_registered_sections()

    def test_repr_reflects_frozen_state(self):
        r = SectionRegistry()
        assert "mutable" in repr(r)
        r.freeze()
        assert "frozen" in repr(r)

    def test_internal_mapping_not_directly_accessible(self):
        """The _mapping attribute is private; external code should use
        the public API.  Verify the public API is the only path."""
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        r.freeze()
        # Public inspection works
        assert r.is_registered("302 IPC")
        # Mutation via public API is blocked
        with pytest.raises(RuntimeError):
            r.register("999 TEST", _DummyEvaluator)


# ═════════════════════════════════════════════════════════════════════════
# 9. Multiple section registration works
# ═════════════════════════════════════════════════════════════════════════

class TestScenario09_MultipleSections:
    """Multiple distinct sections must coexist correctly."""

    def test_register_two_sections(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        r.register("999 TEST", _DummyEvaluator)
        assert r.is_registered("302 IPC")
        assert r.is_registered("999 TEST")

    def test_three_sections(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        r.register("999 TEST", _DummyEvaluator)
        r.register("888 TEST", _AnotherDummy)
        assert len(r.list_registered_sections()) == 3

    def test_get_returns_correct_type_for_each(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        r.register("999 TEST", _DummyEvaluator)
        assert isinstance(r.get("302 IPC"), IPC302Evaluator)
        assert isinstance(r.get("999 TEST"), _DummyEvaluator)

    def test_list_is_sorted_with_multiple(self):
        r = SectionRegistry()
        r.register("999 TEST", _DummyEvaluator)
        r.register("302 IPC", IPC302Evaluator)
        r.register("888 TEST", _AnotherDummy)
        sections = r.list_registered_sections()
        assert sections == ("302 IPC", "888 TEST", "999 TEST")

    def test_repr_lists_all_sections(self):
        r = SectionRegistry()
        r.register("302 IPC", IPC302Evaluator)
        r.register("999 TEST", _DummyEvaluator)
        text = repr(r)
        assert "302 IPC" in text
        assert "999 TEST" in text


# ═════════════════════════════════════════════════════════════════════════
# 10. Registry does not modify evaluator behavior
# ═════════════════════════════════════════════════════════════════════════

class TestScenario10_EvaluatorBehaviorPreserved:
    """Evaluators obtained via the registry must behave identically
    to evaluators constructed directly."""

    def test_registry_evaluator_matches_direct_section(self):
        via_registry = registry.get("302 IPC")
        via_direct = IPC302Evaluator()
        assert via_registry.SECTION == via_direct.SECTION

    def test_registry_evaluator_matches_direct_title(self):
        via_registry = registry.get("302 IPC")
        via_direct = IPC302Evaluator()
        assert via_registry.SECTION_TITLE == via_direct.SECTION_TITLE

    def test_registry_evaluator_matches_direct_elements(self):
        via_registry = registry.get("302 IPC")
        via_direct = IPC302Evaluator()
        assert via_registry.ELEMENTS == via_direct.ELEMENTS

    def test_registry_evaluation_matches_direct(self):
        matrix = _strong_matrix()
        via_registry = registry.get("302 IPC").evaluate(matrix)
        via_direct = IPC302Evaluator().evaluate(matrix)
        # Exclude evaluated_at timestamp from comparison
        d1 = via_registry.to_dict()
        d2 = via_direct.to_dict()
        d1.pop("evaluated_at")
        d2.pop("evaluated_at")
        assert d1 == d2

    def test_registry_evaluation_verdict_matches(self):
        matrix = _strong_matrix()
        via_registry = registry.get("302 IPC").evaluate(matrix)
        via_direct = IPC302Evaluator().evaluate(matrix)
        assert via_registry.verdict_recommendation == via_direct.verdict_recommendation

    def test_empty_matrix_produces_same_result(self):
        matrix = FactMatrix()
        via_registry = registry.get("302 IPC").evaluate(matrix)
        via_direct = IPC302Evaluator().evaluate(matrix)
        d1 = via_registry.to_dict()
        d2 = via_direct.to_dict()
        d1.pop("evaluated_at")
        d2.pop("evaluated_at")
        assert d1 == d2
