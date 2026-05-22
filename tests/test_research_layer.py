"""
Tests for the research layer and citation guardrails.

Covers:
 1. PrecedentEngine — query construction, parse, graceful fallback.
 2. ContextEngine   — query construction, parse, graceful fallback.
 3. ResearchAggregator — merges both engines.
 4. SimulationGuardrails.validate_citations — fabrication detection.

Run:  python -m pytest tests/test_research_layer.py -v
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from core.simulation_guardrails import SimulationGuardrails
from research.context_engine import ContextEngine
from research.precedent_engine import PrecedentEngine
from research.research_aggregator import ResearchAggregator


# ── shared fixtures ─────────────────────────────────────────────────────

@pytest.fixture()
def guardrails() -> SimulationGuardrails:
    return SimulationGuardrails()


def _base_case_analysis() -> dict:
    return {
        "evaluation_result": {
            "section": "302 IPC",
            "section_title": "Murder",
            "element_details": [
                {"element_id": "death_caused", "status": "satisfied",
                 "required": True, "matching_fact_ids": ["f1"],
                 "confidence_notes": []},
                {"element_id": "act_by_accused", "status": "satisfied",
                 "required": True, "matching_fact_ids": ["f2"],
                 "confidence_notes": []},
                {"element_id": "intention", "status": "satisfied",
                 "required": True, "matching_fact_ids": ["f3"],
                 "confidence_notes": []},
            ],
            "elements_satisfied": 3,
            "elements_failed": 0,
            "elements_required": 3,
        },
        "burden_result": {
            "burden_stage": "prima_facie_established",
            "confidence_score": 0.85,
        },
        "metadata": {},
        "evidence_weight_result": {"overall_evidence_score": 0.9},
        "exception_result": {"fully_negated": False},
    }


# ── PrecedentEngine ────────────────────────────────────────────────────

class TestPrecedentEngine:
    def test_no_key_returns_empty(self):
        engine = PrecedentEngine(kanoon_api_key=None)
        result = engine.fetch_precedents(_base_case_analysis())
        assert result == {"precedents": []}

    def test_build_query(self):
        q = PrecedentEngine._build_query(_base_case_analysis())
        assert "302 IPC" in q
        assert "death_caused" in q
        assert "Supreme Court judgment" in q

    def test_parse_response(self):
        engine = PrecedentEngine(kanoon_api_key="fake")
        raw = {
            "docs": [
                {
                    "title": "State v. Sharma",
                    "citation": "2024 SCC 123",
                    "docsource": "Supreme Court of India",
                    "publishdate": "2024-05-10",
                    "headline": "Murder conviction upheld.",
                },
                {
                    "title": "Ram v. State",
                    "docsource": "High Court",
                    "publishdate": "bad-date",
                    "headline": "Acquittal.",
                },
            ]
        }
        parsed = engine._parse_response(raw)
        assert len(parsed) == 2
        assert parsed[0]["source"] == "kanoon"
        assert parsed[0]["year"] == 2024
        assert parsed[0]["court"] == "Supreme Court of India"
        assert parsed[1]["year"] == 0  # bad date

    def test_max_results_capped(self):
        engine = PrecedentEngine(kanoon_api_key="fake", max_results=1)
        raw = {"docs": [{"title": f"Case {i}"} for i in range(5)]}
        # Patch _call_api to return our raw data
        with patch.object(engine, "_call_api", return_value=raw):
            result = engine.fetch_precedents(_base_case_analysis())
        assert len(result["precedents"]) == 1

    def test_api_failure_returns_empty(self):
        engine = PrecedentEngine(kanoon_api_key="fake")
        with patch.object(engine, "_call_api", side_effect=ConnectionError):
            result = engine.fetch_precedents(_base_case_analysis())
        assert result == {"precedents": []}


# ── ContextEngine ──────────────────────────────────────────────────────

class TestContextEngine:
    def test_no_key_returns_empty(self):
        engine = ContextEngine(serper_api_key=None)
        result = engine.fetch_context(_base_case_analysis())
        assert result == {"recent_context": []}

    def test_build_query(self):
        q = ContextEngine._build_query(_base_case_analysis())
        assert "302 IPC" in q
        assert "prima_facie_established" in q
        assert "Recent Supreme Court" in q

    def test_parse_response(self):
        engine = ContextEngine(serper_api_key="fake")
        raw = {
            "organic": [
                {
                    "title": "Analysis of 302 IPC",
                    "link": "https://example.com/1",
                    "snippet": "Recent changes…",
                },
            ]
        }
        parsed = engine._parse_response(raw)
        assert len(parsed) == 1
        assert parsed[0]["source"] == "serper"
        assert parsed[0]["link"] == "https://example.com/1"

    def test_max_results_capped(self):
        engine = ContextEngine(serper_api_key="fake", max_results=2)
        raw = {"organic": [{"title": f"Art {i}"} for i in range(5)]}
        with patch.object(engine, "_call_api", return_value=raw):
            result = engine.fetch_context(_base_case_analysis())
        assert len(result["recent_context"]) == 2

    def test_api_failure_returns_empty(self):
        engine = ContextEngine(serper_api_key="fake")
        with patch.object(engine, "_call_api", side_effect=TimeoutError):
            result = engine.fetch_context(_base_case_analysis())
        assert result == {"recent_context": []}


# ── ResearchAggregator ─────────────────────────────────────────────────

class TestResearchAggregator:
    def test_default_no_keys_returns_empty(self):
        agg = ResearchAggregator()
        result = agg.enrich(_base_case_analysis())
        assert result["precedents"] == []
        assert result["recent_context"] == []

    def test_merges_both_engines(self):
        prec = PrecedentEngine(kanoon_api_key="fake")
        ctx = ContextEngine(serper_api_key="fake")
        agg = ResearchAggregator(prec, ctx)

        prec_raw = {"docs": [{"title": "Case A", "publishdate": "2024"}]}
        ctx_raw = {"organic": [{"title": "Article B", "link": "http://x"}]}

        with patch.object(prec, "_call_api", return_value=prec_raw), \
             patch.object(ctx, "_call_api", return_value=ctx_raw):
            result = agg.enrich(_base_case_analysis())

        assert len(result["precedents"]) == 1
        assert len(result["recent_context"]) == 1
        assert result["precedents"][0]["source"] == "kanoon"
        assert result["recent_context"][0]["source"] == "serper"


# ── Citation guardrail ─────────────────────────────────────────────────

class TestValidateCitations:
    def _sim_output(
        self,
        *,
        pros_args: List[str] | None = None,
        def_args: List[str] | None = None,
        reasoning: List[str] | None = None,
        judgment: str = "",
    ) -> dict:
        return {
            "lawyer_output": {
                "prosecution_arguments": pros_args or [],
                "defense_arguments": def_args or [],
            },
            "panel_result": {
                "judges": [
                    {
                        "key_reasoning_points": reasoning or [],
                        "concerns": [],
                    }
                ],
            },
            "final_judgment": judgment,
        }

    def test_no_citations_no_research_valid(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis()
        sim = self._sim_output()
        rd: Dict[str, Any] = {"precedents": [], "recent_context": []}
        result = guardrails.validate_citations(ca, sim, rd)
        assert result["valid"] is True

    def test_citation_present_in_research_valid(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis()
        sim = self._sim_output(
            pros_args=["As held in State of UP v. Ram Kumar, conviction upheld."],
        )
        rd: Dict[str, Any] = {
            "precedents": [
                {"title": "State of UP v. Ram Kumar", "citation": "2024 SCC 99"},
            ],
            "recent_context": [],
        }
        result = guardrails.validate_citations(ca, sim, rd)
        assert result["valid"] is True

    def test_fabricated_citation_no_research_flagged(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis()
        sim = self._sim_output(
            judgment="As per Fake Corp v. Imaginary Party, conviction is warranted.",
        )
        rd: Dict[str, Any] = {"precedents": [], "recent_context": []}
        result = guardrails.validate_citations(ca, sim, rd)
        assert result["valid"] is False
        assert any("Fake Corp v. Imaginary Party" in v for v in result["violations"])

    def test_fabricated_citation_with_research_flagged(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis()
        sim = self._sim_output(
            reasoning=["See Ghost State v. Phantom Accused for precedent."],
        )
        rd: Dict[str, Any] = {
            "precedents": [
                {"title": "Real Case v. Real Party", "citation": "2023 SCC 50"},
            ],
            "recent_context": [],
        }
        result = guardrails.validate_citations(ca, sim, rd)
        assert result["valid"] is False
        assert any("Ghost State" in v for v in result["violations"])

    def test_no_citations_with_research_valid(
        self, guardrails: SimulationGuardrails,
    ):
        """Simulation doesn't cite anything — always valid."""
        ca = _base_case_analysis()
        sim = self._sim_output(
            pros_args=["All elements satisfied."],
        )
        rd: Dict[str, Any] = {
            "precedents": [
                {"title": "Some Case v. State", "citation": "2024 SCC 1"},
            ],
            "recent_context": [],
        }
        result = guardrails.validate_citations(ca, sim, rd)
        assert result["valid"] is True

    def test_multiple_fabricated_cited(
        self, guardrails: SimulationGuardrails,
    ):
        ca = _base_case_analysis()
        sim = self._sim_output(
            judgment=(
                "This is supported by Alpha v. Beta and also Gamma v. Delta."
            ),
        )
        rd: Dict[str, Any] = {"precedents": [], "recent_context": []}
        result = guardrails.validate_citations(ca, sim, rd)
        assert result["valid"] is False
        assert len(result["violations"]) >= 2


