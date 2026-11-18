# CourtMind

Deterministic legal analysis engine with animated courtroom simulation. Zero LLM in the core — pure rule-based fact evaluation, burden-of-proof staging, multi-section auto-detection, and a simulation layer that produces lawyer arguments, three-judge panel deliberation, and structured judgments.

Key capabilities:
- **Automated fact extraction** from plain-text case narratives (Ollama LLM → keyword fallback)
- **IPC section auto-detection** with exception penalty and severity tie-breaking  
- **Multi-hearing iterative simulation** with 8 judge feedback loops
- **Legal strategy analysis** (prosecution/defense strategies, weak element detection, conviction probability)
- **Animated courtroom UI** — step-by-step event timeline with actor cards, speech bubbles, verdict overlay
- **Full case report panel** — element status, burden analysis, evidence weights, research, strategy, panel deliberation, judgment, explanation, guardrails
- **Report export** — JSON and Markdown via `ReportGenerator`
- **606 tests. No hallucination.**

---

## System Flow

```
                        ┌──────────────────────┐
                        │  Case Text / File     │
                        │  (.txt / .pdf / .docx)│
                        └──────────┬────────────┘
                                   │
                        ┌──────────▼────────────┐
                        │   FactExtractor        │
                        │  Ollama LLM → keyword  │
                        │  fallback (negation-   │
                        │  aware matching)       │
                        └──────────┬────────────┘
                                   │
                        ┌──────────▼────────────┐
                        │     FactMatrix         │
                        │  (structured facts)    │
                        └──────────┬────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │    SectionAutoDetector        │
                    │  Ranks all IPC sections by    │
                    │  combined score + exception   │
                    │  penalty + severity tiebreak  │
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │           EvaluationPipeline             │
              │                                          │
              │  StatuteEvaluator (302/304/420/323)      │
              │         ↓                                │
              │  ExceptionEngine                         │
              │         ↓                                │
              │  BurdenEngine                            │
              │         ↓                                │
              │  EvidenceWeightEngine                    │
              │         ↓                                │
              │  → CaseAnalysis (dict)                   │
              └────────────────────┬────────────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │           Simulation Layer               │
              │                                          │
              │  LawyerAgent                             │
              │         ↓                                │
              │  3× JudgeAgent (panel)                   │
              │    textualist · evidence · burden         │
              │         ↓                                │
              │  PanelEngine (majority vote,             │
              │    exception-aware tie-breaking)         │
              │         ↓                                │
              │  JudgmentWriter (narrative)              │
              └────────────────────┬────────────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │         SimulationGuardrails             │
              │  Validates lawyer, judges, judgment,     │
              │  citations vs deterministic analysis     │
              └────────────────────┬────────────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │         ResearchAggregator               │
              │  PrecedentEngine (Indian Kanoon API)     │
              │  ContextEngine (Serper web search)       │
              └────────────────────┬────────────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │      Strategy + Explainability           │
              │  StrategyEngine (deterministic)          │
              │  ExplanationEngine (LLM opt.)            │
              │  → StrategyReport + Narrative            │
              └────────────────────┬────────────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │      SimulationEventGenerator            │
              │  Converts result → ordered timeline      │
              │  of courtroom events for animated UI     │
              └────────────────────┬────────────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │          FastAPI Web Server              │
              │  POST /analyze → simulation.html         │
              │  Animated courtroom + Full Report panel  │
              └─────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- **Python 3.11+** ([download](https://www.python.org/))
- No LLM required — core engine is fully deterministic
- Ollama optional — only for richer fact extraction and explanations

### Setup

```bash
git clone <repo-url>
cd CourtMind

python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

### Run Tests (606 tests)

```bash
python -m pytest tests/ -v
```

### Run Demo (CLI)

```bash
python demo_realistic_case.py
```

Builds a murder + self-defense case, runs the full pipeline, and prints section, burden, confidence, evidence score, lawyer arguments, three-judge panel verdict, judgment narrative, and guardrail report.

### Run Web UI

