"""
CourtMind — Research Layer: Precedent Engine

Fetches real-world Indian legal precedents from the Indian Kanoon API
based on the detected IPC section and satisfied element keywords.

**Strict rules**

*   Does **not** modify ``CaseAnalysis``.
*   Does **not** influence deterministic outputs.
*   Pure enrichment layer — safe to skip entirely.
*   Graceful fallback when the API is unavailable.

Usage
-----
    from research.precedent_engine import PrecedentEngine

    engine = PrecedentEngine(kanoon_api_key="...")
    result = engine.fetch_precedents(case_analysis_dict)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

log = logging.getLogger(__name__)

# Indian Kanoon public search endpoint
_KANOON_SEARCH_URL = "https://api.indiankanoon.org/search/"


class PrecedentEngine:
    """
    Retrieves precedents from Indian Kanoon for the section under
    analysis.

    Parameters
    ----------
    kanoon_api_key : str | None
        Bearer token for Indian Kanoon API.  If ``None``, every call
        returns an empty result without error.
    max_results : int
        Maximum number of precedents to return (default 5).
    """

    def __init__(
        self,
        kanoon_api_key: Optional[str] = None,
        *,
        max_results: int = 5,
    ) -> None:
        self._api_key = kanoon_api_key
        self._max_results = max_results

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def fetch_precedents(self, case_analysis: dict) -> Dict[str, Any]:
        """
        Fetch precedents relevant to *case_analysis*.

        Returns
        -------
        dict
            ``{"precedents": [...]}``.  Empty list on any failure.
        """
        if not self._api_key:
            return {"precedents": []}

        query = self._build_query(case_analysis)
        if not query:
            return {"precedents": []}

        try:
            raw = self._call_api(query)
            precedents = self._parse_response(raw)
            return {"precedents": precedents[: self._max_results]}
        except Exception:  # noqa: BLE001 — never propagate to caller
            log.warning("PrecedentEngine: API call failed", exc_info=True)
            return {"precedents": []}

    # ------------------------------------------------------------------ #
    # Query construction                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_query(case_analysis: dict) -> str:
        """
        Construct search query from section + satisfied element ids.

        Format::

            "{section} {elem1} {elem2} … Supreme Court judgment"
        """
        eval_r = case_analysis.get("evaluation_result", {})
        section = eval_r.get("section", "")
        element_details = eval_r.get("element_details", [])

        satisfied_ids = [
            e.get("element_id", "")
            for e in element_details
            if e.get("status") == "satisfied" and e.get("element_id")
        ]
        parts = [section] + satisfied_ids + ["Supreme Court judgment"]
        return " ".join(p for p in parts if p)

    # ------------------------------------------------------------------ #
    # API interaction                                                      #
    # ------------------------------------------------------------------ #

    def _call_api(self, query: str) -> dict:
        """
        Call Indian Kanoon search endpoint.

        Uses :mod:`urllib.request` so that no third-party HTTP library
        is required at import time.
        """
        import json
        import urllib.request

        url = f"{_KANOON_SEARCH_URL}?formInput={quote_plus(query)}&pagenum=0"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Token {self._api_key}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    # ------------------------------------------------------------------ #
    # Response parsing                                                      #
    # ------------------------------------------------------------------ #

    def _parse_response(self, raw: dict) -> List[Dict[str, Any]]:
        """
        Normalise Indian Kanoon response docs into a flat list.

        Each entry::

            {
                "title": str,
                "citation": str,
                "court": str,
                "year": int,
                "summary": str,
                "source": "kanoon"
            }
        """
        docs = raw.get("docs", [])
        results: List[Dict[str, Any]] = []
        for doc in docs:
            title = doc.get("title", "")
            citation = doc.get("citation", title)
            court = doc.get("docsource", "")
            headline = doc.get("headline", "")

            # Indian Kanoon puts year in publishdate (e.g. "2024-01-15")
            year = 0
            pub = str(doc.get("publishdate", ""))
            if len(pub) >= 4 and pub[:4].isdigit():
                year = int(pub[:4])

            results.append({
                "title": title,
                "citation": citation,
                "court": court,
                "year": year,
                "summary": headline,
                "source": "kanoon",
            })
        return results
