"""Toolkit-neutral behavior behind the Pipeline sidebar's load / apply actions (PR-GUI-UX-520).

The sidebar owns widgets; this presenter owns the decisions: when a load would replace edits the operator has not saved
(and so needs a confirmation), when saved PromptPack settings are about to be overwritten (always confirm), and what the
inline status says afterwards. It performs no storage work itself; the controller callbacks do, and it never builds a
backend payload. Dialogs are injected so tests drive it without Tk.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from src.gui.view_contracts import config_source_contract as contract

CHANNEL_SETTINGS = "settings"
CHANNEL_PACK = "pack"


@dataclass(frozen=True)
class LoadOutcome:
    """Result of a load request. ``cancelled`` means the operator declined; nothing changed."""

    loaded: bool = False
    cancelled: bool = False
    replaced_edits: bool = False


class SettingsActionsPresenter:
    def __init__(
        self,
        *,
        controller_getter: Callable[[], Any],
        confirm: Callable[[str, str], bool],
        say: Callable[[str, str], None],
    ) -> None:
        self._controller_getter = controller_getter
        self._confirm = confirm
        self._say = say
        # Fingerprint of the working settings when they were last loaded or saved; None until the first such event.
        self._baseline: str | None = None

    # ------------------------------------------------------------------ unsaved-edit tracking

    def _fingerprint(self) -> str:
        getter = getattr(self._controller_getter(), "working_settings_fingerprint", None)
        if not callable(getter):
            return ""
        try:
            return str(getter() or "")
        except Exception:  # noqa: BLE001 - an unreadable working state is "unknown", never "clean"
            return ""

    def mark_working_clean(self) -> None:
        """Record the current working settings as matching their source (call after a load or a save)."""

        self._baseline = self._fingerprint() or None

    def working_is_dirty(self) -> bool:
        """True only when the settings are known to differ from the last loaded or saved state."""

        current = self._fingerprint()
        return bool(self._baseline and current and current != self._baseline)

    # ------------------------------------------------------------------ load

    def load(
        self,
        channel: str,
        source_text: str,
        invoke: Callable[[], bool | None],
        *,
        succeeded: Callable[[], bool],
    ) -> LoadOutcome:
        """Replace the working settings from ``source_text`` via ``invoke``; confirm first when edits would be lost.

        ``invoke`` returns True/False when the controller reports success; a ``None`` return (older controllers and test
        doubles) defers to ``succeeded()``.
        """

        replaced_edits = self.working_is_dirty()
        if replaced_edits:
            title, message = contract.replace_working_confirmation_text(source_text)
            if not self._confirm(title, message):
                self._say(channel, "Load cancelled; the working stage settings were kept.")
                return LoadOutcome(cancelled=True)
        try:
            result = invoke()
        except Exception:  # noqa: BLE001 - the controller logs its own failures; the operator sees an honest status
            result = False
        loaded = result if isinstance(result, bool) else succeeded()
        if loaded:
            self.mark_working_clean()
            self._say(
                channel, contract.load_result_text(source_text, replaced_edits=replaced_edits)
            )
        else:
            self._say(channel, contract.load_failed_text(source_text))
        return LoadOutcome(loaded=bool(loaded), replaced_edits=replaced_edits and bool(loaded))

    # ------------------------------------------------------------------ apply to PromptPacks

    def apply_to_packs(
        self,
        source_text: str,
        pack_ids: Sequence[str],
        invoke: Callable[[list[str]], Any],
    ) -> Any:
        """Confirm, then overwrite the selected packs' saved settings; report exactly what happened.

        ``pack_ids`` is captured by the caller at click time, so a selection change during the (modal) confirmation
        cannot redirect the write. Returns the controller's report, or ``None`` when declined or unreported.
        """

        targets = [str(item) for item in pack_ids if str(item).strip()]
        if not targets:
            self._say(CHANNEL_PACK, "Select at least one PromptPack to apply settings to.")
            return None
        title, message = contract.apply_confirmation_text(source_text, targets)
        if not self._confirm(title, message):
            self._say(CHANNEL_PACK, "Apply cancelled; no PromptPack was changed.")
            return None
        try:
            report = invoke(list(targets))
        except Exception as exc:  # noqa: BLE001
            self._say(CHANNEL_PACK, f"Could not apply {source_text}: {exc}")
            return None
        succeeded = getattr(report, "succeeded", None)
        failed = getattr(report, "failed", None)
        if succeeded is None or failed is None:
            self._say(
                CHANNEL_PACK,
                "There were no current stage settings to apply; no PromptPack was changed.",
            )
            return report
        self._say(
            CHANNEL_PACK,
            contract.apply_result_text(
                source_text,
                list(succeeded),
                [(item.pack_id, item.error) for item in failed],
            ),
        )
        return report


__all__ = ["CHANNEL_PACK", "CHANNEL_SETTINGS", "LoadOutcome", "SettingsActionsPresenter"]
