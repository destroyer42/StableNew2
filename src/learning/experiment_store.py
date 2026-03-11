from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip()).strip("-").lower()
    return text or "experiment"


@dataclass(frozen=True)
class LearningExperimentHandle:
    experiment_id: str
    display_name: str
    created_at: str
    updated_at: str
    session_path: Path


class LearningExperimentStore:
    INDEX_FILE = "index.json"
    SESSION_FILE = "session.json"
    META_FILE = "meta.json"

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_experiment_id(self, display_name: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{stamp}_{_slugify(display_name)}_{uuid.uuid4().hex[:8]}"

    def save_session(
        self,
        *,
        display_name: str,
        payload: dict[str, Any],
        experiment_id: str | None = None,
    ) -> LearningExperimentHandle:
        resolved_id = str(experiment_id or self.create_experiment_id(display_name))
        experiment_dir = self.root / resolved_id
        experiment_dir.mkdir(parents=True, exist_ok=True)
        now = _utc_now_iso()

        meta_path = experiment_dir / self.META_FILE
        previous = self._read_json(meta_path) or {}
        created_at = str(previous.get("created_at") or now)
        meta = {
            "experiment_id": resolved_id,
            "display_name": str(display_name or resolved_id),
            "created_at": created_at,
            "updated_at": now,
            "schema_version": 1,
        }
        self._write_json(meta_path, meta)
        self._write_json(experiment_dir / self.SESSION_FILE, payload)

        index = self._load_index()
        index["last_experiment_id"] = resolved_id
        entries = index.setdefault("entries", {})
        entries[resolved_id] = {
            "display_name": meta["display_name"],
            "created_at": created_at,
            "updated_at": now,
        }
        self._save_index(index)
        return LearningExperimentHandle(
            experiment_id=resolved_id,
            display_name=meta["display_name"],
            created_at=created_at,
            updated_at=now,
            session_path=experiment_dir / self.SESSION_FILE,
        )

    def load_session(self, experiment_id: str) -> dict[str, Any] | None:
        session_path = self.root / str(experiment_id) / self.SESSION_FILE
        data = self._read_json(session_path)
        return data if isinstance(data, dict) else None

    def load_last_session(self) -> tuple[str, dict[str, Any]] | None:
        experiment_id = self.get_last_experiment_id()
        if not experiment_id:
            return None
        payload = self.load_session(experiment_id)
        if not isinstance(payload, dict):
            return None
        return experiment_id, payload

    def get_last_experiment_id(self) -> str | None:
        index = self._load_index()
        experiment_id = index.get("last_experiment_id")
        return str(experiment_id) if experiment_id else None

    def set_last_experiment_id(self, experiment_id: str | None) -> None:
        index = self._load_index()
        index["last_experiment_id"] = str(experiment_id) if experiment_id else None
        self._save_index(index)

    def list_handles(self) -> list[LearningExperimentHandle]:
        handles: list[LearningExperimentHandle] = []
        index = self._load_index()
        entries = index.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}
        for experiment_id, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            handles.append(
                LearningExperimentHandle(
                    experiment_id=str(experiment_id),
                    display_name=str(meta.get("display_name") or experiment_id),
                    created_at=str(meta.get("created_at") or ""),
                    updated_at=str(meta.get("updated_at") or ""),
                    session_path=self.root / str(experiment_id) / self.SESSION_FILE,
                )
            )
        handles.sort(key=lambda item: item.updated_at, reverse=True)
        return handles

    def session_path_for(self, experiment_id: str) -> Path:
        return self.root / str(experiment_id) / self.SESSION_FILE

    def _load_index(self) -> dict[str, Any]:
        data = self._read_json(self.root / self.INDEX_FILE)
        if not isinstance(data, dict):
            return {"last_experiment_id": None, "entries": {}}
        data.setdefault("last_experiment_id", None)
        data.setdefault("entries", {})
        return data

    def _save_index(self, payload: dict[str, Any]) -> None:
        self._write_json(self.root / self.INDEX_FILE, payload)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

