"""Explicit "apply settings to PromptPack(s)" with a truthful per-pack result (PR-GUI-UX-520).

Applying rewrites only the ``preset_data`` of each selected native PromptPack through ``ConfigManager.update_pack_config``
(the canonical versioned storage boundary). Each pack is its own atomic write; there is deliberately no cross-file
transaction, so a failure on one pack never undoes or hides the others and the report says exactly which succeeded.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PackApplyOutcome:
    pack_id: str
    ok: bool
    error: str = ""


@dataclass(frozen=True)
class PackApplyReport:
    """Result of one apply action. ``source`` says what was written (for the confirmation and the result line)."""

    source: str
    outcomes: tuple[PackApplyOutcome, ...] = ()

    @property
    def succeeded(self) -> tuple[str, ...]:
        return tuple(item.pack_id for item in self.outcomes if item.ok)

    @property
    def failed(self) -> tuple[PackApplyOutcome, ...]:
        return tuple(item for item in self.outcomes if not item.ok)

    @property
    def all_ok(self) -> bool:
        return bool(self.outcomes) and not self.failed

    @property
    def partial(self) -> bool:
        return bool(self.succeeded) and bool(self.failed)


def apply_settings_to_packs(
    config_manager: Any,
    pack_ids: Iterable[str],
    config: Mapping[str, Any],
    *,
    source: str,
) -> PackApplyReport:
    """Write ``config`` into each distinct pack's saved settings and report every outcome.

    The caller's ``config`` is never mutated (each pack gets its own copy). Duplicate ids are applied once. A manager
    without ``update_pack_config`` (a test double) falls back to ``save_pack_config`` and a generic failure message.
    """

    outcomes: list[PackApplyOutcome] = []
    for pack_id in dict.fromkeys(str(item) for item in pack_ids if str(item).strip()):
        payload = copy.deepcopy(dict(config))
        updater = getattr(config_manager, "update_pack_config", None)
        try:
            if callable(updater):
                updater(pack_id, payload)
                outcomes.append(PackApplyOutcome(pack_id, True))
            elif config_manager.save_pack_config(pack_id, payload):
                outcomes.append(PackApplyOutcome(pack_id, True))
            else:
                outcomes.append(PackApplyOutcome(pack_id, False, "the pack could not be saved"))
        except Exception as exc:  # noqa: BLE001 - one pack's failure must not hide the others
            outcomes.append(PackApplyOutcome(pack_id, False, str(exc)))
    return PackApplyReport(source=source, outcomes=tuple(outcomes))


def bind_preview_invalidation(config_manager: Any, get_app_state: Callable[[], Any]) -> None:
    """Make every successful saved-settings write invalidate a Preview built from that pack.

    Applying settings rewrites a pack file's ``preset_data``, which the compiler reads, so a Preview compiled from the
    pack's previous contents must not stay accepted. ``AppStateV2.pack_file_saved`` decides, from the pack's resolved
    file, whether the job draft uses it; a failed write never reaches the listener.
    """

    def on_saved(path: Any) -> None:
        state = get_app_state()
        if state is not None:
            state.pack_file_saved(path, packs_dir=config_manager.packs_dir)

    config_manager.pack_saved_listener = on_saved


__all__ = [
    "PackApplyOutcome",
    "PackApplyReport",
    "apply_settings_to_packs",
    "bind_preview_invalidation",
]
