"""
CourtMind — Deterministic Guardrail Enforcement Layer

Validates that simulation-layer outputs (``LawyerAgent``, ``JudgeAgent``,
``JudgmentWriter``) remain consistent with the deterministic
``CaseAnalysis``.

**Strict rules**

*   No LLM usage — pure deterministic validation.
*   Does **not** modify ``CaseAnalysis``.
*   Does **not** modify simulation output.
*   Only validates and flags violations.

Usage
-----
    from core.simulation_guardrails import SimulationGuardrails

    guardrails = SimulationGuardrails()
    report = guardrails.validate_lawyer_output(case_dict, lawyer_output)
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, List, Set


# ── element-reference extraction ────────────────────────────────────────

_ELEMENT_REF_RE = re.compile(r"[Ee]lement\s+'([^']+)'")


def _extract_element_refs(texts: List[str]) -> Set[str]:
    """Return the set of element ids mentioned in *texts* via ``Element 'id'``."""
    refs: Set[str] = set()
    for t in texts:
        refs.update(_ELEMENT_REF_RE.findall(t))
    return refs


# ── known burden stages ─────────────────────────────────────────────────

_ACQUITTAL_STAGES: FrozenSet[str] = frozenset({
    "acquittal_recommended",
})

_NON_CONVICTION_STAGES: FrozenSet[str] = frozenset({
    "prosecution_incomplete",
    "acquittal_recommended",
})

_CONVICTION_STAGES: FrozenSet[str] = frozenset({
    "prima_facie_established",
})


# ── SimulationGuardrails ────────────────────────────────────────────────

class SimulationGuardrails:
    """
    Pure-deterministic validator for simulation-layer outputs.

    Every ``validate_*`` method returns::

        {"valid": bool, "violations": list[str]}
    """

    # ------------------------------------------------------------------ #
    # 1. Lawyer output                                                     #
    # ------------------------------------------------------------------ #

    def validate_lawyer_output(
        self,
        case_analysis: dict,
        lawyer_output: dict,
    ) -> Dict[str, Any]:
        """
        Validate ``LawyerAgent`` output against the deterministic analysis.

        Checks
        ------
        *   ``confirmed_section`` equals the evaluated section.
        *   ``alternate_sections`` are a subset of detected sections.
        *   ``prosecution_arguments`` reference only satisfied elements.
        *   ``defense_arguments`` reference only failed/conflicted/partial
            elements **or** supported exceptions.
        *   ``risk_level`` correlates with ``confidence_score``.
        """
        violations: List[str] = []

        eval_r = case_analysis.get("evaluation_result", {})
        burden_r = case_analysis.get("burden_result", {})
        meta = case_analysis.get("metadata", {})
        exc_r = case_analysis.get("exception_result", {})

        section = eval_r.get("section", "")
        confidence = float(burden_r.get("confidence_score", 0.0))
        element_details = eval_r.get("element_details", [])

        # -- section match ---------------------------------------------------
        confirmed = lawyer_output.get("confirmed_section", "")
        if confirmed != section:
            violations.append(
                f"confirmed_section '{confirmed}' does not match "
                f"evaluated section '{section}'."
            )

        # -- alternate_sections ⊆ detected_sections -------------------------
        detected_sections_raw = meta.get("detected_sections", [])
        detected_codes: Set[str] = set()
        for d in detected_sections_raw:
            if isinstance(d, dict):
                detected_codes.add(d.get("section", ""))
            elif isinstance(d, str):
                detected_codes.add(d)
        # Remove the confirmed section (it's not "alternate")
        detected_codes.discard(section)

        for alt in lawyer_output.get("alternate_sections", []):
            if alt not in detected_codes:
                violations.append(
                    f"alternate_section '{alt}' is not in detected sections."
                )

        # -- prosecution_arguments reference only satisfied elements ---------
        satisfied_ids: Set[str] = {
            e.get("element_id", "")
            for e in element_details
            if e.get("status") == "satisfied"
        }
        pros_refs = _extract_element_refs(
            lawyer_output.get("prosecution_arguments", [])
        )
        for ref in sorted(pros_refs - satisfied_ids):
            violations.append(
                f"prosecution_argument references element '{ref}' "
                f"which is not satisfied."
            )

        # -- defense_arguments reference only failed/conflicted/partial/exc ---
        defense_element_ids: Set[str] = {
            e.get("element_id", "")
            for e in element_details
            if e.get("status") in ("not_satisfied", "conflicted", "partial")
        }
        exceptions_supported: Set[str] = set(
            exc_r.get("exceptions_supported", [])
        )
        negated_elements: Set[str] = set(
            exc_r.get("negated_elements", [])
        )
        allowed_defense = defense_element_ids | exceptions_supported | negated_elements

        def_refs = _extract_element_refs(
            lawyer_output.get("defense_arguments", [])
        )
        for ref in sorted(def_refs - allowed_defense):
            violations.append(
                f"defense_argument references element '{ref}' "
                f"which is not failed/conflicted/partial or exception-supported."
            )

        # -- risk_level vs confidence ----------------------------------------
        risk = lawyer_output.get("risk_level", "")
        expected_risk = self._expected_risk(confidence)
        if risk and expected_risk and risk != expected_risk:
            violations.append(
                f"risk_level '{risk}' inconsistent with confidence "
                f"{confidence} (expected '{expected_risk}')."
            )

        return {"valid": len(violations) == 0, "violations": violations}

    # ------------------------------------------------------------------ #
    # 2. Judge output                                                      #
    # ------------------------------------------------------------------ #

    def validate_judge_output(
        self,
        case_analysis: dict,
        judge_output: dict,
    ) -> Dict[str, Any]:
        """
        Validate a single ``JudgeAgent`` output against the deterministic
        analysis.

        Checks
        ------
        *   ``provisional_verdict`` aligns with ``burden_stage``.
        *   Judge does not contradict ``fully_negated``,
            ``acquittal_recommended``, or ``prosecution_incomplete``.
        *   ``key_reasoning_points`` do not reference unknown elements.
        """
        violations: List[str] = []

        eval_r = case_analysis.get("evaluation_result", {})
        burden_r = case_analysis.get("burden_result", {})
        exc_r = case_analysis.get("exception_result", {})

        burden_stage = burden_r.get("burden_stage", "unknown")
        fully_negated = bool(exc_r.get("fully_negated", False))
        verdict = judge_output.get("provisional_verdict", "")

        # -- fully_negated → must acquit ------------------------------------
        if fully_negated and verdict != "acquit":
            violations.append(
                f"Judge verdict '{verdict}' contradicts fully_negated=True "
                f"(must be 'acquit')."
            )

        # -- acquittal_recommended → must acquit ----------------------------
        if burden_stage in _ACQUITTAL_STAGES and verdict != "acquit":
            violations.append(
                f"Judge verdict '{verdict}' contradicts "
                f"burden_stage='{burden_stage}' (must be 'acquit')."
            )

        # -- prosecution_incomplete → cannot convict ------------------------
        if burden_stage in _NON_CONVICTION_STAGES and verdict == "convict":
            violations.append(
                f"Judge verdict 'convict' contradicts "
                f"burden_stage='{burden_stage}'."
            )

        # -- key_reasoning_points must not reference unknown elements --------
        known_ids: Set[str] = {
            e.get("element_id", "")
            for e in eval_r.get("element_details", [])
        }
        reasoning_refs = _extract_element_refs(
            judge_output.get("key_reasoning_points", [])
        )
        for ref in sorted(reasoning_refs - known_ids):
            violations.append(
                f"key_reasoning_point references unknown element '{ref}'."
            )

        return {"valid": len(violations) == 0, "violations": violations}

    # ------------------------------------------------------------------ #
    # 3. Final judgment text                                               #
    # ------------------------------------------------------------------ #

    def validate_final_judgment(
        self,
        case_analysis: dict,
        final_text: str,
    ) -> Dict[str, Any]:
        """
        Validate the ``JudgmentWriter`` output text against the
        deterministic analysis.

        Checks
        ------
        *   Text mentions the section.
        *   Text mentions the ``burden_stage``.
        *   Does not contradict ``elements_failed`` / ``fully_negated``.
        *   If ``acquittal_recommended`` → contains "acquit".
        *   If ``prima_facie_established`` → contains "convict" or "proceed".
        """
        violations: List[str] = []

        eval_r = case_analysis.get("evaluation_result", {})
        burden_r = case_analysis.get("burden_result", {})
        exc_r = case_analysis.get("exception_result", {})

        section = eval_r.get("section", "")
        burden_stage = burden_r.get("burden_stage", "unknown")
        fully_negated = bool(exc_r.get("fully_negated", False))

        text_lower = final_text.lower()

        # -- must mention section -------------------------------------------
        if section and section.lower() not in text_lower:
            violations.append(
                f"Judgment text does not mention section '{section}'."
            )

        # -- must mention burden_stage --------------------------------------
        if burden_stage and burden_stage.lower() not in text_lower:
            violations.append(
                f"Judgment text does not mention burden_stage "
                f"'{burden_stage}'."
            )

        # -- fully_negated → must not claim conviction ----------------------
        if fully_negated:
            # The judgment should not contain an unqualified conviction claim.
            # We look for a verdict line claiming CONVICT without qualifiers.
            if re.search(
                r"majority\s+verdict\s*:\s*convict", text_lower,
            ):
                violations.append(
                    "Judgment claims CONVICT but fully_negated is True."
                )

        # -- acquittal_recommended → must contain "acquit" ------------------
        # Strip occurrences of the raw burden-stage token so that
        # "acquittal_recommended" alone does not satisfy the check.
        text_sans_stage = text_lower.replace(burden_stage.lower(), "")
        if burden_stage == "acquittal_recommended" and "acquit" not in text_sans_stage:
            violations.append(
                "burden_stage is 'acquittal_recommended' but judgment "
                "does not contain 'acquit'."
            )

        # -- prima_facie_established → must contain "convict" or "proceed" --
        if burden_stage == "prima_facie_established":
            if "convict" not in text_lower and "proceed" not in text_lower:
                violations.append(
                    "burden_stage is 'prima_facie_established' but judgment "
                    "contains neither 'convict' nor 'proceed'."
                )

        return {"valid": len(violations) == 0, "violations": violations}

    # ------------------------------------------------------------------ #
    # 4. Citation validation                                               #
    # ------------------------------------------------------------------ #

    def validate_citations(
        self,
        case_analysis: dict,
        simulation_output: dict,
        research_data: dict,
    ) -> Dict[str, Any]:
        """
        Validate that simulation outputs do not fabricate citations.

        Checks
        ------
        *   Any cited precedent in the simulation must exist in
            ``research_data["precedents"]``.
        *   If ``research_data`` is empty, the simulation must not
            cite external cases.

        Parameters
        ----------
        case_analysis : dict
            Deterministic analysis dict (unused for now but available
            for future rules).
        simulation_output : dict
            Full simulation result (lawyer_output, panel_result,
            final_judgment, etc.).
        research_data : dict
            Output of ``ResearchAggregator.enrich()``.

        Returns
        -------
        dict
            ``{"valid": bool, "violations": list[str]}``
        """
        violations: List[str] = []

        # Build set of known precedent titles (lowered) for fast lookup
        known_titles: Set[str] = set()
        known_citations: Set[str] = set()
        for p in research_data.get("precedents", []):
            t = p.get("title", "")
            c = p.get("citation", "")
            if t:
                known_titles.add(t.lower())
            if c:
                known_citations.add(c.lower())

        # Collect all text surfaces from the simulation that might
        # contain citations.  We check: lawyer prosecution/defense args,
        # judge reasoning points, and the final judgment text.
        simulation_texts: List[str] = []

        lawyer = simulation_output.get("lawyer_output", {})
        simulation_texts.extend(lawyer.get("prosecution_arguments", []))
        simulation_texts.extend(lawyer.get("defense_arguments", []))

        panel = simulation_output.get("panel_result", {})
        for j in panel.get("judges", []):
            simulation_texts.extend(j.get("key_reasoning_points", []))
            simulation_texts.extend(j.get("concerns", []))

        final_text = simulation_output.get("final_judgment", "")
        if final_text:
            simulation_texts.append(final_text)

        # Extract cited case names using a simple heuristic:
        # Patterns like "... v. ..." or "... vs ..." (common in Indian law)
        cited = self._extract_case_citations(simulation_texts)

        if not known_titles and not known_citations:
            # No research data — simulation must not cite any external case
            if cited:
                for c in sorted(cited):
                    violations.append(
                        f"Simulation cites '{c}' but no research data "
                        f"is available."
                    )
        else:
            for c in sorted(cited):
                c_lower = c.lower()
                # Check if referenced in any known title or citation
                if not any(
                    c_lower in t for t in known_titles
                ) and not any(
                    c_lower in ci for ci in known_citations
                ):
                    violations.append(
                        f"Simulation cites '{c}' which is not found "
                        f"in research precedents."
                    )

        return {"valid": len(violations) == 0, "violations": violations}

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_case_citations(texts: List[str]) -> Set[str]:
        """
        Extract case citations from text surfaces.

        Matches patterns like ``State of UP v. Ram Kumar`` or
        ``Party A vs Party B`` — common in Indian legal citations.
        Each party name must start with an uppercase letter and may
        contain additional capitalised words or connecting words
        (of, the, and, for, in).
        """
        _PARTY = (
            r'[A-Z][A-Za-z.]*'
            r'(?:'
            r'\s+(?:of|the|and|for|in)\s+[A-Z][A-Za-z.]*'
            r'|\s+[A-Z][A-Za-z.]*'
            r')*'
        )
        pattern = re.compile(
            rf'\b({_PARTY})\s+(?:v\.?|vs\.?)\s+({_PARTY})',
        )
        found: Set[str] = set()
        for t in texts:
            for m in pattern.finditer(t):
                citation = f"{m.group(1).strip()} v. {m.group(2).strip()}"
                found.add(citation)
        return found

    @staticmethod
    def _expected_risk(confidence: float) -> str:
        """
        Map *confidence* to the expected risk level.

        * confidence > 0.75  → ``"low"``
        * 0.4 ≤ confidence ≤ 0.75 → ``"medium"``
        * confidence < 0.4  → ``"high"``
        """
        if confidence > 0.75:
            return "low"
        if confidence >= 0.4:
            return "medium"
        return "high"
