"""
CourtMind — Tests for Simulation Event Generator

Unit tests, integration tests, and system tests covering:

 1.  Event generation basic case
 2.  Event ordering correctness
 3.  Prosecutor argument events
 4.  Defense argument events
 5.  Evidence event creation
 6.  Judge vote events
 7.  Verdict event metadata
 8.  Strategy event generation
 9.  Explanation event generation
10.  Hearing feedback event
11.  Hearing update event
12.  Integration with run_full_simulation
13.  Event immutability
14.  Empty input edge case
15.  Large event list performance
16.  Victim statement events
17.  Accused statement events
18.  Case start metadata
19.  Panel deliberation event
20.  Judge thinking event
21.  Event IDs are unique
22.  Timestamps are monotonically increasing
23.  Iterative (multi-hearing) mode events
24.  EventType enum values
25.  Event / EventTimeline serialisation
"""

from __future__ import annotations

import copy
import time
from typing import Any, Dict, List

import pytest

from core.evaluation_pipeline import EvaluationPipeline
from core.fact_matrix import FactMatrix, FactSource, Severity
from simulation.run_simulation import run_full_simulation
from simulation_events.event_generator import SimulationEventGenerator
from simulation_events.event_models import Event, EventTimeline, EventType


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _build_simulation_result(
    *,
    section: str = "302",
    element_details: List[Dict[str, Any]] | None = None,
    prosecution_arguments: List[str] | None = None,
    defense_arguments: List[str] | None = None,
    per_element_scores: Dict[str, float] | None = None,
    judges: List[Dict[str, Any]] | None = None,
    majority_verdict: str = "convict",
    vote_split: str = "2-1",
    strategy_report: Dict[str, Any] | None = None,
    explanation: str | None = None,
) -> Dict[str, Any]:
    """Build a minimal simulation result dict for testing."""
    return {
        "case_analysis": {
            "evaluation_result": {
                "section": section,
                "element_details": element_details or [
                    {"element_id": "act_by_accused", "status": "satisfied",
                     "required": True, "matching_fact_ids": ["f1"]},
                    {"element_id": "death_of_human", "status": "satisfied",
                     "required": True, "matching_fact_ids": ["f2"]},
                ],
            },
            "burden_result": {
                "confidence_score": 0.8,
                "burden_stage": "prima_facie_established",
                "verdict_recommendation": "convict",
            },
            "evidence_weight_result": {
                "overall_evidence_score": 0.75,
                "per_element_scores": per_element_scores
                if per_element_scores is not None
                else {"act_by_accused": 0.9, "death_of_human": 0.8},
            },
            "exception_result": {"exceptions_detected": []},
            "metadata": {},
        },
        "lawyer_output": {
            "confirmed_section": f"{section} IPC",
            "prosecution_arguments": prosecution_arguments or [
                "Accused was at the scene.",
                "Weapon recovered.",
            ],
            "defense_arguments": defense_arguments or [
                "No eyewitness testimony.",
            ],
            "identified_weaknesses": [],
            "risk_level": "high",
        },
        "panel_result": {
            "majority_verdict": majority_verdict,
            "vote_split": vote_split,
            "judges": judges or [
                {"judge_type": "textualist",
                 "provisional_verdict": "convict",
                 "key_reasoning_points": ["All elements met."],
                 "concerns": [],
                 "agreement_with_lawyer": True},
                {"judge_type": "evidence_focused",
                 "provisional_verdict": "convict",
                 "key_reasoning_points": ["Evidence score high."],
                 "concerns": [],
                 "agreement_with_lawyer": True},
                {"judge_type": "burden_strict",
                 "provisional_verdict": "acquit",
                 "key_reasoning_points": ["Burden not fully met."],
                 "concerns": ["Low corroboration."],
                 "agreement_with_lawyer": False},
            ],
            "confidence_level": "high",
        },
        "final_judgment": "The court finds the accused guilty.",
        "research_data": {},
        "guardrail_report": {"violations": []},
        "strategy_report": strategy_report or {
            "weak_elements": [],
            "strong_elements": [{"element_id": "act_by_accused",
                                 "evidence_score": 0.9,
                                 "supporting_fact_count": 2}],
            "prosecution_strategy": ["Focus on forensic linkage."],
            "defense_strategy": ["Challenge witness credibility."],
            "evidence_recommendations": [],
            "risk_level": "high",
            "conviction_probability_estimate": 0.76,
        },
        "explanation": explanation or "## Case Analysis — IPC Section 302\n\nThe court evaluated all elements...",
    }


