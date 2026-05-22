"""
Minimal Serper API client for display-only legal research.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"


class SerperClient:
    """Tiny wrapper around Serper search."""

    def __init__(self, api_key: Optional[str] = None, *, max_results: int = 3) -> None:
        self.api_key = api_key
        self.max_results = max_results

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not self.api_key or not query:
            return []

        try:
            payload = json.dumps({"q": query}).encode()
            req = urllib.request.Request(
                _SERPER_URL,
                data=payload,
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode())
        except Exception:
            log.warning("Serper search failed", exc_info=True)
            return []

        results = []
        for item in raw.get("organic", [])[: self.max_results]:
            results.append({
                "title": item.get("title", ""),
                "source": "Serper",
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
            })
        return results
