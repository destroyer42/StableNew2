"""Session-scoped selection of visible, local PromptPacks."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.pipeline.site_create_settings import Choice, describe_settings, validate_settings
from src.utils.file_io import read_prompt_pack
from src.utils.prompt_packs import PromptPackInfo

_MAX_PACK_BYTES = 4 * 1024 * 1024


def pack_digest(path: Path) -> str:
    with path.open("rb") as stream:
        raw = stream.read(_MAX_PACK_BYTES + 1)
    if len(raw) > _MAX_PACK_BYTES:
        raise ValueError("promptpack_too_large")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class PreparePack:
    request_id: str
    pack: PromptPackInfo
    digest: str
    slots: tuple[int, ...]
    overrides: tuple[tuple[str, Choice], ...] = ()


class SitePackCatalog:
    def __init__(
        self,
        root: Path,
        packs: list[PromptPackInfo],
        load_config: Callable[[str], Mapping[str, Any] | None] | None = None,
        resources: Mapping[str, Any] | None = None,
    ) -> None:
        root = root.resolve()
        self.packs: dict[str, PromptPackInfo] = {}
        self._load_config = load_config
        self._resources = dict(resources or {})
        for pack in packs[:500]:
            path = pack.path.resolve()
            if path.parent == root and path.suffix.lower() == ".json" and path.is_file():
                self.packs[secrets.token_hex(16)] = PromptPackInfo(
                    pack.name, path, pack.preset_name
                )

    def list_packs(self) -> list[dict[str, str]]:
        return [{"id": key, "name": pack.name} for key, pack in self.packs.items()]

    def describe(self, key: str) -> dict[str, object]:
        pack = self.packs.get(key)
        if pack is None:
            raise ValueError("unknown_promptpack")
        digest = pack_digest(pack.path)
        rows = read_prompt_pack(pack.path)
        if digest != pack_digest(pack.path) or not rows:
            raise ValueError("promptpack_changed")
        return {
            "id": key,
            "title": pack.name,
            "revision": digest,
            **(
                {"settings": describe_settings(self._load_config(pack.name) or {}, self._resources)}
                if self._load_config is not None
                else {}
            ),
            "slots": [
                {"index": index, "prompt": str(row.get("positive", ""))[:240]}
                for index, row in enumerate(rows[:500])
            ],
        }

    def prepare(
        self, key: str, digest: str, slots: tuple[int, ...], settings: object = None
    ) -> PreparePack:
        pack = self.packs.get(key)
        if pack is None or pack_digest(pack.path) != digest:
            raise ValueError("promptpack_changed")
        overrides = validate_settings({} if settings is None else settings, self._resources)
        return PreparePack(secrets.token_hex(16), pack, digest, slots, tuple(overrides.items()))