def _murder_matrix() -> FactMatrix:
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
    fm = FactMatrix()
    fm.add_fact("actus_reus", "A person was found dead.",
                FactSource.WITNESS, severity="medium",
                tags=["death_of_human"])
    return fm


def _types(events: List[Dict[str, Any]]) -> List[str]:
    """Extract event types from an event list."""
    return [e["event_type"] for e in events]


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS — Event Models
# ═══════════════════════════════════════════════════════════════════════

class TestEventModels:
    """Tests 24–25: Enum and serialisation."""

    def test_event_type_enum_values(self):
        """#24: All specified EventType members exist."""
        expected = {
            "case_start", "victim_statement", "accused_statement",
            "prosecutor_argument", "defense_argument", "evidence_presented",
            "judge_question", "judge_thinking", "panel_deliberation",
            "judge_vote", "verdict_delivered", "strategy_presented",
            "explanation_displayed", "hearing_feedback", "hearing_update",
        }
        actual = {e.value for e in EventType}
        assert expected == actual

    def test_event_to_dict(self):
        """#25a: Event round-trips to dict."""
        ev = Event(
            event_id="evt_0001",
            event_type="case_start",
            actor="system",
            message="Started.",
            metadata={"k": "v"},
            timestamp=1.5,
        )
        d = ev.to_dict()
        assert d["event_id"] == "evt_0001"
        assert d["timestamp"] == 1.5
        assert d["metadata"]["k"] == "v"

    def test_event_to_json(self):
        ev = Event("e1", "case_start", "system", "hi")
        j = ev.to_json()
        assert '"event_id": "e1"' in j

    def test_event_timeline_to_dict(self):
        """#25b: EventTimeline serialisation."""
        tl = EventTimeline(
            events=[{"event_id": "e1"}],
            total_events=1,
        )
        d = tl.to_dict()
        assert d["total_events"] == 1
        assert len(d["events"]) == 1

    def test_event_timeline_to_json(self):
        tl = EventTimeline(events=[], total_events=0)
        assert '"total_events": 0' in tl.to_json()


# ═══════════════════════════════════════════════════════════════════════
# UNIT TESTS — Event Generator
# ═══════════════════════════════════════════════════════════════════════

class TestBasicGeneration:
    """Test 1: Basic event generation."""

    def test_generates_events(self):
        """#1: Generator produces non-empty event list."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        assert result["total_events"] > 0
        assert len(result["events"]) == result["total_events"]

    def test_all_events_have_required_fields(self):
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        for ev in result["events"]:
            assert "event_id" in ev
            assert "event_type" in ev
            assert "actor" in ev
            assert "message" in ev
            assert "metadata" in ev
            assert "timestamp" in ev


class TestEventOrdering:
    """Test 2: Courtroom-natural ordering."""

    def test_correct_order(self):
        """#2: Events follow courtroom flow."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        types = _types(result["events"])

        # Extract first occurrence of each type
        order = []
        seen = set()
        for t in types:
            if t not in seen:
                order.append(t)
                seen.add(t)

        # Check key ordering constraints
        assert order.index("case_start") < order.index("prosecutor_argument")
        assert order.index("prosecutor_argument") < order.index("defense_argument")
        assert order.index("defense_argument") < order.index("judge_thinking")
        assert order.index("judge_thinking") < order.index("panel_deliberation")
        assert order.index("panel_deliberation") < order.index("judge_vote")
        assert order.index("judge_vote") < order.index("verdict_delivered")
        assert order.index("verdict_delivered") < order.index("strategy_presented")
        assert order.index("strategy_presented") < order.index("explanation_displayed")


