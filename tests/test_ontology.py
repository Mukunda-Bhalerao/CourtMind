"""
Unit tests for ontology layer.

Test categories:

 1. All declared tags are valid.
 2. Invalid tag raises validation error.
 3. Oppositional mapping works bidirectionally.
 4. is_opposed() detects correct contradictions.
 5. Section 302 mapping returns correct tag groups.
 6. Unknown section raises error.
 7. Ontology structures are immutable.
 8. Oppositional pairs are symmetric.
 9. No duplicate tags exist.
10. Evaluator integration compatibility check.

Run:  python -m pytest tests/test_ontology.py -v
"""

import pytest
from types import MappingProxyType

from core.ontology import (
    EXCEPTION_NEGATION_MAP,
    LegalTag,
    OPPOSITION_MAP,
    OPPOSITIONAL_TAG_PAIRS,
    SECTION_ELEMENT_ONTOLOGY,
    get_element_negations,
    get_opposing_tags,
    get_section_element_tags,
    is_opposed,
    list_sections,
    list_tags,
    resolve_tag,
    validate_tag,
)
from core.statute_engine import IPC302Evaluator


# ═════════════════════════════════════════════════════════════════════════
# 1. All declared tags are valid
# ═════════════════════════════════════════════════════════════════════════

class TestScenario01_AllDeclaredTagsValid:
    """Every member of LegalTag must pass validate_tag and resolve_tag."""

    def test_every_enum_value_validates(self):
        for tag in LegalTag:
            assert validate_tag(tag.value) is True, (
                f"LegalTag.{tag.name} ({tag.value!r}) failed validate_tag"
            )

    def test_every_enum_value_resolves(self):
        for tag in LegalTag:
            resolved = resolve_tag(tag.value)
            assert resolved is tag

    def test_list_tags_covers_entire_enum(self):
        all_tags = set(list_tags())
        for tag in LegalTag:
            assert tag.value in all_tags

    def test_essential_tags_present(self):
        essential = [
            "death_caused", "act_by_accused", "intention",
            "self-defense", "alibi", "forensic", "premeditated",
            "homicide", "motive", "witness",
        ]
        for val in essential:
            assert validate_tag(val), f"Missing essential tag: {val}"

    def test_tag_is_str_enum(self):
        """LegalTag members are usable as plain strings."""
        assert isinstance(LegalTag.DEATH, str)
        assert LegalTag.DEATH == "death"


# ═════════════════════════════════════════════════════════════════════════
# 2. Invalid tag raises validation error
# ═════════════════════════════════════════════════════════════════════════

class TestScenario02_InvalidTagRaises:
    """Unrecognised strings must fail validation or raise."""

    def test_validate_returns_false(self):
        assert validate_tag("totally_made_up") is False

    def test_empty_string_invalid(self):
        assert validate_tag("") is False

    def test_resolve_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown legal tag"):
            resolve_tag("not_a_tag")

    def test_validate_non_string_raises_type_error(self):
        with pytest.raises(TypeError):
            validate_tag(42)  # type: ignore[arg-type]

    def test_validate_none_raises_type_error(self):
        with pytest.raises(TypeError):
            validate_tag(None)  # type: ignore[arg-type]

    def test_resolve_non_string_raises_type_error(self):
        with pytest.raises(TypeError):
            resolve_tag(123)  # type: ignore[arg-type]

    def test_case_sensitive(self):
        """Tags are case-sensitive; uppercase must fail."""
        assert validate_tag("DEATH") is False
        assert validate_tag("Death_Caused") is False


# ═════════════════════════════════════════════════════════════════════════
# 3. Oppositional mapping works bidirectionally
# ═════════════════════════════════════════════════════════════════════════

