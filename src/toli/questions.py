"""The three typed questions — the only way to ask Toli anything."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .errors import ToliConfigError


@runtime_checkable
class Question(Protocol):
    """Three forms, no more: a closed choice, an ordered degree, a statement.

    Everything else belongs to the calling code.
    """

    def to_dict(self) -> dict[str, Any]:
        """The body put on the wire."""
        ...


@dataclass(frozen=True, slots=True)
class Choice:
    """One option out of a CLOSED set.

    Always leave an escape hatch ("other", "none"…): without one the model is
    forced to pick between boxes that do not describe the case, and the
    confidence it returns stops meaning anything.

    Args:
        instructions: what is being asked, preferably in English.
        criteria: option -> what it covers.
    """

    instructions: str
    criteria: dict[str, str]

    def __post_init__(self) -> None:
        if len(self.criteria) < 2:
            raise ToliConfigError(
                'A Choice with fewer than two options leaves no choice: '
                'add at least an escape hatch ("other").'
            )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "choice", "instructions": self.instructions, "criteria": self.criteria}


@dataclass(frozen=True, slots=True)
class Score:
    """A degree on ORDERED, described levels, from weakest to strongest.

    What comes back is a weighted float, not an index: "1.4" says something
    "level 1" does not.
    """

    instructions: str
    criteria: list[str]

    def __post_init__(self) -> None:
        if len(self.criteria) < 2:
            raise ToliConfigError("A Score needs at least two ordered levels.")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "score", "instructions": self.instructions, "criteria": self.criteria}


@dataclass(frozen=True, slots=True)
class Noul:
    """A statement: is it true?

    What comes back is the probability of yes — and NOT a confidence. 0.5 is the
    admission of ignorance; 0.02 and 0.98 are both frank answers. The SDK
    derives certainty from it (distance from doubt) to pick the route.
    """

    instructions: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "noul", "instructions": self.instructions}