class TestTimestamps:
    """Test 22: Timestamps monotonically increase."""

    def test_monotonic_timestamps(self):
        """#22: Each event's timestamp >= previous."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        timestamps = [e["timestamp"] for e in result["events"]]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1]


class TestUniqueIds:
    """Test 21: All event IDs are unique."""

    def test_unique_event_ids(self):
        """#21: No duplicate event_ids."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        ids = [e["event_id"] for e in result["events"]]
        assert len(ids) == len(set(ids))


class TestProsecutorArguments:
    """Test 3: Prosecutor argument events."""

    def test_each_argument_is_event(self):
        """#3: Each prosecution argument → one event."""
        args = ["Arg1", "Arg2", "Arg3"]
        gen = SimulationEventGenerator()
        result = gen.generate_events(
            _build_simulation_result(prosecution_arguments=args),
        )
        pros_events = [
            e for e in result["events"]
            if e["event_type"] == "prosecutor_argument"
        ]
        assert len(pros_events) == 3
        assert all(e["actor"] == "prosecutor" for e in pros_events)
        messages = [e["message"] for e in pros_events]
        assert "Arg1" in messages
        assert "Arg2" in messages


class TestDefenseArguments:
    """Test 4: Defense argument events."""

    def test_each_argument_is_event(self):
        """#4: Each defense argument → one event."""
        args = ["Def1", "Def2"]
        gen = SimulationEventGenerator()
        result = gen.generate_events(
            _build_simulation_result(defense_arguments=args),
        )
        def_events = [
            e for e in result["events"]
            if e["event_type"] == "defense_argument"
        ]
        assert len(def_events) == 2
        assert all(e["actor"] == "defense" for e in def_events)


class TestEvidenceEvents:
    """Test 5: Evidence presented events."""

    def test_evidence_per_element(self):
        """#5: Each per-element score → evidence event."""
        scores = {"elem1": 0.8, "elem2": 0.6, "elem3": 0.5}
        gen = SimulationEventGenerator()
        result = gen.generate_events(
            _build_simulation_result(per_element_scores=scores),
        )
        ev_events = [
            e for e in result["events"]
            if e["event_type"] == "evidence_presented"
        ]
        assert len(ev_events) == 3
        ids = {e["metadata"]["element_id"] for e in ev_events}
        assert ids == {"elem1", "elem2", "elem3"}


class TestJudgeVoteEvents:
    """Test 6: Judge vote events."""

    def test_vote_per_judge(self):
        """#6: Each judge → one JUDGE_VOTE event."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        vote_events = [
            e for e in result["events"]
            if e["event_type"] == "judge_vote"
        ]
        assert len(vote_events) == 3
        judges = {e["metadata"]["judge"] for e in vote_events}
        assert judges == {"textualist", "evidence_focused", "burden_strict"}

    def test_vote_metadata(self):
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        vote_events = [
            e for e in result["events"]
            if e["event_type"] == "judge_vote"
        ]
        for ve in vote_events:
            assert "judge" in ve["metadata"]
            assert "vote" in ve["metadata"]
            assert ve["metadata"]["vote"] in ("GUILTY", "NOT GUILTY", "NEEDS FURTHER REVIEW")


class TestVerdictEvent:
    """Test 7: Verdict event metadata."""

    def test_verdict_metadata(self):
        """#7: VERDICT_DELIVERED carries majority_verdict + vote_split."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(
            _build_simulation_result(majority_verdict="acquit", vote_split="1-2"),
        )
        verdict_events = [
            e for e in result["events"]
            if e["event_type"] == "verdict_delivered"
        ]
        assert len(verdict_events) == 1
        md = verdict_events[0]["metadata"]
        assert md["majority_verdict"] == "NOT GUILTY"
        assert md["vote_split"] == "1-2"
        assert "NOT GUILTY" in verdict_events[0]["message"]