class TestScenario03_BidirectionalOpposition:
    """If A opposes B in OPPOSITION_MAP, then B opposes A."""

    def test_every_entry_is_bidirectional(self):
        for tag, opposites in OPPOSITION_MAP.items():
            for opp in opposites:
                assert tag in OPPOSITION_MAP[opp], (
                    f"{tag.value} opposes {opp.value} but not vice-versa"
                )

    def test_get_opposing_tags_returns_frozenset(self):
        result = get_opposing_tags(LegalTag.INTENTIONAL)
        assert isinstance(result, frozenset)

    def test_accidental_opposes_intentional(self):
        assert LegalTag.ACCIDENTAL in get_opposing_tags(LegalTag.INTENTIONAL)

    def test_intentional_opposes_accidental(self):
        assert LegalTag.INTENTIONAL in get_opposing_tags(LegalTag.ACCIDENTAL)

    def test_no_opposition_for_evidence_tag(self):
        assert get_opposing_tags(LegalTag.FORENSIC) == frozenset()

    def test_get_opposing_tags_type_error(self):
        with pytest.raises(TypeError):
            get_opposing_tags("intentional")  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════
# 4. is_opposed() detects correct contradictions
# ═════════════════════════════════════════════════════════════════════════

class TestScenario04_IsOpposed:
    """is_opposed() must return True for known pairs, False otherwise."""

    def test_intentional_vs_accidental(self):
        assert is_opposed(LegalTag.INTENTIONAL, LegalTag.ACCIDENTAL) is True

    def test_homicide_vs_natural_cause(self):
        assert is_opposed(LegalTag.HOMICIDE, LegalTag.NATURAL_CAUSE) is True

    def test_motive_vs_no_motive(self):
        assert is_opposed(LegalTag.MOTIVE, LegalTag.NO_MOTIVE) is True

    def test_act_vs_alibi(self):
        assert is_opposed(LegalTag.ACT_BY_ACCUSED, LegalTag.ALIBI) is True

    def test_act_vs_absent(self):
        assert is_opposed(LegalTag.ACT_BY_ACCUSED, LegalTag.ABSENT) is True

    def test_self_defense_vs_aggressor(self):
        assert is_opposed(LegalTag.SELF_DEFENSE, LegalTag.AGGRESSOR) is True

    def test_non_opposed_returns_false(self):
        assert is_opposed(LegalTag.FORENSIC, LegalTag.DNA) is False

    def test_same_tag_not_opposed(self):
        assert is_opposed(LegalTag.INTENTIONAL, LegalTag.INTENTIONAL) is False

    def test_type_error_on_strings(self):
        with pytest.raises(TypeError):
            is_opposed("intentional", "accidental")  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════
# 5. Section 302 mapping returns correct tag groups
# ═════════════════════════════════════════════════════════════════════════

class TestScenario05_Section302Mapping:
    """302 IPC must define the correct elements with correct tag sets."""

    def test_section_present(self):
        assert "302 IPC" in SECTION_ELEMENT_ONTOLOGY

    def test_element_ids(self):
        elements = get_section_element_tags("302 IPC")
        assert set(elements.keys()) == {
            "death_of_human", "act_by_accused",
            "intention_or_knowledge", "supporting_evidence",
        }

    def test_death_tags(self):
        tags = get_section_element_tags("302 IPC")["death_of_human"]
        assert LegalTag.DEATH_CAUSED in tags
        assert LegalTag.HOMICIDE in tags
        assert LegalTag.VICTIM_DEAD in tags
        assert LegalTag.DEATH in tags

    def test_act_tags(self):
        tags = get_section_element_tags("302 IPC")["act_by_accused"]
        assert LegalTag.ACT_BY_ACCUSED in tags
        assert LegalTag.STABBING in tags
        assert LegalTag.VIOLENCE in tags

    def test_intent_tags(self):
        tags = get_section_element_tags("302 IPC")["intention_or_knowledge"]
        assert LegalTag.INTENTION in tags
        assert LegalTag.PREMEDITATED in tags
        assert LegalTag.KNOWLEDGE in tags
        assert LegalTag.MOTIVE in tags

    def test_evidence_tags(self):
        tags = get_section_element_tags("302 IPC")["supporting_evidence"]
        assert LegalTag.FORENSIC in tags
        assert LegalTag.WEAPON in tags
        assert LegalTag.CCTV in tags

    def test_all_entries_are_legal_tags(self):
        for eid, tag_set in get_section_element_tags("302 IPC").items():
            assert isinstance(tag_set, frozenset)
            for tag in tag_set:
                assert isinstance(tag, LegalTag), (
                    f"302 IPC/{eid}: {tag!r} is not a LegalTag"
                )

    def test_returns_mapping_proxy(self):
        result = get_section_element_tags("302 IPC")
        assert isinstance(result, MappingProxyType)


