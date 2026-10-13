"""Fault-isolated legacy recovery with temporary assets only; no owner workspace or backend access."""

from __future__ import annotations

import errno
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

import pytest

from src.photo_optimize import migration
from src.photo_optimize.paths import rename_without_replace
from src.photo_optimize.store import PhotoOptimizeStore
from tests.photo_optimize.test_photo_220 import image


def _winerror(code):
    error = PermissionError(errno.EACCES, f"injected Windows error {code}")
    error.winerror = code
    return error


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    store = PhotoOptimizeStore(tmp_path / "legacy")
    with monkeypatch.context() as context:
        ids = iter(("legacy_a", "legacy_b"))
        context.setattr("src.photo_optimize.store._new_asset_id", lambda: next(ids))
        for name in ("a", "b"):
            store.import_photo(image(tmp_path / f"{name}.png"))
    return store


@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_windows_rename_failure_retries_only_verified_staging(
    legacy, tmp_path, monkeypatch, code
):
    before = _snapshot(legacy.root)
    calls = []
    sleep = Mock()

    def rename(source, destination):
        calls.append((source, destination))
        if len(calls) == 1:
            raise _winerror(code)
        rename_without_replace(source, destination)

    monkeypatch.setattr(migration, "rename_without_replace", rename)
    monkeypatch.setattr(migration.time, "sleep", sleep)
    store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    assert store.migration_report.migrated == ["legacy_a", "legacy_b"]
    assert not store.migration_report.failures
    assert calls[0] == calls[1]  # same newly verified stage, not a second/unverified copy
    sleep.assert_called_once_with(0.1)
    assert _snapshot(legacy.root) == before


def test_persistent_winerror5_does_not_disable_new_import_or_other_assets_and_can_retry(
    legacy, tmp_path, monkeypatch
):
    before = _snapshot(legacy.root)
    sleep = Mock()

    def rename(source, destination):
        if destination.name == "legacy_a":
            raise _winerror(5)
        rename_without_replace(source, destination)

    monkeypatch.setattr(migration.time, "sleep", sleep)
    with monkeypatch.context() as context:
        context.setattr(migration, "rename_without_replace", rename)
        store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    report = store.migration_report
    assert report.migrated == ["legacy_b"] and len(report.failures) == 1
    issue = report.failures[0]
    assert issue.asset_id == "legacy_a" and issue.winerror == 5 and issue.attempts == 3
    assert "publish" in issue.phase and "Retry Legacy Migration" in report.details()
    assert "incomplete" in report.summary() and "1 failed/skipped" in report.summary()
    assert sleep.call_count == 2
    staging = Path(issue.staging)
    staged_before = _snapshot(staging)
    new_asset = store.import_photo(image(tmp_path / "new.png"))
    assert store.get_asset(new_asset.asset_id) is not None
    second = store.retry_migration()
    assert (
        second.migrated == ["legacy_a"]
        and second.already_present == ["legacy_b"]
        and not second.failures
    )
    assert _snapshot(staging) == staged_before and _snapshot(legacy.root) == before
    # A later startup does not copy either successful legacy asset again or overwrite the newer draft/import.
    stages_before = sorted((store.root / "migration_staging").iterdir())
    restarted = PhotoOptimizeStore(store.root, legacy_root=legacy.root)
    assert restarted.migration_report.already_present == ["legacy_a", "legacy_b"]
    assert not restarted.migration_report.migrated and not restarted.migration_report.failures
    assert sorted((store.root / "migration_staging").iterdir()) == stages_before
    assert len(restarted.list_assets()) == 3


@pytest.mark.parametrize("populated", [False, True])
def test_collision_preserves_even_empty_destination_and_other_assets(legacy, tmp_path, populated):
    target = tmp_path / "target"
    collision = target / "assets" / "legacy_a"
    collision.mkdir(parents=True)
    if populated:
        (collision / "owner.txt").write_text("keep")
    identity, before = collision.stat().st_ino, _snapshot(collision)
    store = PhotoOptimizeStore(target, legacy_root=legacy.root)
    assert (
        len(store.migration_report.failures) == 1
        and "collision" in store.migration_report.failures[0].error
    )
    assert store.migration_report.migrated == ["legacy_b"]
    assert collision.stat().st_ino == identity and _snapshot(collision) == before
    assert store.migration_report.failures[0].staging is None