```bash
cd court_mind_web
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** — paste or upload a case file and hit **Analyze**.

---

## Web Interface

### Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Landing page — paste case text or upload file |
| `/analyze` | POST | Main analysis endpoint → animated courtroom simulation |
| `/upload-case` | POST | Parse uploaded file, return extracted text (JSON) |
| `/simulate` | POST | Legacy endpoint — four-field form (victim/accused/evidence/exceptions) |

### Input Formats

`POST /analyze` accepts either:
- **File upload** — `.txt`, `.pdf`, `.docx`
- **Pasted text** — plain case narrative in the textarea

When both are provided, the file takes priority.

### Animated Courtroom UI (`simulation.html`)

After analysis, the browser renders a 3-column courtroom layout:

```
┌─────────────┬─────────────────────┬─────────────┐
│  Victim     │   Courtroom         │  Judge 1    │
│  Accused    │   Transcript /      │  Judge 2    │
│             │   Evidence Board    │  Judge 3    │
└─────────────┴─────────────────────┴─────────────┘
                   ↓ verdict overlay
         [ GUILTY / NOT GUILTY / NEEDS FURTHER REVIEW ]
              [ Replay ]  [ Full Report ]  [ Home ]
```

**Playback controls:** Play/Pause, Prev, Next, speed selector (0.5× – 3×), progress bar.

**Verdict overlay** maps internal verdicts:

| Internal | Displayed |
|----------|-----------|
| `convict` | GUILTY |
| `acquit` | NOT GUILTY |
| `review` | NEEDS FURTHER REVIEW |

**Full Case Report panel** (opened via the "Full Report" button) renders:
1. **Element Status** — per-element table (✔/✖, supporting fact count, weight)
2. **Confidence & Burden Analysis** — burden stage, confidence score, reasoning flags
3. **Evidence Weight Analysis** — overall score + per-element scores
4. **Research Results** — precedent cases (Indian Kanoon) + web context (Serper)
5. **Strategy Analysis** — prosecution strategy, defense strategy, conviction probability, risk level
6. **Panel Deliberation** — each judge's verdict and reasoning points
7. **Final Judgment** — full narrative text
8. **Case Explanation** — structured markdown explanation
9. **Guardrail Report** — safe/unsafe, any violations

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

## Demo Cases

Four ready-to-use case files in `demo_cases/`:

| File | Section | Scenario |
|------|---------|----------|
| `302_murder.txt` | 302 IPC | Premeditated stabbing with witnesses |
| `304_sudden_fight.txt` | 304 IPC | Bar fight resulting in death, self-defense claimed |
| `420_fraud.txt` | 420 IPC | Investment fraud scheme |
| `323_assault.txt` | 323 IPC | Physical altercation causing hurt |

---

## Architecture

### Layer 0 — Fact Extraction (`core/fact_extractor.py`)

Converts raw case narrative text into a populated `FactMatrix`.

- **Primary**: Calls a local Ollama instance (model: `llama3.2` by default, overridden by `OLLAMA_MODEL` env var). Returns structured JSON with actus_reus, mens_rea, evidence, exceptions fields.
- **Fallback**: Negation-aware keyword matching — recognises IPC-relevant phrases and correctly handles negations (e.g., "did not intend" is NOT tagged as intent).
- The LLM is used **only for extraction** — all downstream legal reasoning remains deterministic.

```python
from core.fact_extractor import extract_facts, extract_facts_keyword_only

# With Ollama (auto-falls back to keyword if Ollama unreachable):
fm = extract_facts("Ravi stabbed Mohan with a knife. Mohan died.")

