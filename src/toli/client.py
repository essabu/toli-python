"""The Toli client."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from .errors import (
    ToliAuthError,
    ToliConfigError,
    ToliProtocolError,
    ToliRateLimitError,
    ToliUnavailableError,
    excerpt,
)
from .questions import Question
from .reading import Reading
from .thresholds import Thresholds

#: The Essabu gateway — the only public path.
DEFAULT_BASE_URL = "https://toli.essabu.com"

#: Attempts, then we hand control back.
MAX_ATTEMPTS = 5

#: Statuses worth trying again: quota, overload. 5xx joins them below.
RETRYABLE = frozenset({429, 529})

CONTRACT_VERSION = 1


class Toli:
    """Ask Toli to read a state.

    One call carries a state and every question at once: the model evaluates
    them in parallel, which is an order of magnitude cheaper and faster than one
    request per question.

    Nothing here applies a decision. :meth:`ask` returns a
    :class:`~toli.reading.Reading`; the caller reads the route and acts. That
    asymmetry is deliberate.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        thresholds: Thresholds | None = None,
        model: str = "toli-1",
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ToliConfigError("Missing Toli API key: nothing can be asked without it.")

        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._thresholds = thresholds or Thresholds.defaults()
        self._model = model
        # 15 s to connect, 60 s overall — the contract's deadlines.
        self._client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))
        self._sleep = sleep

    def ask(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[str, Question],
        model: str | None = None,
    ) -> Reading:
        """Read a state with every question, in a single call.

        Send what is needed to judge — and nothing more. Names, phone numbers
        and personal identifiers have no bearing on a category and no business
        leaving your infrastructure.
        """
        if not questions:
            raise ToliConfigError("Asking Toli nothing: provide at least one question.")

        served_model = model or self._model
        payload = {
            "state": dict(state) if isinstance(state, Mapping) else state,
            "model": served_model,
            "questions": {name: question.to_dict() for name, question in questions.items()},
        }

        response = self._send(payload)

        try:
            body = response.json()
        except ValueError:
            raise ToliProtocolError(
                "Unreadable response body: expected JSON.",
                status=response.status_code,
                request_id=response.headers.get("x-request-id"),
                body_excerpt=excerpt(response.text),
            ) from None

        return Reading.parse(body, served_model, self._thresholds)

    def _send(self, payload: dict[str, Any]) -> httpx.Response:
        attempt = 0

        while True:
            attempt += 1

            try:
                response = self._client.post(
                    f"{self._base_url}/v1/ask",
                    json=payload,
                    headers={
                        "authorization": f"Bearer {self._api_key}",
                        "user-agent": f"toli-python/{CONTRACT_VERSION}",
                    },
                )
            except httpx.HTTPError as error:
                # A dropped connection is transient and retries like a 429.
                # Three readings out of 897 were lost before this rule existed.
                if attempt >= MAX_ATTEMPTS:
                    raise ToliUnavailableError(
                        f"Toli unreachable after {attempt} attempts: {error}"
                    ) from error

                self._backoff(attempt)
                continue

            status = response.status_code

            if 200 <= status < 300:
                return response

            request_id = response.headers.get("x-request-id")

            if status in (401, 403):
                raise ToliAuthError(
                    "Toli rejected the key: retrying would change nothing.",
                    status=status,
                    request_id=request_id,
                    body_excerpt=excerpt(response.text),
                )

            if status not in RETRYABLE and status < 500:
                raise ToliProtocolError(
                    f"Toli answered HTTP {status}.",
                    status=status,
                    request_id=request_id,
                    body_excerpt=excerpt(response.text),
                )

            if attempt >= MAX_ATTEMPTS:
                message = f"Toli still failing after {attempt} attempts (HTTP {status})."
                error_type = ToliRateLimitError if status == 429 else ToliUnavailableError

                raise error_type(
                    message,
                    status=status,
                    request_id=request_id,
                    body_excerpt=excerpt(response.text),
                )

            # A server that states its own retry-after knows its load better
            # than our backoff curve does.
            self._backoff(attempt, self._retry_after(response))

    def _backoff(self, attempt: int, retry_after: float | None = None) -> None:
        self._sleep(retry_after if retry_after is not None else float(2 ** (attempt - 1)))

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        header = response.headers.get("retry-after")

        try:
            return float(header) if header else None
        except ValueError:
            return None
