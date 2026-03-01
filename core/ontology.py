"""
CourtMind — Controlled Legal Ontology Layer

Single authoritative source for:

*   Every allowed legal tag  (:class:`LegalTag` enum).
*   Logical contradictions between tags (:data:`OPPOSITIONAL_TAG_PAIRS`).
*   Section → element → tag-set mappings (:data:`SECTION_ELEMENT_ONTOLOGY`).

**Design constraints**

*   No LLM.  No side effects.  No print statements.
*   Pure structured data + deterministic validation helpers.
*   Zero dependencies on FactMatrix, StatuteEvaluator, or BurdenEngine —
    those modules should *import from here*, never the reverse.
*   All public structures are immutable (frozen dataclasses / frozensets /
    ``MappingProxyType``).
*   Fully unit-testable.
"""

from __future__ import annotations

from enum import Enum, unique
from types import MappingProxyType
from typing import Dict, FrozenSet, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════
# 1.  LegalTag — every valid tag in the system
# ═══════════════════════════════════════════════════════════════════════════

@unique
class LegalTag(str, Enum):
    """
    Canonical tag vocabulary.

    Every tag attached to a ``Fact`` should correspond to one of these
    values.  Free-text tags are validated through :func:`validate_tag`.
    """

    # ── Actus Reus: death ──────────────────────────────────────────────
    DEATH = "death"
    DEATH_CAUSED = "death_caused"
    VICTIM_DEAD = "victim_dead"
    HOMICIDE = "homicide"
    NATURAL_CAUSE = "natural_cause"

    # ── Actus Reus: act by accused ─────────────────────────────────────
    ACT_BY_ACCUSED = "act_by_accused"
    ASSAULT = "assault"
    STABBING = "stabbing"
    SHOOTING = "shooting"
    POISONING = "poisoning"
    STRANGULATION = "strangulation"
    VIOLENCE = "violence"

    # ── Mens Rea: intent / knowledge ───────────────────────────────────
    INTENTION = "intention"
    INTENT = "intent"
    INTENTIONAL = "intentional"
    PREMEDITATED = "premeditated"
    KNOWLEDGE = "knowledge"
    KNOWLEDGE_OF_DEATH = "knowledge_of_death"
    MOTIVE = "motive"

    # ── Mens Rea: knowledge without intent (304 IPC) ───────────────────
    KNOWLEDGE_LIKELY_DEATH = "knowledge_likely_death"
    NO_INTENT_TO_KILL = "no_intent_to_kill"

    # ── Actus Reus: hurt (323 IPC) ─────────────────────────────────────
    SIMPLE_HURT = "simple_hurt"
    GRIEVOUS_HURT = "grievous_hurt"

    # ── Actus Reus / Mens Rea: cheating (420 IPC) ─────────────────────
    DECEPTION = "deception"
    DISHONEST_INDUCEMENT = "dishonest_inducement"
    WRONGFUL_GAIN = "wrongful_gain"
    WRONGFUL_LOSS = "wrongful_loss"

    # ── Opposing mental-state tags ─────────────────────────────────────
    ACCIDENTAL = "accidental"
    SPONTANEOUS = "spontaneous"
    NEGLIGENT = "negligent"

    # ── Evidence ───────────────────────────────────────────────────────
    FORENSIC = "forensic"
    WEAPON = "weapon"
    BLOOD = "blood"
    DNA = "dna"
    CCTV = "cctv"
    FINGERPRINT = "fingerprint"
    AUTOPSY = "autopsy"
    WITNESS = "witness"
    TIMELINE = "timeline"

    # ── Exceptions / defenses ──────────────────────────────────────────
    SELF_DEFENSE = "self-defense"
    INSANITY = "insanity"
    ACCIDENT = "accident"
    PROVOCATION = "provocation"
    DURESS = "duress"
    ALIBI = "alibi"
    MISTAKEN_IDENTITY = "mistaken_identity"
    CONSENT = "consent"
    DIMINISHED_RESPONSIBILITY = "diminished_responsibility"

    # ── Misc / contextual ─────────────────────────────────────────────
    AGGRESSOR = "aggressor"
    ABSENT = "absent"
    NO_MOTIVE = "no_motive"


# Fast lookup set — O(1) membership check
_LEGAL_TAG_VALUES: FrozenSet[str] = frozenset(t.value for t in LegalTag)


# ═══════════════════════════════════════════════════════════════════════════
# 2.  Oppositional Tag Pairs — logical contradictions
# ═══════════════════════════════════════════════════════════════════════════

# Each tuple is an **unordered pair**: (A, B) means A contradicts B and
# vice-versa.  The set of pairs is immutable.

