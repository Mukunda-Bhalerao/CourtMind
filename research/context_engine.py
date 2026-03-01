"""
CourtMind — Research Layer: Context Engine

Fetches recent legal commentary and news using the Serper
(Google-search) API, enriching the simulation with real-world
context.

**Strict rules**

*   Does **not** modify ``CaseAnalysis``.
*   Does **not** alter section detection.
*   Pure contextual enrichment — optional layer.
*   Graceful fallback when the API is unavailable.

Usage
-----
    from research.context_engine import ContextEngine

    engine = ContextEngine(serper_api_key="...")
    result = engine.fetch_context(case_analysis_dict)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"


class ContextEngine:
    """
    Retrieves recent legal context via the Serper API.

    Parameters
    ----------
    serper_api_key : str | None
        API key for Serper.  If ``None``, every call returns an empty
        result without error.
    max_results : int
        Maximum organic results to return (default 3).
    """

    def __init__(
        self,
        serper_api_key: Optional[str] = None,
        *,
        max_results: int = 3,
    ) -> None:
        self._api_key = serper_api_key
        self._max_results = max_results

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def fetch_context(self, case_analysis: dict) -> Dict[str, Any]:
        """
        Fetch recent legal context for *case_analysis*.

        Returns
        -------
        dict
            ``{"recent_context": [...]}``.  Empty list on any failure.
        """
        if not self._api_key:
            return {"recent_context": []}

        query = self._build_query(case_analysis)
        if not query:
            return {"recent_context": []}

        try:
            raw = self._call_api(query)
            items = self._parse_response(raw)
            return {"recent_context": items[: self._max_results]}
        except Exception:  # noqa: BLE001 — never propagate to caller
            log.warning("ContextEngine: API call failed", exc_info=True)
            return {"recent_context": []}

    # ------------------------------------------------------------------ #
    # Query construction                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_query(case_analysis: dict) -> str:
        """
        Construct a Serper query from section + burden_stage.

        Format::

            "Recent Supreme Court {section} judgment {burden_stage}"
        """
        eval_r = case_analysis.get("evaluation_result", {})
        burden_r = case_analysis.get("burden_result", {})

        section = eval_r.get("section", "")
        burden_stage = burden_r.get("burden_stage", "")
        parts = ["Recent Supreme Court", section, "judgment", burden_stage]
        return " ".join(p for p in parts if p)

    # ------------------------------------------------------------------ #
    # API interaction                                                      #
    # ------------------------------------------------------------------ #

    def _call_api(self, query: str) -> dict:
        """
        Call Serper search endpoint.

        Uses :mod:`urllib.request` — no third-party HTTP library required.
        """
        import json
        import urllib.request

        payload = json.dumps({"q": query}).encode()
        req = urllib.request.Request(
            _SERPER_URL,
            data=payload,
            headers={
                "X-API-KEY": self._api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    # ------------------------------------------------------------------ #
    # Response parsing                                                     #
    # ------------------------------------------------------------------ #

    def _parse_response(self, raw: dict) -> List[Dict[str, Any]]:
        """
        Extract organic results into a flat list.

        Each entry::

            {
                "title": str,
                "link": str,
                "snippet": str,
                "source": "serper"
            }
        """
        organic = raw.get("organic", [])
        results: List[Dict[str, Any]] = []
        for item in organic:
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": "serper",
            })
        return results
