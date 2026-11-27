"""The review gateway sync worker (RG-120): one background thread, outbound only, no Tk.

Each cycle it sends what this PC owes the gateway (pairing offers, device revocations, acknowledgements not yet
delivered), pulls pending outbox records page by page, applies each through ``RecordApplier`` and acknowledges it,
stores Immich receipts once the gateway offers them (RG-130), publishes the PC's checkout and queue status for admin
phones (LAUNCH-UPDATE-2, once a ``RemoteUpdate`` is attached), and publishes a few new Output Library items. While a
job is running it publishes at most one item every ``BUSY_PUBLISH_SECONDS`` and never transcodes, so it does not
compete with generation. Registered rating sets (RG-170, ``review_gateway_ratings.py``) are sent and submitted
ratings applied once a ``RatingTaskSync`` is attached.

The worker is registered with ``src/utils/thread_registry.py`` and stops on application shutdown. The desktop dialog
calls the public methods from the Tk thread; they only record intent and wake the worker, and ``status()`` returns an
immutable snapshot the dialog renders.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from typing import Any

from src.app.review_gateway_apply import IN_PROGRESS, ApplyDeferred, RecordApplier
from src.app.review_gateway_client import (
    GatewayClient,
    GatewayError,
    GatewayPinMismatch,
    GatewayUnauthorized,
    GatewayUnavailable,
    PinnedHttpsTransport,
    Transport,
)
from src.app.review_gateway_protocol import (
    SCHEMA_VERSION,
    PairingOffer,
    ProtocolError,
    acknowledgement,
    device_revocation,
    display_code,
    encode_json,
    new_pairing_offer,
    parse_immich_receipt,
    parse_json,
    parse_outbox_page,
    parse_timestamp,
    utc_now,
    utc_text,
)
from src.app.review_gateway_publish import GatewayPublisher
from src.app.review_gateway_store import Device, GatewaySettings, GatewaySettingsStore, SyncLedger
from src.app.site_media_files import SiteOutputError
from src.utils.thread_registry import get_thread_registry

log = logging.getLogger(__name__)

SYNC_INTERVAL = 5.0
MAX_BACKOFF = 60.0
BUSY_PUBLISH_SECONDS = 30.0
#: ``pc_status`` is sent when it changes, and at least this often so an admin phone can tell the PC is there.
STATUS_HEARTBEAT_SECONDS = 60.0
#: After a gateway that does not offer the ``pc_status`` route yet, ask again this much later.
STATUS_UNSUPPORTED_SECONDS = 600.0
IDLE_PUBLISH_BATCH = 8
#: After a job completes, its outputs are looked for this long (the index needs a moment to see them).
FRESH_SECONDS = 30.0
#: How old an output may be and still count as the completed job's.
FRESH_OUTPUT_S = 15 * 60
MAX_PAGES_PER_CYCLE = 10
PAGE_SIZE = 100
#: After the PC answers a phone action, the phone is usually about to send the next step ("Queue" after the summary),
#: so for a short window only the outbox is read, every second, instead of every ``SYNC_INTERVAL``.
ACTION_FOLLOW_INTERVAL = 1.0
ACTION_FOLLOW_WINDOW = 60.0

_MESSAGES = {
    "not_configured": "Not set up. Enter the gateway address, certificate fingerprint and sync secret.",
    "connecting": "Connecting to the review gateway…",
    "idle": "Synced.",
    "offline": "The review gateway is not reachable; decisions wait on the gateway.",
    "refused_secret": "The gateway refused the sync secret. Enter the secret from the gateway install.",
    "certificate_mismatch": "The gateway certificate does not match the saved fingerprint; nothing was sent.",
    "invalid_response": "The gateway sent a response outside the sync contract; it was ignored.",
    "evidence_unavailable": "Review evidence could not be saved; phone decisions wait and are retried.",
    "settings_unreadable": "Windows could not read the saved review gateway settings.",
    "error": "A sync step failed unexpectedly; it is retried. See the log.",
    "stopped": "Stopped.",
}


@dataclass(frozen=True)
class SyncStatus:
    state: str = "not_configured"
    address: str = ""
    last_publish_at: str = ""
    last_pull_at: str = ""
    published: int = 0
    pending_publish: int = 0
    refused: int = 0
    devices: tuple[Device, ...] = ()
    pairing_code: str = ""
    pairing_expires_at: str = ""
    recent_refusals: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def message(self) -> str:
        return _MESSAGES.get(self.state, self.state)


class ReviewGatewaySync:
    def __init__(
        self,
        *,
        settings_store: GatewaySettingsStore,
        ledger: SyncLedger,
        publisher_factory: Callable[[], GatewayPublisher | None],
        applier: RecordApplier,
        busy: Callable[[], bool] = lambda: False,
        transport_factory: Callable[[GatewaySettings], Transport] = PinnedHttpsTransport,
        interval: float = SYNC_INTERVAL,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = settings_store
        self._ledger = ledger
        self._publisher_factory = publisher_factory
        self._publisher: GatewayPublisher | None = None
        self._applier = applier
        self._busy = busy
        self._transport_factory = transport_factory
        self._interval = interval
        self._monotonic = monotonic
        self._wake = Event()
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._status = SyncStatus()
        self._offer: PairingOffer | None = None
        self._settings: GatewaySettings | None = None
        self._settings_loaded = False
        self._last_busy_publish = -BUSY_PUBLISH_SECONDS
        self._fresh_until: float | None = None
        self._backoff = 0.0
        self._follow_until = -1.0
        self._last_full_cycle = -interval
        self._status_source: Callable[[], dict[str, Any] | None] | None = None
        self._ratings: Any = None
        self._last_status: dict[str, Any] | None = None
        self._last_status_at = 0.0
        self._status_retry_at = 0.0

    # -- Tk-thread API (records intent only) -----------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            registry = get_thread_registry()
            self._unsubscribe = registry.add_shutdown_listener(self._signal_stop)
            self._thread = registry.spawn(
                target=self._run, name="Review gateway sync", purpose="Sync phone review gateway"
            )

    def _signal_stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def stop(self, timeout: float = 2.0) -> None:
        self._signal_stop()
        thread = self._thread
        if thread is not None and timeout > 0:
            thread.join(timeout=timeout)
        if self._unsubscribe is not None:
            self._unsubscribe()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def notify_job_completed(self) -> None:
        """Publish the finished job's outputs at once, even if the next job is already running. Any thread."""

        self._fresh_until = self._monotonic() + FRESH_SECONDS
        self._wake.set()

    def fresh_outputs_wanted(self) -> bool:
        until = self._fresh_until
        return until is not None and self._monotonic() < until

    def sync_now(self) -> None:
        self._backoff = 0.0
        self._wake.set()

    def configure(self, address: str, fingerprint: str, secret: str) -> None:
        """Validate and save (raises ``ValueError`` with display text, ``OSError`` when Windows cannot save)."""

        settings = GatewaySettings.build(address, fingerprint, secret)
        self._store.save(settings)
        with self._lock:
            self._settings, self._settings_loaded = settings, True
            self._status = replace(self._status, state="connecting", address=settings.address)
        self.sync_now()

    def forget(self) -> None:
        self._store.clear()
        with self._lock:
            self._settings, self._settings_loaded = None, True
            self._status = replace(self._status, state="not_configured", address="")

    def attach_remote_update(self, remote: Any) -> None:
        """LAUNCH-UPDATE-2: answer ``admin_request`` records through ``remote`` and publish its ``pc_status``.

        Called once on the Tk thread before the worker starts; without it admin requests are refused
        (``update_unavailable``) and no status is published.
        """

        self._applier.admin = remote
        self._status_source = remote.status_payload

    def attach_rating_tasks(self, ratings: Any) -> None:
        """RG-170: send registered rating sets and apply submitted ratings through ``ratings`` each full cycle.

        Called once on the Tk thread before the worker starts.
        """

        self._ratings = ratings

    def create_pairing(
        self, label: str = "", *, allow_queue: bool = True, allow_update: bool = False
    ) -> str:
        """Issue a single-use code; returns it for display. Only its salted hash leaves the PC.

        The phone may review and, unless ``allow_queue`` is off, queue the RG-140 phone actions. Queueing is a
        per-phone flag that is on by default (owner decision 2026-11-26, amending D6) and can be withdrawn later
        with ``set_queue``. ``allow_update`` makes this the dedicated remote-update offer (LAUNCH-UPDATE-2, D2): the
        phone also gets the ``admin`` grant, which only such an offer carries. The PC-local "Allow remote update"
        switch must still be on before any request is run.
        """

        scopes = ("review", "queue") if allow_queue else ("review",)
        offer = new_pairing_offer(
            label=label, scopes=(*scopes, "admin") if allow_update else scopes
        )
        payload = offer.payload()
        self._ledger.add_offer(
            offer.offer_id,
            offer.scopes,
            offer.label,
            utc_text(offer.expires_at),
            encode_json(payload).decode(),
        )
        with self._lock:
            self._offer = offer
            self._status = replace(
                self._status,
                pairing_code=display_code(offer.code),
                pairing_expires_at=utc_text(offer.expires_at),
            )
        self.sync_now()
        return display_code(offer.code)

    def set_queue(self, device_id: str, allowed: bool) -> bool:
        """Grant or withdraw one phone's queueing here. The PC is the authority: a withdrawn phone's action requests
        are refused (``not_granted``) from the next record on, while its review continues."""

        changed = self._ledger.set_device_queue(device_id, allowed)
        self._refresh_status()
        return changed

    def revoke(self, device_id: str) -> bool:
        """Refuse the device here at once; the revocation is sent to the gateway on the next cycle."""

        revoked = self._ledger.revoke_device(device_id, utc_text(utc_now()))
        self._refresh_status()
        self.sync_now()
        return revoked

    def status(self) -> SyncStatus:
        with self._lock:
            return self._status

    # -- worker ----------------------------------------------------------------------------------------------------

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._wake.clear()
                try:
                    delay = self.run_cycle()
                except Exception as error:  # noqa: BLE001 - the worker must outlive one bad cycle
                    # Type only: an exception message may carry a path or response text.
                    log.error("Review gateway sync cycle failed (%s)", type(error).__name__)
                    delay = self._fail("error")
                self._wake.wait(delay)
        finally:
            with self._lock:
                self._status = replace(self._status, state="stopped")

    def _load_settings(self) -> GatewaySettings | None:
        with self._lock:
            if self._settings_loaded:
                return self._settings
        try:
            settings = self._store.load()
        except (OSError, ValueError):
            self._set_state("settings_unreadable")
            return None
        with self._lock:
            self._settings, self._settings_loaded = settings, True
        return settings

    def run_cycle(self) -> float:
        """One sync pass; returns the seconds to wait before the next. Public for hermetic tests."""

        settings = self._load_settings()
        if settings is None:
            if self.status().state != "settings_unreadable":
                self._set_state("not_configured")
            self._refresh_status()
            return self._interval
        client = GatewayClient(self._transport_factory(settings), settings.secret)
        now = self._monotonic()
        quick = now < self._follow_until and now - self._last_full_cycle < self._interval
        try:
            if quick:
                self._flush_owed(client)
                self._pull(client)
                self._backoff = 0.0
                return self._next_delay()
            client.health()
            self._flush_owed(client)
            self._pull(client)
            self._pull_immich(client)
            self._send_status(client)
            self._publish(client)
            if self._ratings is not None:
                self._ratings.step(client, busy=self._busy(), cancel=self._stop)
            self._last_full_cycle = now
        except GatewayPinMismatch:
            return self._fail("certificate_mismatch")
        except GatewayUnauthorized:
            return self._fail("refused_secret")
        except GatewayUnavailable:
            return self._fail("offline")
        except (GatewayError, ProtocolError):
            return self._fail("invalid_response")
        except ApplyDeferred:
            return self._fail("evidence_unavailable")
        self._backoff = 0.0
        self._set_state("idle", address=settings.address)
        self._refresh_status()
        return self._next_delay()

    def _next_delay(self) -> float:
        if self._monotonic() < self._follow_until:
            return min(self._interval, ACTION_FOLLOW_INTERVAL)
        return self._interval

    def _fail(self, state: str) -> float:
        self._backoff = min(MAX_BACKOFF, max(self._interval, self._backoff * 2 or self._interval))
        log.info("Review gateway sync paused: %s", state)
        self._set_state(state)
        self._refresh_status()
        return self._backoff

    def _flush_owed(self, client: GatewayClient) -> None:
        for offer_id, payload, expires_at in self._ledger.unsent_offers():
            live = parse_timestamp(expires_at) > utc_now()
            accepted = live and client.send_pairing_offer(parse_json(payload.encode()))
            self._ledger.mark_offer_sent(offer_id, dead=not accepted)
            if not accepted:
                with self._lock:
                    if self._offer is not None and self._offer.offer_id == offer_id:
                        self._offer = None
        for device_id, revoked_at in self._ledger.unsent_revocations():
            client.send_revocation(device_revocation(device_id, at=parse_timestamp(revoked_at)))
            self._ledger.mark_revocation_sent(device_id)
        for owed in self._ledger.unsent_acknowledgements():
            client.acknowledge(
                acknowledgement(
                    owed.record_id, owed.outcome, reason_code=owed.reason, receipt=owed.receipt
                )
            )
            self._ledger.mark_ack_sent(owed.record_id)

    def _pull(self, client: GatewayClient) -> None:
        cursor: str | None = None
        for _ in range(MAX_PAGES_PER_CYCLE):
            if self._stop.is_set():
                return
            page = parse_outbox_page(client.outbox(cursor, PAGE_SIZE))
            if cursor is None:
                listed = {device.device_id for device in page.enrolled_devices}
                if self._ledger.retain_active_devices(listed, utc_text(utc_now())):
                    log.info(
                        "Review gateway no longer lists a paired phone; it is refused here too"
                    )
            for device in page.enrolled_devices:
                if not self._ledger.bind_device(
                    device.device_id, device.offer_id, device.label, utc_text(device.enrolled_at)
                ):
                    log.warning(
                        "Review gateway reported an enrollment for an offer this PC did not issue"
                    )
            unacknowledgeable = 0
            for raw in page.records:
                result = self._applier.handle(raw)
                if result is None:
                    unacknowledgeable += 1
                    continue
                if result.outcome == IN_PROGRESS:
                    continue  # a remote update under way: asked again next cycle, answered once it has a receipt
                if (
                    isinstance(raw, dict)
                    and raw.get("kind") == "action_request"
                    and result.outcome == "applied"
                ):
                    self._follow_until = self._monotonic() + ACTION_FOLLOW_WINDOW
                client.acknowledge(
                    acknowledgement(
                        result.record_id,
                        result.outcome,
                        reason_code=result.reason,
                        receipt=result.receipt,
                    )
                )
                self._ledger.mark_ack_sent(result.record_id)
            if unacknowledgeable:
                log.warning(
                    "Review gateway sent %d record(s) without a valid record id", unacknowledgeable
                )
            self._ledger.set_meta({"last_pull_at": utc_text(utc_now())})
            cursor = page.next_cursor
            if not cursor:
                return

    def _send_status(self, client: GatewayClient) -> None:
        """Send ``pc_status`` when it changed or the heartbeat is due; an older gateway is asked again later."""

        source = self._status_source
        now = self._monotonic()
        if source is None or now < self._status_retry_at:
            return
        payload = source()
        if payload is None:
            return
        comparable = {key: value for key, value in payload.items() if key != "published_at"}
        if (
            comparable == self._last_status
            and now - self._last_status_at < STATUS_HEARTBEAT_SECONDS
        ):
            return
        if not client.send_pc_status(payload):
            self._status_retry_at = now + STATUS_UNSUPPORTED_SECONDS
            log.info(
                "Review gateway does not accept the PC status yet; remote update stays unavailable"
            )
            return
        self._last_status, self._last_status_at = comparable, now

    def _pull_immich(self, client: GatewayClient) -> None:
        """Read the receipts added since last time; the cursor is kept once a page is stored."""

        cursor = self._ledger.get_meta("immich_cursor") or None
        for _ in range(MAX_PAGES_PER_CYCLE):
            if self._stop.is_set():
                return
            next_cursor = self._store_immich_page(client.immich_receipts(cursor))
            if next_cursor is None or next_cursor == cursor:
                return
            cursor = next_cursor
            self._ledger.set_meta({"immich_cursor": cursor})

    def _store_immich_page(self, page: Any) -> str | None:
        if page is None:
            return None
        if (
            not isinstance(page, dict)
            or set(page) - {"schema_version", "type", "receipts", "next_cursor"}
            or page.get("schema_version") != SCHEMA_VERSION
            or page.get("type") != "immich_receipt_page"
            or not isinstance(page.get("receipts"), list)
            or len(page["receipts"]) > 500
        ):
            raise ProtocolError("invalid_record")
        for raw in page["receipts"]:
            try:
                receipt = parse_immich_receipt(raw)
            except ProtocolError:
                continue
            published = self._ledger.published(receipt.item.library_id)
            if published is None or published["sha256"] != receipt.item.sha256:
                continue  # a receipt for an item this PC never published is not stored
            self._ledger.store_immich_receipt(
                receipt.record_id,
                receipt.item.library_id,
                receipt.item.sha256,
                receipt.status,
                receipt.immich_asset_id,
                receipt.album,
                receipt.favorite,
                receipt.error_code,
                utc_text(receipt.at),
            )
        next_cursor = page.get("next_cursor")
        if next_cursor is not None and (
            not isinstance(next_cursor, str) or not 0 < len(next_cursor) <= 256
        ):
            raise ProtocolError("invalid_record")
        return next_cursor

    def _publish(self, client: GatewayClient) -> None:
        if self._publisher is None:
            try:
                self._publisher = self._publisher_factory()
            except (SiteOutputError, OSError):
                log.info("Review gateway publishing is waiting for the Output folder")
                return
            if self._publisher is None:
                return
        self._publisher.withdraw_unpublishable(client, self._stop)
        busy = self._busy()
        if busy and self.fresh_outputs_wanted():
            since = int((utc_now().timestamp() - FRESH_OUTPUT_S) * 1_000_000)
            self._publish_batch(client, busy, IDLE_PUBLISH_BATCH, newer_than=since)
        now = self._monotonic()
        if busy and now - self._last_busy_publish < BUSY_PUBLISH_SECONDS:
            return
        if busy:
            self._last_busy_publish = now
        self._publish_batch(client, busy, 1 if busy else IDLE_PUBLISH_BATCH)

    def _publish_batch(self, client: GatewayClient, busy: bool, limit: int, **newer: int) -> None:
        assert self._publisher is not None
        try:
            result = self._publisher.publish(
                client,
                limit=limit,
                cancel=self._stop,
                allow_transcode=lambda: not self._busy(),
                hold_unlabelled_video=busy,
                **newer,
            )
        except (SiteOutputError, OSError):
            log.info("Review gateway publishing deferred: the Output index is unavailable")
            return
        if result.published:
            self._ledger.set_meta({"last_publish_at": utc_text(utc_now())})
        with self._lock:
            self._status = replace(self._status, pending_publish=result.pending)

    # -- status ----------------------------------------------------------------------------------------------------

    def _set_state(self, state: str, **changes: Any) -> None:
        with self._lock:
            self._status = replace(self._status, state=state, **changes)

    def _refresh_status(self) -> None:
        counts = self._ledger.publish_counts()
        devices = tuple(self._ledger.devices())
        refusals = tuple(self._ledger.recent_refusals(10))
        refused = self._ledger.refusal_count()
        last_publish = self._ledger.get_meta("last_publish_at")
        last_pull = self._ledger.get_meta("last_pull_at")
        with self._lock:
            offer = self._offer
            if offer is not None and offer.expires_at <= datetime.now(UTC):
                offer = self._offer = None
            if offer is not None and any(device.offer_id == offer.offer_id for device in devices):
                offer = self._offer = None
            self._status = replace(
                self._status,
                published=counts.get("published", 0),
                refused=refused,
                devices=devices,
                recent_refusals=refusals,
                pairing_code=display_code(offer.code) if offer is not None else "",
                pairing_expires_at=utc_text(offer.expires_at) if offer is not None else "",
                last_publish_at=last_publish,
                last_pull_at=last_pull,
            )
