"""
CourtMind — Simulation Event Generator

Converts the structured output of ``run_full_simulation()`` into a
chronological timeline of courtroom events suitable for an animated UI.

**Strict rules**

*   Read-only — does NOT modify simulation results.
*   Deterministic — same input always produces the same event list.
*   Backward-compatible — missing keys are silently skipped.

Usage
-----
    from simulation_events.event_generator import SimulationEventGenerator

    gen = SimulationEventGenerator()
    timeline = gen.generate_events(simulation_result)
    for ev in timeline["events"]:
        print(ev["event_type"], ev["actor"], ev["message"])
"""

from __future__ import annotations

from typing import Any, Dict, List

from simulation_events.event_models import Event, EventTimeline, EventType

# Timestamp step between events (seconds).  Kept constant so the UI
# can override with its own animation timing.
_TS_STEP = 1.5

# Map judge_type values to friendly actor names
_JUDGE_ACTOR: Dict[str, str] = {
    "textualist": "textualist_judge",
    "evidence_focused": "evidence_judge",
    "burden_strict": "burden_judge",
}

# Human-readable element descriptions for better simulation text
_ELEMENT_DESCRIPTION: Dict[str, str] = {
    "death_of_human": "the death of the victim",
    "hurt_element": "physical hurt or injury sustained",
    "deception_element": "deception or cheating committed",
    "inducement_element": "inducement that misled the victim",
    "gain_loss_element": "wrongful gain or loss suffered",
    "act_by_accused": "the act committed by the accused",
    "intention_or_knowledge": "intention or knowledge of likely consequences",
    "knowledge_element": "knowledge of the wrongful nature of the act",
    "voluntary_causing": "voluntarily causing hurt",
    "dishonest_intent": "dishonest intent to defraud",
}

# Map backend verdict tokens to courtroom-friendly labels
_VERDICT_LABEL: Dict[str, str] = {
    "convict": "GUILTY",
    "acquit": "NOT GUILTY",
    "review": "NEEDS FURTHER REVIEW",
}


