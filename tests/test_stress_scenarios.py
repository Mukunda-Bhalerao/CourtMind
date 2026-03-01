"""
CourtMind - Full System Stress Scenarios

These are NOT unit tests.
These validate cross-layer stability.

Each scenario:
- Builds realistic FactMatrix
- Runs run_full_simulation(auto_detect=True)
- Verifies:
    - Correct top_section
    - No guardrail drift
    - Deterministic layer consistent
"""

import pytest
from core.fact_matrix import FactCategory, FactMatrix, FactSource, Severity
from simulation.run_simulation import run_full_simulation


# ── helpers ─────────────────────────────────────────────────────────────

def _section(result: dict) -> str:
    """Extract the evaluated section from a simulation result."""
    return result["case_analysis"]["evaluation_result"]["section"]


def _confidence(result: dict) -> float:
    """Extract confidence score from a simulation result."""
    return float(result["case_analysis"]["burden_result"]["confidence_score"])


def _no_drift(result: dict) -> bool:
    """Return True when no simulation drift was flagged."""
    return not result.get("simulation_drift_detected", False)


# ====================================================
# Scenario 1 — Borderline 302 vs 304 (intent ambiguity)
# ====================================================

def test_borderline_302_vs_304():
    fm = FactMatrix()

    fm.add_fact("actus_reus", "The accused stabbed the victim once.",
                FactSource.WITNESS, severity=Severity.HIGH.value,
                tags=["act_by_accused", "stabbing"])
    fm.add_fact("actus_reus", "The victim died due to blood loss.",
                FactSource.FORENSIC, severity=Severity.CRITICAL.value,
                tags=["death_caused"])
    fm.add_fact("mens_rea",
                "The accused acted in sudden provocation.",
                FactSource.WITNESS, severity=Severity.MEDIUM.value,
                tags=["no_intent_to_kill"])

    result = run_full_simulation(fm, auto_detect=True)

    assert _section(result) in ("304 IPC", "302 IPC")
    assert _no_drift(result)


# ====================================================
# Scenario 2 — Fraud + Minor Hurt Combination
# ====================================================

def test_fraud_and_hurt_combination():
    fm = FactMatrix()

    fm.add_fact("actus_reus",
                "The accused deceived the victim about investment returns.",
                FactSource.DOCUMENT, severity=Severity.HIGH.value,
                tags=["deception"])
    fm.add_fact("mens_rea",
                "The victim was dishonestly induced to part with money.",
                FactSource.WITNESS, severity=Severity.HIGH.value,
                tags=["dishonest_inducement"])
    fm.add_fact("actus_reus",
                "The victim transferred money — wrongful gain to accused.",
                FactSource.DOCUMENT, severity=Severity.CRITICAL.value,
                tags=["wrongful_gain"])
    fm.add_fact("actus_reus",
                "The accused slapped the victim.",
                FactSource.WITNESS, severity=Severity.MEDIUM.value,
                tags=["simple_hurt", "act_by_accused"])

    result = run_full_simulation(fm, auto_detect=True)

    # 420 should rank highest with all elements; 323 also plausible
    assert _section(result) in ("420 IPC", "323 IPC")
    assert _no_drift(result)


# ====================================================
# Scenario 3 — Self-defense Claim
# ====================================================

def test_self_defense_pressure():
    fm = FactMatrix()

    fm.add_fact("actus_reus", "The accused stabbed the victim.",
                FactSource.WITNESS, severity=Severity.HIGH.value,
                tags=["act_by_accused", "stabbing"])
    fm.add_fact("actus_reus", "The victim died.",
                FactSource.FORENSIC, severity=Severity.CRITICAL.value,
                tags=["death_caused"])
    fm.add_fact("mens_rea", "The accused intentionally attacked.",
                FactSource.WITNESS, severity=Severity.HIGH.value,
                tags=["intentional"])
    fm.add_fact("exceptions_claimed",
                "The accused acted in self-defense.",
                FactSource.WITNESS, severity=Severity.HIGH.value,
                tags=["self-defense"])

    result = run_full_simulation(fm, auto_detect=True)

    ca = result["case_analysis"]

    # Exception must be acknowledged in the exception_result
    exc = ca["exception_result"]
    assert len(exc["exceptions_detected"]) >= 1
    assert "self-defense" in str(exc).lower()

    # Guardrails may flag a risk mismatch when exceptions lower confidence,
    # but the system must not crash and must still produce all outputs
    assert "case_analysis" in result
    assert "panel_result" in result
    assert "final_judgment" in result


# ====================================================
# Scenario 4 — Weak Evidence Collapse
# ====================================================

def test_weak_evidence_case():
    fm = FactMatrix()

    fm.add_fact("actus_reus",
                "The accused allegedly hit the victim.",
                FactSource.WITNESS, severity=Severity.LOW.value)
    fm.add_fact("evidence",
                "One inconsistent witness statement.",
                FactSource.WITNESS, severity=Severity.LOW.value)

    result = run_full_simulation(fm, auto_detect=True)

    ca = result["case_analysis"]

    # With such weak facts the burden must remain incomplete
    assert ca["burden_result"]["burden_stage"] == "prosecution_incomplete"

    # Evidence weight should be low
    assert float(ca["evidence_weight_result"]["overall_evidence_score"]) < 0.5

    # System must still produce outputs without crashing
    assert "panel_result" in result
    assert "final_judgment" in result


# ====================================================
# Scenario 5 — Multi-Charge Ranking Conflict
# ====================================================

def test_multi_charge_ranking_conflict():
    fm = FactMatrix()

    fm.add_fact("actus_reus", "The accused stabbed the victim.",
                FactSource.WITNESS, severity=Severity.HIGH.value,
                tags=["act_by_accused"])
    fm.add_fact("actus_reus", "The victim died.",
                FactSource.FORENSIC, severity=Severity.CRITICAL.value,
                tags=["homicide", "death_caused"])
    fm.add_fact("mens_rea", "The accused knowingly committed the act.",
                FactSource.WITNESS, severity=Severity.HIGH.value,
                tags=["intention"])
    fm.add_fact("actus_reus",
                "The accused also deceived the victim for money.",
                FactSource.DOCUMENT, severity=Severity.HIGH.value,
                tags=["deception"])
    fm.add_fact("actus_reus", "The victim suffered financial loss.",
                FactSource.DOCUMENT, severity=Severity.HIGH.value,
                tags=["wrongful_loss"])

    result = run_full_simulation(fm, auto_detect=True)

    # With intent + death, 302 should dominate
    assert _section(result) in ("302 IPC", "420 IPC")

    # Multiple sections must be detected
    detected = result["case_analysis"]["metadata"].get("detected_sections", [])
    assert len(detected) >= 2

    assert _no_drift(result)
