"""Toli — typed decisions with a calibrated confidence.

Toli is a judge, not a writer. You give it a state and typed questions; it
returns one decision per question with a probability distribution and a
calibrated confidence. It does not write prose, never decides on its own, and
says so when it does not know.
"""

from .client import CONTRACT_VERSION, DEFAULT_BASE_URL, Toli
from .errors import (
    ToliAuthError,
    ToliConfigError,
    ToliError,
    ToliProtocolError,
    ToliRateLimitError,
    ToliTimeoutError,
    ToliUnavailableError,
)
from .questions import Choice, Noul, Question, Score
from .reading import Answer, AnswerKind, Reading, Usage
from .thresholds import Route, Thresholds

__all__ = [
    "CONTRACT_VERSION",
    "DEFAULT_BASE_URL",
    "Answer",
    "AnswerKind",
    "Choice",
    "Noul",
    "Question",
    "Reading",
    "Route",
    "Score",
    "Thresholds",
    "Toli",
    "ToliAuthError",
    "ToliConfigError",
    "ToliError",
    "ToliProtocolError",
    "ToliRateLimitError",
    "ToliTimeoutError",
    "ToliUnavailableError",
    "Usage",
]