class SimulationEventGenerator:
    """
    Converts ``run_full_simulation()`` output into a courtroom event
    timeline.

    Supports both single-pass and iterative (multi-hearing) result
    formats.
    """

    def generate_events(
        self,
        simulation_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Produce an ordered event timeline.

        Parameters
        ----------
        simulation_result : dict
            Output of ``run_full_simulation()``.

        Returns
        -------
        dict
            ``{"events": [...], "total_events": int}``
        """
        if not simulation_result:
            return EventTimeline(events=[], total_events=0).to_dict()

        events: List[Event] = []
        ts = 0.0

        # --- Iterative (multi-hearing) mode ---
        hearings = simulation_result.get("hearings")
        if hearings and isinstance(hearings, list):
            for hearing in hearings:
                ts = self._generate_hearing_events(
                    events, hearing, ts,
                )
            # Final strategy + explanation from final_result
            final = simulation_result.get("final_result", {})
            ts = self._add_strategy_events(events, final, ts)
            ts = self._add_explanation_event(events, final, ts)
        else:
            # --- Single-pass mode ---
            ts = self._generate_single_pass_events(
                events, simulation_result, ts,
            )

        serialised = [e.to_dict() for e in events]
        return EventTimeline(
            events=serialised,
            total_events=len(serialised),
        ).to_dict()

    # ------------------------------------------------------------------
    # Single-pass event generation
    # ------------------------------------------------------------------

    def _generate_single_pass_events(
        self,
        events: List[Event],
        result: Dict[str, Any],
        ts: float,
    ) -> float:
        ts = self._add_case_start(events, result, ts)
        ts = self._add_statement_events(events, result, ts)
        ts = self._add_lawyer_events(events, result, ts)
        ts = self._add_evidence_events(events, result, ts)
        ts = self._add_judge_thinking(events, ts)
        ts = self._add_panel_events(events, result, ts)
        ts = self._add_verdict_event(events, result, ts)
        ts = self._add_strategy_events(events, result, ts)
        ts = self._add_explanation_event(events, result, ts)
        return ts

    # ------------------------------------------------------------------
    # Hearing-level events (reuses single-pass helpers + feedback)
    # ------------------------------------------------------------------

    def _generate_hearing_events(
        self,
        events: List[Event],
        hearing: Dict[str, Any],
        ts: float,
    ) -> float:
        hearing_num = hearing.get("hearing_number", "?")

        # Case start per hearing
        events.append(self._evt(
            EventType.CASE_START, "system",
            f"Hearing #{hearing_num} commenced.",
            metadata={"hearing_number": hearing_num},
            ts=ts,
        ))
        ts += _TS_STEP

        ts = self._add_statement_events(events, hearing, ts)
        ts = self._add_lawyer_events(events, hearing, ts)
        ts = self._add_evidence_events(events, hearing, ts)
        ts = self._add_judge_thinking(events, ts)
        ts = self._add_panel_events(events, hearing, ts)
        ts = self._add_verdict_event(events, hearing, ts)

        # Hearing-specific: feedback + updates
        ts = self._add_feedback_events(events, hearing, ts)
        ts = self._add_update_events(events, hearing, ts)

        return ts

    # ------------------------------------------------------------------
    # Individual event builders
    # ------------------------------------------------------------------

    def _add_case_start(
        self, events: List[Event], result: Dict[str, Any], ts: float,
    ) -> float:
        ca = result.get("case_analysis", {})
        section = ca.get("evaluation_result", {}).get("section", "Unknown")
        events.append(self._evt(
            EventType.CASE_START, "system",
            f"Case simulation started — IPC Section {section}.",
            metadata={"section": section},
            ts=ts,
        ))
        return ts + _TS_STEP

    # --- Victim / Accused statements ---

    def _add_statement_events(
        self, events: List[Event], result: Dict[str, Any], ts: float,
    ) -> float:
        ca = result.get("case_analysis", {})
        eval_result = ca.get("evaluation_result", {})
        element_details = eval_result.get("element_details", [])

        # victim-side facts
        victim_facts = [
            e for e in element_details
            if e.get("element_id", "").lower() in (
                "death_of_human", "hurt_element", "deception_element",
                "inducement_element", "gain_loss_element",
            ) and e.get("matching_fact_ids")
        ]
        if victim_facts:
            for vf in victim_facts:
                eid = vf.get("element_id", "?")
                desc = _ELEMENT_DESCRIPTION.get(eid, eid.replace('_', ' '))
                fact_count = len(vf.get("matching_fact_ids", []))
                events.append(self._evt(
                    EventType.VICTIM_STATEMENT, "victim",
                    f"The victim testifies about {desc} "
                    f"({fact_count} supporting fact{'s' if fact_count != 1 else ''}).",
                    metadata={"element_id": eid,
                              "fact_count": fact_count},
                    ts=ts,
                ))
                ts += _TS_STEP

        # accused-side facts
        accused_facts = [
            e for e in element_details
            if e.get("element_id", "").lower() in (
                "act_by_accused", "intention_or_knowledge",
                "knowledge_element",
            ) and e.get("matching_fact_ids")
        ]
        if accused_facts:
            for af in accused_facts:
                eid = af.get("element_id", "?")
                desc = _ELEMENT_DESCRIPTION.get(eid, eid.replace('_', ' '))
                events.append(self._evt(
                    EventType.ACCUSED_STATEMENT, "accused",
                    f"The accused responds regarding {desc}.",
                    metadata={"element_id": eid},
                    ts=ts,
                ))
                ts += _TS_STEP

        return ts

    # --- Lawyer arguments ---

    def _add_lawyer_events(
        self, events: List[Event], result: Dict[str, Any], ts: float,
    ) -> float:
        lo = result.get("lawyer_output", {})

        for arg in lo.get("prosecution_arguments", []):
            events.append(self._evt(
                EventType.PROSECUTOR_ARGUMENT, "prosecutor",
                arg,
                ts=ts,
            ))
            ts += _TS_STEP

        for arg in lo.get("defense_arguments", []):
            events.append(self._evt(
                EventType.DEFENSE_ARGUMENT, "defense",
                arg,
                ts=ts,
            ))
            ts += _TS_STEP

        return ts

    # --- Evidence ---

    def _add_evidence_events(
        self, events: List[Event], result: Dict[str, Any], ts: float,
    ) -> float:
        ca = result.get("case_analysis", {})
        ew = ca.get("evidence_weight_result", {})
        per_element = ew.get("per_element_scores", {})

        for eid, score in per_element.items():
            events.append(self._evt(
                EventType.EVIDENCE_PRESENTED, "system",
                f"Evidence for '{eid}' presented (score: {score:.2f}).",
                metadata={"element_id": eid, "evidence_score": score},
                ts=ts,
            ))
            ts += _TS_STEP

        return ts

    # --- Judge thinking ---

    def _add_judge_thinking(
        self, events: List[Event], ts: float,
    ) -> float:
        events.append(self._evt(
            EventType.JUDGE_THINKING, "panel",
            "Judges reviewing evidence and legal elements.",
            ts=ts,
        ))
        return ts + _TS_STEP

    # --- Panel deliberation + votes ---

    def _add_panel_events(
        self, events: List[Event], result: Dict[str, Any], ts: float,
    ) -> float:
        pr = result.get("panel_result", {})
        if not pr:
            return ts

        events.append(self._evt(
            EventType.PANEL_DELIBERATION, "panel",
            "Judicial panel deliberating.",
            metadata={"confidence_level": pr.get("confidence_level", "unknown")},
            ts=ts,
        ))
        ts += _TS_STEP

        for judge in pr.get("judges", []):
            jtype = judge.get("judge_type", "unknown")
            actor = _JUDGE_ACTOR.get(jtype, jtype)
            verdict = judge.get("provisional_verdict", "review")

            reasoning = judge.get("key_reasoning_points", [])
            summary = reasoning[0] if reasoning else "No reasoning provided."

            verdict_label = _VERDICT_LABEL.get(verdict.lower(), verdict.upper())
            events.append(self._evt(
                EventType.JUDGE_VOTE, actor,
                f"Judge ({jtype}) votes: {verdict_label}. {summary}",
                metadata={
                    "judge": jtype,
                    "vote": verdict_label,
                    "agreement_with_lawyer": judge.get("agreement_with_lawyer", False),
                    "concerns": judge.get("concerns", []),
                },
                ts=ts,
            ))
            ts += _TS_STEP

        return ts

    # --- Verdict ---

    def _add_verdict_event(
        self, events: List[Event], result: Dict[str, Any], ts: float,
    ) -> float:
        pr = result.get("panel_result", {})
        if not pr:
            return ts

        majority = pr.get("majority_verdict", "review")
        majority_label = _VERDICT_LABEL.get(majority.lower(), majority.upper())
        split = pr.get("vote_split", "?")

        events.append(self._evt(
            EventType.VERDICT_DELIVERED, "panel",
            f"Majority verdict: {majority_label} (vote split: {split}).",
            metadata={
                "majority_verdict": majority_label,
                "vote_split": split,
            },
            ts=ts,
        ))
        return ts + _TS_STEP

    # --- Strategy ---

    def _add_strategy_events(
        self, events: List[Event], result: Dict[str, Any], ts: float,
    ) -> float:
        sr = result.get("strategy_report")
        if not sr:
            return ts

        risk = sr.get("risk_level", "unknown")
        prob = sr.get("conviction_probability_estimate", 0.0)

        events.append(self._evt(
            EventType.STRATEGY_PRESENTED, "system",
            f"Strategy analysis generated — risk: {risk}, "
            f"conviction probability: {prob:.2%}.",
            metadata={
                "risk_level": risk,
                "conviction_probability": prob,
                "weak_count": len(sr.get("weak_elements", [])),
                "strong_count": len(sr.get("strong_elements", [])),
                "prosecution_strategies": len(sr.get("prosecution_strategy", [])),
                "defense_strategies": len(sr.get("defense_strategy", [])),
            },
            ts=ts,
        ))
        return ts + _TS_STEP

    # --- Explanation ---

    def _add_explanation_event(
        self, events: List[Event], result: Dict[str, Any], ts: float,
    ) -> float:
        explanation = result.get("explanation")
        if not explanation:
            return ts

        # Truncate for the event message; full text in metadata
        preview = explanation[:200] + "…" if len(explanation) > 200 else explanation

        events.append(self._evt(
            EventType.EXPLANATION_DISPLAYED, "system",
            preview,
            metadata={"full_explanation_length": len(explanation)},
            ts=ts,
        ))
        return ts + _TS_STEP

    # --- Hearing feedback ---

    def _add_feedback_events(
        self, events: List[Event], hearing: Dict[str, Any], ts: float,
    ) -> float:
        for fb in hearing.get("feedback", []):
            fb_type = fb.get("type", "unknown")
            msg = fb.get("message", "Judges provided feedback.")
            events.append(self._evt(
                EventType.HEARING_FEEDBACK, "panel",
                msg,
                metadata={
                    "feedback_type": fb_type,
                    "severity": fb.get("severity", "medium"),
                    "requested_element": fb.get("requested_element", ""),
                },
                ts=ts,
            ))
            ts += _TS_STEP

        return ts

    # --- Hearing updates ---

    def _add_update_events(
        self, events: List[Event], hearing: Dict[str, Any], ts: float,
    ) -> float:
        for update in hearing.get("updates_applied", []):
            events.append(self._evt(
                EventType.HEARING_UPDATE, "system",
                update,
                ts=ts,
            ))
            ts += _TS_STEP

        return ts

    # ------------------------------------------------------------------
    # Factory helper
    # ------------------------------------------------------------------

    _counter: int = 0

    def _evt(
        self,
        event_type: EventType,
        actor: str,
        message: str,
        *,
        metadata: Dict[str, Any] | None = None,
        ts: float = 0.0,
    ) -> Event:
        self._counter += 1
        return Event(
            event_id=f"evt_{self._counter:04d}",
            event_type=event_type.value,
            actor=actor,
            message=message,
            metadata=metadata or {},
            timestamp=round(ts, 2),
        )
