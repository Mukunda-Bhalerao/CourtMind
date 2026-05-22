"""
CourtMind — FastAPI Web Interface

Connects the browser UI → Fact Extraction → FactMatrix → Simulation pipeline.

New flow (v2):
    Upload file / paste text → parse → extract_facts (Ollama + keyword fallback)
    → FactMatrix → run_full_simulation → animated courtroom UI

Usage
-----
    cd court_mind_web
    uvicorn main:app --reload
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

# Ensure the project root is on sys.path so `core.*` / `simulation.*` resolve.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.fact_extractor import extract_facts, extract_facts_keyword_only
from core.fact_matrix import FactMatrix, FactSource
from court_mind_web.utils.file_parser import (
    UnsupportedFileType,
    parse_file,
)
from research.context_engine import ContextEngine
from research.precedent_engine import PrecedentEngine
from research.research_aggregator import ResearchAggregator
from simulation.run_simulation import run_full_simulation

log = logging.getLogger(__name__)

app = FastAPI(title="CourtMind", version="2.0.0")

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Disable template caching to avoid issues with unhashable globals in some Jinja2 versions
try:
    templates.env.cache_size = 0
except Exception:
    # best-effort: if attribute not present, leave defaults
    pass
try:
    # Provide a safe cache mapping that tolerates unhashable keys by
    # normalizing them to stable string representations. This prevents
    # Jinja2 from raising "TypeError: unhashable type: 'dict'" when
    # building cache keys that include dicts.
    class _SafeTemplateCache(dict):
        def _norm(self, key):
            try:
                hash(key)
                return key
            except Exception:
                return repr(key)

        def __getitem__(self, key):
            return super().__getitem__(self._norm(key))

        def __setitem__(self, key, value):
            return super().__setitem__(self._norm(key), value)

        def get(self, key, default=None):
            return super().get(self._norm(key), default)

    try:
        # If Jinja2 has already created a Cache wrapper, replace its
        # internal mapping so cache lookups use a tolerant mapping.
        if hasattr(templates.env, "cache") and hasattr(templates.env.cache, "_mapping"):
            templates.env.cache._mapping = _SafeTemplateCache()
        else:
            templates.env.cache = _SafeTemplateCache()
    except Exception:
        templates.env.cache = _SafeTemplateCache()
except Exception:
    pass

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpeg", ".mpg"}


def _load_dotenv() -> None:
    """Load simple KEY=VALUE pairs from the project .env when not already set."""
    env_path = Path(_PROJECT_ROOT) / ".env"
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
        if not upload.filename:
            continue
        if not _is_allowed_evidence(upload):
            continue
        evidence.append({"filename": upload.filename, "file_type": _file_type(upload)})
    return evidence


# ===============================
# Research Aggregator (with API keys from env if available)
# ===============================
def _build_research_aggregator() -> ResearchAggregator:
    """Build a ResearchAggregator with API keys from environment."""
    kanoon_key = os.environ.get("KANOON_API_KEY")
    serper_key = os.environ.get("SERPER_API_KEY")
    return ResearchAggregator(
        precedent_engine=PrecedentEngine(kanoon_api_key=kanoon_key),
        context_engine=ContextEngine(serper_api_key=serper_key),
    )


def _fetch_display_research(result: dict, case_text: str) -> dict:
    """Fetch display-only research after deterministic simulation completes."""
    try:
        return _build_research_aggregator().enrich(
            result.get("case_analysis", {})
        )
    except Exception:
        log.warning("Display research failed", exc_info=True)
        return {
            "precedents": [],
            "recent_context": [],
            "available": False,
            "message": "Research APIs unavailable."
        }


# ===============================
# Routes
# ===============================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Serve the static index.html directly to avoid Jinja loader issues
    try:
        tmpl_path = Path(__file__).parent / "templates" / "index.html"
        content = tmpl_path.read_text(encoding="utf-8")
        return HTMLResponse(content, status_code=200)
    except Exception:
        # Fallback to TemplateResponse if direct file read fails
        return templates.TemplateResponse("index.html", {"request": request})


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    file: Optional[UploadFile] = File(None),
    evidence_files: Optional[List[UploadFile]] = File(None),
    case_text: str = Form(""),
):
    """
    Main analysis endpoint.

    Accepts EITHER an uploaded case file OR pasted text (or both — file
    takes priority).  Extracts facts, runs the full simulation pipeline,
    and returns the animated courtroom UI.
    """
    evidence = _evidence_metadata(evidence_files)

    # 1. Get raw case text
    raw_text = ""
    if file and file.filename:
        try:
            contents = await file.read()
            raw_text = parse_file(file.filename, contents)
        except UnsupportedFileType as exc:
            return templates.TemplateResponse(
                "index.html",
                {"request": request, "error": str(exc)},
            )
        except Exception as exc:
            return templates.TemplateResponse(
                "index.html",
                {"request": request, "error": f"Failed to parse file: {exc}"},
            )

    if not raw_text.strip():
        raw_text = case_text.strip()

    if not raw_text:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Please upload a file or paste case text."},
        )

    # 2. Extract structured facts (Ollama → keyword fallback)
    try:
        fm = extract_facts(raw_text)
    except Exception:
        log.warning("Fact extraction failed, using keyword fallback", exc_info=True)
        fm = extract_facts_keyword_only(raw_text)

    # 3. Run full simulation. Research is fetched afterward for display only.
    result = run_full_simulation(
        fm,
        auto_detect=True,
        research_aggregator=_build_research_aggregator(),
    )
    result["research_data"] = _fetch_display_research(result, raw_text)
    result["uploaded_evidence"] = evidence

    # 4. Prepare JSON for animated courtroom UI
    sim_events = result.get("simulation_events", {"events": [], "total_events": 0})
    events_json = json.dumps(sim_events, default=str, ensure_ascii=False)
    case_result_json = json.dumps(result, default=str, ensure_ascii=False)

    return templates.TemplateResponse(
        "simulation.html",
        {
            "request": request,
            "events_json": events_json,
            "case_result_json": case_result_json,
            "cache_bust": int(time.time()),
        },
    )


@app.post("/upload-case")
async def upload_case(file: UploadFile = File(...)):
    """Parse an uploaded .txt / .pdf / .docx file and return extracted text."""
    try:
        contents = await file.read()
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

    result = run_full_simulation(
        fm,
        auto_detect=True,
        research_aggregator=_build_research_aggregator(),
    )
    result["research_data"] = _fetch_display_research(result, " ".join([victim, accused, evidence, exceptions]))
    result["uploaded_evidence"] = []

    sim_events = result.get("simulation_events", {"events": [], "total_events": 0})
    events_json = json.dumps(sim_events, default=str, ensure_ascii=False)
    case_result_json = json.dumps(result, default=str, ensure_ascii=False)

    return templates.TemplateResponse(
        "simulation.html",
        {
            "request": request,
            "events_json": events_json,
            "case_result_json": case_result_json,
            "cache_bust": int(time.time()),
        },
    )
