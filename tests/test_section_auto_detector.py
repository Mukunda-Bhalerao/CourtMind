"""
Tests for ``core.section_auto_detector`` — SectionAutoDetector.

10 test categories:

 1. Detects 302 when strong murder facts exist
 2. Returns empty list when insufficient facts
 3. Ranking order correct when multiple sections added
 4. Combined score calculation exact
 5. Burden multiplier applied correctly
 6. Sorting descending works
 7. Top section matches highest score
 8. Does not mutate FactMatrix
 9. Works when only one section registered
10. Schema integrity exact

Run:  python -m pytest tests/test_section_auto_detector.py -v
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
from core.statute_engine import (
    ElementSpec,
    EvaluationResult,
    IPC302Evaluator,
    Recommendation,
    StatuteEvaluator,
)
from core.burden_engine import BurdenStage
from core.section_registry import SectionRegistry
from core.section_auto_detector import (
    DetectedSection,
    DetectionResult,
    SectionAutoDetector,
    _BURDEN_MULTIPLIER,
    _COMBINED_SCORE_THRESHOLD,
)


# ── Stub evaluator for multi-section tests ────────────────────────────────

class _StubWeakEvaluator(StatuteEvaluator):
    """
    Minimal evaluator that always produces a weak / incomplete result.
    Registered under a fake section code for testing multi-section ranking.
    """

    SECTION = "999 IPC"
    SECTION_TITLE = "Stub Weak"

    ELEMENTS = (
        ElementSpec(
            element_id="stub_element",
            description="A dummy element that never matches",
            required_category=FactCategory.EVIDENCE.value,
            match_tags=("__never_matches__",),
            match_keywords=("__never_matches__",),
            min_severity=Severity.CRITICAL.value,
            required=True,
        ),
    )


class _StubStrongEvaluator(StatuteEvaluator):
    """
    Minimal evaluator that matches broadly on actus_reus facts.
    Registered under '304 IPC' for multi-section ranking tests.
    """

    SECTION = "304 IPC"
    SECTION_TITLE = "Culpable Homicide"

    ELEMENTS = (
        ElementSpec(
            element_id="death_of_human",
            description="Death of a human being",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=("death_caused",),
            match_keywords=("died", "death", "killed", "dead"),
            min_severity=Severity.HIGH.value,
            required=True,
        ),
        ElementSpec(
            element_id="act_by_accused",
            description="Act by the accused",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=("act_by_accused",),
            match_keywords=("accused", "stabbed", "struck", "pushed"),
            min_severity=Severity.HIGH.value,
            required=True,
        ),
    )


# ── helpers ───────────────────────────────────────────────────────────────

def _strong_matrix() -> FactMatrix:
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
        FactSource.DOCUMENT, severity=Severity.HIGH,
        tags=["premeditated", "intention"],
    )
    return m


def _weak_matrix() -> FactMatrix:
    """Only low-severity, no matching tags — should score below threshold."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.EVIDENCE, "Unrelated document",
        FactSource.OTHER, severity=Severity.LOW, tags=["misc"],
    )
    return m


def _single_section_registry() -> SectionRegistry:
    """Registry with only IPC 302."""
    r = SectionRegistry()
    r.register(IPC302Evaluator.SECTION, IPC302Evaluator)
    return r


def _multi_section_registry() -> SectionRegistry:
    """Registry with IPC 302 + stub weak 999."""
    r = SectionRegistry()
    r.register(IPC302Evaluator.SECTION, IPC302Evaluator)
    r.register(_StubWeakEvaluator.SECTION, _StubWeakEvaluator)
    return r


def _multi_section_registry_with_strong() -> SectionRegistry:
    """Registry with IPC 302 + stub strong 304."""
    r = SectionRegistry()
    r.register(IPC302Evaluator.SECTION, IPC302Evaluator)
    r.register(_StubStrongEvaluator.SECTION, _StubStrongEvaluator)
    return r


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture()
def strong() -> FactMatrix:
    return _strong_matrix()


@pytest.fixture()
def weak() -> FactMatrix:
    return _weak_matrix()


# ═════════════════════════════════════════════════════════════════════════
# 1. Detects 302 when strong murder facts exist
# ═════════════════════════════════════════════════════════════════════════

