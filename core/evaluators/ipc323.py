"""
CourtMind — IPC Section 323: Voluntarily Causing Hurt

Required elements
-----------------
1. **Simple hurt** — actus_reus fact confirming bodily pain, disease or
   infirmity to the victim.
2. **Act by accused** — actus_reus fact linking the accused's conduct
   to the hurt.

This is a simpler offence — no death element, no mens-rea knowledge
threshold.

No LLM.  Deterministic only.  Ontology-driven tag resolution.
"""

from __future__ import annotations

from core.fact_matrix import FactCategory, Severity
from core.ontology import get_section_element_tags as _get_section_tags
from core.statute_engine import ElementSpec, StatuteEvaluator

from typing import Tuple


def _ontology_tags(section: str, element_id: str) -> Tuple[str, ...]:
    return tuple(sorted(t.value for t in _get_section_tags(section)[element_id]))


class IPC323Evaluator(StatuteEvaluator):
    """Deterministic evaluator for **IPC Section 323 — Voluntarily
    Causing Hurt**."""

    SECTION = "323 IPC"
    SECTION_TITLE = "Voluntarily Causing Hurt"

    ELEMENTS = (
        ElementSpec(
            element_id="hurt_element",
            description="Victim suffered simple hurt (bodily pain, disease or infirmity)",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=_ontology_tags("323 IPC", "hurt_element"),
            match_keywords=(
                "hurt", "injury", "bruise", "pain",
                "slapped", "punched", "kicked", "scratched",
                "minor injury", "bodily harm",
            ),
            min_severity=Severity.LOW.value,
            required=True,
        ),
        ElementSpec(
            element_id="act_by_accused",
            description="Act committed by the accused that caused hurt",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=_ontology_tags("323 IPC", "act_by_accused"),
            match_keywords=(
                "accused", "defendant", "struck", "hit", "slapped",
                "punched", "kicked", "pushed", "attacked", "assaulted",
                "beat",
            ),
            min_severity=Severity.LOW.value,
            required=True,
        ),
    )
