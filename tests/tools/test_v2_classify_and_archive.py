from __future__ import annotations

from pathlib import Path

import pytest

from tools.v2_classify_and_archive import build_inventory, move_to_archive


@pytest.mark.parametrize(
    "paths,expect_v1,expect_v2,expect_shared,expect_unknown",
    [
        (
            [
                "src/gui/stage_cards_v2/card.py",
                "src/gui/text_panel.py",
                "src/controller/app_controller.py",
                "src/utils/helper.py",
                "tests/gui_v2/test_dummy.py",
                "misc/unknown.txt",
            ],
            {"src/gui/text_panel.py"},
            {"src/gui/stage_cards_v2/card.py", "src/controller/app_controller.py", "tests/gui_v2/test_dummy.py"},
            {"src/utils/helper.py"},
            {"misc/unknown.txt"},
        )
    ],
)
def test_build_inventory(tmp_path: Path, paths, expect_v1, expect_v2, expect_shared, expect_unknown):
    for rel in paths:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass")

    result = build_inventory(tmp_path)

    assert set(result.v1) == expect_v1
    assert set(result.v2) >= expect_v2
    assert set(result.shared) == expect_shared
    assert set(result.unknown) == expect_unknown


def test_move_to_archive(tmp_path: Path):
    files = ["src/gui/text_panel.py", "src/gui/foo/bar.py"]
    for rel in files:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("legacy")

    archive_root = tmp_path / "archive"
    move_to_archive(tmp_path, archive_root, files, dry_run=True)
    for rel in files:
        assert (tmp_path / rel).exists()

    move_to_archive(tmp_path, archive_root, files, dry_run=False)
    for rel in files:
        assert not (tmp_path / rel).exists()
        assert (archive_root / rel).exists()