@pytest.mark.parametrize("populated", [False, True])
def test_destination_appearing_at_publication_is_never_replaced(
    legacy, tmp_path, monkeypatch, populated
):
    collision = None

    def race(source, destination):
        nonlocal collision
        if destination.name == "legacy_a":
            destination.mkdir()
            if populated:
                (destination / "owner.txt").write_text("keep")
            collision = (destination, destination.stat().st_ino, _snapshot(destination))
        rename_without_replace(source, destination)

    monkeypatch.setattr(migration, "rename_without_replace", race)
    store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    assert (
        len(store.migration_report.failures) == 1
        and store.migration_report.failures[0].attempts == 1
    )
    path, identity, before = collision
    assert path.stat().st_ino == identity and _snapshot(path) == before
    assert Path(store.migration_report.failures[0].staging).is_dir()


def test_destination_is_checked_again_before_retry(legacy, tmp_path, monkeypatch):
    calls = []

    def denied(source, destination):
        calls.append(destination.name)
        if destination.name == "legacy_a":
            raise _winerror(32)
        rename_without_replace(source, destination)

    def competitor(_delay):
        path = tmp_path / "target" / "assets" / "legacy_a"
        path.mkdir()
        (path / "owner.txt").write_text("keep")

    monkeypatch.setattr(migration, "rename_without_replace", denied)
    monkeypatch.setattr(migration.time, "sleep", competitor)
    store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    assert calls.count("legacy_a") == 1 and len(store.migration_report.failures) == 1
    assert (store.asset_dir("legacy_a") / "owner.txt").read_text() == "keep"


def test_two_simultaneous_migrations_validate_the_winner_without_overwrite(
    legacy, tmp_path, monkeypatch
):
    # Restrict this race to one recognized source; retain the other source under an untouched unknown name.
    (legacy.root / "assets" / "legacy_b" / "sidecar.json").rename(
        legacy.root / "assets" / "legacy_b" / "draft.json"
    )
    barrier = Barrier(2, timeout=10)

    def rename(source, destination):
        barrier.wait()
        rename_without_replace(source, destination)

    monkeypatch.setattr(migration, "rename_without_replace", rename)
    target = tmp_path / "target"
    target.mkdir()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(migration.migrate_assets, legacy.root, target) for _ in range(2)]
        reports = [future.result(timeout=15) for future in futures]
    assert all(not report.failures for report in reports)
    assert sum(len(report.migrated) for report in reports) == 1
    assert sum(len(report.already_present) for report in reports) == 1
    assert len(list((target / "migration_staging").iterdir())) == 1  # losing verified copy retained


