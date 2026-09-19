"""The shared conformance suite, replayed against the Python SDK.

These cases live in spec/conformance/ and are replayed by every SDK. They are
the only thing that keeps "confirm" meaning the same in Python and in PHP — a
language-specific test only proves a language-specific belief.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from toli import (
    Choice,
    Noul,
    Reading,
    Score,
    Thresholds,
    Toli,
    ToliAuthError,
    ToliConfigError,
    ToliProtocolError,
    ToliUnavailableError,
)

def _spec_dir() -> Path:
    """The shared fixtures, wherever this package is sitting.

    Two layouts must work: the monorepo, where spec/ is one level above the
    language folder, and the published mirror, where it was vendored at the
    root. A hard-coded path passes in one and fails in the other — which is
    exactly what happened the first time a mirror was cloned.
    """
    here = Path(__file__).resolve()

    for candidate in (here.parents[1] / "spec", here.parents[2] / "spec"):
        if (candidate / "conformance").is_dir():
            return candidate / "conformance"

    raise FileNotFoundError("Conformance fixtures not found")


SPEC = _spec_dir()


def spec(name: str) -> dict[str, Any]:
    return json.loads((SPEC / name).read_text())


ROUTING = spec("routing.json")


class ScriptedTransport(httpx.BaseTransport):
    """A scripted transport: hand it the responses, read back the requests."""

    def __init__(self, responses: list[httpx.Response | str]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)

        if not self._responses:
            raise AssertionError("The scripted transport ran out of responses.")

        nxt = self._responses.pop(0)
        if nxt == "network-failure":
            raise httpx.ConnectError("connection reset by peer", request=request)

        assert isinstance(nxt, httpx.Response)
        return nxt


def ok(body: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(200, json=body, headers=headers or {})


def client(
    responses: list[httpx.Response | str],
    thresholds: Thresholds | None = None,
) -> tuple[Toli, ScriptedTransport, list[float]]:
    transport = ScriptedTransport(responses)
    waits: list[float] = []
    toli = Toli(
        "test-key",
        client=httpx.Client(transport=transport),
        thresholds=thresholds,
        sleep=waits.append,
    )

    return toli, transport, waits


def read(body: dict[str, Any], thresholds: Thresholds | None = None) -> Reading:
    return Reading.parse({"model": "toli-1", **body}, "toli-1", thresholds or Thresholds.defaults())


# --- Routing, straight from the shared fixtures -----------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [(case["answer"], case["expect"]) for case in ROUTING["cases"]],
    ids=[case["name"] for case in ROUTING["cases"]],
)
def test_routing(answer: dict[str, Any], expected: str) -> None:
    thresholds = Thresholds.measured(
        ROUTING["thresholds"]["act"],
        ROUTING["thresholds"]["confirm"],
        "conformance suite",
        "2026-09-19",
    )
    # The fixture describes the answer as it arrives on the wire, minus the
    # `kind` discriminator, which the parser infers from the payload shape.
    wire = {k: v for k, v in answer.items() if k != "kind"}

    assert read({"answers": {"q": wire}}, thresholds).route("q") == expected


def test_a_noul_at_perfect_doubt_never_acts() -> None:
    # THE mistake the contract guards against: comparing `noul` straight to the
    # act threshold would make 0.5 — the admission of ignorance — look like
    # near-certainty.
    reading = read({"answers": {"q": {"noul": 0.5}}})

    assert reading.route("q") == "escalate"
    assert reading.answer("q").certainty == 0.0


def test_a_confident_no_is_worth_a_confident_yes() -> None:
    no = read({"answers": {"q": {"noul": 0.02}}})
    yes = read({"answers": {"q": {"noul": 0.98}}})

    assert no.route("q") == "act"
    assert yes.route("q") == "act"
    assert no.answer("q").certainty == pytest.approx(yes.answer("q").certainty)
    assert not no.answer("q").is_yes
    assert yes.answer("q").is_yes


# --- Advisory mode ----------------------------------------------------------


@pytest.mark.parametrize("certainty", [1.0, 0.99, 0.85, 0.61])
def test_advisory_thresholds_can_never_reach_act(certainty: float) -> None:
    # The guarantee clinical use rests on: for screening or orientation, a wrong
    # answer is not re-routed the next morning. No confidence buys an automatic
    # action, so the route tops out at "confirm" by construction.
    advisory = Thresholds.advisory_only(0.60, "screening corpus", "2026-09-19")

    assert advisory.route(certainty) == "confirm"


def test_advisory_escalates_below_confirm() -> None:
    advisory = Thresholds.advisory_only(0.60, "screening corpus", "2026-09-19")

    assert advisory.route(0.59) == "escalate"


def test_an_advisory_reading_never_returns_act_end_to_end() -> None:
    advisory = Thresholds.advisory_only(0.60, "screening corpus", "2026-09-19")
    reading = read({"answers": {"q": {"choice": "screen", "confidence": 0.999}}}, advisory)

    assert reading.route("q") == "confirm"
    assert reading.to_log()["thresholds"]["advisory"] is True


def test_advisory_thresholds_must_say_on_what_and_when() -> None:
    with pytest.raises(ToliConfigError):
        Thresholds.advisory_only(0.6, "", "")


# --- Requests ---------------------------------------------------------------


def test_every_question_travels_in_a_single_request() -> None:
    toli, transport, _ = client([ok({"model": "toli-1", "answers": {"a": {"noul": 0.9}}})])

    toli.ask(
        "a state",
        {
            "a": Noul("Something is true"),
            "b": Choice("Which team", {"x": "X", "other": "None of the above"}),
            "c": Score("How tense", ["Calm", "Tense"]),
        },
    )

    assert len(transport.requests) == 1
    body = json.loads(transport.requests[0].content)
    assert list(body["questions"]) == ["a", "b", "c"]
    assert body["questions"]["b"]["kind"] == "choice"
    assert str(transport.requests[0].url) == "https://toli.essabu.com/v1/ask"


def test_a_structured_state_is_serialised_as_is() -> None:
    toli, transport, _ = client([ok({"model": "toli-1", "answers": {"a": {"noul": 0.9}}})])
    state = {"interface": "CommCare", "feature": "Sync"}

    toli.ask(state, {"a": Noul("Blocked today")})

    assert json.loads(transport.requests[0].content)["state"] == state


def test_a_single_option_choice_is_refused() -> None:
    with pytest.raises(ToliConfigError):
        Choice("Which team", {"application": "The app"})


def test_a_missing_key_fails_before_the_network() -> None:
    with pytest.raises(ToliConfigError):
        Toli("")


def test_asking_nothing_fails_before_the_network() -> None:
    toli, transport, _ = client([])

    with pytest.raises(ToliConfigError):
        toli.ask("s", {})

    assert transport.requests == []


def test_inverted_and_out_of_bounds_thresholds_are_refused() -> None:
    with pytest.raises(ToliConfigError):
        Thresholds.measured(0.6, 0.85, "x", "2026-09-19")
    with pytest.raises(ToliConfigError):
        Thresholds.measured(1.4, 0.6, "x", "2026-09-19")
    with pytest.raises(ToliConfigError):
        Thresholds.measured(0.9, 0.6, "", "")


# --- Responses --------------------------------------------------------------


def test_the_served_model_wins_over_the_requested_one() -> None:
    # Pinning a version only protects you if you can tell you were served
    # something else.
    reading = Reading.parse(
        {"model": "toli-1.14", "answers": {"q": {"noul": 0.1}}}, "toli-1", Thresholds.defaults()
    )

    assert reading.model == "toli-1.14"


def test_missing_usage_counts_as_zero() -> None:
    assert read({"answers": {"q": {"noul": 0.9}}}).usage.to_dict() == {
        "input_tokens": 0,
        "output_tokens": 0,
    }


def test_a_reading_logs_the_decision_but_never_the_state() -> None:
    log = read(
        {
            "model": "toli-1.13",
            "answers": {
                "q": {
                    "choice": "sync",
                    "confidence": 0.92,
                    "probabilities": {"sync": 0.92, "other": 0.08},
                }
            },
        }
    ).to_log()

    assert log["model"] == "toli-1.13"
    assert log["answers"]["q"]["route"] == "act"
    assert log["answers"]["q"]["probabilities"] == {"sync": 0.92, "other": 0.08}
    assert "thresholds" in log
    assert "state" not in json.dumps(log)


# --- Errors and retries -----------------------------------------------------


def test_a_rejected_key_is_not_retried() -> None:
    toli, transport, _ = client([httpx.Response(401, json={"error": "invalid api key"})])

    with pytest.raises(ToliAuthError) as error:
        toli.ask("s", {"q": Noul("x")})

    assert error.value.status == 401
    assert len(transport.requests) == 1


def test_a_dropped_connection_is_retried() -> None:
    # 3 readings out of 897 were lost before this rule existed.
    toli, transport, _ = client(
        ["network-failure", ok({"model": "toli-1", "answers": {"q": {"noul": 0.9}}})]
    )

    assert toli.ask("s", {"q": Noul("x")}).model == "toli-1"
    assert len(transport.requests) == 2


def test_a_persistent_outage_gives_up_after_five_attempts() -> None:
    toli, transport, _ = client(
        [httpx.Response(503, json={"error": "unavailable"}) for _ in range(6)]
    )

    with pytest.raises(ToliUnavailableError):
        toli.ask("s", {"q": Noul("x")})

    assert len(transport.requests) == 5


def test_the_server_retry_after_wins_over_our_backoff() -> None:
    toli, _, waits = client(
        [
            httpx.Response(429, json={"error": "rate limited"}, headers={"retry-after": "2"}),
            ok({"model": "toli-1", "answers": {"q": {"noul": 0.9}}}),
        ]
    )

    toli.ask("s", {"q": Noul("x")})

    assert waits == [2.0]


def test_a_200_without_answers_is_a_protocol_error() -> None:
    toli, transport, _ = client([ok({"model": "toli-1"})])

    with pytest.raises(ToliProtocolError):
        toli.ask("s", {"q": Noul("x")})

    assert len(transport.requests) == 1


def test_an_error_carries_the_request_id_and_a_bounded_excerpt() -> None:
    toli, _, _ = client(
        [httpx.Response(400, text="x" * 5000, headers={"x-request-id": "req_8fa31"})]
    )

    with pytest.raises(ToliProtocolError) as error:
        toli.ask("s", {"q": Noul("x")})

    assert error.value.request_id == "req_8fa31"
    assert error.value.body_excerpt is not None
    assert len(error.value.body_excerpt) == 300
