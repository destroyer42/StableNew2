"""App-owned outbound transport for a locally enrolled phone browser."""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import re
import secrets
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Empty, Queue
from sqlite3 import Error as SQLiteError
from threading import Event, Thread
from typing import Any
from urllib.parse import urlsplit

from src.app.site_media_files import SiteOutputError
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_output_routes import (
    NATIVE_REVIEW_ACTIONS,
    OUTPUT_CHUNK,
    OUTPUT_LIBRARY,
    OUTPUT_PLAY,
    OUTPUT_RATING,
)
from src.app.site_output_routes import post as post_output
from src.app.site_output_routes import read as read_output
from src.app.site_phone_admission import PhoneQueueAdmission
from src.app.site_phone_credentials import (
    IDENTIFIER,
    SITE_SECRET,
    PhoneFolder,
    PhoneGrant,
    PhoneGrantStore,
)
from src.app.site_phone_eval import PHONE_EVAL_REFRESH, PHONE_EVAL_RUNS, PhoneEvalReports
from src.app.site_phone_queue import PHONE_QUEUE_PATH, PhoneQueueView
from src.app.site_queue_bridge import SITE_ORIGIN
from src.utils.thread_registry import get_thread_registry

_CONNECTION_VERSION = 2
_ENDPOINT = f"/api/stablenew/connector/v{_CONNECTION_VERSION}/"
_REQUIRED_CAPABILITIES = frozenset({"enrollment", "presence", "browser_lease"})
_VERSION_MESSAGE = "Update the Site and StableNew to matching connection versions."
_HOST = urlsplit(SITE_ORIGIN).netloc
_LIBRARY_READS = frozenset(
    {
        "search",
        "thumbnails",
        "inspect",
        "albums",
        "album",
        "review_results",
        "query_v2",
        "facets_v2",
        "previews_v2",
    }
)
_RUN = re.compile(r"/v1/output/runs/(\d{8}_\d{6}_[A-Za-z0-9_-]{1,150})")
_MEDIA = re.compile(r"/v1/output/media/([a-f0-9]{32})")
_POLL_INTERVAL = 4.0
_IO_TIMEOUT = 4.0
_MAX_RESPONSE = 32 * 1024 * 1024
_call_deadline: ContextVar[float | None] = ContextVar("site_phone_call_deadline", default=None)
log = logging.getLogger(__name__)


class PhoneConnectorError(ValueError):
    """Only sanitized errors reach the local pairing UI."""


class PhoneUnauthenticated(PhoneConnectorError):
    """The hosted grant or the credential is no longer accepted."""


class PhoneGrantExpired(PhoneUnauthenticated):
    """The authenticated Worker no longer has this grant."""


class PhoneGrantRevoked(PhoneUnauthenticated):
    """The authenticated Worker has revoked this grant."""


class PhoneVersionMismatch(PhoneConnectorError):
    """The Site cannot enforce the current connection boundary."""


@dataclass(frozen=True, repr=False)
class PhoneEnrollment:
    id: str
    name: str
    site_secret: str
    challenge: str


@dataclass(frozen=True)
class _Reply:
    status: int
    content_type: str
    data: bytes


def _json_reply(status: int, payload: dict[str, Any]) -> _Reply:
    return _Reply(status, "application/json", json.dumps(payload, ensure_ascii=True).encode())


def _response_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload = dict(pairs)
    if len(payload) != len(pairs):
        raise ValueError("Duplicate response fields.")
    return payload


