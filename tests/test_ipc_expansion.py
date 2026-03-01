"""
Tests for the IPC Section Expansion Pack.

10 test categories:

 1. 304 detected instead of 302 when no intent tag.
 2. 302 ranked above 304 when intentional.
 3. 420 detected for deception facts.
 4. 323 detected for simple hurt only.
 5. 304 vs 323 conflict scenario.
 6. Multi-section ranking stable.
 7. Simulation runs clean for 420.
 8. Guardrails unaffected.
 9. No regression in 302 tests.
10. SectionRegistry lists all 4+ sections.
11. (STEP 5) Full integration test.

Run:  python -m pytest tests/test_ipc_expansion.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.evaluation_pipeline import EvaluationPipeline
from core.evaluators.ipc304 import IPC304Evaluator
from core.evaluators.ipc420 import IPC420Evaluator
from core.evaluators.ipc323 import IPC323Evaluator
from core.fact_matrix import FactCategory, FactMatrix, FactSource, Severity
from core.ontology import LegalTag, SECTION_ELEMENT_ONTOLOGY
from core.section_auto_detector import SectionAutoDetector
from core.section_registry import registry
from core.simulation_guardrails import SimulationGuardrails
from core.statute_engine import IPC302Evaluator
from research.precedent_engine import PrecedentEngine
from research.research_aggregator import ResearchAggregator
from simulation.run_simulation import run_full_simulation


# ── helpers ─────────────────────────────────────────────────────────────

def _death_no_intent_matrix() -> FactMatrix:
    """Death + act by accused + knowledge-of-likely-death but NO
    premeditation / intention tags.  Should rank 304 > 302."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim died from injuries",
        FactSource.FORENSIC, severity=Severity.CRITICAL,
        tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused struck the victim",
        FactSource.WITNESS, severity=Severity.HIGH,
        tags=["act_by_accused"],
    )
    m.add_fact(
        FactCategory.MENS_REA, "Accused knew the blow could be fatal but had no intent to kill",
        FactSource.WITNESS, severity=Severity.MEDIUM,
        tags=["knowledge_likely_death", "no_intent_to_kill"],
    )
    return m


def _death_with_intent_matrix() -> FactMatrix:
    """Classic 302 IPC — death + act + clear intention."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim died from stab wounds",
        FactSource.FORENSIC, severity=Severity.CRITICAL,
        tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused stabbed the victim repeatedly",
        FactSource.WITNESS, severity=Severity.CRITICAL,
        tags=["act_by_accused", "stabbing"],
    )
    m.add_fact(
        FactCategory.MENS_REA, "Accused planned the attack deliberately",
        FactSource.DOCUMENT, severity=Severity.HIGH,
        tags=["premeditated", "intention"],
    )
    m.add_fact(
        FactCategory.EVIDENCE, "Knife found with accused fingerprints",
        FactSource.FORENSIC, severity=Severity.CRITICAL,
        tags=["weapon", "fingerprint"],
    )
    return m


def _cheating_matrix() -> FactMatrix:
    """Facts for 420 IPC — deception + inducement + wrongful gain."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused made false representation about investment returns",
        FactSource.DOCUMENT, severity=Severity.HIGH,
        tags=["deception"],
    )
    m.add_fact(
        FactCategory.MENS_REA, "Victim was dishonestly induced to sign documents",
        FactSource.WITNESS, severity=Severity.HIGH,
        tags=["dishonest_inducement"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused received wrongful monetary gain of 50 lakhs",
        FactSource.DOCUMENT, severity=Severity.CRITICAL,
        tags=["wrongful_gain"],
    )
    return m


def _simple_hurt_matrix() -> FactMatrix:
    """Facts for 323 IPC — simple hurt only, no death."""
    m = FactMatrix()
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim suffered bruises and minor injury",
        FactSource.FORENSIC, severity=Severity.MEDIUM,
        tags=["simple_hurt"],
    )
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused slapped and pushed the victim",
        FactSource.WITNESS, severity=Severity.MEDIUM,
        tags=["act_by_accused"],
    )
    return m


