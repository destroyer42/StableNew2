"""STARTUP-STALL: sharing the visible PromptPacks with the Operator Site never lists them on the Tk thread."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.app.site_pack_catalog import SitePackCatalog
from src.app.site_queue_bridge import SiteSession
from src.gui import site_connection_dialog
from src.utils.prompt_packs import PromptPackInfo

_SHARED_TEXT = "Visible PromptPacks and slot prompts are shared for this session."
_FAILED_TEXT = "The visible PromptPacks could not be shared."


def _pack(directory, name):
    path = directory / f"{name}.json"
    path.write_text("{}", encoding="utf-8")
    return PromptPackInfo(name, path)


def _app(packs_dir, packs):
    return SimpleNamespace(
        _packs_dir=packs_dir,
        packs=packs,
        _is_shutting_down=False,
        _config_manager=SimpleNamespace(load_pack_config=lambda _name: {}),
        app_state=SimpleNamespace(resources={"models": ["one.safetensors"]}),
        _ui_dispatch=lambda fn: fn(),
        job_service=None,
    )


def _dialog(app, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(site_connection_dialog, "SitePhoneConnector", Mock())
    monkeypatch.setattr(site_connection_dialog, "PhoneReviewDialog", Mock())
    return site_connection_dialog.SiteConnectionDialog(Mock(), app)


def _until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def _texts(status):
    return [call.kwargs.get("text") for call in status.configure.call_args_list]


def _names(session):
    catalog = session.pack_catalog
    return None if catalog is None else sorted(row["name"] for row in catalog.list_packs())


def test_catalog_keeps_only_existing_json_packs_directly_inside_the_root(tmp_path):
    root = tmp_path / "packs"
    (root / "nested").mkdir(parents=True)
    kept = _pack(root, "kept")
    text = root / "notes.txt"
    text.write_text("x", encoding="utf-8")
    packs = [
        kept,
        PromptPackInfo("notes", text),
        _pack(root / "nested", "nested"),
        _pack(tmp_path, "outside"),
        PromptPackInfo("gone", root / "gone.json"),
    ]

    assert [row["name"] for row in SitePackCatalog(root, packs).list_packs()] == ["kept"]


def test_refresh_shares_the_visible_packs_and_reports_it(tmp_path, monkeypatch):
    app = _app(tmp_path, [_pack(tmp_path, "alpha"), _pack(tmp_path, "beta")])
    dialog = _dialog(app, monkeypatch, tmp_path)
    session, status = SiteSession(), Mock()

    dialog._share_packs(session, status)

    _until(lambda: _SHARED_TEXT in _texts(status))
    assert _names(session) == ["alpha", "beta"]


def test_a_folder_that_cannot_be_listed_keeps_the_previous_catalog_and_says_so(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, [_pack(tmp_path, "alpha")])
    dialog = _dialog(app, monkeypatch, tmp_path)
    session, status = SiteSession(), Mock()
    previous = SitePackCatalog(tmp_path, app.packs)
    session.share_packs(previous)
    monkeypatch.setattr(
        site_connection_dialog, "SitePackCatalog", Mock(side_effect=OSError("unreadable"))
    )

    dialog._share_packs(session, status)

    _until(lambda: _FAILED_TEXT in _texts(status))
    assert session.pack_catalog is previous


class _Gate:
    """Replaces the catalog constructor; records the building thread and can hold a build open."""

    def __init__(self, monkeypatch):
        self.threads: list[int] = []
        self.holds: list[threading.Event] = []
        monkeypatch.setattr(site_connection_dialog, "SitePackCatalog", self)

    def hold_next(self):
        event = threading.Event()
        self.holds.append(event)
        return event

    def __call__(self, *args):
        self.threads.append(threading.get_ident())
        hold = self.holds.pop(0) if self.holds else None
        catalog = SitePackCatalog(*args)
        if hold is not None:
            assert hold.wait(5)
        return catalog


def _queued_dispatch(app):
    posted: list = []
    app._ui_dispatch = posted.append
    return posted


def test_the_catalog_is_built_on_a_worker_and_delivered_through_the_ui_dispatcher(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, [_pack(tmp_path, "alpha")])
    posted = _queued_dispatch(app)
    gate = _Gate(monkeypatch)
    dialog = _dialog(app, monkeypatch, tmp_path)
    session, status = SiteSession(), Mock()

    dialog._share_packs(session, status)

    _until(lambda: len(posted) == 1)
    assert gate.threads and threading.get_ident() not in gate.threads
    assert session.pack_catalog is None  # nothing changes until the UI thread takes the result
    posted.pop()()
    assert _names(session) == ["alpha"]
    assert _texts(status)[-1] == _SHARED_TEXT


def test_app_start_lists_no_pack_on_the_calling_thread(tmp_path, monkeypatch):
    app = _app(tmp_path, [_pack(tmp_path, "alpha")])
    app.job_service = Mock()
    app._config_manager.load_settings = lambda: {"output_dir": str(tmp_path)}
    posted = _queued_dispatch(app)
    gate = _Gate(monkeypatch)
    dialog = _dialog(app, monkeypatch, tmp_path)
    monkeypatch.setattr(site_connection_dialog, "register_protocol", Mock())
    listener = Mock()
    monkeypatch.setattr(site_connection_dialog, "SiteListener", listener)
    monkeypatch.setattr(dialog, "_tick", Mock())
    release = gate.hold_next()

    dialog.start_default()  # returns while the build is still held

    session = listener.call_args.args[0]
    assert session.pack_catalog is None
    release.set()
    _until(lambda: posted)
    posted.pop()()
    assert threading.get_ident() not in gate.threads
    assert _names(session) == ["alpha"]


def test_a_newer_share_request_wins_over_a_slower_older_one(tmp_path, monkeypatch):
    app = _app(tmp_path, [_pack(tmp_path, "old")])
    posted = _queued_dispatch(app)
    gate = _Gate(monkeypatch)
    dialog = _dialog(app, monkeypatch, tmp_path)
    session = SiteSession()
    release = gate.hold_next()

    dialog._share_packs(session)
    _until(lambda: len(gate.threads) == 1)
    app.packs = [_pack(tmp_path, "new")]
    dialog._share_packs(session)
    _until(lambda: len(posted) == 1)
    posted.pop()()
    release.set()
    _until(lambda: len(posted) == 1)
    posted.pop()()

    assert _names(session) == ["new"]


@pytest.mark.parametrize("closed", ["session", "app"])
def test_a_result_for_a_revoked_session_or_a_closing_app_is_dropped(tmp_path, monkeypatch, closed):
    app = _app(tmp_path, [_pack(tmp_path, "alpha")])
    posted = _queued_dispatch(app)
    dialog = _dialog(app, monkeypatch, tmp_path)
    session, status = SiteSession(), Mock()
    shared = Mock()
    monkeypatch.setattr(session, "share_packs", shared)

    dialog._share_packs(session, status)
    _until(lambda: posted)
    if closed == "session":
        session.revoke()
    else:
        app._is_shutting_down = True
    posted.pop()()

    shared.assert_not_called()
    assert _SHARED_TEXT not in _texts(status)


def test_a_closed_thread_registry_does_not_raise_into_the_ui_callback(tmp_path, monkeypatch):
    app = _app(tmp_path, [_pack(tmp_path, "alpha")])
    dialog = _dialog(app, monkeypatch, tmp_path)
    registry = Mock()
    registry.spawn.side_effect = RuntimeError("Thread registry is shutting down")
    monkeypatch.setattr(site_connection_dialog, "get_thread_registry", lambda: registry)
    session = SiteSession()

    dialog._share_packs(session)

    assert session.pack_catalog is None