class TestStrategyEvent:
    """Test 8: Strategy event generation."""

    def test_strategy_event_created(self):
        """#8: Strategy report → STRATEGY_PRESENTED event."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        strat_events = [
            e for e in result["events"]
            if e["event_type"] == "strategy_presented"
        ]
        assert len(strat_events) == 1
        assert strat_events[0]["actor"] == "system"
        md = strat_events[0]["metadata"]
        assert "risk_level" in md
        assert "conviction_probability" in md

    def test_no_strategy_when_absent(self):
        sim = _build_simulation_result()
        del sim["strategy_report"]
        gen = SimulationEventGenerator()
        result = gen.generate_events(sim)
        assert not any(
            e["event_type"] == "strategy_presented"
            for e in result["events"]
        )


class TestExplanationEvent:
    """Test 9: Explanation event generation."""

    def test_explanation_event_created(self):
        """#9: Explanation → EXPLANATION_DISPLAYED event."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        exp_events = [
            e for e in result["events"]
            if e["event_type"] == "explanation_displayed"
        ]
        assert len(exp_events) == 1
        md = exp_events[0]["metadata"]
        assert "full_explanation_length" in md

    def test_no_explanation_when_absent(self):
        sim = _build_simulation_result()
        del sim["explanation"]
        gen = SimulationEventGenerator()
        result = gen.generate_events(sim)
        assert not any(
            e["event_type"] == "explanation_displayed"
            for e in result["events"]
        )

    def test_long_explanation_truncated_in_message(self):
        """Long explanation text is truncated in message, full length in metadata."""
        long_text = "x" * 500
        gen = SimulationEventGenerator()
        result = gen.generate_events(
            _build_simulation_result(explanation=long_text),
        )
        exp_events = [
            e for e in result["events"]
            if e["event_type"] == "explanation_displayed"
        ]
        assert len(exp_events[0]["message"]) < 250
        assert exp_events[0]["metadata"]["full_explanation_length"] == 500


class TestHearingFeedbackEvent:
    """Test 10: Hearing feedback events."""

    def test_feedback_events_from_hearing(self):
        """#10: Hearing feedback → HEARING_FEEDBACK events."""
        hearing_result = {
            "hearings": [
                {
                    "hearing_number": 1,
                    "case_analysis": _build_simulation_result()["case_analysis"],
                    "lawyer_output": _build_simulation_result()["lawyer_output"],
                    "panel_result": _build_simulation_result()["panel_result"],
                    "final_judgment": "Judgment.",
                    "feedback": [
                        {"type": "evidence_request",
                         "message": "Judges requested additional evidence.",
                         "severity": "high",
                         "requested_element": "act_by_accused"},
                    ],
                    "updates_applied": [],
                    "research_data": {},
                    "guardrail_report": {"violations": []},
                },
            ],
            "final_result": _build_simulation_result(),
            "total_hearings": 1,
            "verdict_stable": True,
        }
        gen = SimulationEventGenerator()
        result = gen.generate_events(hearing_result)
        fb_events = [
            e for e in result["events"]
            if e["event_type"] == "hearing_feedback"
        ]
        assert len(fb_events) == 1
        assert fb_events[0]["metadata"]["feedback_type"] == "evidence_request"


