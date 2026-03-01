"""
CourtMind — Research Layer
==========================

Public API re-exports for the research package.
"""

from research.context_engine import ContextEngine
from research.precedent_engine import PrecedentEngine
from research.research_aggregator import ResearchAggregator

__all__ = [
    "PrecedentEngine",
    "ContextEngine",
    "ResearchAggregator",
]