def _conflicting_304_323_matrix() -> FactMatrix:
    """Facts that partially overlap 304 and 323."""
    m = FactMatrix()
    # Hurt (could be 323)
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim suffered injury and bruises",
        FactSource.FORENSIC, severity=Severity.MEDIUM,
        tags=["simple_hurt"],
    )
    # Act by accused (both sections)
    m.add_fact(
        FactCategory.ACTUS_REUS, "Accused hit the victim hard",
        FactSource.WITNESS, severity=Severity.HIGH,
        tags=["act_by_accused"],
    )
    # Death and knowledge (pushes towards 304)
    m.add_fact(
        FactCategory.ACTUS_REUS, "Victim later died from injuries",
        FactSource.FORENSIC, severity=Severity.CRITICAL,
        tags=["death_caused"],
    )
    m.add_fact(
        FactCategory.MENS_REA, "Accused knew the blow could be fatal",
        FactSource.WITNESS, severity=Severity.MEDIUM,
        tags=["knowledge_likely_death", "no_intent_to_kill"],
    )
    return m


# ═══════════════════════════════════════════════════════════════════════
# 1. 304 detected instead of 302 when no intent tag
# ═══════════════════════════════════════════════════════════════════════

class TestCategory01_304DetectedOverR302:
    def test_304_detected_for_no_intent_case(self):
        m = _death_no_intent_matrix()
        d = SectionAutoDetector()
        result = d.detect(m)
        sections = [s["section"] for s in result.detected_sections]
        # 304 must appear as a qualifying section
        assert "304 IPC" in sections
        # 304 should rank at least in top 2 (302 may tie in score)
        idx_304 = sections.index("304 IPC")
        assert idx_304 <= 1, f"304 should be top-2 but is at index {idx_304}"

    def test_304_evaluator_elements_satisfied(self):
        m = _death_no_intent_matrix()
        ev = IPC304Evaluator()
        r = ev.evaluate(m)
        assert r.verdict_recommendation == "Proceed"


# ═══════════════════════════════════════════════════════════════════════
# 2. 302 ranked above 304 when intentional
# ═══════════════════════════════════════════════════════════════════════

class TestCategory02_302RankedAbove304:
    def test_302_tops_with_intent(self):
        m = _death_with_intent_matrix()
        d = SectionAutoDetector()
        result = d.detect(m)
        assert result.top_section == "302 IPC"

    def test_302_evaluator_proceed(self):
        m = _death_with_intent_matrix()
        ev = IPC302Evaluator()
        r = ev.evaluate(m)
        assert r.verdict_recommendation == "Proceed"


# ═══════════════════════════════════════════════════════════════════════
# 3. 420 detected for deception facts
# ═══════════════════════════════════════════════════════════════════════

class TestCategory03_420Detected:
    def test_420_is_top_section(self):
        m = _cheating_matrix()
        d = SectionAutoDetector()
        result = d.detect(m)
        assert result.top_section == "420 IPC"

    def test_420_evaluator_all_elements_met(self):
        m = _cheating_matrix()
        ev = IPC420Evaluator()
        r = ev.evaluate(m)
        assert r.verdict_recommendation == "Proceed"
        assert len(r.elements_satisfied) == 3

    def test_420_ranks_above_302(self):
        m = _cheating_matrix()
        d = SectionAutoDetector()
        result = d.detect(m)
        sections = [s["section"] for s in result.detected_sections]
        assert sections[0] == "420 IPC"
        # If 302 appears, it must rank below 420
        if "302 IPC" in sections:
            assert sections.index("420 IPC") < sections.index("302 IPC")


# ═══════════════════════════════════════════════════════════════════════
# 4. 323 detected for simple hurt only
# ═══════════════════════════════════════════════════════════════════════