OPPOSITIONAL_TAG_PAIRS: FrozenSet[Tuple[LegalTag, LegalTag]] = frozenset({
    (LegalTag.INTENTIONAL, LegalTag.ACCIDENTAL),
    (LegalTag.PREMEDITATED, LegalTag.SPONTANEOUS),
    (LegalTag.SELF_DEFENSE, LegalTag.AGGRESSOR),
    (LegalTag.HOMICIDE, LegalTag.NATURAL_CAUSE),
    (LegalTag.INTENTION, LegalTag.ACCIDENTAL),
    (LegalTag.MOTIVE, LegalTag.NO_MOTIVE),
    (LegalTag.ACT_BY_ACCUSED, LegalTag.ALIBI),
    (LegalTag.ACT_BY_ACCUSED, LegalTag.ABSENT),
    (LegalTag.ACT_BY_ACCUSED, LegalTag.MISTAKEN_IDENTITY),
})

# Pre-computed bidirectional map: tag → set of opposing tags
_OPPOSITION_MAP: Dict[LegalTag, FrozenSet[LegalTag]] = {}
for _a, _b in OPPOSITIONAL_TAG_PAIRS:
    _OPPOSITION_MAP.setdefault(_a, frozenset())
    _OPPOSITION_MAP.setdefault(_b, frozenset())
    _OPPOSITION_MAP[_a] = _OPPOSITION_MAP[_a] | frozenset({_b})
    _OPPOSITION_MAP[_b] = _OPPOSITION_MAP[_b] | frozenset({_a})

# Expose as immutable
OPPOSITION_MAP: MappingProxyType[LegalTag, FrozenSet[LegalTag]] = MappingProxyType(
    _OPPOSITION_MAP
)


# ═══════════════════════════════════════════════════════════════════════════
# 3.  Section → Element → Tag-Set Ontology
# ═══════════════════════════════════════════════════════════════════════════

# Inner mapping: element_id → frozenset of LegalTags that satisfy it.
# Outer mapping: section_code → element mapping.
# Both levels are exposed through MappingProxyType for immutability.

_SECTION_ELEMENT_ONTOLOGY: Dict[str, Dict[str, FrozenSet[LegalTag]]] = {
    "302 IPC": {
        "death_of_human": frozenset({
            LegalTag.DEATH,
            LegalTag.DEATH_CAUSED,
            LegalTag.VICTIM_DEAD,
            LegalTag.HOMICIDE,
        }),
        "act_by_accused": frozenset({
            LegalTag.ACT_BY_ACCUSED,
            LegalTag.ASSAULT,
            LegalTag.STABBING,
            LegalTag.SHOOTING,
            LegalTag.POISONING,
            LegalTag.STRANGULATION,
            LegalTag.VIOLENCE,
        }),
        "intention_or_knowledge": frozenset({
            LegalTag.INTENTION,
            LegalTag.INTENT,
            LegalTag.INTENTIONAL,
            LegalTag.PREMEDITATED,
            LegalTag.KNOWLEDGE,
            LegalTag.KNOWLEDGE_OF_DEATH,
            LegalTag.MOTIVE,
        }),
        "supporting_evidence": frozenset({
            LegalTag.FORENSIC,
            LegalTag.WEAPON,
            LegalTag.BLOOD,
            LegalTag.DNA,
            LegalTag.CCTV,
            LegalTag.FINGERPRINT,
            LegalTag.AUTOPSY,
            LegalTag.WITNESS,
        }),
    },

    # ── 304 IPC — Culpable Homicide not amounting to Murder ────────────
    "304 IPC": {
        "death_of_human": frozenset({
            LegalTag.DEATH,
            LegalTag.DEATH_CAUSED,
            LegalTag.VICTIM_DEAD,
            LegalTag.HOMICIDE,
        }),
        "act_by_accused": frozenset({
            LegalTag.ACT_BY_ACCUSED,
            LegalTag.ASSAULT,
            LegalTag.STABBING,
            LegalTag.SHOOTING,
            LegalTag.POISONING,
            LegalTag.STRANGULATION,
            LegalTag.VIOLENCE,
        }),
        "knowledge_element": frozenset({
            LegalTag.KNOWLEDGE_LIKELY_DEATH,
            LegalTag.NO_INTENT_TO_KILL,
        }),
    },

    # ── 420 IPC — Cheating and dishonestly inducing delivery of property
    "420 IPC": {
        "deception_element": frozenset({
            LegalTag.DECEPTION,
        }),
        "inducement_element": frozenset({
            LegalTag.DISHONEST_INDUCEMENT,
        }),
        "gain_loss_element": frozenset({
            LegalTag.WRONGFUL_GAIN,
            LegalTag.WRONGFUL_LOSS,
        }),
    },

    # ── 323 IPC — Voluntarily causing hurt ─────────────────────────────
    "323 IPC": {
        "hurt_element": frozenset({
            LegalTag.SIMPLE_HURT,
        }),
        "act_by_accused": frozenset({
            LegalTag.ACT_BY_ACCUSED,
        }),
    },
}

# Freeze the inner dicts too, then expose via MappingProxyType
SECTION_ELEMENT_ONTOLOGY: MappingProxyType[
    str, MappingProxyType[str, FrozenSet[LegalTag]]
] = MappingProxyType({
    section: MappingProxyType(elements)
    for section, elements in _SECTION_ELEMENT_ONTOLOGY.items()
})