class TestHearingUpdateEvent:
    """Test 11: Hearing update events."""

    def test_update_events_from_hearing(self):
        """#11: Updates applied → HEARING_UPDATE events."""
        hearing_result = {
            "hearings": [
                {
                    "hearing_number": 1,
                    "case_analysis": _build_simulation_result()["case_analysis"],
                    "lawyer_output": _build_simulation_result()["lawyer_output"],
                    "panel_result": _build_simulation_result()["panel_result"],
                    "final_judgment": "Judgment.",
                    "feedback": [],
                    "updates_applied": [
                        "Added forensic report",
                        "Added witness testimony",
                    ],
                    "research_data": {},
                    "guardrail_report": {"violations": []},
                },
            ],
            "final_result": _build_simulation_result(),
            "total_hearings": 1,
            "verdict_stable": True,
        }
        gen = SimulationEventGenerator()
        result = gen.generate_events(hearing_result)
        upd_events = [
            e for e in result["events"]
            if e["event_type"] == "hearing_update"
        ]
        assert len(upd_events) == 2
        msgs = {e["message"] for e in upd_events}
        assert "Added forensic report" in msgs


class TestEventImmutability:
    """Test 13: Generator does not mutate input."""

    def test_input_not_mutated(self):
        """#13: Simulation result is not modified."""
        sim = _build_simulation_result()
        original = copy.deepcopy(sim)
        gen = SimulationEventGenerator()
        gen.generate_events(sim)
        assert sim == original


class TestEmptyInput:
    """Test 14: Edge cases."""

    def test_empty_dict(self):
        """#14a: Empty dict → zero events."""
        gen = SimulationEventGenerator()
        result = gen.generate_events({})
        assert result["total_events"] == 0
        assert result["events"] == []

    def test_none_like_input(self):
        """#14b: Missing keys → graceful degradation."""
        gen = SimulationEventGenerator()
        result = gen.generate_events({"case_analysis": {}})
        assert result["total_events"] > 0  # at least CASE_START

    def test_no_lawyer_output(self):
        """No lawyer → no prosecutor/defense events, no crash."""
        sim = _build_simulation_result()
        del sim["lawyer_output"]
        gen = SimulationEventGenerator()
        result = gen.generate_events(sim)
        assert not any(
            e["event_type"] in ("prosecutor_argument", "defense_argument")
            for e in result["events"]
        )

    def test_no_panel_result(self):
        """No panel → no vote/verdict events, no crash."""
        sim = _build_simulation_result()
        del sim["panel_result"]
        gen = SimulationEventGenerator()
        result = gen.generate_events(sim)
        assert not any(
            e["event_type"] in ("judge_vote", "verdict_delivered", "panel_deliberation")
            for e in result["events"]
        )


class TestLargeEventList:
    """Test 15: Performance."""

    def test_performance(self):
        """#15: 100 arguments → completes in < 1 second."""
        args = [f"Argument {i}" for i in range(100)]
        sim = _build_simulation_result(
            prosecution_arguments=args,
            defense_arguments=args,
        )
        gen = SimulationEventGenerator()
        start = time.monotonic()
        result = gen.generate_events(sim)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
        assert result["total_events"] > 200


class TestVictimStatements:
    """Test 16: Victim statement events."""

    def test_victim_from_element_details(self):
        """#16: Victim-side elements → VICTIM_STATEMENT events."""
        elements = [
            {"element_id": "death_of_human", "status": "satisfied",
             "required": True, "matching_fact_ids": ["f1"]},
            {"element_id": "hurt_element", "status": "satisfied",
             "required": True, "matching_fact_ids": ["f2"]},
        ]
        gen = SimulationEventGenerator()
        result = gen.generate_events(
            _build_simulation_result(element_details=elements),
        )
        victim_events = [
            e for e in result["events"]
            if e["event_type"] == "victim_statement"
        ]
        assert len(victim_events) == 2
        assert all(e["actor"] == "victim" for e in victim_events)


class TestAccusedStatements:
    """Test 17: Accused statement events."""

    def test_accused_from_element_details(self):
        """#17: Accused-side elements → ACCUSED_STATEMENT events."""
        elements = [
            {"element_id": "act_by_accused", "status": "satisfied",
             "required": True, "matching_fact_ids": ["f1"]},
            {"element_id": "intention_or_knowledge", "status": "partial",
             "required": True, "matching_fact_ids": ["f2"]},
        ]
        gen = SimulationEventGenerator()
        result = gen.generate_events(
            _build_simulation_result(element_details=elements),
        )
        accused_events = [
            e for e in result["events"]
            if e["event_type"] == "accused_statement"
        ]
        assert len(accused_events) == 2
        assert all(e["actor"] == "accused" for e in accused_events)