# Keyword-only (always works, no Ollama needed):
fm = extract_facts_keyword_only("Ravi stabbed Mohan with a knife.")
```

### Layer 1 — Deterministic Core (`core/`)

Zero LLM. Pure rule-based.

| Module | Purpose |
|--------|---------|
| `fact_matrix.py` | Categorised fact storage (actus_reus, mens_rea, evidence, conflicts, exceptions_claimed) with dedup, severity, tags |
| `ontology.py` | `LegalTag` enum, oppositional pairs, `SECTION_ELEMENT_ONTOLOGY` (section → element → tag-set), `EXCEPTION_NEGATION_MAP` |
| `statute_engine.py` | `StatuteEvaluator` base class, `ElementSpec` matching (tags + keywords + severity), `IPC302Evaluator` |
| `evaluators/` | `IPC304Evaluator`, `IPC420Evaluator`, `IPC323Evaluator` |
| `section_registry.py` | Registry mapping section codes → evaluator instances |
| `section_auto_detector.py` | Evaluates all registered sections, scores `combined = conf×0.4 + evidence×0.2 + satisfaction_ratio×0.3 + burden_mult×0.1`, applies exception penalty (`-0.15 × negated_elements`), uses section severity for tie-breaking (less severe wins) |
| `burden_engine.py` | Burden-of-proof staging: prosecution_incomplete → reasonable_doubt → prima_facie_established → acquittal_recommended etc. |
| `evidence_weight_engine.py` | Per-element and overall evidence scoring |
| `exception_engine.py` | Detects claimed exceptions (self-defense, insanity, duress etc.), computes negated elements via `EXCEPTION_NEGATION_MAP` |
| `evaluation_pipeline.py` | Chains evaluator → exception → burden → evidence_weight into a single `CaseAnalysis` |
| `simulation_guardrails.py` | Validates simulation outputs against deterministic analysis — section match, element references, risk-level consistency, burden alignment, citation verification |
| `fact_extractor.py` | LLM + keyword-fallback fact extraction from raw text |
| `report_generator.py` | `ReportGenerator` — exports simulation results as JSON or Markdown |

### Layer 2 — Simulation (`simulation/`)

Deterministic-first courtroom simulation. No facts invented.

| Module | Purpose |
|--------|---------|
| `lawyer_agent.py` | Generates prosecution/defense arguments, risk assessment, weakness identification — all derived from `CaseAnalysis` fields |
| `judge_agent.py` | Three judicial styles: textualist (element-by-element), evidence_focused (score-weighted, exception-aware), burden_strict (stage compliance) |
| `panel_engine.py` | Runs 3-judge panel, computes majority verdict + vote split. 3-way tie → `review`. Exception-aware two-way tie-breaking (acquit wins when exceptions supported) |
| `judgment_writer.py` | Composes structured judgment narrative from analysis + panel result |
| `hearing_manager.py` | Multi-hearing iterative orchestration |
| `run_simulation.py` | Entry point: `run_full_simulation(fact_matrix, auto_detect=True)` → returns `case_analysis`, `lawyer_output`, `panel_result`, `final_judgment`, `guardrail_report`, `research_data`, `strategy_report`, `explanation`, `simulation_events` |

### Layer 3 — Research (`research/`)

Optional enrichment. Safe no-op when API keys absent.

| Module | Purpose |
|--------|---------|
| `precedent_engine.py` | Fetches case law from Indian Kanoon API |
| `context_engine.py` | Web search for recent legal context via Serper API |
| `research_aggregator.py` | Combines precedents + context into enrichment payload |

### Layer 4 — Web Interface (`court_mind_web/`)

| Module | Purpose |
|--------|---------|
| `main.py` | FastAPI app — file/text input → `extract_facts` → `run_full_simulation` → animated courtroom UI with cache-busted JS |
| `templates/index.html` | Landing page — file upload + text input form |
| `templates/simulation.html` | Animated 3-column courtroom with verdict overlay and report panel |
| `static/js/simulation_player.js` | Playback engine — steps through events, updates actor cards, speech bubbles, evidence board, renders full report panel |
| `static/styles.css` | Supplementary styles |
| `utils/` | File parsing helpers (txt/pdf/docx) |

### Layer 5 — Strategy + Explainability (`strategy/`)

Deterministic strategy analysis with optional LLM explanation.

| Module | Purpose |
|--------|--------|
| `strategy_models.py` | `WeakElement`, `StrongElement`, `StrategyReport` dataclasses with `to_dict()` / `to_json()` |
| `strategy_engine.py` | Deterministic analysis: weak/strong element detection, prosecution/defense strategies, evidence recommendations, conviction probability, risk classification |
| `explanation_engine.py` | Human-readable case explanation — deterministic fallback always available; optional Ollama LLM for richer narrative |

**StrategyEngine** produces a `StrategyReport` with:
- **Weak elements**: `not_satisfied`, `partial`, `conflicted` required elements
- **Strong elements**: `satisfied` elements with score ≥ 0.7 or ≥ 2 supporting facts
- **Prosecution strategy**: element-specific strengthening advice, motive suggestions, confidence warnings
- **Defense strategy**: exploit weak elements, leverage exceptions, challenge evidence reliability
- **Evidence recommendations**: element-specific templates (autopsy, CCTV, financial records, etc.)
- **Conviction probability**: `confidence × 0.5 + evidence_score × 0.4 + burden_multiplier × 0.1`
- **Risk level**: `high` (≥ 0.75), `moderate` (0.5–0.75), `low` (< 0.5)

### Layer 6 — Simulation Events (`simulation_events/`)

Converts simulation results into a chronological event timeline for the animated UI.

| Module | Purpose |
|--------|--------|
| `event_models.py` | `EventType` enum (15 types), `Event` dataclass, `EventTimeline` container |
| `event_generator.py` | `SimulationEventGenerator` — reads simulation result and produces ordered events with natural-language messages using `_ELEMENT_DESCRIPTION` and `_VERDICT_LABEL` maps |

**Event types:** `CASE_START`, `VICTIM_STATEMENT`, `ACCUSED_STATEMENT`, `PROSECUTOR_ARGUMENT`, `DEFENSE_ARGUMENT`, `EVIDENCE_PRESENTED`, `JUDGE_QUESTION`, `JUDGE_THINKING`, `PANEL_DELIBERATION`, `JUDGE_VOTE`, `VERDICT_DELIVERED`, `STRATEGY_PRESENTED`, `EXPLANATION_DISPLAYED`, `HEARING_FEEDBACK`, `HEARING_UPDATE`

**Courtroom flow order:**
```
CASE_START → VICTIM_STATEMENT → ACCUSED_STATEMENT
  → PROSECUTOR_ARGUMENT → DEFENSE_ARGUMENT → EVIDENCE_PRESENTED
  → JUDGE_THINKING → PANEL_DELIBERATION → JUDGE_VOTE
  → VERDICT_DELIVERED → STRATEGY_PRESENTED → EXPLANATION_DISPLAYED
