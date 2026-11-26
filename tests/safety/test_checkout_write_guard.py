"""The pytest guard that keeps tests from writing into the checkout's own runtime folders."""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from tests.helpers import checkout_write_guard
from tests.helpers.checkout_write_guard import CheckoutWriteGuard

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("folder", ["output", "outdir", "test_output", "MagicMock"])
def test_a_write_into_a_guarded_folder_is_recorded_without_interrupting_the_writer(
    tmp_path: Path, folder: str
) -> None:
    guard = CheckoutWriteGuard(tmp_path)

    # Raising here once drove the app into a modal error dialog that hung every Linux census shard.
    guard.audit("open", (str(tmp_path / folder / "a.json"), "w", 0))

    assert guard.take() == [f"open {os.path.normcase(os.path.join(folder, 'a.json'))}"]
    assert guard.take() == []


def test_every_way_of_creating_something_there_is_seen(tmp_path: Path) -> None:
    guard = CheckoutWriteGuard(tmp_path)

    for event, args in (
        ("os.mkdir", (tmp_path / "outdir", 0o777, -1)),
        ("os.mkdir", (str(tmp_path / "output" / "manifests"), 0o777, -1)),
        ("os.rename", (str(tmp_path / "a.tmp"), str(tmp_path / "output" / "a.json"), -1, -1)),
        ("open", (os.fsencode(tmp_path / "output" / "b.json"), None, os.O_WRONLY | os.O_CREAT)),
    ):
        guard.audit(event, args)

    assert len(guard.take()) == 4


@pytest.mark.skipif(os.name != "nt", reason="the long-path prefix is a Windows form")
def test_the_windows_long_path_form_is_the_same_folder(tmp_path: Path) -> None:
    guard = CheckoutWriteGuard(tmp_path)

    guard.audit("os.mkdir", ("\\\\?\\" + str(tmp_path / "output" / "PhotoOptimize"), 0o777, -1))

    assert guard.take() == [f"os.mkdir {os.path.normcase(os.path.join('output', 'PhotoOptimize'))}"]


@pytest.mark.skipif(os.name != "nt", reason="the long-path prefix is a Windows form")
def test_the_windows_long_path_form_of_a_network_share_is_the_same_folder() -> None:
    guard = CheckoutWriteGuard(Path(r"\\server\share\repo"))

    # ``photo_optimize.paths.io_path`` writes a network path as ``\\?\UNC\server\share\...``.
    guard.audit("os.mkdir", (r"\\?\UNC\server\share\repo\output\PhotoOptimize", 0o777, -1))

    assert guard.take() == [f"os.mkdir {os.path.normcase(os.path.join('output', 'PhotoOptimize'))}"]


def test_deletes_copies_and_links_there_are_seen(tmp_path: Path) -> None:
    guard = CheckoutWriteGuard(tmp_path)
    inside = tmp_path / "output" / "a.png"
    outside = tmp_path / "elsewhere.png"

    for event, args in (
        ("os.remove", (str(inside), -1)),
        ("os.rmdir", (str(tmp_path / "output"), -1)),
        ("shutil.rmtree", (tmp_path / "output", None)),
        ("os.truncate", (str(inside), 0)),
        ("os.link", (str(outside), str(inside), -1, -1)),
        ("os.symlink", (str(outside), str(inside), -1)),
        # ``shutil.copy2`` on Windows copies without raising an ``open`` event.
        ("_winapi.CopyFile2", (str(outside), str(inside), 0)),
    ):
        guard.audit(event, args)
        assert len(guard.take()) == 1, event


def test_a_name_relative_to_a_directory_descriptor_is_not_read_against_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On Linux ``rmtree`` removes each entry by bare name through a descriptor, wherever that directory is.
    monkeypatch.chdir(tmp_path)
    guard = CheckoutWriteGuard(tmp_path)

    for event, args in (
        ("os.remove", ("output", 7)),
        ("os.rmdir", ("output", 7)),
        ("shutil.rmtree", ("output", 7)),
        ("os.rename", ("output", "outdir", 7, 7)),
    ):
        guard.audit(event, args)

    assert guard.take() == []