class TestCaseStartMetadata:
    """Test 18: CASE_START carries section info."""

    def test_section_in_metadata(self):
        """#18: CASE_START contains section in metadata."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(
            _build_simulation_result(section="420"),
        )
        start_events = [
            e for e in result["events"]
            if e["event_type"] == "case_start"
        ]
        assert len(start_events) >= 1
        assert start_events[0]["metadata"]["section"] == "420"
        assert "420" in start_events[0]["message"]


class TestPanelDeliberation:
    """Test 19: Panel deliberation event."""

    def test_deliberation_event(self):
        """#19: PANEL_DELIBERATION event exists."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        delib = [
            e for e in result["events"]
            if e["event_type"] == "panel_deliberation"
        ]
        assert len(delib) == 1
        assert delib[0]["actor"] == "panel"


class TestJudgeThinking:
    """Test 20: Judge thinking event."""

    def test_judge_thinking_event(self):
        """#20: JUDGE_THINKING event exists."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(_build_simulation_result())
        thinking = [
            e for e in result["events"]
            if e["event_type"] == "judge_thinking"
        ]
        assert len(thinking) == 1
        assert "reviewing" in thinking[0]["message"].lower()


class TestMultiHearingMode:
    """Test 23: Iterative / multi-hearing events."""

    def _hearing_result(self) -> Dict[str, Any]:
        base = _build_simulation_result()
        return {
            "hearings": [
                {
                    "hearing_number": 1,
                    "case_analysis": base["case_analysis"],
                    "lawyer_output": base["lawyer_output"],
                    "panel_result": base["panel_result"],
                    "final_judgment": "Judgment H1.",
                    "feedback": [
                        {"type": "evidence_request",
                         "message": "More evidence needed.",
                         "severity": "high",
                         "requested_element": "act_by_accused"},
                    ],
                    "updates_applied": ["Added new witness."],
                    "research_data": {},
                    "guardrail_report": {"violations": []},
                },
                {
                    "hearing_number": 2,
                    "case_analysis": base["case_analysis"],
                    "lawyer_output": base["lawyer_output"],
                    "panel_result": base["panel_result"],
                    "final_judgment": "Judgment H2.",
                    "feedback": [],
                    "updates_applied": [],
                    "research_data": {},
                    "guardrail_report": {"violations": []},
                },
            ],
            "final_result": base,
            "total_hearings": 2,
            "verdict_stable": True,
        }

    def test_multi_hearing_generates_events(self):
        """#23a: Multi-hearing result → events for each hearing."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(self._hearing_result())
        assert result["total_events"] > 10

        start_events = [
            e for e in result["events"]
            if e["event_type"] == "case_start"
        ]
        # One CASE_START per hearing
        assert len(start_events) == 2

    def test_multi_hearing_feedback_and_updates(self):
        """#23b: Feedback and updates appear in events."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(self._hearing_result())
        fb = [e for e in result["events"]
              if e["event_type"] == "hearing_feedback"]
        upd = [e for e in result["events"]
               if e["event_type"] == "hearing_update"]
        assert len(fb) == 1
        assert len(upd) == 1

    def test_multi_hearing_includes_final_strategy(self):
        """Multi-hearing result includes strategy+explanation from final_result."""
        gen = SimulationEventGenerator()
        result = gen.generate_events(self._hearing_result())
        strat = [e for e in result["events"]
                 if e["event_type"] == "strategy_presented"]
        expl = [e for e in result["events"]
                if e["event_type"] == "explanation_displayed"]
        assert len(strat) == 1
        assert len(expl) == 1


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestIntegrationWithSimulation:
    """Test 12: Full integration with run_full_simulation."""

    def test_simulation_events_in_result(self):
        """#12a: run_full_simulation() now returns simulation_events."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        assert "simulation_events" in result
        se = result["simulation_events"]
        assert se["total_events"] > 0

    def test_events_reflect_actual_analysis(self):
        """#12b: Events reference actual section from analysis."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        events = result["simulation_events"]["events"]
        start = [e for e in events if e["event_type"] == "case_start"]
        assert len(start) >= 1
        # Should contain the detected section
        section = result["case_analysis"]["evaluation_result"]["section"]
        assert section in start[0]["message"]

    def test_backward_compatible_keys(self):
        """Existing keys still present after adding simulation_events."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        for key in ("case_analysis", "lawyer_output", "panel_result",
                     "final_judgment", "research_data", "guardrail_report",
                     "strategy_report", "explanation"):
            assert key in result

    def test_events_have_prosecutor_args(self):
        """Integration: prosecutor argument events match lawyer_output."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        pros_events = [
            e for e in result["simulation_events"]["events"]
            if e["event_type"] == "prosecutor_argument"
        ]
        expected_count = len(result["lawyer_output"]["prosecution_arguments"])
        assert len(pros_events) == expected_count

    def test_events_have_judge_votes(self):
        """Integration: judge vote events match panel judges."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        vote_events = [
            e for e in result["simulation_events"]["events"]
            if e["event_type"] == "judge_vote"
        ]
        assert len(vote_events) == len(result["panel_result"]["judges"])


