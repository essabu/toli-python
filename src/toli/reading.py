"""What Toli read: one answer per question, plus enough to replay it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .errors import ToliProtocolError
from .thresholds import Route, Thresholds

AnswerKind = Literal["choice", "score", "noul"]


@dataclass(frozen=True, slots=True)
class Answer:
    """Toli's answer to ONE question, and the route it calls for.

    ``certainty`` is the quantity the route is decided on. For a choice or a
    score it is the confidence the model returned. A noul carries no confidence:
    there it is the distance from doubt.
    """

    kind: AnswerKind
    value: str | float
    certainty: float
    route: Route
    probabilities: dict[str, float] = field(default_factory=dict)
    legend: str | None = None

    @property
    def is_yes(self) -> bool:
        """True when Toli leans towards yes — only meaningful for a noul."""
        return self.kind == "noul" and float(self.value) > 0.5

    def to_log(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "certainty": self.certainty,
            "route": self.route,
            "probabilities": self.probabilities,
            "legend": self.legend,
        }


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


def _probabilities(raw: dict[str, Any]) -> dict[str, float]:
    values = raw.get("probabilities")
    if not isinstance(values, dict):
        return {}

    return {
        str(option): float(p) if isinstance(p, (int, float)) else 0.0
        for option, p in values.items()
    }


def _parse_answer(name: str, raw: dict[str, Any], thresholds: Thresholds) -> Answer:
    confidence = raw.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.0

    if "choice" in raw:
        return Answer(
            kind="choice",
            value=str(raw["choice"]),
            certainty=confidence,
            route=thresholds.route(confidence),
            probabilities=_probabilities(raw),
        )

    if "score" in raw:
        legend = raw.get("legend")

        return Answer(
            kind="score",
            value=float(raw["score"]),
            certainty=confidence,
            route=thresholds.route(confidence),
            legend=str(legend) if isinstance(legend, str) else None,
        )

    if "noul" in raw:
        noul = float(raw["noul"])
        # A noul returns no confidence: 0.5 is the admission of ignorance, while
        # 0.02 and 0.98 are both frank answers. Certainty is therefore the
        # distance from doubt, rescaled onto [0, 1] — without which a confident
        # "no" would rank below an "I don't know".
        certainty = abs(noul - 0.5) * 2

        return Answer(
            kind="noul",
            value=noul,
            certainty=certainty,
            route=thresholds.route(certainty),
        )

    raise ToliProtocolError(
        f'Answer "{name}" has an unknown shape: neither choice, score, nor noul.'
    )


@dataclass(frozen=True, slots=True)
class Reading:
    model: str
    answers: dict[str, Answer]
    usage: Usage
    thresholds: Thresholds

    @classmethod
    def parse(cls, body: dict[str, Any], requested_model: str, thresholds: Thresholds) -> Reading:
        raw_answers = body.get("answers")
        if not isinstance(raw_answers, dict):
            raise ToliProtocolError(
                'Response without "answers": the server replied, but not to the question asked.'
            )

        answers = {
            str(name): _parse_answer(str(name), raw, thresholds)
            for name, raw in raw_answers.items()
            if isinstance(raw, dict)
        }

        raw_usage = body.get("usage")
        raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
        usage = Usage(
            input_tokens=int(raw_usage.get("input_tokens", 0) or 0),
            output_tokens=int(raw_usage.get("output_tokens", 0) or 0),
        )

        model = body.get("model")

        return cls(
            # The model as the SERVER reported it, never echoed from the
            # request: that is what surfaces the day the provider ships an
            # update and you are no longer served the version you pinned.
            model=str(model) if isinstance(model, str) else requested_model,
            answers=answers,
            usage=usage,
            thresholds=thresholds,
        )

    def answer(self, question: str) -> Answer:
        try:
            return self.answers[question]
        except KeyError:
            raise ToliProtocolError(
                f'No answer for "{question}": Toli did not answer that question.'
            ) from None

    def route(self, question: str) -> Route:
        """The route to take for this question: act, propose, or escalate."""
        return self.answer(question).route

    def value(self, question: str) -> str | float:
        return self.answer(question).value

    def to_log(self) -> dict[str, Any]:
        """Enough to replay every decision. The state is not in there."""
        return {
            "model": self.model,
            "thresholds": self.thresholds.to_dict(),
            "usage": self.usage.to_dict(),
            "answers": {name: answer.to_log() for name, answer in self.answers.items()},
        }