class PhoneHttp:
    """Send credentials only to the fixed TLS origin. Follow no redirects."""

    def request(
        self,
        action: str,
        site_secret: str,
        credential: str,
        *,
        instance: str = "",
        session: str = "",
        body: dict[str, Any] | _Reply | None = None,
    ) -> dict[str, Any]:
        headers = {
            "X-StableNew-Connection": str(_CONNECTION_VERSION),
            "OAI-Sites-Authorization": f"Bearer {site_secret}",
            "Authorization": f"Bearer {credential}",
        }
        if instance:
            headers["X-StableNew-Instance"] = instance
        if session:
            headers["X-StableNew-Session"] = session
        if isinstance(body, _Reply):
            headers["Content-Type"] = body.content_type
            headers["X-StableNew-Result"] = str(body.status)
            data = body.data
        elif body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        else:
            data = b""
        connection = http.client.HTTPSConnection(_HOST, timeout=_IO_TIMEOUT)
        try:
            connection.request("POST", _ENDPOINT + action, body=data, headers=headers)
            response = connection.getresponse()
            raw = response.read(131073)
            if response.status == 204 and action != "compatibility":
                return {}
            payload = None
            if len(raw) <= 131072:
                try:
                    payload = json.loads(raw, object_pairs_hook=_response_object)
                except (ValueError, RecursionError):
                    pass
            reason = payload.get("error") if isinstance(payload, dict) else None
            if response.status == 404 or (
                response.status == 409 and reason == "connection_version_required"
            ):
                raise PhoneVersionMismatch(_VERSION_MESSAGE)
            if response.status == 410 and action in {"inspect", "enroll", "poll"}:
                if reason == "phone_pairing_expired":
                    raise PhoneGrantExpired("The phone pairing expired.")
                if reason == "phone_pairing_revoked":
                    raise PhoneGrantRevoked("The phone pairing was revoked.")
            if response.status in {401, 403, 410}:
                raise PhoneUnauthenticated(
                    "The private Site refused the phone pairing or service credential."
                )
            if action == "compatibility" and (
                response.status == 204 or response.status == 200 and not isinstance(payload, dict)
            ):
                raise PhoneVersionMismatch(_VERSION_MESSAGE)
            if response.status != 200:
                raise PhoneConnectorError(
                    "The private Site could not complete the phone connection."
                )
            if not isinstance(payload, dict):
                raise PhoneConnectorError("Invalid response from the private Site.")
            return payload
        except (OSError, http.client.HTTPException) as error:
            raise PhoneConnectorError("StableNew could not reach the private Site.") from error
        finally:
            connection.close()


def _desktop_call(
    catalog: SiteOutputCatalog,
    method: object,
    path: object,
    body: object,
    rating: bool,
    *,
    phone_queue: PhoneQueueView | PhoneQueueAdmission | None = None,
    phone_eval: PhoneEvalReports | None = None,
    grant: PhoneGrant | None = None,
) -> _Reply:
    if not isinstance(path, str):
        return _json_reply(403, {"error": "phone_scope_refused"})
    result: dict[str, Any] | tuple[str, bytes]
    try:
        catalog.require_active()
        if (
            path.startswith(PHONE_QUEUE_PATH + "/")
            and phone_queue is not None
            and grant is not None
        ):
            try:
                result = phone_queue.handle(
                    catalog, grant, path.removeprefix(PHONE_QUEUE_PATH + "/"), method, body
                )
            except (AttributeError, KeyError, RuntimeError, TypeError):
                log.exception("Phone queue request could not complete")
                return _json_reply(503, {"error": "queue_unavailable"})
        elif (
            path == PHONE_EVAL_RUNS and method == "GET" and body is None and phone_eval is not None
        ):
            result = phone_eval.list(catalog)
        elif (
            (match := PHONE_EVAL_REFRESH.fullmatch(path))
            and method == "POST"
            and rating
            and phone_eval is not None
        ):
            result = phone_eval.refresh(catalog, match[1], body)
        elif method == "GET" and body is None:
            if path == "/v1/output/runs":
                result = {"runs": catalog.list_runs()}
            elif match := _RUN.fullmatch(path):
                result = catalog.get_run(match[1])
            elif match := _MEDIA.fullmatch(path):
                result = catalog.read_media(match[1])
            else:
                result = read_output(catalog, path)
        elif method == "POST" and isinstance(body, dict):
            action = body.get("action")
            allowed_library = (
                path == OUTPUT_LIBRARY
                and isinstance(action, str)
                and (
                    action in _LIBRARY_READS
                    or rating
                    and action in {"rate", "rating_sync"}
                    or catalog.native_review is not None
                    and action in NATIVE_REVIEW_ACTIONS
                )
            )
            if not (
                allowed_library
                or path in {OUTPUT_PLAY, OUTPUT_CHUNK}
                or (rating and OUTPUT_RATING.fullmatch(path))
            ):
                return _json_reply(403, {"error": "phone_scope_refused"})
            result = post_output(catalog, path, body)
        else:
            return _json_reply(403, {"error": "phone_scope_refused"})
        catalog.require_active()
    except SiteOutputError as error:
        return _json_reply(
            403 if str(error) == "phone_scope_refused" else 409, {"error": str(error)}
        )
    except SQLiteError:
        return _json_reply(503, {"error": "queue_unavailable"})
    except (ValueError, OSError, RecursionError):
        return _json_reply(409, {"error": "output_unavailable"})
    if isinstance(result, tuple):
        reply = _Reply(200, result[0], result[1])
    else:
        reply = _json_reply(200, result)
    if len(reply.data) > _MAX_RESPONSE:
        return _json_reply(413, {"error": "media_too_large"})
    return reply