# ── ReportGenerator Tests ─────────────────────────────────────────────

import json
from core.report_generator import ReportGenerator


def _sample_simulation_result() -> dict:
    return {
        "case_analysis": {
            "evaluation_result": {
                "section": "302 IPC",
                "confidence_score": 0.85,
                "element_details": [
                    {"element_id": "death_of_human", "satisfied": True,
                     "matching_fact_ids": ["f1"], "weight": 0.3},
                    {"element_id": "act_by_accused", "satisfied": True,
                     "matching_fact_ids": ["f2"], "weight": 0.3},
                    {"element_id": "intention_or_knowledge", "satisfied": False,
                     "matching_fact_ids": [], "weight": 0.4},
                ],
            },
            "burden_result": {
                "burden_stage": "prosecution_affirmative",
                "confidence_score": 0.85,
                "burden_met": True,
            },
            "evidence_weight_result": {
                "overall_evidence_score": 0.7,
                "per_element_scores": {"death_of_human": 0.9},
            },
        },
        "panel_result": {
            "majority_verdict": "convict",
            "vote_split": "2-1",
            "judges": [
                {"judge_type": "textualist", "provisional_verdict": "convict",
                 "key_reasoning_points": ["Elements met."]},
            ],
        },
        "final_judgment": "Accused found guilty under 302 IPC.",
        "research_data": {"precedents": [], "recent_context": []},
        "guardrail_report": {"violations": []},
        "strategy_report": {
            "prosecution_strategy": ["Emphasize forensic evidence."],
            "defense_strategy": ["Challenge intention."],
            "conviction_probability_estimate": 0.72,
            "risk_level": "high",
            "weak_elements": ["intention_or_knowledge"],
            "strong_elements": ["death_of_human"],
        },
        "explanation": "Deterministic explanation text.",
    }


class TestReportGenerator:
    def test_to_json_valid(self):
        gen = ReportGenerator()
        js = gen.to_json(_sample_simulation_result())
        parsed = json.loads(js)
        assert parsed["case_analysis"]["evaluation_result"]["section"] == "302 IPC"

    def test_to_markdown_has_key_sections(self):
        gen = ReportGenerator()
        md = gen.to_markdown(_sample_simulation_result())
        assert "# CourtMind Case Report" in md
        assert "302 IPC" in md
        assert "## Element Status" in md
        assert "death of human" in md
        assert "## Panel Deliberation" in md
        assert "CONVICT" in md
        assert "## Strategy Analysis" in md
        assert "72.0%" in md
        assert "## Final Judgment" in md

    def test_to_markdown_empty_result(self):
        gen = ReportGenerator()
        md = gen.to_markdown({})
        assert "# CourtMind Case Report" in md

    def test_to_json_empty_result(self):
        gen = ReportGenerator()
        js = gen.to_json({})
        assert json.loads(js) == {}