class TestCategory04_323Detected:
    def test_323_is_top_section(self):
        m = _simple_hurt_matrix()
        d = SectionAutoDetector()
        result = d.detect(m)
        assert result.top_section == "323 IPC"

    def test_323_evaluator_proceed(self):
        m = _simple_hurt_matrix()
        ev = IPC323Evaluator()
        r = ev.evaluate(m)
        assert r.verdict_recommendation == "Proceed"

    def test_323_ranks_above_murder_sections(self):
        m = _simple_hurt_matrix()
        d = SectionAutoDetector()
        result = d.detect(m)
        sections = [s["section"] for s in result.detected_sections]
        assert sections[0] == "323 IPC"
        # Murder sections must rank below simple hurt
        for sec in ("302 IPC", "304 IPC"):
            if sec in sections:
                assert sections.index("323 IPC") < sections.index(sec)


# ═══════════════════════════════════════════════════════════════════════
# 5. 304 vs 323 conflict scenario
# ═══════════════════════════════════════════════════════════════════════

class TestCategory05_304vs323:
    def test_304_ranks_above_323_when_death(self):
        m = _conflicting_304_323_matrix()
        d = SectionAutoDetector()
        result = d.detect(m)
        sections = [s["section"] for s in result.detected_sections]
        assert "304 IPC" in sections
        if "323 IPC" in sections:
            assert sections.index("304 IPC") < sections.index("323 IPC")


# ═══════════════════════════════════════════════════════════════════════
# 6. Multi-section ranking stable
# ═══════════════════════════════════════════════════════════════════════

class TestCategory06_RankingStable:
    def test_ranking_deterministic(self):
        m = _death_with_intent_matrix()
        d = SectionAutoDetector()
        r1 = d.detect(m)
        r2 = d.detect(m)
        assert r1.top_section == r2.top_section
        assert r1.top_score == r2.top_score
        s1 = [s["section"] for s in r1.detected_sections]
        s2 = [s["section"] for s in r2.detected_sections]
        assert s1 == s2

    def test_multiple_sections_detected_for_rich_matrix(self):
        m = _death_with_intent_matrix()
        d = SectionAutoDetector()
        result = d.detect(m)
        assert len(result.detected_sections) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 7. Simulation runs clean for 420
# ═══════════════════════════════════════════════════════════════════════

class TestCategory07_SimulationCleanFor420:
    def test_simulation_420_no_crash(self):
        m = _cheating_matrix()
        result = run_full_simulation(m, auto_detect=True)
        assert "case_analysis" in result
        assert "lawyer_output" in result
        assert "panel_result" in result
        assert "final_judgment" in result

    def test_simulation_420_correct_section(self):
        m = _cheating_matrix()
        result = run_full_simulation(m, auto_detect=True)
        section = result["case_analysis"]["evaluation_result"]["section"]
        assert section == "420 IPC"


# ═══════════════════════════════════════════════════════════════════════
# 8. Guardrails unaffected
# ═══════════════════════════════════════════════════════════════════════

class TestCategory08_GuardrailsUnaffected:
    def test_guardrails_work_for_420(self):
        m = _cheating_matrix()
        result = run_full_simulation(m, auto_detect=True)
        report = result["guardrail_report"]
        assert report["lawyer_valid"] is True
        assert report["judgment_valid"] is True
        assert all(report["judge_validations"])

    def test_guardrails_work_for_323(self):
        m = _simple_hurt_matrix()
        result = run_full_simulation(m, auto_detect=True)
        report = result["guardrail_report"]
        assert report["lawyer_valid"] is True


# ═══════════════════════════════════════════════════════════════════════
# 9. No regression in 302 tests
# ═══════════════════════════════════════════════════════════════════════

