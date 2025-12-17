# Subsystem: Adapters
# Role: Exposes prompt pack summaries and metadata to GUI widgets.

"""Thin adapter that exposes prompt pack summaries for GUI V2 widgets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.utils.file_io import read_prompt_pack
from src.utils.prompt_packs import PromptPackInfo, discover_packs


@dataclass(frozen=True)
class PromptPackSummary:
    """Lightweight data transfer object for prompt pack display."""

    name: str
    path: Path
    description: str = ""
    prompt_count: int = 0


class PromptPackAdapterV2:
    """Expose prompt packs to GUI V2 without Tk or controller dependencies."""

    def __init__(self, packs_dir: Path | str | None = None) -> None:
        self.packs_dir = Path(packs_dir) if packs_dir is not None else Path("packs")

    def load_summaries(self) -> list[PromptPackSummary]:
        """Return prompt pack summaries for display."""

        descriptors = self._discover(self.packs_dir)
        summaries: list[PromptPackSummary] = []
        for info in descriptors:
            prompts = self._safe_read_pack(info.path)
            description = self._first_positive_prompt(prompts)
            summaries.append(
                PromptPackSummary(
                    name=info.name,
                    path=info.path,
                    description=description,
                    prompt_count=len(prompts),
                )
            )
        return summaries

    def get_base_prompt(self, summary: PromptPackSummary) -> str:
        """Return the base prompt text for the given pack (first positive prompt)."""

        prompts = self._safe_read_pack(summary.path)
        return self._first_positive_prompt(prompts)

    def _discover(self, packs_dir: Path) -> list[PromptPackInfo]:
        try:
            return discover_packs(packs_dir)
        except Exception:
            return []

    def _safe_read_pack(self, pack_path: Path) -> list[dict[str, str]]:
        try:
            return read_prompt_pack(pack_path)
        except Exception:
            return []

    @staticmethod
    def _first_positive_prompt(prompts: Iterable[dict[str, str]] | None) -> str:
        if not prompts:
            return ""
        try:
            first = next(iter(prompts))
        except StopIteration:
            return ""
        return (first.get("positive") or "").strip()


__all__ = ["PromptPackAdapterV2", "PromptPackSummary"]
