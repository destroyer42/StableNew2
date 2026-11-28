"""KEEP-SPACE: files only move to a Recycle Bin that can take them, in bounded batches. The shell is fake."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.utils import recycle_bin as module
from src.utils.recycle_bin import RecycleBinRefused
from tests.helpers.recycle_bin import fake_bin


def _files(folder: Path, count: int) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    found = [folder / f"f{number:04d}.png" for number in range(count)]
    for path in found:
        path.write_bytes(b"png")
    return found


def test_the_move_is_undoable_and_windows_must_ask_before_destroying() -> None:
    flags = module.RECYCLE_FLAGS

    assert flags & module.FOF_ALLOWUNDO and flags & module.FOF_WANTNUKEWARNING


def test_room_is_the_limit_less_what_the_bin_holds(tmp_path: Path) -> None:
    recycle_bin, _shell = fake_bin(tmp_path / "bin", limit_mb=10, used=4 * 1024 * 1024)

    room = recycle_bin.room("T:\\")

    assert (room.limit_bytes, room.free_bytes) == (10 * 1024 * 1024, 6 * 1024 * 1024)


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"fixed": False}, "not a local fixed drive"),
        ({"disabled": True}, "turned off"),
        ({"limit_mb": None}, "not recorded"),
    ],
)
def test_a_bin_that_cannot_be_established_refuses(tmp_path: Path, kwargs, words: str) -> None:
    recycle_bin, _shell = fake_bin(tmp_path / "bin", **kwargs)

    with pytest.raises(RecycleBinRefused, match=words):
        recycle_bin.room("T:\\")


def test_files_move_in_batches(tmp_path: Path) -> None:
    recycle_bin, shell = fake_bin(tmp_path / "bin")
    files = _files(tmp_path / "run", module.BATCH_FILES + 5)

    recycle_bin.move(files)

    assert [len(batch) for batch in shell.batches] == [module.BATCH_FILES, 5]
    assert len(shell.recycled()) == len(files) and not any(path.exists() for path in files)


def test_a_failed_batch_stops_the_move_and_deletes_nothing(tmp_path: Path) -> None:
    recycle_bin, shell = fake_bin(tmp_path / "bin", takes=2)
    files = _files(tmp_path / "run", module.BATCH_FILES + 5)

    with pytest.raises(RecycleBinRefused):
        recycle_bin.move(files)

    assert len(shell.batches) == 1
    assert len(shell.recycled()) == 2
    assert sum(path.exists() for path in files) == len(files) - 2


def test_a_path_too_long_for_the_shell_moves_nothing(tmp_path: Path) -> None:
    recycle_bin, shell = fake_bin(tmp_path / "bin")

    with pytest.raises(RecycleBinRefused, match="too long"):
        recycle_bin.move([tmp_path / ("x" * 300)])

    assert shell.batches == []
