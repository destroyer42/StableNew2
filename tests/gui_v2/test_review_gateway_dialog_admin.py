"""LAUNCH-UPDATE-2: the desktop's dedicated remote-update pairing offer (D2). Tk side only; the sync is a fake."""

from __future__ import annotations

from src.app.review_gateway_store import Device
from src.app.review_gateway_sync import SyncStatus
from src.gui.review_gateway_dialog import ReviewGatewayDialog


class FakeSync:
    def __init__(self) -> None:
        self.pairings: list[dict] = []
        self.devices: tuple[Device, ...] = ()

    def create_pairing(self, label: str = "", **flags) -> str:
        self.pairings.append(flags)
        return "ABCD-EFGH"

    def status(self) -> SyncStatus:
        return SyncStatus(state="idle", devices=self.devices)

    def sync_now(self) -> None:
        pass


def test_the_update_offer_needs_a_confirmation_and_is_separate_from_pairing(tk_root):
    sync = FakeSync()
    dialog = ReviewGatewayDialog(tk_root, sync)
    dialog.open()
    try:
        answers = [False, True]
        dialog.confirm = lambda *_args: answers.pop(0)

        dialog.pair()
        dialog.pair_for_update()  # declined
        dialog.pair_for_update()

        assert sync.pairings == [
            {"allow_queue": True, "allow_update": False},
            {"allow_queue": True, "allow_update": True},
        ]
        assert "remote update" in dialog._vars["code"].get()
    finally:
        dialog.close()


def test_the_device_list_shows_the_update_grant(tk_root):
    sync = FakeSync()
    sync.devices = (
        Device("phone-a-0001", "o1", ("review", "queue", "admin"), "Pixel", "T", None, False),
        Device("phone-b-0002", "o2", ("review",), "Old", "T", None, False),
    )
    dialog = ReviewGatewayDialog(tk_root, sync)
    dialog.open()
    try:
        devices = dialog._devices
        assert devices is not None
        assert devices.item("phone-a-0001", "values")[2] == "review, queue, update"
        assert devices.item("phone-b-0002", "values")[2] == "review"
    finally:
        dialog.close()
