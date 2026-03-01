"""
CourtMind — Research Layer: Research Aggregator

Combines :class:`PrecedentEngine` and :class:`ContextEngine` into a
single ``enrich()`` call that returns unified research data.

**Strict rules**

*   Pure enrichment — does **not** modify ``CaseAnalysis``.
*   Safe if either engine returns empty results.

Usage
-----
    from research.research_aggregator import ResearchAggregator
    from research.precedent_engine import PrecedentEngine
    from research.context_engine import ContextEngine

    aggregator = ResearchAggregator(
        precedent_engine=PrecedentEngine(kanoon_api_key="..."),
        context_engine=ContextEngine(serper_api_key="..."),
    )
    data = aggregator.enrich(case_analysis_dict)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from research.context_engine import ContextEngine
from research.precedent_engine import PrecedentEngine


class ResearchAggregator:
    """
    Facade that runs both research engines and merges their results.

    Parameters
    ----------
    precedent_engine : PrecedentEngine | None
        If ``None`` a no-key (no-op) engine is used.
    context_engine : ContextEngine | None
        If ``None`` a no-key (no-op) engine is used.
    """

    def __init__(
        self,
        precedent_engine: Optional[PrecedentEngine] = None,
        context_engine: Optional[ContextEngine] = None,
    ) -> None:
        self._precedent = precedent_engine or PrecedentEngine()
        self._context = context_engine or ContextEngine()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def enrich(self, case_analysis: dict) -> Dict[str, Any]:
        """
        Run both research engines and return merged results.

        Returns
        -------
        dict
            ``{"precedents": [...], "recent_context": [...]}``.
        """
        prec = self._precedent.fetch_precedents(case_analysis)
        ctx = self._context.fetch_context(case_analysis)
        return {
            "precedents": prec.get("precedents", []),
            "recent_context": ctx.get("recent_context", []),
        }
