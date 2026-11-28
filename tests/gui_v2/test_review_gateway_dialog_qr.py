"""PHONE-CORE PP-1: the pairing dialog shows the code as text and as a QR of the phone app's pairing link.

Tk side only; the sync is a fake and the address is a placeholder.
"""

from __future__ import annotations

import pytest

from src.app.review_gateway_store import Device
from src.app.review_gateway_sync import SyncStatus
from src.gui.review_gateway_dialog import ReviewGatewayDialog
from src.utils.qr_code import qr_modules

ADDRESS = "https://review.example.test"
CODE = "ABCD-EFGH"


class FakeSync:
    def __init__(self, address: str = ADDRESS) -> None:
        self.address = address
        self.code = ""
        self.devices: tuple[Device, ...] = ()

    def phone_address(self) -> str:
        return self.address

    def set_phone_address(self, text: str) -> None:
        if text.startswith("http://"):
            raise ValueError("Enter the phone app address as https://host.")
        self.address = text

    def create_pairing(self, label: str = "", **_flags) -> str:
        self.code = CODE
        return CODE

    def status(self) -> SyncStatus:
        return SyncStatus(state="idle", devices=self.devices, pairing_code=self.code)

    def sync_now(self) -> None:
        pass


@pytest.fixture
def opened(tk_root):
    dialogs: list[ReviewGatewayDialog] = []

    def build(sync: FakeSync) -> ReviewGatewayDialog:
        dialog = ReviewGatewayDialog(tk_root, sync)
        dialog.open()
        dialogs.append(dialog)
        return dialog

    yield build
    for dialog in dialogs:
        dialog.close()


def drawn(dialog: ReviewGatewayDialog) -> list[list[bool]]:
    """The module grid read back from the canvas, without its quiet zone."""

    canvas = dialog._qr
    assert canvas is not None
    boxes = [canvas.coords(item) for item in canvas.find_withtag("dark")]
    unit = min(box[3] - box[1] for box in boxes)
    cells = set()
    for left, top, right, _bottom in boxes:
        for column in range(round(left / unit), round(right / unit)):
            cells.add((round(top / unit) - 4, column - 4))
    size = int(canvas.cget("width")) // int(unit) - 8
    return [[(row, column) in cells for column in range(size)] for row in range(size)]


def test_pairing_shows_the_text_code_and_a_qr_of_the_pairing_link(opened):
    dialog = opened(FakeSync())
    assert dialog._qr.winfo_manager() == ""  # nothing before a code is made

    dialog.pair()

    assert CODE in dialog._vars["code"].get()
    assert dialog._qr.winfo_manager() == "pack"
    expected = [list(row) for row in qr_modules(f"{ADDRESS}/#/pair/{CODE}")]
    assert drawn(dialog) == expected


def test_the_qr_goes_with_the_code(opened):
    sync = FakeSync()
    dialog = opened(sync)
    dialog.pair()

    sync.code = ""  # used or expired
    dialog.render(sync.status())

    assert dialog._qr.winfo_manager() == "" and not dialog._qr.find_all()
    assert dialog._vars["code"].get() == ""


def test_without_a_phone_address_the_text_code_still_pairs(opened):
    dialog = opened(FakeSync(address=""))

    dialog.pair()

    assert CODE in dialog._vars["code"].get()
    assert dialog._qr.winfo_manager() == ""
    assert "phone app address" in dialog._vars["qr_note"].get()


def test_a_saved_address_draws_the_qr_of_a_live_code_and_a_bad_one_is_refused(opened, monkeypatch):
    sync = FakeSync(address="")
    dialog = opened(sync)
    errors: list[str] = []
    monkeypatch.setattr(
        "src.gui.review_gateway_dialog.messagebox.showerror",
        lambda _title, text, **_options: errors.append(text),
    )
    dialog.pair()

    dialog._vars["phone_address"].set("http://review.example.test")
    dialog.save_phone_address()
    assert errors and sync.address == "" and dialog._qr.winfo_manager() == ""

    dialog._vars["phone_address"].set(ADDRESS)
    dialog.save_phone_address()
    assert dialog._qr.winfo_manager() == "pack"


def test_the_device_list_shows_when_each_phone_was_last_seen(opened):
    sync = FakeSync()
    sync.devices = (
        Device("phone-a-0001", "o1", ("review",), "Pixel", "T", None, False, "2026-11-28T08:15"),
        Device("phone-b-0002", "o2", ("review",), "Old", "T", None, False),
    )
    dialog = opened(sync)

    assert dialog._devices is not None
    assert dialog._devices.item("phone-a-0001", "values")[4] == "2026-11-28T08:15"
    assert dialog._devices.item("phone-b-0002", "values")[4] == "not reported"
