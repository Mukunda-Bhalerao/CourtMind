"""
CourtMind — IPC Section 420: Cheating and dishonestly inducing delivery
of property

Required elements
-----------------
1. **Deception** — actus_reus fact establishing that the accused deceived
   the victim.
2. **Dishonest inducement** — mens_rea fact showing the victim was
   induced to deliver property / consent.
3. **Wrongful gain or wrongful loss** — actus_reus fact confirming
   material gain by accused or loss by victim.

No LLM.  Deterministic only.  Ontology-driven tag resolution.
"""

from __future__ import annotations

from core.fact_matrix import FactCategory, Severity
from core.ontology import get_section_element_tags as _get_section_tags
from core.statute_engine import ElementSpec, StatuteEvaluator

from typing import Tuple


def _ontology_tags(section: str, element_id: str) -> Tuple[str, ...]:
    return tuple(sorted(t.value for t in _get_section_tags(section)[element_id]))


class IPC420Evaluator(StatuteEvaluator):
    """Deterministic evaluator for **IPC Section 420 — Cheating**."""

    SECTION = "420 IPC"
    SECTION_TITLE = "Cheating and dishonestly inducing delivery of property"

    ELEMENTS = (
        ElementSpec(
            element_id="deception_element",
            description="Accused deceived the victim",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=_ontology_tags("420 IPC", "deception_element"),
            match_keywords=(
                "deception", "deceived", "false representation",
                "misrepresentation", "fraud", "cheating", "lied",
                "fabricated", "false pretense", "forged", "fake",
                "impersonat", "false promise", "false document",
                "bogus", "sham", "fraudulent",
            ),
            min_severity=Severity.MEDIUM.value,
            required=True,
        ),
        ElementSpec(
            element_id="inducement_element",
            description="Victim was dishonestly induced to deliver property or consent",
            required_category=FactCategory.MENS_REA.value,
            match_tags=_ontology_tags("420 IPC", "inducement_element"),
            match_keywords=(
                "induced", "inducement", "dishonest", "coerced into signing",
                "tricked into", "persuaded falsely", "lured",
                "convinced to invest", "promised returns", "invest",
                "deposit", "hand over", "deliver", "signed over",
                "transfer", "gave money", "paid",
            ),
            min_severity=Severity.MEDIUM.value,
            required=True,
        ),
        ElementSpec(
            element_id="gain_loss_element",
            description="Wrongful gain to accused or wrongful loss to victim",
            required_category=FactCategory.ACTUS_REUS.value,
            match_tags=_ontology_tags("420 IPC", "gain_loss_element"),
            match_keywords=(
                "wrongful gain", "wrongful loss", "financial loss",
                "monetary gain", "property transferred", "stolen funds",
                "embezzled", "misappropriated", "lost money",
                "lost savings", "vanished", "ran away with",
                "absconded", "never returned", "loss of",
                "crore", "lakh", "rupees", "investment",
            ),
            min_severity=Severity.MEDIUM.value,
            required=True,
        ),
    )
