"""
CourtMind — Section Registry

Centralised, deterministic mapping from section codes (``"302 IPC"``) to
their corresponding :class:`StatuteEvaluator` sub-classes.

**Design constraints**

*   No LLM.  No dynamic imports.  No reflection.
*   Pure explicit registration.
*   Immutable once ``freeze()`` is called (optional).
*   Import-safe — depends only on ``statute_engine.StatuteEvaluator``
    and ``statute_engine.IPC302Evaluator``.

Usage
-----
    from core.section_registry import registry

    evaluator = registry.get("302 IPC")
    result = evaluator.evaluate(matrix)
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple, Type

from core.statute_engine import IPC302Evaluator, StatuteEvaluator
from core.evaluators.ipc304 import IPC304Evaluator
from core.evaluators.ipc420 import IPC420Evaluator
from core.evaluators.ipc323 import IPC323Evaluator


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class SectionRegistry:
    """
    Thread-safe, deterministic registry of IPC section evaluators.

    Maintains an internal mapping::

        section_code  →  evaluator **class**  (subclass of StatuteEvaluator)

    Public API
    ----------
    - ``register(section_code, evaluator_cls)``
    - ``get(section_code)`` → evaluator *instance*
    - ``list_registered_sections()`` → ``tuple[str, ...]``
    - ``is_registered(section_code)`` → ``bool``
    - ``freeze()`` — prevent any further registration
    """

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def __init__(self) -> None:
        self._mapping: Dict[str, Type[StatuteEvaluator]] = {}
        self._frozen: bool = False

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def register(
        self,
        section_code: str,
        evaluator_cls: Type[StatuteEvaluator],
    ) -> None:
        """
        Register *evaluator_cls* for *section_code*.

        Raises
        ------
        TypeError
            If *section_code* is not a string **or** *evaluator_cls* is
            not a subclass of :class:`StatuteEvaluator`.
        ValueError
            If *section_code* is already registered (duplicates rejected).
        RuntimeError
            If the registry has been frozen.
        """
        if self._frozen:
            raise RuntimeError(
                "Registry is frozen — no further registrations allowed."
            )
        if not isinstance(section_code, str):
            raise TypeError(
                f"section_code must be a string, got {type(section_code).__name__}"
            )
        if not section_code:
            raise ValueError("section_code must not be empty.")
        if not (
            isinstance(evaluator_cls, type)
            and issubclass(evaluator_cls, StatuteEvaluator)
        ):
            raise TypeError(
                f"evaluator_cls must be a subclass of StatuteEvaluator, "
                f"got {evaluator_cls!r}"
            )
        if section_code in self._mapping:
            raise ValueError(
                f"Section {section_code!r} is already registered "
                f"(mapped to {self._mapping[section_code].__name__})."
            )
        self._mapping[section_code] = evaluator_cls

    # ------------------------------------------------------------------ #
    # Retrieval
    # ------------------------------------------------------------------ #

    def get(
        self,
        section_code: str,
        *,
        override: Optional[StatuteEvaluator] = None,
    ) -> StatuteEvaluator:
        """
        Return an evaluator *instance* for *section_code*.

        Parameters
        ----------
        section_code : str
            The IPC section code, e.g. ``"302 IPC"``.
        override : StatuteEvaluator | None
            If supplied, return this instance instead of constructing one
            from the registry (dependency-injection hook).

        Raises
        ------
        TypeError
            If *section_code* is not a string.
        KeyError
            If *section_code* is not registered.
        """
        if override is not None:
            return override
        if not isinstance(section_code, str):
            raise TypeError(
                f"section_code must be a string, got {type(section_code).__name__}"
            )
        if section_code not in self._mapping:
            raise KeyError(
                f"Section {section_code!r} is not registered. "
                f"Known sections: {sorted(self._mapping.keys())}"
            )
        return self._mapping[section_code]()

    # ------------------------------------------------------------------ #
    # Inspection helpers
    # ------------------------------------------------------------------ #

    def list_registered_sections(self) -> Tuple[str, ...]:
        """Return registered section codes as a sorted tuple."""
        return tuple(sorted(self._mapping.keys()))

    def is_registered(self, section_code: str) -> bool:
        """Return ``True`` if *section_code* has been registered."""
        if not isinstance(section_code, str):
            raise TypeError(
                f"section_code must be a string, got {type(section_code).__name__}"
            )
        return section_code in self._mapping

    # ------------------------------------------------------------------ #
    # Freeze (immutability opt-in)
    # ------------------------------------------------------------------ #

    def freeze(self) -> None:
        """Lock the registry — all future ``register()`` calls will raise."""
        self._frozen = True

    @property
    def frozen(self) -> bool:
        """Whether the registry has been frozen."""
        return self._frozen

    # ------------------------------------------------------------------ #
    # Repr
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        sections = ", ".join(sorted(self._mapping.keys()))
        state = "frozen" if self._frozen else "mutable"
        return f"<SectionRegistry [{state}] sections=[{sections}]>"


# ---------------------------------------------------------------------------
# Module-level default registry
# ---------------------------------------------------------------------------

registry = SectionRegistry()
registry.register(IPC302Evaluator.SECTION, IPC302Evaluator)
registry.register(IPC304Evaluator.SECTION, IPC304Evaluator)
registry.register(IPC420Evaluator.SECTION, IPC420Evaluator)
registry.register(IPC323Evaluator.SECTION, IPC323Evaluator)
