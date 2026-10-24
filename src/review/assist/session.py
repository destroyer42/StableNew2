"""One Review image's Smart Review state: tickets, staleness, caps and the accept hand-off (PR-IMG-REVIEW-320).

Tk-free and thread-agnostic. A dialog drives it: the UI thread calls ``begin_*``/``adopt_*``/``accept``/``reject``/``close``;
a tracked worker calls the blocking ``run_*`` between them. The session starts no thread, process or job and never writes
a file, a prompt, a rating or a queue entry; the only thing it can hand out is the bytes of a mask the operator accepted.

Staleness is structural. Every request gets a ticket bound to the source identity (file SHA-256, size and EXIF orientation,
not the file name) and to the session epoch; binding another image, closing, or issuing a newer request of the same kind
makes every older reply unadoptable, whatever order replies arrive in.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from src.review.assist.captions import build_caption_proposal
from src.review.assist.contracts import (
    CAPABILITIES,
    CAPABILITY_CAPTION,
    CAPABILITY_SEGMENT,
    CODE_BUSY,
    CODE_CANCELLED,
    CODE_DISABLED,
    CODE_OUTPUT,
    CODE_STALE,
    MAX_CONCURRENT_ANALYSES,
    AssistError,
    Availability,
    BoxPrompt,
    CancelCheck,
    CaptionProposal,
    PointPrompt,
    SegmentProposal,
    SourceIdentity,
)
from src.review.assist.geometry import validate_prompts
from src.review.assist.identity import LoadedSource, reverify_source
from src.review.assist.masks import logits_to_mask_png, validate_mask_png
from src.review.assist.providers import (
    AvailabilityProbe,
    CaptionAdapter,
    SegmentAdapter,
    availability_from,
)

KIND_SEGMENT = "segment"
KIND_CAPTION = "caption"


class AssistEnablement:
    """Per-capability opt-in. Everything starts OFF; nothing persists it, so a new session starts OFF again."""

    def __init__(self) -> None:
        self._enabled = dict.fromkeys(CAPABILITIES, False)
        # One analysis at a time for everything sharing this opt-in state (every Smart Review window of one Review tab).
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_ANALYSES)

    def try_acquire_slot(self) -> bool:
        return self._slots.acquire(blocking=False)

    def release_slot(self) -> None:
        self._slots.release()

    def is_enabled(self, capability: str) -> bool:
        return self._enabled.get(capability, False)

    def set(self, capability: str, enabled: bool) -> None:
        if capability in self._enabled:
            self._enabled[capability] = bool(enabled)


@dataclass(frozen=True, slots=True)
class Ticket:
    id: int
    kind: str
    epoch: int
    identity: SourceIdentity
    #: Set by ``cancel``/``bind``/``close`` of the binding this request was made under (never replaced for this ticket).
    cancel: threading.Event = field(default_factory=threading.Event, compare=False)


class AssistSession:
    def __init__(
        self,
        source_path: Path | str,
        *,
        segmenter: SegmentAdapter,
        captioner: CaptionAdapter,
        probe: AvailabilityProbe,
        enablement: AssistEnablement,
    ) -> None:
        self._path = Path(source_path)
        self._segmenter = segmenter
        self._captioner = captioner
        self._probe = probe
        self._enablement = enablement
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._probe_cancel = (
            threading.Event()
        )  # only ``close`` sets it: cancelling an analysis must not abort a probe
        self._holds_slot = False
        self._loaded: LoadedSource | None = None
        self._epoch = 0
        self._next = 0
        self._latest: dict[str, int] = {}
        self._running = 0
        self._closed = False
        self.segment: SegmentProposal | None = None
        self.caption: CaptionProposal | None = None

    # -- binding -------------------------------------------------------------------------------------------------
    @property
    def identity(self) -> SourceIdentity | None:
        return self._loaded.identity if self._loaded is not None else None

    @property
    def closed(self) -> bool:
        return self._closed

    def bind(self, loaded: LoadedSource, path: Path | str | None = None) -> None:
        """Bind to (another) image. Everything proposed for the previous one is dropped and its replies become stale."""

        with self._lock:
            self._epoch += 1
            self._cancel.set()  # stop any request still running for the previous binding
            self._cancel = threading.Event()
            self._loaded = loaded
            if path is not None:
                self._path = Path(path)
            self._latest.clear()
            self.segment = None
            self.caption = None

    # -- availability --------------------------------------------------------------------------------------------
    def availability(self, capability: str) -> Availability:
        """Blocking. Disabled capabilities are never probed; an enabled one is checked against the real resource."""

        if not self._enablement.is_enabled(capability):
            return availability_from(capability, ("disabled",))
        return self._probe.check(capability, self._probe_cancel.is_set)

    # -- tickets -------------------------------------------------------------------------------------------------
    def _begin(self, kind: str, capability: str) -> Ticket:
        if self._closed or self._loaded is None:
            raise AssistError(CODE_STALE, "Smart Review is closed.")
        if not self._enablement.is_enabled(capability):
            raise AssistError(
                CODE_DISABLED, "This assistance is turned off.", reasons=("disabled",)
            )
        with self._lock:
            if self._running >= MAX_CONCURRENT_ANALYSES or not self._enablement.try_acquire_slot():
                raise AssistError(
                    CODE_BUSY, "An analysis is already running. Cancel it or wait for it to finish."
                )
            self._running += 1
            self._holds_slot = True
            self._next += 1
            self._latest[kind] = self._next
            return Ticket(self._next, kind, self._epoch, self._loaded.identity, self._cancel)

    def _end(self) -> None:
        with self._lock:
            self._running = max(0, self._running - 1)
            if self._holds_slot and self._running == 0:
                self._holds_slot = False
                self._enablement.release_slot()

    def release(self) -> None:
        """Give the analysis slot back when a reserved request could not be started (``run_*`` otherwise does it)."""

        self._end()

    def is_current(self, ticket: Ticket) -> bool:
        with self._lock:
            return (
                not self._closed
                and self._loaded is not None
                and ticket.epoch == self._epoch
                and self._latest.get(ticket.kind) == ticket.id
                and ticket.identity == self._loaded.identity
            )

    @staticmethod
    def _checked_cancel(ticket: Ticket) -> CancelCheck:
        return ticket.cancel.is_set

    # -- object selection ----------------------------------------------------------------------------------------
    def begin_segment(self, points: Sequence[PointPrompt], boxes: Sequence[BoxPrompt]) -> Ticket:
        """UI thread. Validates the prompts, then reserves the single analysis slot. Raises before any model is touched."""

        if self._loaded is None:
            raise AssistError(CODE_STALE, "No image is loaded.")
        validate_prompts(points, boxes, self._loaded.identity.size)
        return self._begin(KIND_SEGMENT, CAPABILITY_SEGMENT)

    def run_segment(
        self, ticket: Ticket, points: Sequence[PointPrompt], boxes: Sequence[BoxPrompt]
    ) -> SegmentProposal:
        """Worker thread (blocking). Releases the analysis slot on every outcome."""

        loaded = self._loaded
        try:
            if loaded is None or not self.is_current(ticket):
                raise AssistError(CODE_STALE, "The selection changed; the request was dropped.")
            cancel = self._checked_cancel(ticket)
            output = self._segmenter.segment(loaded, tuple(points), tuple(boxes), cancel)
            if cancel():
                raise AssistError(CODE_CANCELLED, "Cancelled.")
            png, facts = logits_to_mask_png(output.logits, ticket.identity)
            reverify_source(self._path, ticket.identity)
            return SegmentProposal(
                ticket=ticket.id,
                identity=ticket.identity,
                mask_png=png,
                mask_sha256=facts.sha256,
                coverage=facts.coverage,
                score=output.score,
                model=output.model,
            )
        finally:
            self._end()

    def adopt_segment(self, ticket: Ticket, proposal: SegmentProposal) -> bool:
        """UI thread. ``True`` only when the reply still belongs to the current image and request."""

        if (
            not self.is_current(ticket)
            or not self._enablement.is_enabled(CAPABILITY_SEGMENT)
            or proposal.identity != ticket.identity
            or proposal.ticket != ticket.id
        ):
            return False
        validate_mask_png(proposal.mask_png, proposal.identity)  # before display
        self.segment = proposal
        return True

    def accept_mask(self) -> bytes:
        """UI thread. The accepted mask's bytes, re-validated against the exact source file as it is now."""

        proposal = self.segment
        if proposal is None or self._loaded is None or proposal.identity != self._loaded.identity:
            raise AssistError(CODE_STALE, "There is no current suggestion to accept.")
        reverify_source(self._path, proposal.identity)
        facts = validate_mask_png(proposal.mask_png, proposal.identity)  # before use
        if facts.sha256 != proposal.mask_sha256:
            raise AssistError(CODE_OUTPUT, "The suggested mask changed after it was shown.")
        self.segment = None
        return bytes(proposal.mask_png)

    def reject_mask(self) -> None:
        self.segment = None

    # -- captions ------------------------------------------------------------------------------------------------
    def begin_caption(self) -> Ticket:
        return self._begin(KIND_CAPTION, CAPABILITY_CAPTION)

    def run_caption(self, ticket: Ticket) -> CaptionProposal:
        loaded = self._loaded
        try:
            if loaded is None or not self.is_current(ticket):
                raise AssistError(CODE_STALE, "The selection changed; the request was dropped.")
            cancel = self._checked_cancel(ticket)
            output = self._captioner.caption(loaded, cancel)
            if cancel():
                raise AssistError(CODE_CANCELLED, "Cancelled.")
            reverify_source(self._path, ticket.identity)
            return build_caption_proposal(ticket.id, ticket.identity, output)
        finally:
            self._end()

    def adopt_caption(self, ticket: Ticket, proposal: CaptionProposal) -> bool:
        if (
            not self.is_current(ticket)
            or not self._enablement.is_enabled(CAPABILITY_CAPTION)
            or proposal.identity != ticket.identity
            or proposal.ticket != ticket.id
        ):
            return False
        self.caption = proposal
        return True

    def reject_caption(self) -> None:
        self.caption = None

    # -- lifecycle -----------------------------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        with self._lock:
            return self._running > 0

    def cancel(self) -> None:
        """Ask the running request to stop (its child process tree is killed by the bounded runner) and drop suggestions."""

        self._cancel.set()
        with self._lock:
            self._cancel = threading.Event() if not self._closed else self._cancel
            self._latest.clear()
            self.segment = None
            self.caption = None

    def close(self) -> None:
        self._probe_cancel.set()
        with self._lock:
            self._closed = True
            self._epoch += 1
            self._cancel.set()
            self._latest.clear()
            self.segment = None
            self.caption = None
            self._loaded = None


__all__ = ["AssistEnablement", "AssistSession", "KIND_CAPTION", "KIND_SEGMENT", "Ticket"]
