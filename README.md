# CourtMind

Deterministic legal analysis engine with courtroom simulation. Zero LLM in the core — pure rule-based fact evaluation, burden-of-proof staging, multi-section auto-detection, and a simulation layer that produces lawyer arguments, three-judge panel deliberation, and structured judgments. **404 tests. No hallucination.**

---

## System Flow

```
                        ┌──────────────┐
                        │  FactMatrix  │
                        │  (user input)│
                        └──────┬───────┘
                               │
                    ┌──────────▼───────────┐
                    │  SectionAutoDetector  │
                    │  Ranks all IPC sections│
                    │  by combined score    │
                    └──────────┬───────────┘
                               │
              ┌────────────────▼────────────────┐
              │       EvaluationPipeline         │
              │                                  │
              │  StatuteEvaluator (302/304/420/323)│
              │         ↓                        │
              │  ExceptionEngine                 │
              │         ↓                        │
              │  BurdenEngine                    │
              │         ↓                        │
              │  EvidenceWeightEngine            │
              │         ↓                        │
              │  → CaseAnalysis (dict)           │
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │       Simulation Layer           │
              │                                  │
              │  LawyerAgent                     │
              │         ↓                        │
              │  3× JudgeAgent (panel)           │
              │    textualist · evidence · burden │
              │         ↓                        │
              │  PanelEngine (majority vote)      │
              │         ↓                        │
              │  JudgmentWriter (narrative)       │
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │    SimulationGuardrails          │
              │  Validates lawyer, judges,       │
              │  judgment, citations vs          │
              │  deterministic analysis          │
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │    ResearchAggregator            │
              │  PrecedentEngine (Kanoon API)    │
              │  ContextEngine (web search)      │
              └────────────────┬────────────────┘
                               │
                        ┌──────▼───────┐
                        │ Final Result │
                        └──────────────┘
```

---

## Quick Start

### Prerequisites

