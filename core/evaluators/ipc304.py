"""
CourtMind — IPC Section 304: Culpable Homicide not amounting to Murder

Required elements
-----------------
1. **Death of a human being** — actus_reus fact confirming death.
2. **Act by accused caused death** — actus_reus fact linking the accused.
3. **Knowledge that act is likely to cause death BUT no intention to kill**
   — mens_rea fact establishing knowledge without premeditated intent.

Distinguishing factor from 302 IPC: absence of clear intention /
premeditation, replaced by knowledge-of-likely-death.

No LLM.  Deterministic only.  Ontology-driven tag resolution.
"""

from __future__ import annotations

from core.fact_matrix import FactCategory, Severity
from core.ontology import get_section_element_tags as _get_section_tags
from core.statute_engine import ElementSpec, StatuteEvaluator

from typing import Tuple


def _ontology_tags(section: str, element_id: str) -> Tuple[str, ...]:
    return tuple(sorted(t.value for t in _get_section_tags(section)[element_id]))


class IPC304Evaluator(StatuteEvaluator):
    """Deterministic evaluator for **IPC Section 304 — Culpable Homicide
    not amounting to Murder**."""

    SECTION = "304 IPC"
    SECTION_TITLE = "Culpable Homicide not amounting to Murder"

    ELEMENTS = (
        ElementSpec(
            element_id="death_of_human",
            description="Death of a human being",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=_ontology_tags("304 IPC", "death_of_human"),
            match_keywords=("died", "death", "killed", "dead", "deceased", "fatal"),
            min_severity=Severity.HIGH.value,
            required=True,
        ),
        ElementSpec(
            element_id="act_by_accused",
            description="Act committed by the accused that caused death",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=_ontology_tags("304 IPC", "act_by_accused"),
            match_keywords=(
                "accused", "defendant", "struck", "stabbed", "shot",
                "poisoned", "strangled", "attacked", "assaulted", "hit",
                "beat", "pushed",
            ),
            min_severity=Severity.HIGH.value,
            required=True,
        ),
        ElementSpec(
            element_id="knowledge_element",
            description="Knowledge that act is likely to cause death, without intent to kill",
            required_category=FactCategory.MENS_REA.value,
            match_tags=_ontology_tags("304 IPC", "knowledge_element"),
            match_keywords=(
                "knew likely", "knowledge", "aware", "reckless",
                "no intent to kill", "without intention", "not premeditated",
                "likely to cause death",
            ),
            min_severity=Severity.MEDIUM.value,
            required=True,
        ),
    )