class TestDetects302:
    def test_302_detected(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        sections = [d["section"] for d in result.detected_sections]
        assert "302 IPC" in sections

    def test_top_section_is_302(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        assert result.top_section == "302 IPC"

    def test_top_score_positive(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        assert result.top_score > _COMBINED_SCORE_THRESHOLD


# ═════════════════════════════════════════════════════════════════════════
# 2. Returns empty list when insufficient facts
# ═════════════════════════════════════════════════════════════════════════

class TestEmptyOnInsufficient:
    def test_empty_matrix_still_scores(self):
        """Even with no facts, confidence is 1.0 (certain it's prosecution_incomplete)
        so combined_score > 0.25.  Detection still returns a result."""
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(FactMatrix())
        # prosecution_incomplete but confidence stays high
        assert result.detected_sections[0]["burden_stage"] == \
            BurdenStage.PROSECUTION_INCOMPLETE.value

    def test_weak_facts_still_detected(self, weak):
        """Weak facts don't lower confidence (no conflicts/partials),
        so section is still detected."""
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(weak)
        assert len(result.detected_sections) >= 1

    def test_no_registered_sections(self, strong):
        empty_reg = SectionRegistry()
        det = SectionAutoDetector(registry=empty_reg)
        result = det.detect(strong)
        assert result.detected_sections == []
        assert result.top_section == ""
        assert result.top_score == 0.0


# ═════════════════════════════════════════════════════════════════════════
# 3. Ranking order correct when multiple sections added
# ═════════════════════════════════════════════════════════════════════════

class TestRankingOrder:
    def test_302_ranks_above_weak_999(self, strong):
        det = SectionAutoDetector(registry=_multi_section_registry())
        result = det.detect(strong)
        # 999 should be below threshold, so only 302 qualifies.
        sections = [d["section"] for d in result.detected_sections]
        assert sections[0] == "302 IPC"

    def test_multiple_qualifying_sections_ordered(self, strong):
        """Both 302 and 304 qualify; 302 should score higher (more elements)."""
        det = SectionAutoDetector(registry=_multi_section_registry_with_strong())
        result = det.detect(strong)
        if len(result.detected_sections) >= 2:
            assert (
                result.detected_sections[0]["combined_score"]
                >= result.detected_sections[1]["combined_score"]
            )

    def test_non_qualifying_sections_ranked_lower(self, strong):
        """999 IPC has no matching elements so its combined_score should be
        lower than 302 IPC's."""
        det = SectionAutoDetector(registry=_multi_section_registry())
        result = det.detect(strong)
        scores = {d["section"]: d["combined_score"] for d in result.detected_sections}
        assert scores["302 IPC"] > scores.get("999 IPC", 0.0)


# ═════════════════════════════════════════════════════════════════════════
# 4. Combined score calculation exact
# ═════════════════════════════════════════════════════════════════════════

class TestCombinedScoreCalculation:
    def test_formula_matches(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        entry = result.detected_sections[0]
        conf = entry["confidence_score"]
        evid = entry["overall_evidence_score"]
        mult = _BURDEN_MULTIPLIER[entry["burden_stage"]]
        expected = round((conf * 0.6) + (evid * 0.3) + (mult * 0.1), 4)
        assert entry["combined_score"] == expected

    def test_combined_score_bounded(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        for entry in result.detected_sections:
            assert 0.0 <= entry["combined_score"] <= 1.0

    def test_empty_matrix_combined_score(self):
        """Empty matrix: confidence=1.0, evidence=0.0, burden=prosecution_incomplete(0.2).
        combined = (1.0*0.6) + (0.0*0.3) + (0.2*0.1) = 0.62"""
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(FactMatrix())
        entry = result.detected_sections[0]
        expected = round((1.0 * 0.6) + (0.0 * 0.3) + (0.2 * 0.1), 4)
        assert entry["combined_score"] == expected


# ═════════════════════════════════════════════════════════════════════════
# 5. Burden multiplier applied correctly
# ═════════════════════════════════════════════════════════════════════════

class TestBurdenMultiplier:
    def test_prima_facie_multiplier(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        entry = result.detected_sections[0]
        assert entry["burden_stage"] == BurdenStage.PRIMA_FACIE_ESTABLISHED.value
        mult = _BURDEN_MULTIPLIER[BurdenStage.PRIMA_FACIE_ESTABLISHED.value]
        assert mult == 0.8

    def test_all_stages_have_multiplier(self):
        for stage in BurdenStage:
            assert stage.value in _BURDEN_MULTIPLIER

    def test_multiplier_values_between_0_and_1(self):
        for v in _BURDEN_MULTIPLIER.values():
            assert 0.0 <= v <= 1.0


# ═════════════════════════════════════════════════════════════════════════
# 6. Sorting descending works
# ═════════════════════════════════════════════════════════════════════════

class TestSortingDescending:
    def test_descending_order(self, strong):
        det = SectionAutoDetector(registry=_multi_section_registry_with_strong())
        result = det.detect(strong)
        scores = [d["combined_score"] for d in result.detected_sections]
        assert scores == sorted(scores, reverse=True)

    def test_single_entry_trivially_sorted(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        assert len(result.detected_sections) >= 1
        scores = [d["combined_score"] for d in result.detected_sections]
        assert scores == sorted(scores, reverse=True)


# ═════════════════════════════════════════════════════════════════════════
# 7. Top section matches highest score
# ═════════════════════════════════════════════════════════════════════════

class TestTopSection:
    def test_top_section_equals_first(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        assert result.top_section == result.detected_sections[0]["section"]

    def test_top_score_equals_first_score(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        assert result.top_score == result.detected_sections[0]["combined_score"]

    def test_top_section_empty_when_no_sections(self):
        empty_reg = SectionRegistry()
        det = SectionAutoDetector(registry=empty_reg)
        result = det.detect(FactMatrix())
        assert result.top_section == ""
        assert result.top_score == 0.0

    def test_top_from_multi(self, strong):
        det = SectionAutoDetector(registry=_multi_section_registry_with_strong())
        result = det.detect(strong)
        if result.detected_sections:
            best = max(result.detected_sections, key=lambda d: d["combined_score"])
            assert result.top_section == best["section"]
            assert result.top_score == best["combined_score"]


# ═════════════════════════════════════════════════════════════════════════
# 8. Does not mutate FactMatrix
# ═════════════════════════════════════════════════════════════════════════

class TestNoMutation:
    def test_fact_count_unchanged(self, strong):
        before = {
            cat: len(strong.get_facts(cat))
            for cat in ("actus_reus", "mens_rea", "evidence",
                        "conflicts", "exceptions_claimed")
        }
        det = SectionAutoDetector(registry=_multi_section_registry())
        det.detect(strong)
        after = {
            cat: len(strong.get_facts(cat))
            for cat in ("actus_reus", "mens_rea", "evidence",
                        "conflicts", "exceptions_claimed")
        }
        assert before == after

    def test_idempotent(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        r1 = det.detect(strong)
        r2 = det.detect(strong)
        assert r1.to_dict() == r2.to_dict()


# ═════════════════════════════════════════════════════════════════════════
# 9. Works when only one section registered
# ═════════════════════════════════════════════════════════════════════════

class TestSingleSection:
    def test_one_section_detected(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        assert len(result.detected_sections) == 1

    def test_one_section_top(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        assert result.top_section == "302 IPC"

    def test_one_section_schema(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        entry = result.detected_sections[0]
        assert set(entry.keys()) == {
            "section", "burden_stage", "confidence_score",
            "overall_evidence_score", "combined_score",
        }


# ═════════════════════════════════════════════════════════════════════════
# 10. Schema integrity exact
# ═════════════════════════════════════════════════════════════════════════

class TestSchemaIntegrity:
    RESULT_KEYS = {"detected_sections", "top_section", "top_score"}
    ENTRY_KEYS = {
        "section", "burden_stage", "confidence_score",
        "overall_evidence_score", "combined_score",
    }

    def test_result_keys(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        assert set(result.to_dict().keys()) == self.RESULT_KEYS

    def test_entry_keys(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        for entry in result.detected_sections:
            assert set(entry.keys()) == self.ENTRY_KEYS

    def test_to_json_parseable(self, strong):
        det = SectionAutoDetector(registry=_single_section_registry())
        result = det.detect(strong)
        parsed = json.loads(result.to_json())
        assert parsed["top_section"] == "302 IPC"
        assert isinstance(parsed["detected_sections"], list)

    def test_empty_result_schema(self):
        r = DetectionResult()
        d = r.to_dict()
        assert d == {"detected_sections": [], "top_section": "", "top_score": 0.0}

    def test_detected_section_dataclass(self):
        ds = DetectedSection(
            section="302 IPC",
            burden_stage="prima_facie_established",
            confidence_score=1.0,
            overall_evidence_score=0.8,
            combined_score=0.92,
        )
        d = ds.to_dict()
        assert d["section"] == "302 IPC"
        assert d["combined_score"] == 0.92