# ═══════════════════════════════════════════════════════════════════════════
# 4.  Exception → Element negation mapping
# ═══════════════════════════════════════════════════════════════════════════

# Authoritative map: exception LegalTag → tuple of element_ids it negates.
EXCEPTION_NEGATION_MAP: MappingProxyType[LegalTag, Tuple[str, ...]] = MappingProxyType({
    LegalTag.SELF_DEFENSE: ("intention_or_knowledge", "knowledge_element"),
    LegalTag.INSANITY: ("intention_or_knowledge", "knowledge_element",
                        "deception_element", "inducement_element"),
    LegalTag.ACCIDENT: ("intention_or_knowledge", "act_by_accused",
                        "knowledge_element"),
    LegalTag.PROVOCATION: ("intention_or_knowledge", "knowledge_element"),
    LegalTag.DURESS: ("intention_or_knowledge", "knowledge_element",
                      "deception_element"),
    LegalTag.ALIBI: ("act_by_accused",),
    LegalTag.MISTAKEN_IDENTITY: ("act_by_accused",),
    LegalTag.CONSENT: ("act_by_accused", "hurt_element"),
})


# ═══════════════════════════════════════════════════════════════════════════
# 5.  Utility functions
# ═══════════════════════════════════════════════════════════════════════════

def validate_tag(tag: str) -> bool:
    """
    Return ``True`` if *tag* is a declared :class:`LegalTag` value.

    Raises
    ------
    TypeError
        If *tag* is not a string.
    """
    if not isinstance(tag, str):
        raise TypeError(f"Tag must be a string, got {type(tag).__name__}")
    return tag in _LEGAL_TAG_VALUES


def resolve_tag(tag: str) -> LegalTag:
    """
    Convert a raw string tag to its :class:`LegalTag` enum member.

    Raises
    ------
    ValueError
        If *tag* is not a valid LegalTag value.
    TypeError
        If *tag* is not a string.
    """
    if not isinstance(tag, str):
        raise TypeError(f"Tag must be a string, got {type(tag).__name__}")
    try:
        return LegalTag(tag)
    except ValueError:
        raise ValueError(
            f"Unknown legal tag: {tag!r}. "
            f"Valid tags: {sorted(_LEGAL_TAG_VALUES)}"
        ) from None


def get_opposing_tags(tag: LegalTag) -> FrozenSet[LegalTag]:
    """
    Return all tags that logically oppose *tag*.

    Returns an empty frozenset when *tag* has no declared oppositions.

    Raises
    ------
    TypeError
        If *tag* is not a :class:`LegalTag` member.
    """
    if not isinstance(tag, LegalTag):
        raise TypeError(
            f"Expected LegalTag, got {type(tag).__name__}. "
            f"Use resolve_tag() to convert a string first."
        )
    return OPPOSITION_MAP.get(tag, frozenset())


def is_opposed(tag1: LegalTag, tag2: LegalTag) -> bool:
    """
    Return ``True`` if *tag1* and *tag2* are a declared oppositional pair.

    Raises
    ------
    TypeError
        If either argument is not a :class:`LegalTag` member.
    """
    if not isinstance(tag1, LegalTag) or not isinstance(tag2, LegalTag):
        raise TypeError(
            "Both arguments must be LegalTag members. "
            "Use resolve_tag() to convert strings first."
        )
    return tag2 in OPPOSITION_MAP.get(tag1, frozenset())


def get_section_element_tags(
    section_code: str,
) -> MappingProxyType[str, FrozenSet[LegalTag]]:
    """
    Return the element → tag-set mapping for a given section code.

    Raises
    ------
    KeyError
        If *section_code* is not present in the ontology.
    TypeError
        If *section_code* is not a string.
    """
    if not isinstance(section_code, str):
        raise TypeError(
            f"section_code must be a string, got {type(section_code).__name__}"
        )
    try:
        return SECTION_ELEMENT_ONTOLOGY[section_code]
    except KeyError:
        raise KeyError(
            f"Unknown section code: {section_code!r}. "
            f"Known sections: {sorted(SECTION_ELEMENT_ONTOLOGY.keys())}"
        ) from None


def get_element_negations(tag: LegalTag) -> Tuple[str, ...]:
    """
    Return element_ids that are negated by the given exception *tag*.

    Returns an empty tuple when *tag* is not in the negation map.

    Raises
    ------
    TypeError
        If *tag* is not a :class:`LegalTag` member.
    """
    if not isinstance(tag, LegalTag):
        raise TypeError(
            f"Expected LegalTag, got {type(tag).__name__}. "
            f"Use resolve_tag() to convert a string first."
        )
    return EXCEPTION_NEGATION_MAP.get(tag, ())


def list_sections() -> Tuple[str, ...]:
    """Return all section codes present in the ontology."""
    return tuple(sorted(SECTION_ELEMENT_ONTOLOGY.keys()))


def list_tags() -> Tuple[str, ...]:
    """Return all valid tag values, sorted alphabetically."""
    return tuple(sorted(_LEGAL_TAG_VALUES))
