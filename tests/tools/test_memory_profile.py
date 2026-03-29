from __future__ import annotations

import tempfile
from pathlib import Path

from tools.test_helpers.memory_profile import (
    create_memprof_dir,
    temporary_memprof_plugin,
    write_memprof_plugin,
)


def test_create_memprof_dir_defaults_to_system_temp_not_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    repo_like_root = tmp_path / "repo"
    repo_like_root.mkdir()
    monkeypatch.chdir(repo_like_root)

    memprof_dir = create_memprof_dir()
    try:
        assert memprof_dir.exists()
        assert memprof_dir.parent != repo_like_root
        assert memprof_dir.parent == Path(tempfile.gettempdir())
    finally:
        if memprof_dir.exists():
            memprof_dir.rmdir()


def test_write_memprof_plugin_writes_plugin_file_under_requested_base_dir(tmp_path: Path) -> None:
    plugin_path = write_memprof_plugin("print('ok')", base_dir=tmp_path)
    try:
        assert plugin_path.name == "mem_profile_plugin.py"
        assert plugin_path.parent.parent == tmp_path
        assert plugin_path.read_text(encoding="utf-8") == "print('ok')"
    finally:
        if plugin_path.parent.exists():
            for child in plugin_path.parent.iterdir():
                child.unlink()
            plugin_path.parent.rmdir()


def test_temporary_memprof_plugin_cleans_up_temp_dir(tmp_path: Path) -> None:
    created_parent: Path | None = None
    with temporary_memprof_plugin("print('ok')", base_dir=tmp_path) as plugin_path:
        created_parent = plugin_path.parent
        assert plugin_path.exists()

    assert created_parent is not None
    assert not created_parent.exists()
