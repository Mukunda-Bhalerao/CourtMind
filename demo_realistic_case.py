# demo_realistic_case.py
"""
CourtMind — Realistic Case Demo

Builds a murder-with-self-defense fact matrix and runs the full
simulation pipeline: auto-detection → evaluation → lawyer → panel →
judgment → guardrails → research.

Expected behaviour
------------------
*   302 IPC (Murder) and 304 IPC (Culpable Homicide) will compete.
*   Self-defense exception negates the intent element in 302, causing
    the detector to favour 304.
*   The panel deliberates with split verdicts across three judicial styles.
*   Guardrails flag any simulation drift.
"""
from core.fact_matrix import FactMatrix, FactSource
from simulation.run_simulation import run_full_simulation


def build_case():
    fm = FactMatrix()

    # Victim narrative
    fm.add_fact("actus_reus",
                "The accused stabbed the victim during an argument.",
                FactSource.USER_INPUT,
                tags=["act_by_accused", "stabbing"],
                severity="high")

    fm.add_fact("actus_reus",
                "The victim died due to internal bleeding.",
                FactSource.USER_INPUT,
                tags=["death_caused", "homicide"],
                severity="critical")

    fm.add_fact("mens_rea",
                "The accused had threatened the victim earlier.",
                FactSource.USER_INPUT,
                tags=["intention", "premeditated"],
                severity="high")

    fm.add_fact("evidence",
                "CCTV footage shows the accused holding a knife.",
                FactSource.DOCUMENT,
                severity="high")

    fm.add_fact("evidence",
                "Forensic report confirms blood on accused clothes.",
                FactSource.FORENSIC,
                severity="critical")

    # Accused narrative
    fm.add_fact("exceptions_claimed",
                "The accused claims he acted in self-defense.",
                FactSource.USER_INPUT,
                tags=["self-defense"],
                severity="medium")

    return fm


if __name__ == "__main__":
    fm = build_case()

    result = run_full_simulation(fm, auto_detect=True)

    ca = result["case_analysis"]
    section = ca["evaluation_result"]["section"]
    burden = ca["burden_result"]["burden_stage"]
    confidence = ca["burden_result"]["confidence_score"]
    evidence = ca["evidence_weight_result"]["overall_evidence_score"]

    print("\n" + "=" * 60)
    print("  CourtMind — Realistic Case Demo Output")
    print("=" * 60)

    print(f"\n  Detected Section   : {section}")
    print(f"  Burden Stage       : {burden}")
    print(f"  Confidence Score   : {confidence}")
    print(f"  Evidence Score     : {evidence}")

    # Lawyer
    lo = result["lawyer_output"]
    print(f"\n  Confirmed Section  : {lo['confirmed_section']}")
    print(f"  Alternate Sections : {lo['alternate_sections']}")
    print(f"  Risk Level         : {lo['risk_level']}")
    print("  Prosecution Arguments:")
    for a in lo["prosecution_arguments"]:
        print(f"    + {a}")
    print("  Defense Arguments:")
    for a in lo["defense_arguments"]:
        print(f"    - {a}")

    # Panel
    pr = result["panel_result"]
    print(f"\n  Majority Verdict   : {pr['majority_verdict']}")
    print(f"  Vote Split         : {pr['vote_split']}")
    for j in pr["judges"]:
        print(f"    {j['judge_type']:20s} => {j['provisional_verdict']}")

    # Judgment (first 5 + last 5 lines for brevity)
    jlines = result["final_judgment"].strip().splitlines()
    print("\n  Final Judgment (excerpt):")
    for line in jlines[:5]:
        print(f"    {line}")
    if len(jlines) > 10:
        print("    ...")
    for line in jlines[-5:]:
        print(f"    {line}")

    # Guardrails
    gr = result["guardrail_report"]
    print(f"\n  Guardrail — Lawyer Valid    : {gr['lawyer_valid']}")
    print(f"  Guardrail — Judge Results   : {gr['judge_validations']}")
    print(f"  Guardrail — Judgment Valid  : {gr['judgment_valid']}")
    if gr["violations"]:
        print("  Violations:")
        for v in gr["violations"]:
            print(f"    ! {v}")

    # Research
    rd = result["research_data"]
    print(f"\n  Precedents found   : {len(rd['precedents'])}")
    print(f"  Context items      : {len(rd['recent_context'])}")

    print("\n" + "=" * 60)
    print("  Demo complete.")
    print("=" * 60 + "\n")
