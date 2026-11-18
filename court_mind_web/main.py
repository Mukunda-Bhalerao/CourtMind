"""
CourtMind — FastAPI Web Interface

Connects the browser UI → Fact Extraction → FactMatrix → Simulation pipeline.

Flow:
    Upload file / paste text → parse → extract_facts (Ollama + keyword fallback)
    → FactMatrix → run_full_simulation → animated courtroom UI

Usage (from the project root)
-----------------------------
    uvicorn court_mind_web.main:app --reload

Production (Render / any PaaS)
------------------------------
    uvicorn court_mind_web.main:app --host 0.0.0.0 --port $PORT
"""

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Optional

# Ensure the project root is on sys.path so `core.*` / `simulation.*` resolve.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.fact_extractor import (
    extract_facts,
    extract_facts_keyword_only,
    llm_extraction_enabled,
)
from core.fact_matrix import FactMatrix, FactSource
from court_mind_web.utils.file_parser import UnsupportedFileType, parse_file
from research.context_engine import ContextEngine
from research.precedent_engine import PrecedentEngine
from research.research_aggregator import ResearchAggregator
from simulation.run_simulation import run_full_simulation

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("courtmind")

_WEB_DIR = Path(__file__).resolve().parent
APP_VERSION = "2.1.0"

app = FastAPI(title="CourtMind", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpeg", ".mpg"}

# Case files larger than this are rejected (bytes). Evidence files are never
# read, so they are not limited here.
MAX_CASE_FILE_BYTES = int(os.environ.get("MAX_CASE_FILE_MB", "10")) * 1024 * 1024
MAX_CASE_TEXT_CHARS = 100_000


def _load_dotenv() -> None:
    """Load simple KEY=VALUE pairs from the project .env when not already set."""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


# ===============================
# Sample cases (shown on the landing page)
# ===============================
_SAMPLE_DIR = _PROJECT_ROOT / "courtmind_demo_cases"
_SAMPLE_META = {
    "case_1_murder_302": ("Murder", "302", "Premeditated knife attack"),
    "case_2_self_defense_304": ("Sudden Fight", "304", "Bar fight, claimed self-defence"),
    "case_3_cheating_420": ("Cheating", "420", "Investment fraud"),
    "case_4_simple_hurt_323": ("Simple Hurt", "323", "Slaps and punches in an argument"),
    "courtmind_not_guilty_test_case": ("Self-Defence", "—", "Prosecution case with gaps"),
}


def _list_samples() -> List[dict]:
    samples = []
    if not _SAMPLE_DIR.is_dir():
        return samples
    for path in sorted(_SAMPLE_DIR.glob("*.txt")):
        title, section, blurb = _SAMPLE_META.get(
            path.stem, (path.stem.replace("_", " ").title(), "—", "")
        )
        samples.append(
            {"id": path.stem, "title": title, "section": section, "blurb": blurb}
        )
    return samples


# ===============================
# Helpers
# ===============================
def _file_type(upload: UploadFile) -> str:
    """Return lightweight file type metadata without reading file contents."""
    if upload.content_type:
        return upload.content_type
    return Path(upload.filename or "").suffix.lower().lstrip(".") or "unknown"


def _is_allowed_evidence(upload: UploadFile) -> bool:
    content_type = (upload.content_type or "").lower()
    suffix = Path(upload.filename or "").suffix.lower()
    return (
        content_type.startswith("image/")
        or content_type.startswith("video/")
        or content_type == "application/pdf"
        or suffix in IMAGE_EXTENSIONS
        or suffix in VIDEO_EXTENSIONS
        or suffix == ".pdf"
    )


def _evidence_metadata(files: Optional[List[UploadFile]]) -> List[dict]:
    evidence = []
    for upload in files or []:
        if not upload.filename or not _is_allowed_evidence(upload):
            continue
        evidence.append({"filename": upload.filename, "file_type": _file_type(upload)})
    return evidence


def _build_research_aggregator() -> ResearchAggregator:
    """Build a ResearchAggregator with API keys from environment."""
    return ResearchAggregator(
        precedent_engine=PrecedentEngine(kanoon_api_key=os.environ.get("KANOON_API_KEY")),
        context_engine=ContextEngine(serper_api_key=os.environ.get("SERPER_API_KEY")),
    )


def _fetch_display_research(result: dict) -> dict:
    """Fetch display-only research after deterministic simulation completes."""
    try:
        return _build_research_aggregator().enrich(result.get("case_analysis", {}))
    except Exception:
        log.warning("Display research failed", exc_info=True)
        return {
            "precedents": [],
            "recent_context": [],
            "available": False,
            "message": "Research APIs unavailable.",
        }


def _render_index(request: Request, error: Optional[str] = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "error": error,
            "samples": _list_samples(),
            "version": APP_VERSION,
        },
        status_code=status_code,
    )


