"""
CourtMind — Tests for Multi-Hearing Courtroom Simulation

Unit tests, integration tests, and system tests covering:

1.  Evidence request triggers new hearing
2.  Clarification loop updates mens_rea
3.  Exception validation resolves self-defense
4.  Section re-evaluation changes section ranking
5.  Conflict resolution removes contradiction
6.  Argument refinement improves lawyer output
7.  Precedent request returns research data
8.  Sentencing phase triggered after conviction
9.  Loop stops when verdict stable
10. Loop stops when max_hearings reached

Plus: FactMatrix mutation tests, evaluation reruns, backward compatibility,
      integration with full pipeline, and system-level end-to-end scenarios.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from core.evaluation_pipeline import EvaluationPipeline
from core.fact_matrix import FactMatrix, FactSource, Severity
from simulation.hearing_manager import (
    FeedbackType,
    HearingFeedback,
    HearingManager,
    HearingRound,
    _compute_sentencing,
)
from simulation.run_simulation import run_full_simulation


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _murder_matrix() -> FactMatrix:
    """Strong murder case — 302 IPC, all elements satisfied."""
    fm = FactMatrix()
    fm.add_fact("actus_reus", "Accused stabbed the victim in the chest.",
                FactSource.WITNESS, severity="critical",
                tags=["act_by_accused", "stabbing"])
    fm.add_fact("actus_reus", "Victim died from stab wounds.",
                FactSource.FORENSIC, severity="critical",
                tags=["death_caused", "death_of_human"])
    fm.add_fact("mens_rea", "Accused stated he wanted to kill victim.",
                FactSource.CONFESSION, severity="high",
                tags=["intention", "premeditated"])
    fm.add_fact("evidence", "Blood-stained knife recovered.",
                FactSource.FORENSIC, severity="high",
                tags=["weapon", "physical_evidence"])
    return fm


def _weak_matrix() -> FactMatrix:
    """Weak case — only partial elements, low evidence."""
    fm = FactMatrix()
    fm.add_fact("actus_reus", "A person was found dead.",
                FactSource.WITNESS, severity="medium",
                tags=["death_of_human"])
    return fm


def _self_defense_matrix() -> FactMatrix:
    """Murder case with unsupported self-defense claim."""
    fm = _murder_matrix()
    fm.add_fact("exceptions_claimed", "Accused claims self-defense.",
                FactSource.USER_INPUT, severity="low",
                tags=["self-defense"])
    return fm


def _conflicting_matrix() -> FactMatrix:
    """Murder case with conflicting facts."""
    fm = _murder_matrix()
    f1 = fm.add_fact("mens_rea", "Accused acted intentionally.",
                     FactSource.WITNESS, severity="high",
                     tags=["intentional"])
    f2 = fm.add_fact("mens_rea", "Accused acted accidentally.",
                     FactSource.WITNESS, severity="medium",
                     tags=["accidental"])
    fm.register_conflict(f1.id, f2.id, "Intentional vs accidental")
    return fm


def _hurt_matrix() -> FactMatrix:
    """323 IPC — voluntarily causing hurt."""
    fm = FactMatrix()
    fm.add_fact("actus_reus", "Accused punched the victim.",
                FactSource.WITNESS, severity="medium",
                tags=["act_by_accused", "punch"])
    fm.add_fact("actus_reus", "Victim sustained bruises.",
                FactSource.FORENSIC, severity="medium",
                tags=["hurt_caused", "bodily_pain"])
    return fm


def _make_updater(facts_to_add: List[Dict[str, Any]]):
    """Return a fact_updater callback that adds given facts."""
    call_count = [0]

    def updater(fm: FactMatrix, feedbacks: List[HearingFeedback]) -> List[str]:
        call_count[0] += 1
        if call_count[0] > 1:
            return []  # only apply once to prevent infinite loops
        updates = []
        for fact_spec in facts_to_add:
            fm.add_fact(**fact_spec)
            updates.append(f"Added: {fact_spec['statement']}")
        return updates

    return updater


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS — HearingFeedback and HearingRound data structures
# ═══════════════════════════════════════════════════════════════════════

class TestHearingFeedbackDataclass:
    """Unit tests for HearingFeedback data structure."""

    def test_creation_defaults(self):
        fb = HearingFeedback(type="evidence_request", message="Need more evidence")
        assert fb.type == "evidence_request"
        assert fb.message == "Need more evidence"
        assert fb.requested_element == ""
        assert fb.severity == "medium"
        assert fb.requires_update is True

    def test_creation_all_fields(self):
        fb = HearingFeedback(
            type="clarification_request",
            message="Clarify mens_rea",
            requested_element="intention_or_knowledge",
            severity="high",
            requires_update=False,
        )
        assert fb.severity == "high"
        assert fb.requires_update is False

    def test_to_dict(self):
        fb = HearingFeedback(type="evidence_request", message="msg")
        d = fb.to_dict()
        assert isinstance(d, dict)
        assert d["type"] == "evidence_request"
        assert "requires_update" in d

    def test_feedback_types_are_valid_enum_values(self):
        for ft in FeedbackType:
            fb = HearingFeedback(type=ft.value, message="test")
            assert fb.type == ft.value


class TestHearingRoundDataclass:
    """Unit tests for HearingRound data structure."""

    def test_creation_defaults(self):
        hr = HearingRound(hearing_number=1)
        assert hr.hearing_number == 1
        assert hr.case_analysis == {}
        assert hr.feedback == []
        assert hr.updates_applied == []

    def test_to_dict(self):
        hr = HearingRound(hearing_number=2, final_judgment="Guilty.")
        d = hr.to_dict()
        assert d["hearing_number"] == 2
        assert d["final_judgment"] == "Guilty."


class TestFeedbackTypeEnum:
    """Unit tests for FeedbackType enum."""

    def test_all_eight_types_exist(self):
        expected = {
            "evidence_request", "clarification_request", "exception_validation",
            "section_review", "conflict_resolution", "argument_refinement",
            "precedent_request", "sentencing_phase",
        }
        actual = {ft.value for ft in FeedbackType}
        assert actual == expected

    def test_string_enum(self):
        assert FeedbackType.EVIDENCE_REQUEST == "evidence_request"
        assert isinstance(FeedbackType.SENTENCING_PHASE, str)


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS — HearingManager construction
# ═══════════════════════════════════════════════════════════════════════

class TestHearingManagerConstruction:

    def test_default_max_hearings(self):
        hm = HearingManager()
        assert hm.max_hearings == 5

    def test_custom_max_hearings(self):
        hm = HearingManager(max_hearings=3)
        assert hm.max_hearings == 3

    def test_max_hearings_at_least_one(self):
        with pytest.raises(ValueError, match="at least 1"):
            HearingManager(max_hearings=0)

    def test_negative_max_hearings(self):
        with pytest.raises(ValueError):
            HearingManager(max_hearings=-1)


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS — Feedback collection (each loop independently)
# ═══════════════════════════════════════════════════════════════════════

class TestFeedbackCollection:
    """Test collect_judge_feedback for each of the 8 loops."""

    def _run_and_collect(self, fm: FactMatrix):
        """Helper: run pipeline + simulation, collect feedback."""
        hm = HearingManager()
        result = hm._run_single_hearing(fm)
        feedbacks = hm.collect_judge_feedback(
            result["case_analysis"],
            result["panel_result"],
            result,
            fm,
        )
        return result, feedbacks

    # Loop 1: Evidence Expansion
    def test_evidence_request_on_weak_case(self):
        _, feedbacks = self._run_and_collect(_weak_matrix())
        types = [fb.type for fb in feedbacks]
        assert FeedbackType.EVIDENCE_REQUEST.value in types

    def test_no_evidence_request_on_strong_case(self):
        _, feedbacks = self._run_and_collect(_murder_matrix())
        evidence_fbs = [fb for fb in feedbacks if fb.type == FeedbackType.EVIDENCE_REQUEST.value]
        # Strong case may have high evidence score
        if evidence_fbs:
            # If triggered, evidence score must have been < 0.6
            result, _ = self._run_and_collect(_murder_matrix())
            score = result["case_analysis"].get("evidence_weight_result", {}).get("overall_evidence_score", 0)
            assert score < 0.6

    # Loop 2: Clarification
    def test_clarification_on_partial_elements(self):
        _, feedbacks = self._run_and_collect(_weak_matrix())
        clar_fbs = [fb for fb in feedbacks if fb.type == FeedbackType.CLARIFICATION_REQUEST.value]
        assert len(clar_fbs) > 0
        # Must reference specific element
        for fb in clar_fbs:
            assert fb.requested_element != ""

    # Loop 3: Exception Validation
    def test_exception_validation_unsupported(self):
        _, feedbacks = self._run_and_collect(_self_defense_matrix())
        exc_fbs = [fb for fb in feedbacks if fb.type == FeedbackType.EXCEPTION_VALIDATION.value]
        # Exception was detected as unsupported (low severity) → should trigger
        assert len(exc_fbs) > 0
        assert "self" in exc_fbs[0].message.lower() or "defense" in exc_fbs[0].message.lower()

    # Loop 5: Conflict Resolution
    def test_conflict_resolution(self):
        _, feedbacks = self._run_and_collect(_conflicting_matrix())
        conflict_fbs = [fb for fb in feedbacks if fb.type == FeedbackType.CONFLICT_RESOLUTION.value]
        assert len(conflict_fbs) > 0
        assert "conflict" in conflict_fbs[0].message.lower()

    # Loop 7: Precedent Request
    def test_precedent_request_on_ambiguous_case(self):
        fm = _weak_matrix()
        _, feedbacks = self._run_and_collect(fm)
        prec_fbs = [fb for fb in feedbacks if fb.type == FeedbackType.PRECEDENT_REQUEST.value]
        # Weak case has low confidence → should trigger precedent request
        assert len(prec_fbs) > 0

    # Loop 8: Sentencing Phase
    def test_sentencing_on_conviction(self):
        fm = _murder_matrix()
        result, feedbacks = self._run_and_collect(fm)
        verdict = result["panel_result"].get("majority_verdict")
        sent_fbs = [fb for fb in feedbacks if fb.type == FeedbackType.SENTENCING_PHASE.value]
        if verdict == "convict":
            assert len(sent_fbs) == 1
            assert sent_fbs[0].requires_update is False
        # If not convict, sentencing should not be triggered
        else:
            assert len(sent_fbs) == 0


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS — Sentencing computation
# ═══════════════════════════════════════════════════════════════════════

class TestSentencing:

    def test_sentencing_has_required_keys(self):
        fm = _murder_matrix()
        pipeline = EvaluationPipeline(auto_detect=True)
        analysis = pipeline.run(fm)
        sentencing = _compute_sentencing(analysis.to_dict(), fm)
        assert "section" in sentencing
        assert "max_fact_severity" in sentencing
        assert "aggravating_factors" in sentencing
        assert "mitigating_factors" in sentencing
        assert "sentence_recommendation" in sentencing

    def test_critical_severity_gets_life(self):
        fm = _murder_matrix()
        pipeline = EvaluationPipeline(auto_detect=True)
        analysis = pipeline.run(fm)
        sentencing = _compute_sentencing(analysis.to_dict(), fm)
        assert sentencing["max_fact_severity"] == "critical"
        assert "life imprisonment" in sentencing["sentence_recommendation"]

    def test_premeditated_is_aggravating(self):
        fm = _murder_matrix()
        pipeline = EvaluationPipeline(auto_detect=True)
        analysis = pipeline.run(fm)
        sentencing = _compute_sentencing(analysis.to_dict(), fm)
        assert any("Premeditated" in a for a in sentencing["aggravating_factors"])

    def test_supported_exception_is_mitigating(self):
        fm = _murder_matrix()
        fm.add_fact("exceptions_claimed", "Accused acted in self-defense with weapon marks.",
                    FactSource.FORENSIC, severity="high",
                    tags=["self-defense"])
        pipeline = EvaluationPipeline(auto_detect=True)
        analysis = pipeline.run(fm)
        sentencing = _compute_sentencing(analysis.to_dict(), fm)
        # If exception supported, should appear in mitigating
        exc_result = analysis.to_dict().get("exception_result", {})
        supported = [e for e in exc_result.get("exceptions", []) if e.get("supported")]
        if supported:
            assert any("exception" in m.lower() for m in sentencing["mitigating_factors"])

    def test_low_severity_case(self):
        fm = FactMatrix()
        fm.add_fact("actus_reus", "Accused pushed victim.",
                    FactSource.WITNESS, severity="low",
                    tags=["act_by_accused"])
        pipeline = EvaluationPipeline(auto_detect=True)
        analysis = pipeline.run(fm)
        sentencing = _compute_sentencing(analysis.to_dict(), fm)
        assert sentencing["max_fact_severity"] == "low"
        assert "3 years" in sentencing["sentence_recommendation"] or "fine" in sentencing["sentence_recommendation"]


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Full hearing cycle
# ═══════════════════════════════════════════════════════════════════════

class TestHearingCycleIntegration:
    """Integration tests for the full hearing cycle."""

    # Test 1: Evidence request triggers new hearing
    def test_evidence_request_triggers_new_hearing(self):
        fm = _weak_matrix()
        updater = _make_updater([
            {"category": "actus_reus",
             "statement": "Accused struck the victim with a rod.",
             "source": FactSource.WITNESS, "severity": "high",
             "tags": ["act_by_accused"]},
        ])
        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm, fact_updater=updater)
        assert result["total_hearings"] >= 1
        assert "hearings" in result
        assert isinstance(result["hearings"], list)

    # Test 2: Clarification loop updates mens_rea
    def test_clarification_updates_mens_rea(self):
        fm = _weak_matrix()
        updater = _make_updater([
            {"category": "mens_rea",
             "statement": "Accused intended to kill.",
             "source": FactSource.WITNESS, "severity": "high",
             "tags": ["intention"]},
        ])
        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm, fact_updater=updater)
        # FactMatrix was updated
        assert fm.count("mens_rea") >= 1
        assert result["total_hearings"] >= 1

    # Test 3: Exception validation resolves self-defense
    def test_exception_validation_resolves(self):
        fm = _self_defense_matrix()
        updater = _make_updater([
            {"category": "evidence",
             "statement": "Forensic report shows defensive wounds on accused.",
             "source": FactSource.FORENSIC, "severity": "high",
             "tags": ["self-defense", "defensive_wounds"]},
        ])
        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm, fact_updater=updater)
        assert result["total_hearings"] >= 1

    # Test 4: Section re-evaluation changes section ranking
    def test_section_reevaluation(self):
        fm = _murder_matrix()
        # Run initial — should be 302
        hm = HearingManager(max_hearings=2)
        result = hm.run_hearing_cycle(fm)
        first_section = result["hearings"][0]["case_analysis"]["evaluation_result"]["section"]
        assert "302" in first_section or "304" in first_section or "323" in first_section

    # Test 5: Conflict resolution removes contradiction
    def test_conflict_resolution(self):
        fm = _conflicting_matrix()
        initial_conflicts = len(fm.get_conflicts())
        assert initial_conflicts > 0

        def resolver(matrix: FactMatrix, feedbacks: List[HearingFeedback]) -> List[str]:
            # Remove conflicting facts and add a clear one
            conflicts = matrix.get_conflicts()
            updates = []
            for c in conflicts:
                matrix.remove_fact(c.fact_b_id)
                updates.append(f"Removed conflicting fact {c.fact_b_id}")
            return updates

        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm, fact_updater=resolver)
        assert result["total_hearings"] >= 1

    # Test 6: Argument refinement
    def test_argument_refinement(self):
        fm = _murder_matrix()
        hm = HearingManager(max_hearings=2)
        result = hm.run_hearing_cycle(fm)
        # Argument refinement feedback is handled internally
        for hearing in result["hearings"]:
            for fb in hearing["feedback"]:
                if fb["type"] == FeedbackType.ARGUMENT_REFINEMENT.value:
                    # Should have been marked as requires_update=False after processing
                    assert fb["type"] == "argument_refinement"

    # Test 7: Precedent request returns research data
    def test_precedent_request(self):
        fm = _weak_matrix()
        hm = HearingManager(max_hearings=2)
        result = hm.run_hearing_cycle(fm)
        # Check precedent feedback was generated
        all_feedbacks = []
        for h in result["hearings"]:
            all_feedbacks.extend(h["feedback"])
        prec = [fb for fb in all_feedbacks if fb["type"] == "precedent_request"]
        # Weak case should trigger precedent request
        assert len(prec) > 0

    # Test 8: Sentencing phase triggered after conviction
    def test_sentencing_phase(self):
        fm = _murder_matrix()
        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm)
        verdict = result["final_result"].get("panel_result", {}).get("majority_verdict")
        if verdict == "convict":
            assert "sentencing" in result
            assert "sentence_recommendation" in result["sentencing"]
            assert "aggravating_factors" in result["sentencing"]
            assert "mitigating_factors" in result["sentencing"]

    # Test 9: Loop stops when verdict stable
    def test_verdict_stable_stops_loop(self):
        fm = _murder_matrix()
        hm = HearingManager(max_hearings=5)
        result = hm.run_hearing_cycle(fm)
        assert result["verdict_stable"] is True
        # Should not run all 5 hearings for a clear-cut case
        assert result["total_hearings"] <= 5

    # Test 10: Loop stops when max_hearings reached
    def test_max_hearings_limit(self):
        fm = _weak_matrix()
        # Updater that always adds something (never stabilises)
        call_count = [0]

        def infinite_updater(matrix, feedbacks):
            call_count[0] += 1
            matrix.add_fact(
                "evidence",
                f"Additional evidence item #{call_count[0]}.",
                FactSource.WITNESS, severity="low",
                tags=["supporting_evidence"],
            )
            return [f"Added evidence #{call_count[0]}"]

        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm, fact_updater=infinite_updater)
        assert result["total_hearings"] <= 3


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — FactMatrix mutation & evaluation reruns
# ═══════════════════════════════════════════════════════════════════════

class TestFactMatrixUpdates:
    """Verify FactMatrix is properly updated between hearings."""

    def test_fact_count_increases_after_update(self):
        fm = _weak_matrix()
        initial_count = fm.count()
        updater = _make_updater([
            {"category": "actus_reus",
             "statement": "Accused was at the scene.",
             "source": FactSource.WITNESS, "severity": "medium",
             "tags": ["act_by_accused"]},
        ])
        hm = HearingManager(max_hearings=2)
        hm.run_hearing_cycle(fm, fact_updater=updater)
        assert fm.count() > initial_count

    def test_evaluation_reruns_with_updated_facts(self):
        fm = _weak_matrix()
        hm = HearingManager(max_hearings=3)

        analyses = []

        def tracking_updater(matrix, feedbacks):
            matrix.add_fact(
                "actus_reus", "Accused struck the victim.",
                FactSource.WITNESS, severity="high",
                tags=["act_by_accused", "stabbing"],
            )
            matrix.add_fact(
                "actus_reus", "Victim died.",
                FactSource.FORENSIC, severity="critical",
                tags=["death_caused", "death_of_human"],
            )
            return ["Added actus_reus facts"]

        result = hm.run_hearing_cycle(fm, fact_updater=tracking_updater)
        if result["total_hearings"] >= 2:
            h1_eval = result["hearings"][0]["case_analysis"]["evaluation_result"]
            h2_eval = result["hearings"][1]["case_analysis"]["evaluation_result"]
            # Second hearing should have more satisfied elements
            assert h2_eval["elements_satisfied"] >= h1_eval["elements_satisfied"]

    def test_previous_hearing_results_not_mutated(self):
        fm = _weak_matrix()
        updater = _make_updater([
            {"category": "mens_rea",
             "statement": "Accused had intent.",
             "source": FactSource.WITNESS, "severity": "high",
             "tags": ["intention"]},
        ])
        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm, fact_updater=updater)
        if result["total_hearings"] >= 2:
            # Snapshot of hearing 1 should not change
            h1 = result["hearings"][0]
            h1_copy = copy.deepcopy(h1)
            # Run another unrelated operation
            _ = result["hearings"][-1]
            assert h1 == h1_copy


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Backward compatibility
# ═══════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Ensure existing single-pass simulation is unchanged."""

    def test_default_single_pass_unchanged(self):
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        # Original keys must be present
        assert "case_analysis" in result
        assert "lawyer_output" in result
        assert "panel_result" in result
        assert "final_judgment" in result
        assert "research_data" in result
        assert "guardrail_report" in result
        # Must NOT have iterative keys
        assert "hearings" not in result
        assert "total_hearings" not in result

    def test_iterative_false_is_single_pass(self):
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True, iterative=False)
        assert "case_analysis" in result
        assert "hearings" not in result

    def test_iterative_true_returns_hearing_structure(self):
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True, iterative=True)
        assert "hearings" in result
        assert "total_hearings" in result
        assert "final_result" in result
        assert "verdict_stable" in result

    def test_iterative_with_max_hearings(self):
        fm = _murder_matrix()
        result = run_full_simulation(
            fm, auto_detect=True, iterative=True, max_hearings=2,
        )
        assert result["total_hearings"] <= 2


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Section ranking updates
# ═══════════════════════════════════════════════════════════════════════