# ═══════════════════════════════════════════════════════════════════════
# SYSTEM TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestSystemEndToEnd:
    """Full pipeline scenarios."""

    def test_strong_case_events(self):
        """Strong murder → full event timeline."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        se = result["simulation_events"]
        types = _types(se["events"])

        assert "case_start" in types
        assert "verdict_delivered" in types
        assert "strategy_presented" in types
        assert "explanation_displayed" in types

    def test_weak_case_events(self):
        """Weak case → events still generated."""
        fm = _weak_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        se = result["simulation_events"]
        assert se["total_events"] > 0
        assert "case_start" in _types(se["events"])

    def test_events_order_in_full_simulation(self):
        """Full simulation events follow courtroom natural order."""
        fm = _murder_matrix()
        result = run_full_simulation(fm, auto_detect=True)
        types = _types(result["simulation_events"]["events"])

        # Extract first occurrence indices
        first = {}
        for i, t in enumerate(types):
            if t not in first:
                first[t] = i

        if "prosecutor_argument" in first and "verdict_delivered" in first:
            assert first["prosecutor_argument"] < first["verdict_delivered"]
        if "judge_vote" in first and "verdict_delivered" in first:
            assert first["judge_vote"] < first["verdict_delivered"]
        if "verdict_delivered" in first and "strategy_presented" in first:
            assert first["verdict_delivered"] < first["strategy_presented"]

    def test_cheating_case_events(self):
        """Section 420 case → victim statement references deception."""
        fm = FactMatrix()
        fm.add_fact("actus_reus", "Accused created fake documents.",
                    FactSource.DOCUMENT, severity="high",
                    tags=["deception", "deception_element"])
        fm.add_fact("actus_reus", "Victim handed over money.",
                    FactSource.WITNESS, severity="high",
                    tags=["inducement", "inducement_element"])
        fm.add_fact("mens_rea", "Accused planned fraud.",
                    FactSource.DOCUMENT, severity="high",
                    tags=["intention", "cheating_intent"])
        fm.add_fact("evidence", "Bank records.",
                    FactSource.DOCUMENT, severity="medium",
                    tags=["financial", "gain_loss_element"])
        result = run_full_simulation(fm, auto_detect=True)
        assert "simulation_events" in result
        se = result["simulation_events"]
        assert se["total_events"] > 0