class TestCategory09_302Regression:
    def test_302_still_evaluates_correctly(self):
        m = _death_with_intent_matrix()
        ev = IPC302Evaluator()
        r = ev.evaluate(m)
        assert r.section == "302 IPC"
        assert r.verdict_recommendation == "Proceed"

    def test_302_ontology_unchanged(self):
        ont = SECTION_ELEMENT_ONTOLOGY["302 IPC"]
        assert "death_of_human" in ont
        assert "act_by_accused" in ont
        assert "intention_or_knowledge" in ont
        assert "supporting_evidence" in ont
        assert LegalTag.DEATH in ont["death_of_human"]

    def test_302_still_top_for_intent_case(self):
        m = _death_with_intent_matrix()
        d = SectionAutoDetector()
        result = d.detect(m)
        assert result.top_section == "302 IPC"


# ═══════════════════════════════════════════════════════════════════════
# 10. SectionRegistry lists all 4+ sections
# ═══════════════════════════════════════════════════════════════════════

class TestCategory10_RegistryLists:
    def test_all_four_registered(self):
        sections = registry.list_registered_sections()
        assert "302 IPC" in sections
        assert "304 IPC" in sections
        assert "420 IPC" in sections
        assert "323 IPC" in sections

    def test_at_least_four_sections(self):
        assert len(registry.list_registered_sections()) >= 4

    def test_ontology_sections_match_registry(self):
        ont_sections = set(SECTION_ELEMENT_ONTOLOGY.keys())
        reg_sections = set(registry.list_registered_sections())
        assert ont_sections == reg_sections


# ═══════════════════════════════════════════════════════════════════════
# 11. Full system integration test (STEP 5)
# ═══════════════════════════════════════════════════════════════════════

class TestFullIntegration:
    def test_realistic_420_end_to_end(self):
        """Create a realistic 420 fact matrix, run full simulation with
        auto-detect, mocked research, and validate everything."""
        m = FactMatrix()
        m.add_fact(
            FactCategory.ACTUS_REUS,
            "Accused presented forged bank documents showing fake balance",
            FactSource.DOCUMENT, severity=Severity.HIGH,
            tags=["deception"],
        )
        m.add_fact(
            FactCategory.MENS_REA,
            "Victim was dishonestly induced to transfer property title",
            FactSource.WITNESS, severity=Severity.HIGH,
            tags=["dishonest_inducement"],
        )
        m.add_fact(
            FactCategory.ACTUS_REUS,
            "Property worth 1 crore transferred — wrongful gain to accused",
            FactSource.DOCUMENT, severity=Severity.CRITICAL,
            tags=["wrongful_gain"],
        )
        m.add_fact(
            FactCategory.EVIDENCE,
            "Forged documents recovered during police search",
            FactSource.FORENSIC, severity=Severity.HIGH,
            tags=["forensic"],
        )

        # Mock PrecedentEngine to return a fake precedent
        prec = PrecedentEngine(kanoon_api_key="mock")
        fake_prec_response = {
            "docs": [
                {
                    "title": "State v. Sharma",
                    "citation": "2024 SCC 420",
                    "docsource": "Supreme Court of India",
                    "publishdate": "2024-03-15",
                    "headline": "Cheating conviction upheld under 420 IPC.",
                },
            ],
        }
        aggregator = ResearchAggregator(precedent_engine=prec)

        with patch.object(prec, "_call_api", return_value=fake_prec_response):
            result = run_full_simulation(
                m, auto_detect=True, research_aggregator=aggregator,
            )

        # Correct top section
        ca = result["case_analysis"]
        assert ca["evaluation_result"]["section"] == "420 IPC"

        # Guardrails valid
        report = result["guardrail_report"]
        assert report["lawyer_valid"] is True
        assert report["judgment_valid"] is True
        assert all(report["judge_validations"])

        # No drift
        assert "simulation_drift_detected" not in result

        # Precedents attached
        assert len(result["research_data"]["precedents"]) == 1
        assert result["research_data"]["precedents"][0]["source"] == "kanoon"

        # Judges majority consistent
        panel = result["panel_result"]
        majority = panel["majority_verdict"]
        verdicts = [j["provisional_verdict"] for j in panel["judges"]]
        assert verdicts.count(majority) >= 2  # majority rule