# ═════════════════════════════════════════════════════════════════════════
# 6. Unknown section raises error
# ═════════════════════════════════════════════════════════════════════════

class TestScenario06_UnknownSection:
    """Querying an undeclared section must raise a clear error."""

    def test_unknown_section_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown section code"):
            get_section_element_tags("999 IPC")

    def test_empty_string_raises(self):
        with pytest.raises(KeyError):
            get_section_element_tags("")

    def test_non_string_raises_type_error(self):
        with pytest.raises(TypeError):
            get_section_element_tags(302)  # type: ignore[arg-type]

    def test_similar_but_wrong_raises(self):
        with pytest.raises(KeyError):
            get_section_element_tags("302")  # missing " IPC"


# ═════════════════════════════════════════════════════════════════════════
# 7. Ontology structures are immutable
# ═════════════════════════════════════════════════════════════════════════

class TestScenario07_Immutability:
    """All public ontology structures must reject mutation."""

    def test_section_ontology_is_mapping_proxy(self):
        assert isinstance(SECTION_ELEMENT_ONTOLOGY, MappingProxyType)

    def test_cannot_add_section(self):
        with pytest.raises(TypeError):
            SECTION_ELEMENT_ONTOLOGY["999"] = {}  # type: ignore[index]

    def test_cannot_add_element_to_section(self):
        with pytest.raises(TypeError):
            SECTION_ELEMENT_ONTOLOGY["302 IPC"]["new"] = frozenset()  # type: ignore[index]

    def test_inner_dicts_are_mapping_proxy(self):
        for section, elements in SECTION_ELEMENT_ONTOLOGY.items():
            assert isinstance(elements, MappingProxyType)

    def test_tag_sets_are_frozensets(self):
        for section, elements in SECTION_ELEMENT_ONTOLOGY.items():
            for eid, tag_set in elements.items():
                assert isinstance(tag_set, frozenset)

    def test_opposition_map_is_immutable(self):
        assert isinstance(OPPOSITION_MAP, MappingProxyType)
        with pytest.raises(TypeError):
            OPPOSITION_MAP[LegalTag.FORENSIC] = frozenset()  # type: ignore[index]

    def test_negation_map_is_immutable(self):
        assert isinstance(EXCEPTION_NEGATION_MAP, MappingProxyType)
        with pytest.raises(TypeError):
            EXCEPTION_NEGATION_MAP[LegalTag.FORENSIC] = ("x",)  # type: ignore[index]

    def test_oppositional_pairs_are_frozenset(self):
        assert isinstance(OPPOSITIONAL_TAG_PAIRS, frozenset)


# ═════════════════════════════════════════════════════════════════════════
# 8. Oppositional pairs are symmetric
# ═════════════════════════════════════════════════════════════════════════

class TestScenario08_PairsSymmetric:
    """Each pair must have exactly two distinct LegalTag members, and
    is_opposed must agree in both directions."""

    def test_each_pair_has_two_elements(self):
        for pair in OPPOSITIONAL_TAG_PAIRS:
            assert len(pair) == 2

    def test_no_self_opposition_in_pairs(self):
        for a, b in OPPOSITIONAL_TAG_PAIRS:
            assert a != b

    def test_all_pair_members_are_legal_tags(self):
        for a, b in OPPOSITIONAL_TAG_PAIRS:
            assert isinstance(a, LegalTag)
            assert isinstance(b, LegalTag)

    def test_is_opposed_symmetric_for_every_pair(self):
        for a, b in OPPOSITIONAL_TAG_PAIRS:
            assert is_opposed(a, b) is True, f"{a.value} → {b.value} failed"
            assert is_opposed(b, a) is True, f"{b.value} → {a.value} failed"

    def test_premeditated_vs_spontaneous(self):
        assert is_opposed(LegalTag.PREMEDITATED, LegalTag.SPONTANEOUS) is True
        assert is_opposed(LegalTag.SPONTANEOUS, LegalTag.PREMEDITATED) is True


