import json
from pathlib import Path
from typing import Any, cast


class ConfigService:
    def __init__(self, packs_dir: Path, presets_dir: Path, lists_dir: Path):
        self.packs_dir = Path(packs_dir)
        self.presets_dir = Path(presets_dir)
        self.lists_dir = Path(lists_dir)

        self.packs_dir.mkdir(parents=True, exist_ok=True)
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        self.lists_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_pack_path(self, pack: str | Path) -> Path:
        candidate = Path(pack)
        if candidate.suffix.lower() == ".json":
            base = candidate.name
        elif candidate.suffix:
            base = candidate.with_suffix("").name
        else:
            base = candidate.name
        return self.packs_dir / f"{base}.json"

    def load_pack_config(self, pack: str) -> dict[str, Any]:
        path = self._resolve_pack_path(pack)
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))

    def save_pack_config(self, pack: str, cfg: dict) -> None:
        path = self._resolve_pack_path(pack)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def list_presets(self) -> list[str]:
        return [p.stem for p in self.presets_dir.glob("*.json")]

    def load_preset(self, name: str) -> dict[str, Any]:
        path = self.presets_dir / f"{name}.json"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))

    def save_preset(self, name: str, cfg: dict, overwrite: bool = True) -> None:
        path = self.presets_dir / f"{name}.json"
        if path.exists() and not overwrite:
            raise FileExistsError(f"Preset {name} already exists.")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def delete_preset(self, name: str) -> None:
        path = self.presets_dir / f"{name}.json"
        if path.exists():
            path.unlink()

    def _resolve_list_path(self, name: str | Path) -> Path:
        candidate = Path(name)
        if candidate.suffix.lower() == ".json":
            return self.lists_dir / candidate.name
        return self.lists_dir / f"{candidate.stem}.json"

    def load_list(self, name: str) -> list[str]:
        path = self._resolve_list_path(name)
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = cast(dict[str, Any], json.load(f))
        return cast(list[str], data.get("packs", []))

    def save_list(self, name: str, packs: list[str], overwrite: bool = True) -> None:
        path = self._resolve_list_path(name)
        if path.exists() and not overwrite:
            raise FileExistsError(f"List {name} already exists.")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"packs": packs}, f, indent=2)

    def delete_list(self, name: str) -> None:
        path = self._resolve_list_path(name)
        if path.exists():
            path.unlink()

    def list_lists(self) -> list[str]:
        return sorted(p.stem for p in self.lists_dir.glob("*.json"))