def _render_simulation(request: Request, result: dict, case_text: str):
    sim_events = result.get("simulation_events", {"events": [], "total_events": 0})
    # Escape "</" so case text can never close the inline <script> tag.
    events_json = json.dumps(sim_events, default=str, ensure_ascii=False).replace("</", "<\\/")
    case_result_json = json.dumps(result, default=str, ensure_ascii=False).replace("</", "<\\/")
    return templates.TemplateResponse(
        request,
        "simulation.html",
        {
            "events_json": events_json,
            "case_result_json": case_result_json,
            "case_excerpt": case_text[:600],
            "cache_bust": APP_VERSION,
        },
    )


def _run_pipeline(fm: FactMatrix) -> dict:
    result = run_full_simulation(
        fm,
        auto_detect=True,
        research_aggregator=_build_research_aggregator(),
    )
    result["research_data"] = _fetch_display_research(result)
    return result


# ===============================
# Routes
# ===============================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return _render_index(request)


@app.get("/health")
@app.get("/healthz")
async def health():
    """Lightweight health check used by the hosting platform."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "llm_extraction": llm_extraction_enabled(),
    }


@app.get("/api/samples")
async def list_samples():
    return {"samples": _list_samples()}


@app.get("/api/samples/{sample_id}")
async def get_sample(sample_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", sample_id):
        raise HTTPException(status_code=404, detail="Sample not found")
    path = _SAMPLE_DIR / f"{sample_id}.txt"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"id": sample_id, "text": path.read_text(encoding="utf-8", errors="replace")}


@app.get("/analyze")
@app.get("/simulate")
async def analyze_get():
    """Someone refreshed the results page — send them back to the form."""
    return RedirectResponse("/", status_code=303)


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    file: Optional[UploadFile] = File(None),
    evidence_files: Optional[List[UploadFile]] = File(None),
    case_text: str = Form(""),
):
    """
    Main analysis endpoint.

    Accepts EITHER an uploaded case file OR pasted text (file takes priority).
    Extracts facts, runs the full simulation pipeline, and returns the
    animated courtroom UI.
    """
    evidence = _evidence_metadata(evidence_files)

    # 1. Get raw case text
    raw_text = ""
    if file and file.filename:
        contents = await file.read()
        if len(contents) > MAX_CASE_FILE_BYTES:
            return _render_index(
                request,
                f"Case file is too large (limit {MAX_CASE_FILE_BYTES // (1024 * 1024)} MB).",
                status_code=413,
            )
        try:
            raw_text = parse_file(file.filename, contents)
        except UnsupportedFileType as exc:
            return _render_index(request, str(exc), status_code=400)
        except Exception as exc:
            log.warning("File parse failed", exc_info=True)
            return _render_index(request, f"Failed to parse file: {exc}", status_code=400)

    if not raw_text.strip():
        raw_text = case_text.strip()

    if not raw_text:
        return _render_index(request, "Please upload a file or paste case text.", status_code=400)

    raw_text = raw_text[:MAX_CASE_TEXT_CHARS]

    # 2. Extract structured facts (Ollama → keyword fallback)
    try:
        fm = extract_facts(raw_text)
    except Exception:
        log.warning("Fact extraction failed, using keyword fallback", exc_info=True)
        fm = extract_facts_keyword_only(raw_text)

    # 3. Run full simulation. Research is fetched afterward for display only.
    try:
        result = _run_pipeline(fm)
    except Exception as exc:
        log.exception("Simulation failed")
        return _render_index(request, f"The simulation could not complete: {exc}", status_code=500)

    result["uploaded_evidence"] = evidence
    return _render_simulation(request, result, raw_text)


@app.post("/upload-case")
async def upload_case(file: UploadFile = File(...)):
    """Parse an uploaded .txt / .pdf / .docx file and return extracted text."""
    contents = await file.read()
    if len(contents) > MAX_CASE_FILE_BYTES:
        return JSONResponse({"detail": "File too large."}, status_code=413)
    try:
        text = parse_file(file.filename or "unknown.txt", contents)
        return JSONResponse({"extracted_text": text})
    except UnsupportedFileType as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"detail": f"Failed to parse file: {exc}"}, status_code=500)


# Keep old /simulate route for backward compatibility
@app.post("/simulate", response_class=HTMLResponse)
async def simulate_legacy(
    request: Request,
    victim: str = Form(""),
    accused: str = Form(""),
    evidence: str = Form(""),
    exceptions: str = Form(""),
):
    """Legacy endpoint — builds FactMatrix from four text fields."""
    fm = FactMatrix()
    if victim.strip():
        fm.add_fact("actus_reus", victim, FactSource.USER_INPUT)
    if accused.strip():
        fm.add_fact("mens_rea", accused, FactSource.USER_INPUT)
    if evidence.strip():
        fm.add_fact("evidence", evidence, FactSource.DOCUMENT)
    if exceptions.strip():
        fm.add_fact("exceptions_claimed", exceptions, FactSource.USER_INPUT, severity="medium")

    result = _run_pipeline(fm)
    result["uploaded_evidence"] = []
    return _render_simulation(request, result, " ".join([victim, accused, evidence, exceptions]))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
