"""
CourtMind - Deterministic Fact Matrix Engine

Extracts and categorizes legal facts into predefined buckets
for deterministic IPC element evaluation. No LLM usage.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class FactCategory(str, Enum):
    """Allowed fact categories aligned with IPC element evaluation."""

    ACTUS_REUS = "actus_reus"              # Physical act / conduct
    MENS_REA = "mens_rea"                  # Intention / knowledge / motive
    EVIDENCE = "evidence"                  # Documents, witness statements, forensic data
    CONFLICTS = "conflicts"                # Contradictory facts across sources
    EXCEPTIONS_CLAIMED = "exceptions_claimed"  # Self-defense, insanity, duress, etc.


class FactSource(str, Enum):
    """Origin type for a fact entry."""

    CASE_FILE = "case_file"
    WITNESS = "witness"
    FORENSIC = "forensic"
    DOCUMENT = "document"
    CONFESSION = "confession"
    KANOON = "kanoon"
    USER_INPUT = "user_input"
    OTHER = "other"


class Severity(str, Enum):
    """How critical the fact is to the case outcome."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class Fact:
    """A single legal fact entry."""

    id: str
    category: str
    statement: str
    source: str
    severity: str = Severity.MEDIUM.value
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # ---- helpers ----------------------------------------------------------

    def content_hash(self) -> str:
        """Deterministic hash of the fact's meaningful content."""
        payload = f"{self.category}|{self.statement.strip().lower()}|{self.source}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Conflict:
    """A detected contradiction between two facts."""

    id: str
    fact_a_id: str
    fact_b_id: str
    reason: str
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Fact Matrix Engine
# ---------------------------------------------------------------------------

