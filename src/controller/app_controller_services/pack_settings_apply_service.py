"""Explicit "apply settings to PromptPack(s)" with a truthful per-pack result (PR-GUI-UX-520).

Applying rewrites only the ``preset_data`` of each selected native PromptPack through ``ConfigManager.update_pack_config``
(the canonical versioned storage boundary). Each pack is its own atomic write; there is deliberately no cross-file
transaction, so a failure on one pack never undoes or hides the others and the report says exactly which succeeded.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
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


__all__ = ["PackApplyOutcome", "PackApplyReport", "apply_settings_to_packs"]