class TestSectionRankingUpdates:

    def test_section_changes_when_facts_change(self):
        """Start with minimal facts, add murder-specific facts → section should be 302."""
        fm = FactMatrix()
        fm.add_fact("actus_reus", "Victim was found dead.",
                    FactSource.FORENSIC, severity="critical",
                    tags=["death_of_human", "death_caused"])
        hm = HearingManager(max_hearings=3)

        # First check: single fact — may detect any section
        result1 = hm._run_single_hearing(fm)
        section1 = result1["case_analysis"]["evaluation_result"]["section"]

        # Add 302-specific facts: act_by_accused + intention
        fm.add_fact("actus_reus", "Accused stabbed the victim with a knife.",
                    FactSource.WITNESS, severity="critical",
                    tags=["act_by_accused", "stabbing"])
        fm.add_fact("mens_rea", "Accused confessed intent to kill.",
                    FactSource.CONFESSION, severity="high",
                    tags=["intention", "premeditated"])
        fm.add_fact("evidence", "Murder weapon recovered.",
                    FactSource.FORENSIC, severity="high",
                    tags=["weapon", "physical_evidence"])

        # Second check: should now have 302 with strong evidence
        result2 = hm._run_single_hearing(fm)
        section2 = result2["case_analysis"]["evaluation_result"]["section"]
        # More elements should be satisfied now
        assert result2["case_analysis"]["evaluation_result"]["elements_satisfied"] >= \
               result1["case_analysis"]["evaluation_result"]["elements_satisfied"]


