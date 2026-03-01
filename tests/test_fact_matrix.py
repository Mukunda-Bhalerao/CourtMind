"""
Tests for core.fact_matrix — FactMatrix engine.
Run:  python -m pytest tests/test_fact_matrix.py -v
"""

import json
import pytest

from core.fact_matrix import (
    Conflict,
    Fact,
    FactCategory,
    FactMatrix,
    FactSource,
    Severity,
)


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def matrix() -> FactMatrix:
    return FactMatrix()


@pytest.fixture
def populated(matrix: FactMatrix) -> FactMatrix:
    """Matrix pre-loaded with a handful of facts."""
    matrix.add_fact(
        FactCategory.ACTUS_REUS,
        "Accused struck the victim with an iron rod",
        FactSource.WITNESS,
        severity=Severity.CRITICAL,
        tags=["violence", "intentional"],
    )
    matrix.add_fact(
        FactCategory.MENS_REA,
        "Accused had premeditated the attack per phone records",
        FactSource.FORENSIC,
        severity=Severity.HIGH,
        tags=["premeditated"],
    )
    matrix.add_fact(
        FactCategory.EVIDENCE,
        "CCTV footage shows accused at the scene at 22:14",
        FactSource.DOCUMENT,
        severity=Severity.HIGH,
        tags=["cctv", "timeline"],
    )
    matrix.add_fact(
        FactCategory.EXCEPTIONS_CLAIMED,
        "Defense claims the act was spontaneous self-defense",
        FactSource.CASE_FILE,
        severity=Severity.HIGH,
        tags=["self-defense", "spontaneous"],
    )
    return matrix


# ── category validation ───────────────────────────────────────────────────

class TestCategoryValidation:
    def test_allowed_categories_match_enum(self):
        assert set(FactMatrix.ALLOWED_CATEGORIES) == {c.value for c in FactCategory}

    def test_add_fact_invalid_category_raises(self, matrix: FactMatrix):
        with pytest.raises(ValueError, match="Invalid category"):
            matrix.add_fact("invalid_bucket", "some fact", "src")

    def test_get_facts_invalid_category_raises(self, matrix: FactMatrix):
        with pytest.raises(ValueError, match="Invalid category"):
            matrix.get_facts("nope")


# ── adding facts ──────────────────────────────────────────────────────────

class TestAddFact:
    def test_add_returns_fact(self, matrix: FactMatrix):
        f = matrix.add_fact(FactCategory.ACTUS_REUS, "X did Y", "witness")
        assert isinstance(f, Fact)
        assert f.category == "actus_reus"
        assert f.statement == "X did Y"

    def test_empty_statement_raises(self, matrix: FactMatrix):
        with pytest.raises(ValueError, match="must not be empty"):
            matrix.add_fact(FactCategory.EVIDENCE, "   ", "src")

    def test_dedup_returns_existing(self, matrix: FactMatrix):
        f1 = matrix.add_fact(FactCategory.EVIDENCE, "blood sample matched", "lab")
        f2 = matrix.add_fact(FactCategory.EVIDENCE, "blood sample matched", "lab")
        assert f1.id == f2.id
        assert matrix.count() == 1

    def test_whitespace_normalised_for_dedup(self, matrix: FactMatrix):
        matrix.add_fact(FactCategory.EVIDENCE, "  blood sample  ", "lab")
        matrix.add_fact(FactCategory.EVIDENCE, "blood sample", "lab")
        assert matrix.count() == 1

    def test_count_per_category(self, populated: FactMatrix):
        assert populated.count(FactCategory.ACTUS_REUS) == 1
        assert populated.count(FactCategory.MENS_REA) == 1
        assert populated.count(FactCategory.EVIDENCE) == 1
        assert populated.count(FactCategory.EXCEPTIONS_CLAIMED) == 1
        assert populated.count() == 4

    def test_add_facts_bulk(self, matrix: FactMatrix):
        batch = [
            {"category": "actus_reus", "statement": "A hit B", "source": "witness"},
            {"category": "evidence", "statement": "Knife found", "source": "forensic"},
        ]
        created = matrix.add_facts_bulk(batch)
        assert len(created) == 2
        assert matrix.count() == 2


# ── removal ───────────────────────────────────────────────────────────────

class TestRemoveFact:
    def test_remove_existing(self, matrix: FactMatrix):
        f = matrix.add_fact(FactCategory.EVIDENCE, "item", "src")
        assert matrix.remove_fact(f.id) is True
        assert matrix.count() == 0
        assert matrix.get_fact_by_id(f.id) is None

    def test_remove_nonexistent_returns_false(self, matrix: FactMatrix):
        assert matrix.remove_fact("nope") is False

    def test_remove_cleans_conflicts(self, matrix: FactMatrix):
        f1 = matrix.add_fact(FactCategory.ACTUS_REUS, "A did X", "w1")
        f2 = matrix.add_fact(FactCategory.ACTUS_REUS, "A was elsewhere", "w2")
        matrix.register_conflict(f1.id, f2.id, "contradictory location")
        assert len(matrix.get_conflicts()) == 1
        matrix.remove_fact(f1.id)
        assert len(matrix.get_conflicts()) == 0


