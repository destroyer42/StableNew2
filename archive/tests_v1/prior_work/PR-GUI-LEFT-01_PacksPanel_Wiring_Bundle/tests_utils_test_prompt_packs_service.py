import os
from pathlib import Path

import pytest

# from src.utils.prompt_packs import PackService  # to be implemented


class TestPackService:
    def test_empty_directory_returns_no_packs(self, tmp_path: Path) -> None:
        # Arrange: empty directory
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()

        # TODO: replace with real PackService once implemented
        # service = PackService(base_dir=packs_dir)
        # Act
        # packs = service.list_packs()

        # Assert
        # assert packs == []
        pytest.skip("PackService not implemented yet")

    def test_discovers_multiple_packs(self, tmp_path: Path) -> None:
        # This test should create a couple of fake pack files/dirs
        # and assert that PackService.list_packs() returns them by name.
        pytest.skip("PackService discovery test not implemented yet")