def test_opening_a_database_there_is_seen(tmp_path: Path) -> None:
    guard = CheckoutWriteGuard(tmp_path)
    database = tmp_path / "output" / "a.db"

    for target in (
        database,
        str(database),
        os.fsencode(database),
        database.as_uri(),
        f"{database.as_uri()}?mode=rwc",
        f"file:{database.as_posix()}",
    ):
        guard.audit("sqlite3.connect", (target,))
        assert guard.take() == [
            f"sqlite3.connect {os.path.normcase(os.path.join('output', 'a.db'))}"
        ], target


def test_a_database_that_cannot_write_there_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    guard = CheckoutWriteGuard(tmp_path)
    database = tmp_path / "output" / "a.db"

    for target in (
        ":memory:",
        "",
        f"{database.as_uri()}?mode=ro",
        "file:output/shared?mode=memory&cache=shared",
        "file::memory:?cache=shared",
        tmp_path / "state.db",
    ):
        guard.audit("sqlite3.connect", (target,))

    assert guard.take() == []


@pytest.mark.parametrize("operation", ["remove", "rmdir", "rmtree", "copy2", "sqlite"])
def test_this_session_sees_the_real_operation(tmp_path: Path, operation: str) -> None:
    guard = checkout_write_guard.session_guard()
    assert guard is not None, "tests/conftest.py installs the guard"
    # The parent does not exist, so each call fails after its audit event and changes nothing.
    probe = REPO_ROOT / "test_output" / f"guard-probe-{uuid.uuid4().hex}"
    source = tmp_path / "source.txt"
    source.write_text("x", encoding="utf-8")
    call = {
        "remove": lambda: os.remove(probe / "a"),
        "rmdir": lambda: os.rmdir(probe / "a"),
        "rmtree": lambda: shutil.rmtree(probe),
        "copy2": lambda: shutil.copy2(source, probe / "a"),
        "sqlite": lambda: sqlite3.connect(probe / "a.db"),
    }[operation]

    with pytest.raises((OSError, sqlite3.OperationalError)):
        call()

    assert guard.take(), "the attempt is recorded; consuming it keeps this test green"
    assert not probe.exists()


def test_reads_other_folders_and_the_bare_output_folder_are_left_alone(tmp_path: Path) -> None:
    guard = CheckoutWriteGuard(tmp_path / "repo")
    repo = tmp_path / "repo"

    for event, args in (
        ("open", (str(repo / "output" / "a.json"), "r", 0)),
        ("open", (str(repo / "output" / "a.json"), None, os.O_RDONLY)),
        ("open", (7, "w", 0)),
        ("open", (str(repo / "outputs-are-not-guarded.json"), "w", 0)),
        ("open", (str(tmp_path / "output" / "outside-the-checkout.json"), "w", 0)),
        # ``StructuredLogger()`` creates an empty ``output`` folder; only what goes inside it matters.
        ("os.mkdir", (str(repo / "output"), 0o777, -1)),
        ("os.listdir", (str(repo / "output"),)),
    ):
        guard.audit(event, args)

    assert guard.take() == []


def test_this_session_records_a_real_write_into_the_checkout() -> None:
    guard = checkout_write_guard.session_guard()
    assert guard is not None, "tests/conftest.py installs the guard"
    probe = REPO_ROOT / "test_output" / f"guard-probe-{uuid.uuid4().hex}"

    # ``os.mkdir`` without its parent fails after the audit event, so nothing is created even where the folder is absent.
    with pytest.raises(FileNotFoundError):
        os.mkdir(probe / "child")

    assert guard.take(), "the attempt is recorded; consuming it keeps this test green"
    assert not probe.exists()


def test_the_photo_workspace_is_redirected_out_of_the_checkout() -> None:
    from src.photo_optimize import store

    assert REPO_ROOT not in store.get_photo_optimize_store()._root.parents