# ── conflict detection ────────────────────────────────────────────────────

class TestConflicts:
    def test_register_conflict(self, matrix: FactMatrix):
        f1 = matrix.add_fact(FactCategory.EVIDENCE, "victim alive at 10pm", "w1")
        f2 = matrix.add_fact(FactCategory.EVIDENCE, "victim dead at 9pm", "w2")
        c = matrix.register_conflict(f1.id, f2.id, "time of death contradicts")
        assert isinstance(c, Conflict)
        assert len(matrix.get_conflicts()) == 1

    def test_register_conflict_bad_ids(self, matrix: FactMatrix):
        f1 = matrix.add_fact(FactCategory.EVIDENCE, "something", "src")
        with pytest.raises(KeyError):
            matrix.register_conflict(f1.id, "nonexistent", "reason")

    def test_register_conflict_same_fact(self, matrix: FactMatrix):
        f1 = matrix.add_fact(FactCategory.EVIDENCE, "something", "src")
        with pytest.raises(ValueError, match="cannot conflict with itself"):
            matrix.register_conflict(f1.id, f1.id, "reason")

    def test_register_conflict_empty_reason(self, matrix: FactMatrix):
        f1 = matrix.add_fact(FactCategory.EVIDENCE, "a", "s1")
        f2 = matrix.add_fact(FactCategory.EVIDENCE, "b", "s2")
        with pytest.raises(ValueError, match="must not be empty"):
            matrix.register_conflict(f1.id, f2.id, "  ")

    def test_detect_conflicts_by_tags(self, populated: FactMatrix):
        # populated has "premeditated" (mens_rea) and "spontaneous" (exception)
        new = populated.detect_conflicts_by_tags()
        assert len(new) >= 1
        reasons = [c.reason for c in new]
        assert any("premeditated" in r and "spontaneous" in r for r in reasons)


# ── search & queries ──────────────────────────────────────────────────────

class TestSearch:
    def test_search_by_keyword(self, populated: FactMatrix):
        hits = populated.search(keyword="iron rod")
        assert len(hits) == 1
        assert "iron rod" in hits[0].statement

    def test_search_by_category(self, populated: FactMatrix):
        hits = populated.search(category=FactCategory.EVIDENCE)
        assert len(hits) == 1

    def test_search_by_severity(self, populated: FactMatrix):
        hits = populated.search(severity=Severity.CRITICAL)
        assert len(hits) == 1

    def test_search_by_tag(self, populated: FactMatrix):
        hits = populated.search(tag="cctv")
        assert len(hits) == 1

    def test_search_combined_filters(self, populated: FactMatrix):
        hits = populated.search(category=FactCategory.EVIDENCE, tag="timeline")
        assert len(hits) == 1

    def test_search_no_match(self, populated: FactMatrix):
        hits = populated.search(keyword="nonexistent xyz")
        assert hits == []


# ── export / import ───────────────────────────────────────────────────────

class TestExportImport:
    def test_to_dict_structure(self, populated: FactMatrix):
        d = populated.to_dict()
        assert "facts" in d
        assert "conflicts" in d
        assert "summary" in d
        assert set(d["facts"].keys()) == set(FactMatrix.ALLOWED_CATEGORIES)

    def test_to_json_roundtrip(self, populated: FactMatrix):
        populated.register_conflict(
            populated.get_facts(FactCategory.ACTUS_REUS)[0].id,
            populated.get_facts(FactCategory.EXCEPTIONS_CLAIMED)[0].id,
            "act vs exception",
        )
        json_str = populated.to_json()
        restored = FactMatrix.from_json(json_str)

        assert restored.count() == populated.count()
        assert len(restored.get_conflicts()) == len(populated.get_conflicts())
        # All original fact ids survive
        for cat in FactMatrix.ALLOWED_CATEGORIES:
            orig_ids = {f.id for f in populated.get_facts(cat)}
            rest_ids = {f.id for f in restored.get_facts(cat)}
            assert orig_ids == rest_ids

    def test_to_json_is_valid_json(self, populated: FactMatrix):
        parsed = json.loads(populated.to_json())
        assert isinstance(parsed, dict)

    def test_from_dict_empty(self):
        m = FactMatrix.from_dict({})
        assert m.count() == 0


# ── summary ───────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_keys(self, populated: FactMatrix):
        s = populated.summary()
        assert s["total_facts"] == 4
        assert s["total_conflicts"] == 0
        assert isinstance(s["by_category"], dict)

    def test_repr(self, populated: FactMatrix):
        r = repr(populated)
        assert "facts=4" in r
        assert "conflicts=0" in r
