"""The thresholds that decide between the three routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .errors import ToliConfigError

#: The three routes — the heart of Toli.
#:
#: Toli never decides alone: it returns a route, and the caller acts. A library
#: that applied the decision on the caller's behalf would remove the human
#: guardrail without anyone having chosen to.
Route = Literal["act", "confirm", "escalate"]


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Where the three routes begin.

    A threshold holds for ONE model, ONE set of questions, ONE corpus. Lifting
    it from another project without re-measuring is flying blind — hence
    ``measured_on`` and ``measured_at``, required as soon as you depart from the
    defaults: whoever reads ``act=0.9`` six months from now must be able to tell
    what that 0.9 was established on, and when.
    """

    act: float
    confirm: float
    measured_on: str
    measured_at: str
    advisory: bool = False

    @classmethod
    def measured(cls, act: float, confirm: float, measured_on: str, measured_at: str) -> Thresholds:
        """MEASURED thresholds: say on what, and when.

        Args:
            measured_on: the corpus — "896 do-alo tickets, French".
            measured_at: the date — "2026-09-18".
        """
        if not measured_on or not measured_at:
            raise ToliConfigError(
                "Measured thresholds state what they were measured on and when: "
                "measured_on and measured_at are required."
            )
        if act > 1 or confirm <= 0:
            raise ToliConfigError(
                "Thresholds out of bounds: 0 < confirm <= act <= 1 "
                f"(got act={act}, confirm={confirm})."
            )
        if confirm > act:
            raise ToliConfigError(
                "Confirm threshold above the act threshold: the 'propose' route would be "
                f"unreachable (act={act}, confirm={confirm})."
            )

        return cls(act=act, confirm=confirm, measured_on=measured_on, measured_at=measured_at)

    @classmethod
    def advisory_only(cls, confirm: float, measured_on: str, measured_at: str) -> Thresholds:
        """ADVISORY thresholds: Toli may propose, never act.

        For any domain where acting alone would be irreversible or unsafe —
        clinical orientation, screening for sickle-cell disease, haemophilia or
        rare diseases, anything touching a person's care. There, a wrong answer
        is not re-routed the next morning.

        The guarantee is structural, not a matter of picking a high threshold:
        :meth:`route` cannot return ``"act"``, whatever the model's confidence.
        The most a reading can earn is ``"confirm"`` — a proposal a qualified
        human accepts or rejects.
        """
        if not measured_on or not measured_at:
            raise ToliConfigError(
                "Advisory thresholds state what they were measured on and when: "
                "measured_on and measured_at are required."
            )
        if confirm <= 0 or confirm > 1:
            raise ToliConfigError(
                f"Confirm threshold out of bounds: 0 < confirm <= 1 (got {confirm})."
            )

        return cls(
            act=1.0,
            confirm=confirm,
            measured_on=measured_on,
            measured_at=measured_at,
            advisory=True,
        )

    @classmethod
    def defaults(cls) -> Thresholds:
        """The contract defaults, NOT measured on your data.

        Fine to start with, wrong to decide with: measure, then move to
        :meth:`measured`.
        """
        return cls(
            act=0.85,
            confirm=0.60,
            measured_on="contract defaults — not measured on your data",
            measured_at="",
        )

    def route(self, certainty: float) -> Route:
        """The route a given certainty calls for. Both thresholds are INCLUSIVE."""
        if self.advisory:
            # No amount of confidence buys an automatic action here.
            return "confirm" if certainty >= self.confirm else "escalate"

        if certainty >= self.act:
            return "act"
        if certainty >= self.confirm:
            return "confirm"

        return "escalate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "act": self.act,
            "confirm": self.confirm,
            "measured_on": self.measured_on,
            "measured_at": self.measured_at,
            "advisory": self.advisory,
        }
