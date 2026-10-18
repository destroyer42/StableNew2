"""A small typed HTTP transport (audit E1, P3-4).

Every failure of a request to a local runtime falls into exactly one of four classes, and the class says what a caller
may safely do next:

* ``EndpointUnavailable``: the request provably never reached the server (connection refused, connect timeout, DNS).
  Retrying cannot duplicate work.
* ``DispatchOutcomeUnknown``: the request may have been received and acted on, but no definite answer came back (read
  timeout, connection dropped after sending).  A non-idempotent request (starting a generation) must **never** be retried
  automatically: the server may already be doing the work.
* ``DefiniteRefusal``: the server answered with an error status.  ``status_code`` and a bounded ``body`` are kept.
* ``MalformedResponse``: the server answered but the payload is not what the endpoint promises.

``RequestPolicy`` carries the timeout and whether a request is idempotent.  Only an idempotent request may be retried, and
only for the two classes where that is safe to reason about; retries are off unless asked for.  This module imports
nothing from the rest of the application.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BODY_LIMIT = 2000


class HttpTransportError(RuntimeError):
    """Base of every typed transport failure.  ``method`` and ``path`` identify the request; no secrets are kept."""

    def __init__(self, message: str, *, method: str = "", path: str = "") -> None:
        super().__init__(message)
        self.method = method
        self.path = path


class EndpointUnavailable(HttpTransportError):
    """The request never reached the server.  Safe to retry; cannot have caused work."""


class DispatchOutcomeUnknown(HttpTransportError):
    """The request may have been received.  Never retry a non-idempotent request after this."""


class DefiniteRefusal(HttpTransportError):
    """The server answered with an error status."""

    def __init__(
        self,
        message: str,
        *,
        method: str = "",
        path: str = "",
        status_code: int | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message, method=method, path=path)
        self.status_code = status_code
        self.body = body


class MalformedResponse(HttpTransportError):
    """The server answered, but not with the payload the endpoint promises."""


@dataclass(frozen=True, slots=True)
class RequestPolicy:
    """How one request is bounded.  ``idempotent`` gates retries; ``retries`` defaults to none."""

    timeout: float | tuple[float, float] = 10.0
    idempotent: bool = False
    retries: int = 0
    retry_delay_seconds: float = 0.5


def classify_request_exception(
    exc: BaseException, *, method: str = "", path: str = ""
) -> HttpTransportError:
    """Map a ``requests`` exception to the transport class that says what a caller may do next."""

    where = f"{method} {path}".strip()
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return EndpointUnavailable(f"{where}: connect timed out", method=method, path=path)
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return DispatchOutcomeUnknown(
            f"{where}: no response before the read timeout; the server may have acted on it",
            method=method,
            path=path,
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        if _never_connected(exc):
            return EndpointUnavailable(
                f"{where}: could not connect to the server", method=method, path=path
            )
        return DispatchOutcomeUnknown(
            f"{where}: the connection dropped after the request was sent; the server may have acted on it",
            method=method,
            path=path,
        )
    if isinstance(exc, requests.exceptions.Timeout):
        return DispatchOutcomeUnknown(f"{where}: timed out", method=method, path=path)
    return DispatchOutcomeUnknown(
        f"{where}: request failed ({type(exc).__name__}: {exc})", method=method, path=path
    )


# urllib3 is requests' own dependency (not declared separately), so its exceptions are recognised by class name.
_CONNECT_PHASE_ERRORS = frozenset(
    {"NewConnectionError", "ConnectTimeoutError", "NameResolutionError"}
)


def _never_connected(exc: BaseException) -> bool:
    """True when the failure happened while *establishing* the connection (nothing was sent)."""

    pending: list[Any] = [exc]
    seen: set[int] = set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if type(item).__name__ in _CONNECT_PHASE_ERRORS:
            return True
        pending.extend(getattr(item, "args", ()))
        reason = getattr(item, "reason", None)
        if reason is not None:
            pending.append(reason)
        if isinstance(item, BaseException):
            for link in (item.__cause__, item.__context__):
                if link is not None:
                    pending.append(link)
    return False


class HttpTransport:
    """Typed JSON requests against one base URL, over an injectable ``requests.Session``."""

    def __init__(
        self,
        base_url: str,
        session: requests.Session | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self._session = session or requests.Session()
        self._sleep = sleep

    @property
    def session(self) -> requests.Session:
        return self._session

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # noqa: BLE001 - closing is best-effort
            pass

    def send(
        self,
        method: str,
        path: str,
        *,
        policy: RequestPolicy,
        **request_kwargs: Any,
    ) -> requests.Response:
        """Send one request and return the response, raising a typed error for anything but a 2xx.

        Retries (``policy.retries``) apply only to an idempotent request, and only to ``EndpointUnavailable`` or
        ``DispatchOutcomeUnknown``; a ``DefiniteRefusal`` is the server's answer and is never retried."""

        method = method.upper()
        attempts = 1 + (max(0, policy.retries) if policy.idempotent else 0)
        last: HttpTransportError | None = None
        for attempt in range(attempts):
            if attempt:
                self._sleep(policy.retry_delay_seconds)
            try:
                response = self._call(method, path, policy, request_kwargs)
            except requests.exceptions.RequestException as exc:
                last = classify_request_exception(exc, method=method, path=path)
                logger.debug("[http_transport] %s", last)
                continue
            status = int(getattr(response, "status_code", 200) or 200)
            if status >= 400:
                raise _refusal(response, method=method, path=path, status=status)
            return response
        assert last is not None
        raise last

    def request_json(
        self,
        method: str,
        path: str,
        *,
        policy: RequestPolicy,
        **request_kwargs: Any,
    ) -> dict[str, Any]:
        """Like ``send`` but requires the body to be a JSON object."""

        response = self.send(method, path, policy=policy, **request_kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise MalformedResponse(
                f"{method.upper()} {path}: the response is not JSON", method=method, path=path
            ) from exc
        if not isinstance(payload, dict):
            raise MalformedResponse(
                f"{method.upper()} {path} returned a non-dict payload", method=method, path=path
            )
        return payload

    def _call(
        self, method: str, path: str, policy: RequestPolicy, request_kwargs: dict[str, Any]
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        if method == "GET":
            return self._session.get(url, timeout=policy.timeout, **request_kwargs)
        if method == "POST":
            return self._session.post(url, timeout=policy.timeout, **request_kwargs)
        return self._session.request(method, url, timeout=policy.timeout, **request_kwargs)


def _refusal(
    response: requests.Response, *, method: str, path: str, status: int
) -> DefiniteRefusal:
    body = ""
    try:
        body = str(response.text or "").strip()[:_BODY_LIMIT]
    except Exception:  # noqa: BLE001 - a body that cannot be read is simply absent
        body = ""
    suffix = f" | response_body={body}" if body else ""
    return DefiniteRefusal(
        f"{method} {path} was refused with HTTP {status}{suffix}",
        method=method,
        path=path,
        status_code=status,
        body=body,
    )


__all__ = [
    "DefiniteRefusal",
    "DispatchOutcomeUnknown",
    "EndpointUnavailable",
    "HttpTransport",
    "HttpTransportError",
    "MalformedResponse",
    "RequestPolicy",
    "classify_request_exception",
]