```

### Legacy Layer (`agents/`, `interface/`, `app.py`)

Original LLM-based multi-agent system (LangGraph + Ollama/Groq). Still functional but independent from the deterministic core.

---

## How Auto-Detection Works

1. `SectionAutoDetector` iterates every section in `SectionRegistry`
2. For each section, runs the full `EvaluationPipeline`
3. Extracts `confidence_score`, `overall_evidence_score`, `burden_stage`, and `element_details`
4. Computes: **`combined = confidence×0.4 + evidence×0.2 + satisfaction_ratio×0.3 + burden_mult×0.1`**
   - `satisfaction_ratio` = required elements with `status=="satisfied"` / total required elements
5. **Exception penalty**: if supported exceptions negate elements, subtracts `0.15 × number_of_negated_elements`
6. Filters sections below threshold (0.25)
7. On score ties, **less-severe section wins** (benefit of the doubt): 302 > 304 > 420 > 323 in severity; lower severity wins ties

Burden multipliers: `prima_facie_established=0.8`, `defense_rebuttal_required=0.5`, `exception_established=0.4`, `reasonable_doubt=0.3`, `manual_review_required=0.3`, `prosecution_incomplete=0.2`, `acquittal_recommended=0.1`

---

## How the Panel Verdict Works

Three judges deliberate independently using different judicial styles:

| Judge | Style | Logic |
|-------|-------|-------|
| **textualist** | Element-by-element | Votes convict only if all required elements satisfied; votes acquit if any required element unsatisfied or exception present |
| **evidence_focused** | Score-weighted | Normal: convict if evidence ≥ 0.5 and confidence ≥ 0.6. When exceptions are supported: requires evidence ≥ 0.8 AND confidence ≥ 0.8, else votes review |
| **burden_strict** | Stage compliance | Only convicts at `prima_facie_established`; acquits at `prosecution_incomplete` / `acquittal_recommended`; review otherwise |

**Majority rules (3 votes → 2+1 majority wins):**
- 3-way split (all three disagree) → `"review"`
- 2-way tie on leading verdict → checks for supported exceptions: if "acquit" is tied and exceptions exist → `"acquit"`; otherwise → `"review"`

---

## How Guardrails Work

After simulation, `SimulationGuardrails` validates:

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

## Multi-Hearing Simulation Architecture

The `HearingManager` orchestrates iterative hearing rounds where judges request additional information before a final verdict.

### Enabling Multi-Hearing Mode

```python
from simulation.run_simulation import run_full_simulation

