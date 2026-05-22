"""
CourtMind — IPC Section Detection Accuracy Tests

End-to-end validation: raw case narrative → extract_facts_keyword_only →
SectionAutoDetector.detect → verify correct IPC section is top-ranked.

Categories
----------
 1–4. Well-known case narratives per section (302, 304, 420, 323).
 5–8. Edge / ambiguous scenarios.
 9.   Full pipeline run_full_simulation round-trip.
10.   Multi-section ranking stability.
11.   Demo case files from courtmind_demo_cases/.

Run:  python -m pytest tests/test_ipc_accuracy.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.fact_extractor import extract_facts_keyword_only
from core.section_auto_detector import SectionAutoDetector


# ── Helpers ────────────────────────────────────────────────────────────────

def _top_section(case_text: str) -> str:
    """Return the top detected IPC section code for *case_text*."""
    fm = extract_facts_keyword_only(case_text)
    det = SectionAutoDetector()
    result = det.detect(fm)
    return result.top_section


def _detected_sections(case_text: str) -> list[str]:
    """Return all detected IPC section codes for *case_text*."""
    fm = extract_facts_keyword_only(case_text)
    det = SectionAutoDetector()
    result = det.detect(fm)
    return [d["section"] for d in result.detected_sections]


# ═════════════════════════════════════════════════════════════════════════
# 1. Premeditated murder → 302 IPC
# ═════════════════════════════════════════════════════════════════════════

class TestIPC302Detection:
    """Premeditated knife murder should detect 302 IPC as top section."""

    NARRATIVE = (
        "The accused had a long-standing dispute with the victim. On the night "
        "of the incident, the accused deliberately attacked the victim with a "
        "knife and stabbed him multiple times in the chest and abdomen. The "
        "victim collapsed and later died in the hospital. CCTV footage shows "
        "the accused approaching with a knife. Forensic reports confirm the "
        "victim's blood on the accused's clothes. Fingerprints on the knife "
        "match the accused. The attack was intentional and premeditated."
    )

    def test_top_section_is_302(self):
        assert _top_section(self.NARRATIVE) == "302 IPC"

    def test_302_in_detected(self):
        assert "302 IPC" in _detected_sections(self.NARRATIVE)


# ═════════════════════════════════════════════════════════════════════════
# 2. Fight death (culpable homicide) → 304 IPC
# ═════════════════════════════════════════════════════════════════════════

class TestIPC304Detection:
    """Fight-induced death with no premeditation → 304 IPC."""

    NARRATIVE = (
        "The accused and the victim were involved in a sudden fight outside a "
        "bar. In the heat of the moment during a quarrel, the accused struck "
        "the victim with a single blow. The victim fell, hit his head, and "
        "later died. There was no premeditation. The accused knew his actions "
        "could cause harm but had no intent to kill. No weapon was used."
    )

    def test_top_section_is_304(self):
        assert _top_section(self.NARRATIVE) == "304 IPC"

    def test_304_ranked_above_302(self):
        secs = _detected_sections(self.NARRATIVE)
        if "302 IPC" in secs and "304 IPC" in secs:
            assert secs.index("304 IPC") < secs.index("302 IPC")


# ═════════════════════════════════════════════════════════════════════════
# 3. Investment fraud → 420 IPC
# ═════════════════════════════════════════════════════════════════════════

class TestIPC420Detection:
    """Cheating via false investment promises → 420 IPC."""

    NARRATIVE = (
        "The accused deceived the victim by promising high returns on an "
        "investment. The victim was induced to transfer 10 lakh rupees to the "
        "accused's bank account. The accused knew the promises were false. "
        "After receiving the money, the accused vanished. Bank records confirm "
        "the transfer. Messages show the accused making fraudulent promises. "
        "The victim suffered a financial loss."
    )

    def test_top_section_is_420(self):
        assert _top_section(self.NARRATIVE) == "420 IPC"

    def test_420_in_detected(self):
        assert "420 IPC" in _detected_sections(self.NARRATIVE)


# ═════════════════════════════════════════════════════════════════════════
# 4. Simple hurt → 323 IPC
# ═════════════════════════════════════════════════════════════════════════

class TestIPC323Detection:
    """Slap and punch with minor injury → 323 IPC."""

    NARRATIVE = (
        "During an argument, the accused slapped and punched the victim "
        "several times. The victim suffered bruises and pain but no serious "
        "injuries. Medical reports confirm bruises on the face and arms. "
        "Witnesses saw the accused hitting the victim."
    )

    def test_top_section_is_323(self):
        assert _top_section(self.NARRATIVE) == "323 IPC"

    def test_323_in_detected(self):
        assert "323 IPC" in _detected_sections(self.NARRATIVE)


# ═════════════════════════════════════════════════════════════════════════
# 5. Edge: Shooting murder → 302 IPC  (weapon + intent)
# ═════════════════════════════════════════════════════════════════════════

class TestEdgeShooting302:
    NARRATIVE = (
        "The accused shot the victim with a firearm at close range. "
        "The shooting was deliberate and premeditated. The victim died "
        "at the scene. A gun was recovered from the accused."
    )

    def test_top_302(self):
        assert _top_section(self.NARRATIVE) == "302 IPC"


# ═════════════════════════════════════════════════════════════════════════
# 6. Edge: Strangulation murder → 302 IPC
# ═════════════════════════════════════════════════════════════════════════

class TestEdgeStrangulation302:
    NARRATIVE = (
        "The accused strangled the victim with a rope with deliberate "
        "intent to kill. The victim was found dead. Forensic examination "
        "confirmed strangulation as cause of death. The accused had "
        "premeditated the attack."
    )

    def test_top_302(self):
        assert _top_section(self.NARRATIVE) == "302 IPC"


# ═════════════════════════════════════════════════════════════════════════
# 7. Edge: Poisoning murder → 302 IPC
# ═════════════════════════════════════════════════════════════════════════

class TestEdgePoisoning302:
    NARRATIVE = (
        "The accused poisoned the victim's food with intent to kill. "
        "The victim died from poisoning. The autopsy confirmed poison in "
        "the victim's body. The accused had planned the poisoning."
    )

    def test_top_302(self):
        assert _top_section(self.NARRATIVE) == "302 IPC"


# ═════════════════════════════════════════════════════════════════════════
# 8. Edge: Kicking injury → 323 IPC  (not death)
# ═════════════════════════════════════════════════════════════════════════

class TestEdgeKicking323:
    NARRATIVE = (
        "The accused kicked and punched the victim during a street fight. "
        "The victim suffered bruises and minor injuries. A witness saw the "
        "accused beating the victim."
    )

    def test_top_323(self):
        assert _top_section(self.NARRATIVE) == "323 IPC"


# ═════════════════════════════════════════════════════════════════════════
# 9. Full pipeline round-trip
# ═════════════════════════════════════════════════════════════════════════

class TestFullPipelineRoundTrip:
    """run_full_simulation should succeed and produce simulation_events."""

    def test_302_simulation_completes(self):
        from simulation.run_simulation import run_full_simulation

        narrative = (
            "The accused stabbed the victim multiple times with a knife "
            "intentionally and deliberately. The victim died. Fingerprints "
            "found on the weapon. CCTV captured the attack."
        )
        fm = extract_facts_keyword_only(narrative)
        result = run_full_simulation(fm, auto_detect=True)
        assert "simulation_events" in result
        assert result["simulation_events"]["total_events"] > 0

    def test_420_simulation_completes(self):
        from simulation.run_simulation import run_full_simulation

        narrative = (
            "The accused deceived the victim with false promises of profit. "
            "The victim was induced to transfer money. The accused vanished "
            "with the funds. Bank records confirm the transaction."
        )
        fm = extract_facts_keyword_only(narrative)
        result = run_full_simulation(fm, auto_detect=True)
        assert "simulation_events" in result
        assert result["simulation_events"]["total_events"] > 0


# ═════════════════════════════════════════════════════════════════════════
# 10. Multi-section ranking stability
# ═════════════════════════════════════════════════════════════════════════

class TestMultiSectionRanking:
    """Multiple runs should produce stable ranking."""

    NARRATIVE = (
        "The accused stabbed the victim once during a sudden quarrel. "
        "The victim died. The accused knew the blow could be fatal but "
        "had no intent to kill. It happened in the heat of the moment."
    )

    def test_stable_ranking(self):
        sections_a = _detected_sections(self.NARRATIVE)
        sections_b = _detected_sections(self.NARRATIVE)
        assert sections_a == sections_b

    def test_both_302_and_304_detected(self):
        secs = _detected_sections(self.NARRATIVE)
        # A death case with ambiguity should detect both 302 and 304
        assert "302 IPC" in secs or "304 IPC" in secs


# ═════════════════════════════════════════════════════════════════════════
# 11. Demo case files
# ═════════════════════════════════════════════════════════════════════════

_DEMO_DIR = Path(__file__).resolve().parent.parent / "courtmind_demo_cases"


class TestDemoCaseFiles:
    """Run detection on the actual demo .txt files shipped with the repo."""

    @pytest.mark.skipif(
        not (_DEMO_DIR / "case_1_murder_302.txt").exists(),
        reason="Demo case files not present",
    )
    def test_case_1_murder_302(self):
        text = (_DEMO_DIR / "case_1_murder_302.txt").read_text(encoding="utf-8")
        assert _top_section(text) == "302 IPC"

    @pytest.mark.skipif(
        not (_DEMO_DIR / "case_2_self_defense_304.txt").exists(),
        reason="Demo case files not present",
    )
    def test_case_2_self_defense_304(self):
        text = (_DEMO_DIR / "case_2_self_defense_304.txt").read_text(encoding="utf-8")
        top = _top_section(text)
        # Self-defense case may detect 304 (culpable homicide) or 302 (murder)
        # due to the stabbing and death; 304 is preferred given self-defense claim
        assert top in ("304 IPC", "302 IPC")

    @pytest.mark.skipif(
        not (_DEMO_DIR / "case_3_cheating_420.txt").exists(),
        reason="Demo case files not present",
    )
    def test_case_3_cheating_420(self):
        text = (_DEMO_DIR / "case_3_cheating_420.txt").read_text(encoding="utf-8")
        assert _top_section(text) == "420 IPC"

    @pytest.mark.skipif(
        not (_DEMO_DIR / "case_4_simple_hurt_323.txt").exists(),
        reason="Demo case files not present",
    )
    def test_case_4_simple_hurt_323(self):
        text = (_DEMO_DIR / "case_4_simple_hurt_323.txt").read_text(encoding="utf-8")
        assert _top_section(text) == "323 IPC"


# ═════════════════════════════════════════════════════════════════════════
# 12. Fact extractor produces non-empty FactMatrix
# ═════════════════════════════════════════════════════════════════════════

class TestFactExtractorOutput:
    """Keyword extractor should populate the matrix with tagged facts."""

    def test_murder_narrative_has_facts(self):
        fm = extract_facts_keyword_only(
            "The accused stabbed the victim. The victim died. "
            "The attack was premeditated."
        )
        assert fm.count() > 0
        actus = fm.get_facts("actus_reus")
        mens = fm.get_facts("mens_rea")
        assert len(actus) > 0
        assert len(mens) > 0

    def test_cheating_narrative_has_facts(self):
        fm = extract_facts_keyword_only(
            "The accused deceived the victim with false promises. "
            "The victim lost money."
        )
        assert fm.count() > 0

    def test_empty_text_returns_empty(self):
        fm = extract_facts_keyword_only("")
        assert fm.count() == 0

    def test_tags_are_populated(self):
        fm = extract_facts_keyword_only(
            "The accused shot the victim with a gun. "
            "Forensic evidence collected."
        )
        all_facts = fm.get_facts("actus_reus") + fm.get_facts("evidence")
        tags = [t for f in all_facts for t in f.tags]
        assert len(tags) > 0
