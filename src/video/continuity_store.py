from __future__ import annotations

import json
from pathlib import Path

from src.video.continuity_models import ContinuityPack, ContinuityPackLink, ContinuityPackSummary


class ContinuityStore:
    DEFAULT_ROOT = Path("data") / "continuity"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else self.DEFAULT_ROOT

    @staticmethod
    def _safe_pack_id(pack_id: str) -> str:
        return str(pack_id).replace("/", "_").replace(":", "_")

    def pack_path(self, pack_id: str) -> Path:
        safe_pack_id = self._safe_pack_id(pack_id)
        if not safe_pack_id:
            raise ValueError("Continuity pack id is required")
        return self.root / f"{safe_pack_id}.json"

    def save_pack(self, pack: ContinuityPack) -> Path:
        path = self.pack_path(pack.pack_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(pack.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(path)
        return path

    def load_pack(self, pack_id: str) -> ContinuityPack | None:
        path = self.pack_path(pack_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return ContinuityPack.from_dict(payload)

    def has_pack(self, pack_id: str) -> bool:
        return self.pack_path(pack_id).exists()

    def list_pack_summaries(self) -> list[ContinuityPackSummary]:
        if not self.root.exists():
            return []
        summaries: list[ContinuityPackSummary] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            summaries.append(ContinuityPack.from_dict(payload).summary())
        summaries.sort(key=lambda item: (item.display_name.lower(), item.pack_id))
        return summaries

    def get_link(self, pack_id: str) -> ContinuityPackLink | None:
        pack = self.load_pack(pack_id)
        return pack.link() if pack is not None else None


__all__ = ["ContinuityStore"]