# Single-pass (default):
result = run_full_simulation(fm, auto_detect=True)

# Multi-hearing (iterative):
result = run_full_simulation(fm, auto_detect=True, iterative=True, max_hearings=5)
```

### 8 Judge Feedback Loops

| # | Type | Trigger | Action |
|---|------|---------|--------|
| 1 | **Evidence Expansion** | `evidence_score <= 0.6` | Request additional evidence facts |
| 2 | **Clarification** | Element status is `partial` or `not_satisfied` | Request clarification for specific element |
| 3 | **Exception Validation** | Exception claimed but `supported=False` | Request supporting evidence for exception |
| 4 | **Section Re-evaluation** | Auto-detector suggests different section | Re-rank sections with new facts |
| 5 | **Conflict Resolution** | FactMatrix has unresolved conflicts | Request clarifying evidence to resolve contradictions |
| 6 | **Argument Refinement** | Guardrail violations detected | LawyerAgent regenerates arguments |
| 7 | **Precedent / Research** | Low confidence or ambiguous burden stage | ResearchAggregator fetches case law |
| 8 | **Sentencing Phase** | `majority_verdict == "convict"` | Compute sentencing recommendation |

### Stop Conditions

- Verdict stable (same verdict in consecutive hearings)
- No pending updates
- Max hearings reached (default 5)

---

## Environment Variables

Create `.env` in project root:

```bash
# Optional — only needed for research enrichment
KANOON_API_KEY=your_kanoon_api_key
SERPER_API_KEY=your_serper_api_key

# Optional — only for LLM-based fact extraction and ExplanationEngine
OLLAMA_MODEL=llama3.2
```

The deterministic core needs **no API keys**. Research enrichment and LLM extraction degrade gracefully to empty/keyword results when keys/Ollama are absent.

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
│   ├── section_auto_detector.py   # Multi-section scoring, exception penalty, severity tiebreak
│   ├── burden_engine.py           # Burden-of-proof staging
│   ├── evidence_weight_engine.py  # Evidence scoring per element
│   ├── exception_engine.py        # Exception detection + element negation
│   ├── evaluation_pipeline.py     # Full pipeline → CaseAnalysis
│   ├── simulation_guardrails.py   # Output validation layer
│   ├── fact_extractor.py          # LLM + keyword-fallback fact extraction
│   └── report_generator.py        # JSON and Markdown export
│
├── simulation/                    # Courtroom simulation
│   ├── lawyer_agent.py            # Prosecution + defense argument generation
│   ├── judge_agent.py             # Three judicial styles (exception-aware)
│   ├── panel_engine.py            # 3-judge majority vote + exception tie-breaking
│   ├── judgment_writer.py         # Structured judgment narrative
│   ├── hearing_manager.py         # Multi-hearing iterative orchestration
│   └── run_simulation.py          # Entry point: run_full_simulation()
│
├── research/                      # Optional enrichment
│   ├── precedent_engine.py        # Indian Kanoon case law
│   ├── context_engine.py          # Web search context
│   └── research_aggregator.py     # Combined enrichment
│
├── strategy/                      # Strategy + Explainability layer
│   ├── strategy_models.py         # WeakElement, StrongElement, StrategyReport
│   ├── strategy_engine.py         # Deterministic strategy analysis
│   └── explanation_engine.py      # Explanation with optional Ollama LLM
│
├── simulation_events/             # Event timeline for animated UI
│   ├── event_models.py            # EventType enum, Event, EventTimeline
│   └── event_generator.py         # SimulationEventGenerator
│
├── court_mind_web/                # FastAPI web interface
│   ├── main.py                    # Routes, fact extraction, simulation dispatch
│   ├── requirements.txt           # fastapi, uvicorn, jinja2, python-multipart
│   ├── templates/
│   │   ├── index.html             # Landing page — file upload + text input
│   │   └── simulation.html        # Animated courtroom + report panel
│   ├── static/
│   │   ├── js/simulation_player.js # Playback engine + report rendering
│   │   └── styles.css
│   └── utils/                     # File parsing (txt/pdf/docx)
│
├── demo_cases/                    # Ready-to-use case files
│   ├── 302_murder.txt
│   ├── 304_sudden_fight.txt
│   ├── 420_fraud.txt
│   └── 323_assault.txt
│
├── tests/                         # 606 tests
│   ├── test_fact_matrix.py
│   ├── test_ontology.py
│   ├── test_statute_engine.py
│   ├── test_burden_engine.py
│   ├── test_evidence_weight_engine.py
│   ├── test_exception_engine.py
│   ├── test_evaluation_pipeline.py
│   ├── test_section_registry.py
│   ├── test_section_auto_detector.py
│   ├── test_simulation_guardrails.py
│   ├── test_research_layer.py     # Includes ReportGenerator tests
│   ├── test_ipc_accuracy.py       # 24 IPC detection accuracy tests
│   ├── test_ipc_expansion.py      # 304/420/323 integration
│   ├── test_stress_scenarios.py   # Cross-layer stability (5 scenarios)
│   ├── test_hearing_manager.py    # Multi-hearing cycle (55 tests)
│   ├── test_strategy_engine.py    # Strategy + explainability (52 tests)
│   └── test_simulation_events.py  # Event timeline generation (46 tests)
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
from core.fact_extractor import extract_facts, extract_facts_keyword_only
from simulation.run_simulation import run_full_simulation

# Option A: extract facts from raw text (Ollama → keyword fallback)
fm = extract_facts("Ravi stabbed Mohan. Mohan died from injuries.")

# Option B: keyword-only (no Ollama required)
fm = extract_facts_keyword_only("Ravi stabbed Mohan. Mohan died from injuries.")

result = run_full_simulation(fm, auto_detect=True)

print(result["case_analysis"]["evaluation_result"]["section"])         # "302 IPC"
print(result["case_analysis"]["burden_result"]["burden_stage"])        # "prima_facie_established"
print(result["panel_result"]["majority_verdict"])                      # "convict"
print(result["guardrail_report"]["violations"])                        # []
print(result["strategy_report"]["risk_level"])                         # "high"
print(result["strategy_report"]["conviction_probability_estimate"])    # 0.76

# Export report
from core.report_generator import ReportGenerator
gen = ReportGenerator()
print(gen.to_markdown(result))   # Full Markdown report
print(gen.to_json(result))       # JSON string

# Simulation events for animated UI
events = result["simulation_events"]
print(events["total_events"])    # 15+
for ev in events["events"][:3]:
    print(f"  {ev['event_type']:25s} {ev['actor']:12s} {ev['message'][:60]}")
```