- **Python 3.11+** ([download](https://www.python.org/))
- No LLM required — core engine is fully deterministic

### Setup

```bash
# Clone
git clone <repo-url>
cd CourtMind

# Virtual environment
python -m venv venv

# Activate
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Run Tests (404 tests)

```bash
python -m pytest tests/ -v
```

### Run Demo

```bash
python demo_realistic_case.py
```

Builds a murder + self-defense case, runs the full pipeline, and prints:
- Detected section, burden stage, confidence, evidence score
- Lawyer prosecution/defense arguments
- Three-judge panel deliberation and verdict
- Final judgment narrative
- Guardrail report (drift detection)

### Run Web UI

```bash
cd court_mind_web
pip install -r requirements.txt
uvicorn main:app --reload
```

Open **http://127.0.0.1:8000** — enter victim/accused/evidence/exception narratives and hit **Run Simulation**.

---

## Supported IPC Sections

| Section | Title | Required Elements |
|---------|-------|-------------------|
| **302 IPC** | Murder | death_of_human, act_by_accused, intention_or_knowledge, supporting_evidence (optional) |
| **304 IPC** | Culpable Homicide not amounting to Murder | death_of_human, act_by_accused, knowledge_element |
| **420 IPC** | Cheating | deception_element, inducement_element, gain_loss_element |
| **323 IPC** | Voluntarily Causing Hurt | hurt_element, act_by_accused |

The `SectionRegistry` is extensible — add new sections by subclassing `StatuteEvaluator` and registering.

---

## Architecture

### Layer 1 — Deterministic Core (`core/`)

Zero LLM. Pure rule-based.

| Module | Purpose |
|--------|---------|
| `fact_matrix.py` | Categorised fact storage (actus_reus, mens_rea, evidence, conflicts, exceptions_claimed) with dedup, severity, tags |
| `ontology.py` | `LegalTag` enum, oppositional pairs, `SECTION_ELEMENT_ONTOLOGY` (section → element → tag-set), `EXCEPTION_NEGATION_MAP` |
| `statute_engine.py` | `StatuteEvaluator` base class, `ElementSpec` matching (tags + keywords + severity), `IPC302Evaluator` |
| `evaluators/` | `IPC304Evaluator`, `IPC420Evaluator`, `IPC323Evaluator` |
| `section_registry.py` | Registry mapping section codes → evaluator instances |
| `section_auto_detector.py` | Evaluates all registered sections, scores `combined = conf×0.6 + evidence×0.3 + burden_mult×0.1`, returns ranked list |
| `burden_engine.py` | Burden-of-proof staging: prosecution_incomplete → reasonable_doubt → prima_facie_established → acquittal_recommended etc. |
| `evidence_weight_engine.py` | Per-element and overall evidence scoring |
| `exception_engine.py` | Detects claimed exceptions (self-defense, insanity, duress etc.), computes negated elements via `EXCEPTION_NEGATION_MAP` |
| `evaluation_pipeline.py` | Chains evaluator → exception → burden → evidence_weight into a single `CaseAnalysis` |
| `simulation_guardrails.py` | Validates simulation outputs against deterministic analysis — section match, element references, risk-level consistency, burden alignment, citation verification |

### Layer 2 — Simulation (`simulation/`)

Deterministic-first courtroom simulation. No facts invented.

| Module | Purpose |
|--------|---------|
| `lawyer_agent.py` | Generates prosecution/defense arguments, risk assessment, weakness identification — all derived from `CaseAnalysis` fields |
| `judge_agent.py` | Three judicial styles: textualist (element-by-element), evidence_focused (score-weighted), burden_strict (stage compliance) |
| `panel_engine.py` | Runs 3-judge panel, computes majority verdict + vote split |
| `judgment_writer.py` | Composes structured judgment narrative from analysis + panel result |
| `run_simulation.py` | Entry point: `run_full_simulation(fact_matrix, auto_detect=True)` → returns case_analysis, lawyer_output, panel_result, final_judgment, guardrail_report, research_data |

### Layer 3 — Research (`research/`)

Optional enrichment. Safe no-op when API keys absent.

| Module | Purpose |
|--------|---------|
| `precedent_engine.py` | Fetches case law from Indian Kanoon API |
| `context_engine.py` | Web search for recent legal context |
| `research_aggregator.py` | Combines precedents + context into enrichment payload |

### Layer 4 — Web Interface (`court_mind_web/`)

| Module | Purpose |
|--------|---------|
| `main.py` | FastAPI app — form input → FactMatrix → `run_full_simulation` → results page |
| `templates/index.html` | Tailwind-styled courtroom UI with section detection, lawyer output, judgment, guardrails |
| `static/styles.css` | Supplementary styles |

### Legacy Layer (`agents/`, `interface/`, `app.py`)

Original LLM-based multi-agent system (LangGraph + Ollama/Groq). Still functional but independent from the deterministic core.

---

## How Auto-Detection Works

1. `SectionAutoDetector` iterates every section in `SectionRegistry`
2. For each section, runs the full `EvaluationPipeline`
3. Extracts `confidence_score`, `overall_evidence_score`, `burden_stage`
4. Computes: **`combined_score = confidence × 0.6 + evidence × 0.3 + burden_multiplier × 0.1`**
5. Filters out sections below threshold (0.25)
6. Returns sorted list — top section used for simulation

Burden multipliers: `prima_facie_established=0.8`, `defense_rebuttal_required=0.5`, `exception_established=0.4`, `reasonable_doubt=0.3`, `manual_review_required=0.3`, `prosecution_incomplete=0.2`, `acquittal_recommended=0.1`

---

## How Guardrails Work

After the simulation layer produces outputs, `SimulationGuardrails` validates:

| Check | What it catches |
|-------|-----------------|
| **Lawyer section match** | `confirmed_section` must equal the evaluated section |
| **Alternate sections** | Must be subset of auto-detected sections |
| **Prosecution references** | Can only cite satisfied elements |
| **Defense references** | Can only cite failed/conflicted/partial elements or supported exceptions |
| **Risk-level alignment** | Must correlate with confidence score |
| **Judge verdict alignment** | Cannot convict if burden is `prosecution_incomplete` or `acquittal_recommended` |
| **Judgment narrative** | Must mention correct section, must not claim conviction when acquittal is staged |
| **Citation validity** | Case citations must exist in research data |

Any violation is flagged in `guardrail_report["violations"]`. If violations exist, `simulation_drift_detected = True`.

---

## Environment Variables

Create `.env` in project root:

```bash
# Optional — only needed for research enrichment
KANOON_API_KEY=your_kanoon_api_key
SERPER_API_KEY=your_serper_api_key

# Optional — only needed for legacy LLM-based agents
OLLAMA_MODEL=gpt-oss:120b-cloud
```

The deterministic core needs **no API keys**. Research enrichment degrades gracefully to empty results when keys are absent.

---

## Project Structure

```
CourtMind/
├── core/                          # Deterministic engine (zero LLM)
│   ├── fact_matrix.py             # Fact storage, dedup, categories, severity
│   ├── ontology.py                # LegalTag enum, section→element→tag mappings
│   ├── statute_engine.py          # StatuteEvaluator base + IPC302Evaluator
│   ├── evaluators/                # Additional IPC section evaluators
│   │   ├── ipc304.py              # Culpable Homicide
│   │   ├── ipc420.py              # Cheating
│   │   └── ipc323.py              # Voluntarily Causing Hurt
│   ├── section_registry.py        # Section code → evaluator registry
│   ├── section_auto_detector.py   # Multi-section scoring and ranking
│   ├── burden_engine.py           # Burden-of-proof staging
│   ├── evidence_weight_engine.py  # Evidence scoring per element
│   ├── exception_engine.py        # Exception detection + element negation
│   ├── evaluation_pipeline.py     # Full pipeline → CaseAnalysis
│   └── simulation_guardrails.py   # Output validation layer
│
├── simulation/                    # Courtroom simulation
│   ├── lawyer_agent.py            # Prosecution + defense argument generation
│   ├── judge_agent.py             # Three judicial styles
│   ├── panel_engine.py            # 3-judge majority vote
│   ├── judgment_writer.py         # Structured judgment narrative
│   └── run_simulation.py          # Entry point: run_full_simulation()
│
├── research/                      # Optional enrichment
│   ├── precedent_engine.py        # Indian Kanoon case law
│   ├── context_engine.py          # Web search context
│   └── research_aggregator.py     # Combined enrichment
│
├── court_mind_web/                # FastAPI web interface
│   ├── main.py                    # Routes + FactMatrix builder
│   ├── requirements.txt           # fastapi, uvicorn, jinja2, python-multipart
│   ├── templates/index.html       # Tailwind courtroom UI
│   └── static/styles.css
│
├── tests/                         # 404 tests
│   ├── test_fact_matrix.py        # FactMatrix CRUD, dedup, conflicts
│   ├── test_ontology.py           # Tag validation, oppositional pairs
│   ├── test_statute_engine.py     # IPC302 evaluation scenarios
│   ├── test_burden_engine.py      # Burden staging rules
│   ├── test_evidence_weight_engine.py
│   ├── test_exception_engine.py   # Exception detection + negation
│   ├── test_evaluation_pipeline.py
│   ├── test_section_registry.py
│   ├── test_section_auto_detector.py
│   ├── test_simulation_guardrails.py
│   ├── test_research_layer.py
│   ├── test_ipc_expansion.py      # 304/420/323 evaluators + integration
│   └── test_stress_scenarios.py   # Cross-layer stability (5 scenarios)
│
├── agents/                        # Legacy LLM-based agents
├── interface/                     # Legacy Streamlit UI
├── app.py                         # Legacy FastAPI + LangGraph backend
├── demo_realistic_case.py         # CLI demo script
├── requirements.txt               # Python dependencies
└── sample_case.txt                # Example case input
```

---

## Running the Full Pipeline in Code

```python
from core.fact_matrix import FactMatrix, FactSource, Severity
from simulation.run_simulation import run_full_simulation

fm = FactMatrix()

fm.add_fact("actus_reus", "Accused stabbed the victim.",
            FactSource.WITNESS, severity="high",
            tags=["act_by_accused", "stabbing"])

fm.add_fact("actus_reus", "Victim died from injuries.",
            FactSource.FORENSIC, severity="critical",
            tags=["death_caused"])

fm.add_fact("mens_rea", "Accused planned the attack.",
            FactSource.DOCUMENT, severity="high",
            tags=["intention", "premeditated"])

result = run_full_simulation(fm, auto_detect=True)

print(result["case_analysis"]["evaluation_result"]["section"])   # "302 IPC"
print(result["case_analysis"]["burden_result"]["burden_stage"])   # "prima_facie_established"
print(result["panel_result"]["majority_verdict"])                 # "convict"
print(result["guardrail_report"]["violations"])                   # []
```

---

## Adding a New IPC Section

1. **Ontology** — Add `LegalTag` members + `SECTION_ELEMENT_ONTOLOGY` entry in `core/ontology.py`
2. **Evaluator** — Create `core/evaluators/ipc_XXX.py` subclassing `StatuteEvaluator` with `SECTION`, `SECTION_TITLE`, `ELEMENTS`
3. **Registry** — Import and register in `core/section_registry.py`
4. **Tests** — Add evaluator + auto-detection tests
5. Run `python -m pytest tests/ -v` — must stay green

---

## Test Categories

| Test File | Count | What it covers |
|-----------|-------|----------------|
| `test_fact_matrix.py` | ~50 | CRUD, dedup, conflict detection, bulk ops, export |
| `test_ontology.py` | ~30 | Tag validation, oppositional pairs, section mappings |
| `test_statute_engine.py` | ~15 | 302 evaluation: strong/weak/conflicted/exception cases |
| `test_burden_engine.py` | ~40 | All burden stages, confidence scoring, exception handling |
| `test_evidence_weight_engine.py` | ~20 | Per-element + overall scoring |
| `test_exception_engine.py` | ~25 | Exception detection, negation, cross-section coverage |
| `test_evaluation_pipeline.py` | ~30 | Pipeline integration, auto-detect routing |
| `test_section_registry.py` | ~10 | Registration, lookup, listing |
| `test_section_auto_detector.py` | ~25 | Scoring, ranking, threshold, multi-section |
| `test_simulation_guardrails.py` | ~50 | All guardrail checks: section, element refs, risk, burden, judgment, citations |
| `test_research_layer.py` | ~30 | Precedent + context + aggregator with mocked APIs |
| `test_ipc_expansion.py` | 24 | 304/420/323 evaluators, auto-detection, simulation, guardrails, registry, integration |
| `test_stress_scenarios.py` | 5 | Cross-layer: borderline 302/304, fraud+hurt, self-defense, weak evidence, multi-charge |
