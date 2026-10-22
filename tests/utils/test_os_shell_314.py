"""PR-VID-UX-314: open / reveal helpers (injected launchers; no real viewer or file manager starts)."""

from __future__ import annotations

from pathlib import Path

from src.utils.os_shell import open_file, reveal_in_file_manager


def test_open_hands_an_existing_file_to_the_opener(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    opened: list[str] = []
    result = open_file(clip, opener=opened.append)
    assert result.ok and opened == [str(clip)]


def test_open_and_reveal_refuse_a_missing_file_without_launching(tmp_path: Path) -> None:
    opened: list[str] = []
    launched: list[list[str]] = []
    missing = tmp_path / "gone.mp4"
    result = open_file(missing, opener=opened.append)
    assert not result.ok and "no longer exists" in result.message and opened == []
    result = reveal_in_file_manager(missing, launcher=launched.append, platform="win32")
    assert not result.ok and launched == []
    assert not open_file("", opener=opened.append).ok


def test_a_viewer_failure_is_a_value_not_an_exception(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")

    def boom(_path: str) -> None:
        raise OSError("no association")

    result = open_file(clip, opener=boom)
    assert not result.ok and "no association" in result.message

    def refuse(_command) -> None:
        raise OSError("no file manager")

    assert not reveal_in_file_manager(clip, launcher=refuse, platform="linux").ok


def test_reveal_builds_the_platform_argument_vector_without_a_shell(tmp_path: Path) -> None:
    clip = tmp_path / "my clip.mp4"
    clip.write_bytes(b"x")
    seen: dict[str, list[str]] = {}
    for platform in ("win32", "darwin", "linux"):
        assert reveal_in_file_manager(
            clip,
            launcher=lambda command, key=platform: seen.__setitem__(key, list(command)),
            platform=platform,
        ).ok
    assert seen["win32"] == ["explorer", f"/select,{clip}"]
    assert seen["darwin"] == ["open", "-R", str(clip)]
    assert seen["linux"] == ["xdg-open", str(tmp_path)]


def test_a_relative_name_that_looks_like_an_option_is_made_absolute(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "-rf.mp4").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    opened: list[str] = []
    assert open_file("-rf.mp4", opener=opened.append).ok
    assert opened == [str(tmp_path / "-rf.mp4")]