---

## Adding a New IPC Section

1. **Ontology** — Add `LegalTag` members + `SECTION_ELEMENT_ONTOLOGY` entry in `core/ontology.py`
2. **Evaluator** — Create `core/evaluators/ipc_XXX.py` subclassing `StatuteEvaluator` with `SECTION`, `SECTION_TITLE`, `ELEMENTS`
3. **Registry** — Import and register in `core/section_registry.py`
4. **Severity** — Add section code + severity score to `_SECTION_SEVERITY` in `core/section_auto_detector.py`
5. **Tests** — Add evaluator + auto-detection tests
6. Run `python -m pytest tests/ -v` — must stay green

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
| `test_section_auto_detector.py` | ~25 | Scoring, ranking, exception penalty, threshold |
| `test_simulation_guardrails.py` | ~50 | All guardrail checks: section, element refs, risk, burden, judgment, citations |
| `test_research_layer.py` | ~30 | Precedent + context + aggregator + ReportGenerator |
| `test_ipc_accuracy.py` | 24 | IPC section detection accuracy across case types |
| `test_ipc_expansion.py` | 24 | 304/420/323 evaluators, auto-detection, simulation, integration |
| `test_stress_scenarios.py` | 5 | Cross-layer: borderline 302/304, fraud+hurt, self-defense, weak evidence, multi-charge |
| `test_hearing_manager.py` | 55 | Multi-hearing cycle, 8 feedback loops, sentencing, backward compat |
| `test_strategy_engine.py` | 52 | Strategy analysis, explainability, end-to-end system |
| `test_simulation_events.py` | 46 | Event timeline generation, event types, actor assignments |


---

---

## 🚀 Deployment

The web app deploys to **Render (free tier)** straight from GitHub using the included `render.yaml` blueprint.
See **[DEPLOY.md](DEPLOY.md)** for the step-by-step guide.