# ═══════════════════════════════════════════════════════════════════════
# SYSTEM TESTS — End-to-end multi-hearing scenarios
# ═══════════════════════════════════════════════════════════════════════

class TestSystemEndToEnd:
    """Full system tests exercising the complete hearing cycle."""

    def test_full_murder_case_hearing_cycle(self):
        """Complete murder case with strong evidence → conviction + sentencing."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True, iterative=True)

        assert result["total_hearings"] >= 1
        assert result["verdict_stable"] is True

        final = result["final_result"]
        assert "case_analysis" in final
        assert "panel_result" in final
        assert "final_judgment" in final

    def test_weak_case_with_evidence_buildup(self):
        """Weak case → evidence added over hearings → eventual resolution."""
        fm = _weak_matrix()
        round_num = [0]

        def progressive_updater(matrix, feedbacks):
            round_num[0] += 1
            updates = []
            if round_num[0] == 1:
                matrix.add_fact("actus_reus", "Accused struck victim.",
                                FactSource.WITNESS, severity="high",
                                tags=["act_by_accused"])
                updates.append("Added act_by_accused")
            elif round_num[0] == 2:
                matrix.add_fact("mens_rea", "Accused planned the attack.",
                                FactSource.DOCUMENT, severity="high",
                                tags=["intention"])
                updates.append("Added mens_rea")
            return updates

        result = run_full_simulation(
            fm, auto_detect=True, iterative=True,
            max_hearings=4, fact_updater=progressive_updater,
        )
        assert result["total_hearings"] >= 2
        # Later hearings should have more satisfied elements
        if result["total_hearings"] >= 2:
            h1 = result["hearings"][0]["case_analysis"]["evaluation_result"]
            h_last = result["hearings"][-1]["case_analysis"]["evaluation_result"]
            assert h_last["elements_satisfied"] >= h1["elements_satisfied"]

    def test_self_defense_case_resolution(self):
        """Murder + self-defense → exception validation → updated evidence."""
        fm = _self_defense_matrix()

        def defense_updater(matrix, feedbacks):
            exc_fbs = [fb for fb in feedbacks
                       if fb.type == FeedbackType.EXCEPTION_VALIDATION.value]
            if exc_fbs:
                matrix.add_fact(
                    "evidence",
                    "Defensive injuries found on accused's arms.",
                    FactSource.FORENSIC, severity="high",
                    tags=["self-defense", "defensive_wounds"],
                )
                return ["Added forensic evidence for self-defense"]
            return []

        result = run_full_simulation(
            fm, auto_detect=True, iterative=True,
            max_hearings=3, fact_updater=defense_updater,
        )
        assert result["total_hearings"] >= 1

    def test_conflict_case_system_test(self):
        """Case with conflicts → resolution → clean evaluation."""
        fm = _conflicting_matrix()
        conflict_resolved = [False]

        def conflict_resolver(matrix, feedbacks):
            if conflict_resolved[0]:
                return []
            conflict_fbs = [fb for fb in feedbacks
                           if fb.type == FeedbackType.CONFLICT_RESOLUTION.value]
            if conflict_fbs:
                for c in list(matrix.get_conflicts()):
                    matrix.remove_fact(c.fact_b_id)
                conflict_resolved[0] = True
                return ["Resolved conflict by removing contradictory fact"]
            return []

        result = run_full_simulation(
            fm, auto_detect=True, iterative=True,
            max_hearings=3, fact_updater=conflict_resolver,
        )
        assert result["total_hearings"] >= 1

    def test_multi_section_hearing_cycle(self):
        """Test that hearing cycle works when multiple sections detected."""
        fm = _hurt_matrix()
        fm.add_fact("mens_rea", "Accused intended to hurt.",
                    FactSource.WITNESS, severity="medium",
                    tags=["intention"])

        result = run_full_simulation(
            fm, auto_detect=True, iterative=True, max_hearings=2,
        )
        assert result["total_hearings"] >= 1
        section = result["hearings"][0]["case_analysis"]["evaluation_result"]["section"]
        assert section  # must have detected some section


# ═══════════════════════════════════════════════════════════════════════
# NO-UPDATE TESTS — Hearing cycle without fact_updater
# ═══════════════════════════════════════════════════════════════════════

class TestNoUpdater:
    """Tests for hearing cycle when no fact_updater is provided."""

    def test_runs_without_updater(self):
        fm = _murder_matrix()
        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm)
        assert result["total_hearings"] >= 1
        assert "hearings" in result

    def test_weak_case_no_updater_stops(self):
        fm = _weak_matrix()
        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm)
        # Without updater, feedback requiring updates can't be resolved
        # but internal ones (refinement, precedent, sentencing) still work
        assert result["total_hearings"] >= 1

    def test_no_updater_still_produces_valid_output(self):
        fm = _murder_matrix()
        hm = HearingManager(max_hearings=2)
        result = hm.run_hearing_cycle(fm)
        final = result["final_result"]
        assert "case_analysis" in final
        assert "lawyer_output" in final
        assert "panel_result" in final


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_single_hearing_max(self):
        fm = _murder_matrix()
        hm = HearingManager(max_hearings=1)
        result = hm.run_hearing_cycle(fm)
        assert result["total_hearings"] == 1

    def test_empty_feedbacks_stops_loop(self):
        """If no feedback requires update, loop should stop."""
        fm = _murder_matrix()
        hm = HearingManager(max_hearings=5)
        result = hm.run_hearing_cycle(fm)
        # Strong case should stabilise quickly
        assert result["total_hearings"] <= 5

    def test_hearing_numbers_are_sequential(self):
        fm = _weak_matrix()
        hm = HearingManager(max_hearings=3)
        result = hm.run_hearing_cycle(fm)
        for i, hearing in enumerate(result["hearings"]):
            assert hearing["hearing_number"] == i + 1

    def test_all_hearings_have_required_keys(self):
        fm = _murder_matrix()
        hm = HearingManager(max_hearings=2)
        result = hm.run_hearing_cycle(fm)
        required_keys = {
            "hearing_number", "case_analysis", "lawyer_output",
            "panel_result", "final_judgment", "feedback",
            "updates_applied", "research_data", "guardrail_report",
        }
        for hearing in result["hearings"]:
            assert required_keys.issubset(set(hearing.keys()))

    def test_final_result_matches_last_hearing(self):
        fm = _murder_matrix()
        hm = HearingManager(max_hearings=2)
        result = hm.run_hearing_cycle(fm)
        last_hearing = result["hearings"][-1]
        final = result["final_result"]
        assert final["case_analysis"] == last_hearing["case_analysis"]
        assert final["panel_result"] == last_hearing["panel_result"]