def test_interrupted_partial_copy_is_retained_but_never_reused(legacy, tmp_path, monkeypatch):
    from shutil import copytree

    def interrupted(source, destination, *args, **kwargs):
        if Path(source).name == "legacy_a":
            Path(destination).mkdir(parents=True)
            (Path(destination) / "partial.txt").write_text("unverified partial bytes")
            raise OSError("injected interrupted copy")
        return copytree(source, destination, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(migration.shutil, "copytree", interrupted)
        store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    issue = store.migration_report.failures[0]
    assert store.migration_report.migrated == ["legacy_b"]
    assert len(store.migration_report.failures) == 1
    staging = Path(issue.staging)
    before = _snapshot(staging)
    assert not store.sidecar_path("legacy_a").exists()
    assert store.retry_migration().migrated == ["legacy_a"]
    assert _snapshot(staging) == before
    assert not (store.asset_dir("legacy_a") / "partial.txt").exists()


@pytest.mark.parametrize("payload", [[], {"schema_version": "future"}, {"asset_id": "different"}])
def test_bad_legacy_sidecar_is_reported_per_asset(legacy, tmp_path, payload):
    legacy.sidecar_path("legacy_a").write_text(json.dumps(payload))
    before = _snapshot(legacy.root)
    store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    assert len(store.migration_report.failures) == 1 and store.migration_report.migrated == [
        "legacy_b"
    ]
    assert _snapshot(legacy.root) == before
    assert store.import_photo(image(tmp_path / "new.png")) is not None


def test_legacy_scan_denied_is_visible_without_disabling_new_imports(legacy, tmp_path, monkeypatch):
    iterdir = Path.iterdir

    def denied(path):
        if path == legacy.root / "assets":
            raise _winerror(5)
        return iterdir(path)

    monkeypatch.setattr(Path, "iterdir", denied)
    store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    assert len(store.migration_report.failures) == 1
    assert store.migration_report.failures[0].phase == "scan"
    assert "incomplete" in store.migration_report.summary()
    assert store.import_photo(image(tmp_path / "new.png")) is not None


@pytest.mark.parametrize("change", ["image", "marker", "sidecar"])
def test_changed_migrated_copy_is_never_replaced(legacy, tmp_path, change):
    target = tmp_path / "target"
    store = PhotoOptimizeStore(target, legacy_root=legacy.root)
    destination = store.asset_dir("legacy_a")
    if change == "image":
        Path(store.get_asset("legacy_a").managed_original_path).write_bytes(b"changed owner bytes")
    elif change == "marker":
        (destination / "migration.json").write_text("[]")
    else:
        (destination / "sidecar.json").write_text("[]")
    before = _snapshot(destination)
    report = store.retry_migration()
    assert report.already_present == ["legacy_b"] and not report.migrated
    assert len(report.failures) == 1 and report.failures[0].asset_id == "legacy_a"
    assert _snapshot(destination) == before


def test_successful_migration_accepts_later_draft_edits(legacy, tmp_path):
    store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    asset = store.get_asset("legacy_a")
    asset.notes = "operator draft after migration"
    asset.baseline.prompt = "updated prompt"
    store.save_asset(asset)
    before = _snapshot(store.asset_dir("legacy_a"))
    report = store.retry_migration()
    assert report.already_present == ["legacy_a", "legacy_b"] and not report.failures
    assert _snapshot(store.asset_dir("legacy_a")) == before


def test_gui_exposes_migration_failure_and_import_still_succeeds(legacy, tmp_path, monkeypatch):
    from unittest.mock import patch

    from .test_photo_220_form import Variable, form

    tab = form(tmp_path)
    monkeypatch.setattr(migration, "rename_without_replace", Mock(side_effect=_winerror(5)))
    monkeypatch.setattr(migration.time, "sleep", Mock())
    tab.store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    tab.migration_status_var = Variable()
    tab._render_migration_report()
    assert "2 failed/skipped" in tab.migration_status_var.get()
    assert "New imports remain available" in tab.migration_status_var.get()
    with patch("src.gui.views.photo_optimize_tab_frame_v2.messagebox.showinfo") as details:
        tab._show_migration_details()
    assert "legacy_a" in details.call_args.args[1] and "legacy_b" in details.call_args.args[1]
    assert "Retained staging" in details.call_args.args[1]
    tab._run_photo_operation = lambda operation, completed: completed(operation())
    tab._refresh_assets = Mock()
    tab._build_import_defaults = Mock(return_value={})
    with (
        patch(
            "src.gui.views.photo_optimize_tab_frame_v2.filedialog.askopenfilenames",
            return_value=[str(image(tmp_path / "new.png"))],
        ),
        patch("src.gui.views.photo_optimize_tab_frame_v2.messagebox.showerror") as error,
    ):
        tab._on_import_photos()
    error.assert_not_called()
    assert len(tab.store.list_assets()) == 1
    assert "2 failed/skipped" in tab.migration_status_var.get()
    assert (
        tab._refresh_assets.call_args.kwargs["select_asset_id"]
        == tab.store.list_assets()[0].asset_id
    )


def test_gui_retry_uses_worker_and_only_gui_poll_updates_warning(legacy, tmp_path, monkeypatch):
    from concurrent.futures import Future
    from unittest.mock import patch

    from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrameV2

    from .test_photo_220_form import Variable, form

    tab = form(tmp_path)
    with monkeypatch.context() as context:
        context.setattr(migration, "rename_without_replace", Mock(side_effect=_winerror(5)))
        context.setattr(migration.time, "sleep", Mock())
        tab.store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    tab.migration_status_var = Variable()
    tab._render_migration_report()
    warning = tab.migration_status_var.get()
    tab._operation_future = None
    tab._run_photo_operation = PhotoOptimizeTabFrameV2._run_photo_operation.__get__(tab)
    tab._refresh_assets = Mock()
    callbacks = []
    tab.after = lambda delay, callback: callbacks.append(callback)
    executor = Mock()
    future = Future()
    executor.submit.return_value = future
    with patch(
        "src.gui.views.photo_optimize_tab_frame_v2.ThreadPoolExecutor", return_value=executor
    ):
        tab._retry_legacy_migration()
    executor.submit.assert_called_once_with(tab.store.retry_migration)
    result = executor.submit.call_args.args[0]()
    assert result.migrated == ["legacy_a", "legacy_b"] and not result.failures
    assert tab.migration_status_var.get() == warning
    tab._refresh_assets.assert_not_called()
    future.set_result(result)
    callbacks[0]()
    assert "0 failed/skipped" in tab.migration_status_var.get()
    tab._refresh_assets.assert_called_once_with()
    assert tab._operation_future is None


def test_gui_unwritable_workspace_never_claims_ready(tmp_path):
    from unittest.mock import patch

    from .test_photo_220_form import form

    tab = form(tmp_path)
    tab.store = None
    tab._workspace_future = Mock()
    tab._workspace_future.done.return_value = True
    tab._workspace_future.result.side_effect = OSError("workspace is not writable")
    tab._workspace_executor = Mock()
    with (
        patch("src.gui.views.photo_optimize_tab_frame_v2.messagebox.showerror") as error,
        patch("src.gui.views.photo_optimize_tab_frame_v2.messagebox.showwarning") as warning,
    ):
        tab._poll_workspace()
        assert not tab._workspace_ready()
    assert tab.store is None and "Workspace unavailable" in tab.submission_summary_var.get()
    error.assert_called_once()
    warning.assert_called_once()
    tab._workspace_executor.shutdown.assert_called_once_with(wait=False)


def test_non_windows_permission_or_disk_failure_is_not_blindly_retried(
    legacy, tmp_path, monkeypatch
):
    calls = Mock(side_effect=OSError(errno.ENOSPC, "disk full"))
    sleep = Mock()
    monkeypatch.setattr(migration, "rename_without_replace", calls)
    monkeypatch.setattr(migration.time, "sleep", sleep)
    report = migration.migrate_assets(legacy.root, tmp_path / "target")
    assert calls.call_count == 2 and len(report.failures) == 2
    assert all(issue.attempts == 1 for issue in report.failures)
    sleep.assert_not_called()


def test_unwritable_new_workspace_fails_before_any_legacy_copy(legacy, tmp_path, monkeypatch):
    before = _snapshot(legacy.root)
    copy = Mock()
    monkeypatch.setattr(migration.shutil, "copytree", copy)
    monkeypatch.setattr(
        "src.photo_optimize.store.tempfile.TemporaryFile", Mock(side_effect=_winerror(5))
    )
    with pytest.raises(OSError, match="workspace is not writable"):
        PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    copy.assert_not_called()
    assert _snapshot(legacy.root) == before


@pytest.mark.skipif(os.name != "nt", reason="Native Windows sharing semantics")
@pytest.mark.parametrize("kind,code", [("child", 5), ("directory", 32)])
def test_native_windows_handle_denial_recovers_after_handle_closes(
    legacy, tmp_path, monkeypatch, kind, code
):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    errors = []

    def rename(staged, destination):
        if errors:
            return rename_without_replace(staged, destination)
        locked = next((staged / "original").iterdir()) if kind == "child" else staged
        handle = kernel.CreateFileW(
            str(locked),
            0x80000000,
            0x1 | 0x2,
            None,
            3,
            0x02000000 if kind == "directory" else 0,
            None,
        )
        assert handle != wintypes.HANDLE(-1).value
        try:
            try:
                rename_without_replace(staged, destination)
            except OSError as exc:
                errors.append(exc.winerror)
                raise
        finally:
            kernel.CloseHandle(handle)

    monkeypatch.setattr(migration, "rename_without_replace", rename)
    monkeypatch.setattr(migration.time, "sleep", Mock())
    store = PhotoOptimizeStore(tmp_path / "target", legacy_root=legacy.root)
    assert errors == [code]
    assert not store.migration_report.failures and len(store.list_assets()) == 2