class FactMatrix:
    """
    Deterministic fact storage and categorisation engine.

    Responsibilities
    ----------------
    * Store facts under validated legal categories.
    * Detect duplicate entries via content hashing.
    * Surface contradictions between facts.
    * Export the full matrix as structured JSON.
    * Remain LLM-free — all logic is rule-based.

    Designed for downstream integration with a statute/IPC evaluation engine.
    """

    ALLOWED_CATEGORIES: Tuple[str, ...] = tuple(c.value for c in FactCategory)

    def __init__(self) -> None:
        # Primary storage: category -> list of Facts
        self._buckets: Dict[str, List[Fact]] = {cat: [] for cat in self.ALLOWED_CATEGORIES}
        # Fast lookup by id
        self._index: Dict[str, Fact] = {}
        # Content hashes for dedup
        self._hashes: set[str] = set()
        # Detected conflicts
        self._conflicts: List[Conflict] = []

    # ------------------------------------------------------------------
    # Public API — mutators
    # ------------------------------------------------------------------

    def add_fact(
        self,
        category: str,
        statement: str,
        source: str,
        *,
        severity: str = Severity.MEDIUM.value,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Fact:
        """
        Add a fact to the matrix under *category*.

        Parameters
        ----------
        category : str
            Must be one of :pyattr:`ALLOWED_CATEGORIES`.
        statement : str
            Human-readable description of the fact.
        source : str
            Origin label (free-form) or a :class:`FactSource` value.
        severity : str, optional
            One of low / medium / high / critical.
        tags : list[str], optional
            Arbitrary labels for filtering.
        metadata : dict, optional
            Extra key-value pairs (section numbers, page refs, …).

        Returns
        -------
        Fact
            The newly created (or existing duplicate) fact.

        Raises
        ------
        ValueError
            If *category* is not in :pyattr:`ALLOWED_CATEGORIES`.
        ValueError
            If *statement* is empty.
        """
        self._validate_category(category)
        statement = statement.strip()
        if not statement:
            raise ValueError("Fact statement must not be empty.")

        fact = Fact(
            id=uuid.uuid4().hex[:12],
            category=category,
            statement=statement,
            source=source,
            severity=severity,
            tags=tags or [],
            metadata=metadata or {},
        )

        # Dedup check
        h = fact.content_hash()
        if h in self._hashes:
            # Return the existing fact instead of adding a duplicate
            for existing in self._buckets[category]:
                if existing.content_hash() == h:
                    return existing
            # Hash collision across categories — still skip
            return fact

        self._hashes.add(h)
        self._buckets[category].append(fact)
        self._index[fact.id] = fact
        return fact

    def add_facts_bulk(self, facts: Sequence[Dict[str, Any]]) -> List[Fact]:
        """
        Add multiple facts at once.

        Each dict in *facts* must contain at least ``category``, ``statement``,
        and ``source``.  Extra keys are forwarded as keyword arguments.

        Returns list of created :class:`Fact` objects.
        """
        created: List[Fact] = []
        for entry in facts:
            entry = dict(entry)  # shallow copy
            cat = entry.pop("category")
            stmt = entry.pop("statement")
            src = entry.pop("source")
            created.append(self.add_fact(cat, stmt, src, **entry))
        return created

    def remove_fact(self, fact_id: str) -> bool:
        """Remove a fact by its id.  Returns ``True`` if found and removed."""
        fact = self._index.pop(fact_id, None)
        if fact is None:
            return False
        self._buckets[fact.category] = [
            f for f in self._buckets[fact.category] if f.id != fact_id
        ]
        self._hashes.discard(fact.content_hash())
        # Also remove any conflicts referencing this fact
        self._conflicts = [
            c for c in self._conflicts
            if c.fact_a_id != fact_id and c.fact_b_id != fact_id
        ]
        return True

    # ------------------------------------------------------------------
    # Public API — conflict detection
    # ------------------------------------------------------------------

    def register_conflict(
        self,
        fact_a_id: str,
        fact_b_id: str,
        reason: str,
    ) -> Conflict:
        """
        Manually register a contradiction between two existing facts.

        Raises
        ------
        KeyError
            If either fact id does not exist in the matrix.
        ValueError
            If *reason* is empty or facts are the same.
        """
        if fact_a_id not in self._index:
            raise KeyError(f"Fact '{fact_a_id}' not found in matrix.")
        if fact_b_id not in self._index:
            raise KeyError(f"Fact '{fact_b_id}' not found in matrix.")
        if fact_a_id == fact_b_id:
            raise ValueError("A fact cannot conflict with itself.")
        reason = reason.strip()
        if not reason:
            raise ValueError("Conflict reason must not be empty.")

        conflict = Conflict(
            id=uuid.uuid4().hex[:12],
            fact_a_id=fact_a_id,
            fact_b_id=fact_b_id,
            reason=reason,
        )
        self._conflicts.append(conflict)
        return conflict

    def detect_conflicts_by_tags(self) -> List[Conflict]:
        """
        Auto-detect potential conflicts: facts sharing a tag but residing
        in different categories, or flagged with opposing sentiment tags
        (e.g. ``"intentional"`` vs ``"accidental"``).

        Returns newly created :class:`Conflict` objects (also stored internally).
        """
        OPPOSING_PAIRS = [
            ("intentional", "accidental"),
            ("premeditated", "spontaneous"),
            ("guilty", "innocent"),
            ("present", "absent"),
            ("armed", "unarmed"),
            ("voluntary", "involuntary"),
            ("provoked", "unprovoked"),
        ]

        all_facts = self._all_facts()
        new_conflicts: List[Conflict] = []
        seen_pairs: set[Tuple[str, str]] = {
            (c.fact_a_id, c.fact_b_id) for c in self._conflicts
        }

        for i, fa in enumerate(all_facts):
            for fb in all_facts[i + 1:]:
                pair = (fa.id, fb.id) if fa.id < fb.id else (fb.id, fa.id)
                if pair in seen_pairs:
                    continue

                tags_a = {t.lower() for t in fa.tags}
                tags_b = {t.lower() for t in fb.tags}

                for pos, neg in OPPOSING_PAIRS:
                    if (pos in tags_a and neg in tags_b) or (neg in tags_a and pos in tags_b):
                        c = Conflict(
                            id=uuid.uuid4().hex[:12],
                            fact_a_id=pair[0],
                            fact_b_id=pair[1],
                            reason=f"Opposing tags detected: '{pos}' vs '{neg}'",
                        )
                        self._conflicts.append(c)
                        new_conflicts.append(c)
                        seen_pairs.add(pair)
                        break  # one conflict per pair is enough

        return new_conflicts

    # ------------------------------------------------------------------
    # Public API — queries
    # ------------------------------------------------------------------

    def get_facts(self, category: str) -> List[Fact]:
        """Return all facts in *category* (copy of list)."""
        self._validate_category(category)
        return list(self._buckets[category])

    def get_fact_by_id(self, fact_id: str) -> Optional[Fact]:
        """Look up a single fact by id."""
        return self._index.get(fact_id)

    def get_conflicts(self) -> List[Conflict]:
        """Return all registered conflicts."""
        return list(self._conflicts)

    def count(self, category: Optional[str] = None) -> int:
        """Count facts globally or within a *category*."""
        if category is not None:
            self._validate_category(category)
            return len(self._buckets[category])
        return sum(len(v) for v in self._buckets.values())

    def summary(self) -> Dict[str, Any]:
        """Quick stats about the matrix."""
        return {
            "total_facts": self.count(),
            "by_category": {cat: len(facts) for cat, facts in self._buckets.items()},
            "total_conflicts": len(self._conflicts),
        }

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        severity: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Fact]:
        """
        Filter facts by one or more criteria.  All supplied filters
        are combined with AND logic.
        """
        results = self._all_facts()
        if category is not None:
            self._validate_category(category)
            results = [f for f in results if f.category == category]
        if source is not None:
            results = [f for f in results if f.source == source]
        if severity is not None:
            results = [f for f in results if f.severity == severity]
        if tag is not None:
            tag_lower = tag.lower()
            results = [f for f in results if tag_lower in (t.lower() for t in f.tags)]
        if keyword is not None:
            kw = keyword.lower()
            results = [f for f in results if kw in f.statement.lower()]
        return results

    # ------------------------------------------------------------------
    # Public API — export / import
    # ------------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        """Export full matrix as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_dict(self) -> Dict[str, Any]:
        """Export full matrix as a plain dict."""
        return {
            "facts": {
                cat: [f.to_dict() for f in facts]
                for cat, facts in self._buckets.items()
            },
            "conflicts": [c.to_dict() for c in self._conflicts],
            "summary": self.summary(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FactMatrix":
        """Reconstruct a FactMatrix from a dict produced by :meth:`to_dict`."""
        matrix = cls()
        for category, fact_dicts in data.get("facts", {}).items():
            for fd in fact_dicts:
                fact = Fact(**fd)
                matrix._buckets.setdefault(category, []).append(fact)
                matrix._index[fact.id] = fact
                matrix._hashes.add(fact.content_hash())
        for cd in data.get("conflicts", []):
            matrix._conflicts.append(Conflict(**cd))
        return matrix

    @classmethod
    def from_json(cls, json_str: str) -> "FactMatrix":
        """Reconstruct a FactMatrix from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _validate_category(self, category: str) -> None:
        if category not in self.ALLOWED_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}'. "
                f"Allowed: {', '.join(self.ALLOWED_CATEGORIES)}"
            )

    def _all_facts(self) -> List[Fact]:
        return [f for facts in self._buckets.values() for f in facts]

    def __repr__(self) -> str:
        return f"<FactMatrix facts={self.count()} conflicts={len(self._conflicts)}>"
