"""Toolkit-neutral save coordination for the Photo Optimize active-photo baseline (PR-GUI-UX-580).

The view captures an immutable ``BaselineDraft`` of the form (pure, no file access) and hands it here. This session
sends the write to the store on a worker, one asset at a time and strictly in submission order, coalescing a burst of
edits into the latest draft, and reports a truthful per-asset status. Rules it keeps:

* a draft always names its asset, so a delayed write can never land on another photo;
* the write is conditional on the baseline the form was loaded against (``expected_baseline``), so a stale form can
  never replace a newer promotion, revert or batch edit; the refusal is shown and the edit stays "not saved";
* a failed write is never reported as saved; the error stays until a later write succeeds or the photo is reloaded;
* callers that need the persisted baseline (plan preparation, promotion, batch edit) wait for ``when_settled``.

It owns no sidecar, thread or timer: the store owns the sidecar, the injected runner owns the worker, the view owns
the debounce timer.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.photo_optimize.models import PhotoOptimizeBaseline
from src.photo_optimize.settings import resolve_geometry, validate_settings


@dataclass(frozen=True)
class BaselineDraft:
    """What the operator intends one managed photo's draft to be, captured on the UI thread."""

    asset_id: str
    notes: str
    tags: tuple[str, ...]
    baseline: PhotoOptimizeBaseline


@dataclass(frozen=True)
class SaveOutcome:
    ok: bool
    message: str = ""


@dataclass
class _AssetState:
    dirty: bool = False
    submitted: int = 0
    completed: int = 0  # the latest revision whose write finished, successfully or not
    saved: int = 0
    error: str = ""
    waiters: list[Callable[[SaveOutcome], None]] = field(default_factory=list)


def write_draft(store: Any, draft: BaselineDraft, expected_baseline: dict[str, Any] | None) -> Any:
    """Worker-side: resolve geometry from the decoded working image, validate, then write conditionally."""

    asset = store.get_asset(draft.asset_id)
    if asset is None:
        raise KeyError(draft.asset_id)
    baseline = PhotoOptimizeBaseline.from_dict(draft.baseline.to_dict())
    baseline.config = resolve_geometry(baseline, asset.current_input_path)
    validate_settings(baseline.config)
    if not baseline.working_image_path:
        baseline.working_image_path = asset.managed_original_path
    return store.update_asset_fields(
        draft.asset_id,
        notes=draft.notes,
        tags=list(draft.tags),
        baseline=baseline,
        expected_baseline=expected_baseline,
    )


class PhotoBaselineSaveSession:
    def __init__(
        self,
        *,
        get_store: Callable[[], Any],
        runner: Any,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._get_store = get_store
        self._runner = runner
        self._on_change = on_change
        self._states: dict[str, _AssetState] = {}
        self._expected: dict[str, dict[str, Any]] = {}
        self._expected_lock = threading.Lock()

    # ------------------------------------------------------------------ state

    def _state(self, asset_id: str) -> _AssetState:
        return self._states.setdefault(asset_id, _AssetState())

    def rebase(self, asset_id: str, baseline: PhotoOptimizeBaseline) -> None:
        """The form was (re)loaded from the store: this baseline is what later edits are made against."""

        with self._expected_lock:
            self._expected[asset_id] = baseline.to_dict()
        state = self._state(asset_id)
        state.dirty = False
        state.error = ""
        self._changed()

    def note_edit(self, asset_id: str) -> None:
        self._state(asset_id).dirty = True
        self._changed()

    def is_dirty(self, asset_id: str) -> bool:
        return self._state(asset_id).dirty

    def is_busy(self, asset_id: str) -> bool:
        state = self._state(asset_id)
        return state.completed < state.submitted

    def has_unsaved_work(self) -> bool:
        return any(
            state.dirty or state.completed < state.submitted or state.error
            for state in self._states.values()
        )

    def status(self, asset_id: str) -> tuple[str, str]:
        """``(state, message)`` with state one of saved, dirty, saving, error."""

        state = self._state(asset_id)
        if state.dirty:
            return "dirty", "Unsaved changes"
        if state.completed < state.submitted:
            return "saving", "Saving..."
        if state.error:
            return "error", f"Not saved: {state.error}"
        return "saved", "Saved"

    # ------------------------------------------------------------------ writes

    def save(self, draft: BaselineDraft, *, on_saved: Callable[[Any], None] | None = None) -> int:
        """Send the captured draft to the worker; a newer draft for the same asset supersedes a pending one."""

        state = self._state(draft.asset_id)
        state.dirty = False
        state.submitted += 1
        revision = state.submitted
        asset_id = draft.asset_id

        def work() -> Any:
            with self._expected_lock:
                expected = self._expected.get(asset_id)
            asset = write_draft(self._get_store(), draft, expected)
            with self._expected_lock:
                self._expected[asset_id] = asset.baseline.to_dict()
            return asset

        def done(_is_latest: bool, error: Exception | None) -> None:
            self._finished(asset_id, revision, error)

        def result(asset: Any) -> None:
            if on_saved is not None:
                on_saved(asset)

        self._runner.submit(
            f"photo:baseline:{asset_id}",
            work,
            on_result=result,
            on_complete=done,
            name="photo-baseline-save",
            purpose="Save one managed photo's draft baseline without blocking Tk",
        )
        self._changed()
        return revision

    def _finished(self, asset_id: str, revision: int, error: Exception | None) -> None:
        state = self._state(asset_id)
        state.completed = max(state.completed, revision)
        if error is None:
            state.saved = max(state.saved, revision)
            state.error = ""
        else:
            state.error = str(error) or type(error).__name__
        self._changed()
        self._release_waiters(asset_id)

    # ------------------------------------------------------------------ waiting

    def when_settled(self, asset_id: str, callback: Callable[[SaveOutcome], None]) -> None:
        """Call ``callback`` once no write for ``asset_id`` is outstanding (now, if none is)."""

        state = self._state(asset_id)
        if state.completed >= state.submitted:
            callback(self._outcome(state))
            return
        state.waiters.append(callback)

    @staticmethod
    def _outcome(state: _AssetState) -> SaveOutcome:
        if state.error:
            return SaveOutcome(False, state.error)
        return SaveOutcome(True)

    def _release_waiters(self, asset_id: str) -> None:
        state = self._state(asset_id)
        if state.completed < state.submitted or not state.waiters:
            return
        waiters, state.waiters = state.waiters, []
        outcome = self._outcome(state)
        for waiter in waiters:
            waiter(outcome)

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()


__all__ = ["BaselineDraft", "PhotoBaselineSaveSession", "SaveOutcome", "write_draft"]