# ═════════════════════════════════════════════════════════════════════════
# 9. No duplicate tags exist
# ═════════════════════════════════════════════════════════════════════════

class TestScenario09_NoDuplicates:
    """LegalTag enum must contain strictly unique values."""

    def test_enum_values_unique(self):
        values = [t.value for t in LegalTag]
        assert len(values) == len(set(values))

    def test_list_tags_no_duplicates(self):
        tags = list_tags()
        assert len(tags) == len(set(tags))

    def test_list_tags_sorted(self):
        tags = list_tags()
        assert tags == tuple(sorted(tags))

    def test_list_sections_no_duplicates(self):
        sections = list_sections()
        assert len(sections) == len(set(sections))

    def test_list_tags_is_tuple(self):
        assert isinstance(list_tags(), tuple)

    def test_list_sections_is_tuple(self):
        assert isinstance(list_sections(), tuple)


# ═════════════════════════════════════════════════════════════════════════
# 10. Evaluator integration compatibility check
# ═════════════════════════════════════════════════════════════════════════

class TestScenario10_EvaluatorCompatibility:
    """Every match_tag used by IPC302Evaluator must be a valid LegalTag,
    and every element_id must appear in the section ontology."""

    _evaluator = IPC302Evaluator()

    def test_evaluator_section_in_ontology(self):
        assert self._evaluator.SECTION in SECTION_ELEMENT_ONTOLOGY

    def test_all_element_ids_in_ontology(self):
        ontology_elements = get_section_element_tags(self._evaluator.SECTION)
        for spec in self._evaluator.ELEMENTS:
            assert spec.element_id in ontology_elements, (
                f"Element {spec.element_id!r} not in ontology for "
                f"{self._evaluator.SECTION}"
            )

    def test_all_evaluator_match_tags_are_valid(self):
        for spec in self._evaluator.ELEMENTS:
            for tag_str in spec.match_tags:
                assert validate_tag(tag_str), (
                    f"Evaluator element {spec.element_id!r} uses unknown "
                    f"tag {tag_str!r}"
                )

    def test_evaluator_match_tags_subset_of_ontology(self):
        """Every match_tag in the evaluator must appear in the ontology
        tag set for its element_id."""
        ontology_elements = get_section_element_tags(self._evaluator.SECTION)
        for spec in self._evaluator.ELEMENTS:
            ontology_tags = {t.value for t in ontology_elements[spec.element_id]}
            evaluator_tags = set(spec.match_tags)
            assert evaluator_tags <= ontology_tags, (
                f"Element {spec.element_id!r}: evaluator tags "
                f"{evaluator_tags - ontology_tags} not in ontology"
            )

    def test_ontology_tags_superset_of_evaluator(self):
        """Ontology may define extra tags the evaluator doesn't use,
        but every evaluator tag must be covered."""
        ontology_elements = get_section_element_tags(self._evaluator.SECTION)
        for spec in self._evaluator.ELEMENTS:
            ontology_tag_vals = {t.value for t in ontology_elements[spec.element_id]}
            for tag_str in spec.match_tags:
                assert tag_str in ontology_tag_vals

    def test_negation_map_exception_tags_valid(self):
        """All keys in EXCEPTION_NEGATION_MAP must be valid LegalTags."""
        for tag in EXCEPTION_NEGATION_MAP:
            assert isinstance(tag, LegalTag)

    def test_negation_targets_are_real_element_ids(self):
        """All element_ids referenced in the negation map must exist in
        at least one section ontology."""
        all_element_ids: set = set()
        for section, elements in SECTION_ELEMENT_ONTOLOGY.items():
            all_element_ids.update(elements.keys())
        for tag, eids in EXCEPTION_NEGATION_MAP.items():
            for eid in eids:
                assert eid in all_element_ids, (
                    f"Negation map references unknown element {eid!r} "
                    f"for exception {tag.value!r}"
                )
