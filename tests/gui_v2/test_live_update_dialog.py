"""LAUNCH-UPDATE-1: the desktop Update control (Tk side only; the service is a fake)."""

from __future__ import annotations

from types import SimpleNamespace

from src.app import live_update as lu
from src.gui import live_update_dialog as ui

OLD = "a" * 40
NEW = "b" * 40


class FakeService:
    def __init__(self, tmp_path) -> None:
        self.store = lu.LiveUpdateStore(tmp_path)
        self.exit_requested = False
        self.remote = False
        self.updates: list[str] = []

    def last_result(self):
        return None

    def allow_remote(self) -> bool:
        return self.remote

    def set_allow_remote(self, allowed: bool) -> None:
        self.remote = allowed

    def check(self):
        return lu.Preflight(True, "", OLD, NEW, commits_ahead=2)

    def update(self, *, source, expected_sha, record_id=None):
        self.updates.append(source)
        return SimpleNamespace(status="restarting", old_sha=OLD, target_sha=NEW)

    def mark_started(self, head):
        pass

    def collect_result(self):
        return None


def test_receipt_text():
    assert ui.describe(None) == "No update has run yet."
    assert ui.describe(
        {"status": "applied", "old_sha": OLD, "new_sha": NEW, "finished_at": "T"}
    ).startswith("Updated aaaaaaaaaa -> bbbbbbbbbb")
    refused = ui.describe({"status": "refused", "reason": "rolled_back", "finished_at": "T"})
    assert "moved back" in refused
    assert "2 commit(s)" in ui.describe_check(lu.Preflight(True, "", OLD, NEW, commits_ahead=2))
    assert ui.describe_check(lu.Preflight(False, lu.DIRTY_CHECKOUT, OLD, "")).startswith(
        "The checkout has"
    )


def test_tick_closes_the_app_once_when_the_service_asks(tk_root, tmp_path):
    exits: list[str] = []
    service = FakeService(tmp_path)
    control = ui.LiveUpdateControl(tk_root, service, exits.append, lambda: OLD)

    control._tick()
    assert exits == []
    service.exit_requested = True
    control._tick()
    control._tick()

    assert exits == ["live-update"]
    control.shutdown()


def test_dialog_switch_and_confirmed_update(tk_root, tmp_path, monkeypatch):
    service = FakeService(tmp_path)
    control = ui.LiveUpdateControl(tk_root, service, lambda _reason: None, lambda: OLD)
    ran = []
    monkeypatch.setattr(control, "_spawn", lambda target, name: (ran.append(name), target()))
    dialog = control.dialog
    dialog.open()

    dialog._vars["remote"].set(True)
    dialog._toggle_remote()
    assert service.remote is True

    dialog.confirm = lambda *_args: False
    dialog._update()
    assert service.updates == []

    dialog.confirm = lambda *_args: True
    dialog._update()
    assert service.updates == ["desktop"]
    assert control.message.startswith("Restarting to update aaaaaaaaaa -> bbbbbbbbbb")

    control.check()
    assert control.message.startswith("Update available")
    dialog.render()
    assert dialog._vars["message"].get().startswith("Update available")
    dialog.close()
    control.shutdown()
