"""
Minimal Indian Kanoon API client for display-only legal research.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

log = logging.getLogger(__name__)

_KANOON_SEARCH_URL = "https://api.indiankanoon.org/search/"


class KanoonClient:
    """Tiny wrapper around Indian Kanoon search."""

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
            url = f"{_KANOON_SEARCH_URL}?formInput={quote_plus(query)}&pagenum=0"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode())
        except Exception:
            log.warning("Indian Kanoon search failed", exc_info=True)
            return []

        results = []
        for doc in raw.get("docs", [])[: self.max_results]:
            title = doc.get("title") or doc.get("citation") or "Indian Kanoon result"
            doc_id = doc.get("tid") or doc.get("docid") or doc.get("id")
            link = f"https://indiankanoon.org/doc/{doc_id}/" if doc_id else ""
            results.append({
                "title": title,
                "source": doc.get("docsource") or "Indian Kanoon",
                "snippet": doc.get("headline", ""),
                "link": link,
            })
        return results