@dataclass(frozen=True)
class _Claim:
    id: str
    session: str
    deadline: float
    reply: Future[_Reply]


class SitePhoneConnector:
    """One polling actor and at most one native call, independent of Tk."""

    def __init__(
        self,
        store: PhoneGrantStore | None = None,
        http: PhoneHttp | None = None,
        *,
        review_outputs: Callable[[str], Sequence[str]] | None = None,
        review_records: Path | None = None,
        phone_queue: PhoneQueueView | PhoneQueueAdmission | None = None,
        phone_eval: PhoneEvalReports | None = None,
        preview_idle: Callable[[], bool] = lambda: True,
    ) -> None:
        self._store = store if store is not None else PhoneGrantStore()
        self._http = http if http is not None else PhoneHttp()
        self._review_outputs = review_outputs
        self._review_records = review_records
        self._preview_idle = preview_idle
        self._phone_queue = phone_queue
        self._phone_eval = phone_eval
        self._commands: Queue[Callable[[], None]] = Queue()
        self._stopping = Event()
        self._revoke_requested = Event()
        self._instance = secrets.token_hex(16)
        self._thread: Thread | None = None
        self._grant: PhoneGrant | None = None
        self._catalog: SiteOutputCatalog | None = None
        self._presence: tuple[str, float] | None = None
        self._needs_compatibility = True
        self._claim: _Claim | None = None
        self.status = "Phone review is off."

    def start(self) -> None:
        if self._thread is None:
            registry = get_thread_registry()
            remove_listener = registry.add_shutdown_listener(self._signal_stop)

            def run() -> None:
                try:
                    self._run()
                finally:
                    remove_listener()

            try:
                self._thread = registry.spawn(
                    target=run,
                    name="StableNew phone connector",
                    purpose="Paired phone review transport",
                )
            except RuntimeError:
                remove_listener()
                self.status = "Phone review is unavailable during shutdown."

    def _check_compatibility(self, site_secret: str, credential: str) -> None:
        reply = self._http.request("compatibility", site_secret, credential)
        version, capabilities = reply.get("version"), reply.get("capabilities")
        if (
            type(version) is not int
            or version != _CONNECTION_VERSION
            or not isinstance(capabilities, list)
            or any(type(capability) is not str for capability in capabilities)
            or len(capabilities) != len(set(capabilities))
            or not _REQUIRED_CAPABILITIES.issubset(capabilities)
        ):
            raise PhoneVersionMismatch(_VERSION_MESSAGE)

    def inspect(self, site_secret: str, challenge: str) -> Future[PhoneEnrollment]:
        future: Future[PhoneEnrollment] = Future()

        def command() -> None:
            try:
                if self._grant is not None:
                    raise PhoneConnectorError("Revoke the existing phone before pairing another.")
                if not SITE_SECRET.fullmatch(site_secret) or not IDENTIFIER.fullmatch(challenge):
                    raise PhoneConnectorError(
                        "Enter the Site service credential and the phone pairing code."
                    )
                self._check_compatibility(site_secret, challenge)
                result = self._http.request("inspect", site_secret, challenge)
                grant_id, name = result.get("id"), result.get("name")
                if (
                    not isinstance(grant_id, str)
                    or not IDENTIFIER.fullmatch(grant_id)
                    or (not isinstance(name, str) or not name or len(name) > 40)
                ):
                    raise PhoneConnectorError("Invalid phone pairing from the private Site.")
                future.set_result(PhoneEnrollment(grant_id, name, site_secret, challenge))
            except PhoneConnectorError as error:
                future.set_exception(error)

        self._commands.put(command)
        return future

    def enroll(
        self,
        enrollment: PhoneEnrollment,
        folder: Path,
        rating: bool,
        *,
        native_review: bool = False,
        queue_submit: bool = False,
    ) -> Future[None]:
        future: Future[None] = Future()

        def command() -> None:
            try:
                if self._grant is not None or self._revoke_requested.is_set():
                    raise PhoneConnectorError("Revoke the existing phone before pairing another.")
                grant = PhoneGrant(
                    enrollment.id,
                    enrollment.name,
                    enrollment.site_secret,
                    secrets.token_hex(32),
                    PhoneFolder.approve(folder),
                    rating,
                    pending=enrollment.challenge,
                    native_review=native_review,
                    queue_submit=queue_submit,
                )
                self._check_compatibility(grant.site_secret, grant.pending)
                if self._revoke_requested.is_set() or self._stopping.is_set():
                    raise PhoneConnectorError("Phone pairing was canceled.")
                self._store.save(grant)
                self._grant = grant
                self.status = "Confirming phone pairing with the private Site…"
                try:
                    self._confirm_enrollment(grant)
                except (PhoneVersionMismatch, PhoneGrantExpired):
                    # This new attempt was refused before the Worker could enroll it.
                    self._store.clear()
                    self._grant = None
                    self.status = "Phone review is off."
                    raise
                except PhoneConnectorError:
                    # A lost reply can follow server-side enrollment. Keep the approved
                    # recovery record and retry with the same challenge, host and scopes.
                    pass
                future.set_result(None)
            except PhoneConnectorError as error:
                future.set_exception(error)
            except (ValueError, OSError):
                future.set_exception(
                    PhoneConnectorError("Could not protect the selected phone pairing or folder.")
                )

        self._commands.put(command)
        return future

    def revoke(self) -> None:
        self._revoke_requested.set()
        self._commands.put(self._apply_revocation)

    def update_site_credential(self, credential: str) -> Future[None]:
        future: Future[None] = Future()

        def command() -> None:
            if self._grant is None or not SITE_SECRET.fullmatch(credential):
                future.set_exception(
                    PhoneConnectorError("A saved pairing and a valid Site credential are required.")
                )
                return
            grant = replace(self._grant, site_secret=credential)
            try:
                self._check_compatibility(credential, grant.pending or grant.host_secret)
                self._store.save(grant)
            except PhoneConnectorError as error:
                future.set_exception(error)
            except OSError:
                future.set_exception(
                    PhoneConnectorError("Windows could not save the updated Site credential.")
                )
            else:
                self._drop_presence()
                self._grant = grant
                future.set_result(None)

        self._commands.put(command)
        return future

    def _signal_stop(self) -> None:
        self._stopping.set()
        self._commands.put(lambda: None)

    def close(self, timeout: float = 1.0) -> None:
        self._signal_stop()
        if self._thread is not None and timeout > 0:
            self._thread.join(timeout=timeout)

    def _apply_revocation(self) -> None:
        self._drop_presence()
        try:
            if self._grant is not None and not self._grant.revoked:
                revoked = replace(self._grant, revoked=True)
                self._store.save(revoked)
                self._grant = revoked
            self._revoke_requested.clear()
        except (OSError, ValueError):
            self.status = (
                "Phone review is blocked. Keep StableNew open while it saves the revocation."
            )

    def _run(self) -> None:
        try:
            self._grant = self._store.load()
        except (OSError, ValueError):
            self.status = "Windows could not read the saved phone pairing."
        try:
            while not self._stopping.is_set():
                if self._revoke_requested.is_set():
                    self._apply_revocation()
                if self._grant is not None and not self._revoke_requested.is_set():
                    self._step(self._grant)
                try:
                    self._commands.get(timeout=_POLL_INTERVAL)()
                except Empty:
                    pass
        finally:
            if self._revoke_requested.is_set():
                self._apply_revocation()
            self._drop_presence()
            if self._grant is not None:
                try:
                    if self._grant.revoked:
                        self._flush_revocation(self._grant)
                    elif not self._grant.pending:
                        self._request(self._grant, "close")
                except (PhoneConnectorError, OSError):
                    pass  # The hosted presence expires without a heartbeat.

    def _request(self, grant: PhoneGrant, action: str, **options: Any) -> dict[str, Any]:
        return self._http.request(
            action, grant.site_secret, grant.host_secret, instance=self._instance, **options
        )

    def _flush_revocation(self, grant: PhoneGrant) -> None:
        if grant.pending:
            self._http.request(
                "cancel",
                grant.site_secret,
                grant.pending,
                body={"host": hashlib.sha256(grant.host_secret.encode()).hexdigest()},
            )
        else:
            self._request(grant, "revoke")
        self._store.clear()
        self._grant = None
        self.status = "Phone pairing revoked."

    def _step(self, grant: PhoneGrant) -> None:
        try:
            if grant.revoked:
                self.status = "Phone is blocked here. Confirming revocation with the private Site…"
                self._flush_revocation(grant)
                return
            if not grant.folder.matches():
                self._drop_presence()
                self.status = "The approved Output folder changed. Revoke and pair the phone again."
                return
            if self._presence is not None and self._presence[1] <= time.monotonic():
                self._drop_presence()
            if self._needs_compatibility:
                self._check_compatibility(grant.site_secret, grant.pending or grant.host_secret)
            if grant.pending:
                grant = self._confirm_enrollment(grant)
            self._poll(grant)
        except PhoneVersionMismatch as error:
            self._drop_presence()
            self.status = str(error)
        except (PhoneGrantExpired, PhoneGrantRevoked) as error:
            self._drop_presence()
            try:
                self._store.clear()
                self._grant = None
                self.status = f"{error} Pair again from your phone."
            except OSError:
                self.status = "Windows could not remove the expired phone pairing."
        except PhoneUnauthenticated:
            self._drop_presence()
            self.status = (
                "The Site refused phone review. Check the credential or revoke and pair again."
            )
        except (PhoneConnectorError, ValueError, OSError):
            # Fence new work while unavailable. The same live presence can recover
            # its catalog and opaque media scope after compatibility is verified.
            self._needs_compatibility = True
            self.status = "Phone review is offline. StableNew will reconnect."

    def _confirm_enrollment(self, grant: PhoneGrant) -> PhoneGrant:
        if self._revoke_requested.is_set() or self._stopping.is_set():
            raise PhoneConnectorError("Phone pairing was canceled.")
        approved = self._http.request(
            "enroll",
            grant.site_secret,
            grant.pending,
            instance=self._instance,
            body={
                "host": hashlib.sha256(grant.host_secret.encode()).hexdigest(),
                "rating": grant.rating,
                **({"native_review": True} if grant.native_review else {}),
                **({"queue_submit": True} if grant.queue_submit else {}),
            },
        )
        if approved.get("id") != grant.id:
            raise PhoneConnectorError("The approved phone pairing changed.")
        confirmed = replace(grant, pending="")
        self._store.save(confirmed)
        self._grant = confirmed
        return confirmed

    def _live(self, session: str, folder: PhoneFolder) -> bool:
        current = self._presence
        deadline = _call_deadline.get()
        now = time.monotonic()
        return (
            not self._stopping.is_set()
            and not self._revoke_requested.is_set()
            and not self._needs_compatibility
            and current is not None
            and current[0] == session
            and current[1] > now
            and (deadline is None or deadline > now)
            and folder.matches()
        )

    def _drop_presence(self) -> None:
        self._needs_compatibility = True
        self._presence = None
        if self._catalog is not None:
            self._catalog.revoke()
            self._catalog = None

    def _poll(self, grant: PhoneGrant) -> None:
        started = time.monotonic()
        reply = self._request(grant, "poll", body={"claim": self._claim is None})
        if type(reply.get("version")) is not int or reply["version"] != _CONNECTION_VERSION:
            raise PhoneVersionMismatch(_VERSION_MESSAGE)
        session, ttl = reply.get("session"), reply.get("ttl")
        if (
            not isinstance(session, str)
            or not IDENTIFIER.fullmatch(session)
            or (type(ttl) is not int or not 0 < ttl <= 30000)
        ):
            raise PhoneConnectorError("Invalid presence lease from the private Site.")
        if self._presence is None or self._presence[0] != session:
            self._drop_presence()
            self._catalog = SiteOutputCatalog(
                Path(grant.folder.path),
                active=lambda: self._live(session, grant.folder),
                review_outputs=self._review_outputs,
                review_records=self._review_records if grant.native_review else None,
                preview_idle=self._preview_idle,
            )
        self._presence = session, started + ttl / 1000
        self._needs_compatibility = False
        if not self._live(session, grant.folder):
            self._drop_presence()
            return
        if self._catalog is not None:
            self._catalog.library.start()
        self.status = f"Phone review online · {grant.name}"
        if self._claim is not None and self._claim.reply.done():
            claim, self._claim = self._claim, None
            if claim.session == session and claim.deadline > time.monotonic():
                self._request(
                    grant, "fulfill/" + claim.id, session=session, body=claim.reply.result()
                )
        call = reply.get("call")
        if call is not None and self._claim is None and self._catalog is not None:
            self._start_call(call, session, started, self._catalog, grant)

    def _start_call(
        self, call: Any, session: str, started: float, catalog: SiteOutputCatalog, grant: PhoneGrant
    ) -> None:
        if not isinstance(call, dict):
            return
        call_id, ttl = call.get("id"), call.get("ttl")
        if (
            not isinstance(call_id, str)
            or not IDENTIFIER.fullmatch(call_id)
            or (type(ttl) is not int or not 0 < ttl <= 75000)
        ):
            return
        future: Future[_Reply] = Future()
        claim = _Claim(call_id, session, started + ttl / 1000, future)
        self._claim = claim

        def dispatch() -> None:
            token = _call_deadline.set(claim.deadline)
            try:
                future.set_result(
                    _desktop_call(
                        catalog,
                        call.get("method"),
                        call.get("path"),
                        call.get("body"),
                        grant.rating,
                        phone_queue=self._phone_queue,
                        phone_eval=self._phone_eval,
                        grant=grant,
                    )
                )
            finally:
                _call_deadline.reset(token)
                self._commands.put(lambda: None)

        try:
            get_thread_registry().spawn(
                target=dispatch, name="StableNew phone review call", purpose="Scoped Output review"
            )
        except RuntimeError:
            self._claim = None
