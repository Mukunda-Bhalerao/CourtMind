"""
CourtMind — FastAPI Web Interface

Connects the browser UI → FactMatrix → run_full_simulation pipeline.

Usage
-----
    cd court_mind_web
    uvicorn main:app --reload
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `core.*` / `simulation.*` resolve.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.fact_matrix import FactMatrix, FactSource
from simulation.run_simulation import run_full_simulation

app = FastAPI(title="CourtMind", version="1.0.0")

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ===============================
# Utility: Convert narrative to FactMatrix
# ===============================
def build_fact_matrix(victim_text: str, accused_text: str, evidence_text: str, exception_text: str) -> FactMatrix:
    fm = FactMatrix()

    if victim_text.strip():
        fm.add_fact("actus_reus", victim_text, FactSource.USER_INPUT)

    if accused_text.strip():
        fm.add_fact("mens_rea", accused_text, FactSource.USER_INPUT)

    if evidence_text.strip():
        fm.add_fact("evidence", evidence_text, FactSource.DOCUMENT)

    if exception_text.strip():
        fm.add_fact(
            "exceptions_claimed",
            exception_text,
            FactSource.USER_INPUT,
            severity="medium",
        )

    return fm


# ===============================
# Routes
# ===============================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/simulate", response_class=HTMLResponse)
async def simulate(
    request: Request,
    victim: str = Form(...),
    accused: str = Form(...),
    evidence: str = Form(""),
    exceptions: str = Form(""),
):
    fm = build_fact_matrix(victim, accused, evidence, exceptions)

    result = run_full_simulation(fm, auto_detect=True)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "result": result,
        },
    )
