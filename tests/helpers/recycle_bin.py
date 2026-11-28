"""A fake Windows shell for the Recycle Bin: files "recycled" land in a folder of the test's temp directory."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from src.utils.recycle_bin import RecycleBin


class FakeShell:
    def __init__(
        self,
        bin_folder: Path,
        *,
        limit_mb: int | None = 1000,
        used: int = 0,
        disabled: bool = False,
        fixed: bool = True,
        takes: int | None = None,
    ) -> None:
        self.bin_folder = bin_folder
        self.limit_mb = limit_mb
        self.used = used
        self.disabled = disabled
        self.fixed = fixed
        self.takes = takes  # how many files the shell moves before it gives up; None: all
        self.batches: list[list[str]] = []

    def volume_root(self, folder: str) -> str:
        return "T:\\"

    def is_fixed_drive(self, volume: str) -> bool:
        return self.fixed

    def used_bytes(self, volume: str) -> int:
        return self.used

    def limit(self, volume: str) -> tuple[int | None, bool]:
        return self.limit_mb, self.disabled

    def move_to_bin(self, paths: Sequence[str]) -> bool:
        self.batches.append(list(paths))
        self.bin_folder.mkdir(parents=True, exist_ok=True)
        for text in paths:
            if self.takes is not None:
                if self.takes <= 0:
                    return False
                self.takes -= 1
            path = Path(text)
            path.rename(self.bin_folder / f"{len(self.recycled())}_{path.name}")
        return True

    def recycled(self) -> list[str]:
        if not self.bin_folder.is_dir():
            return []
        return sorted(item.name.split("_", 1)[1] for item in self.bin_folder.iterdir())


def fake_bin(folder: Path, **kwargs: object) -> tuple[RecycleBin, FakeShell]:
    shell = FakeShell(folder, **kwargs)  # type: ignore[arg-type]
    return RecycleBin(shell), shell
