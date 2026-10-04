"""Isolation, layout and the owned managed-Forge runtime (WebUIProcessManager is the only lifecycle authority)."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any

from .spec import ASSETS, FORGE_SHA

PORT = 7885  # qualification-owned loopback port, outside 7860-7869 and the production Forge 7871


def assert_isolated(root: Path, *, repo_root: Path, managed_install: Path, a1111_home: Path | None = None) -> None:
    """The evidence/model roots live outside the repository, the managed install, A1111 and every application env."""

    resolved = Path(root).resolve()
    for forbidden in filter(None, (repo_root, managed_install, a1111_home)):
        other = Path(forbidden).resolve()
        if resolved == other or other in resolved.parents:
            raise ValueError(f"qualification root {resolved} must be outside {other}")
    lowered = str(resolved).lower()
    for marker in (".venv", "stable-diffusion-webui", "comfyruntime", "managedcomfy"):
        if marker in lowered:
            raise ValueError(f"qualification root {resolved} must not be inside {marker}")


def build_layout(root: Path) -> dict[str, Path]:
    """assets/ holds the downloads; forge-data/models/* gets same-volume hard links (no copy into any library)."""

    root = Path(root)
    layout = {name: root / name for name in ("assets", "model-home", "forge-data", "evidence", "outputs", "runtime")}
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    models = layout["forge-data"] / "models"
    for asset in ASSETS.values():
        target_dir = models / asset.models_subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        target, source = target_dir / asset.filename, layout["assets"] / asset.filename
        if source.exists() and not target.exists():
            os.link(source, target)
    config = layout["forge-data"] / "config.json"
    if not config.exists():  # Forge blocks on an interactive prompt without its VERSION_UID marker
        config.write_text(json.dumps({"VERSION_UID": "PY313"}), encoding="utf-8")
    layout["models"] = models
    return layout


def launch_profile(root: Path, install_dir: Path, *, port: int = PORT) -> dict[str, Any]:
    """The managed Forge's own interpreter/source/env, with every writable path repointed into the qualification root."""

    from tools.runtime.verify_managed_forge import build_launch_profile, load_manifest

    base = build_launch_profile(load_manifest(), install_dir=Path(install_dir), model_home=Path(root) / "model-home", port=port)
    venv_python = str(Path(install_dir) / "venv" / "Scripts" / "python.exe")
    command = [venv_python, "launch.py", "--uv", "--api", "--port", str(port), "--data-dir", str(Path(root) / "forge-data"), "--skip-install"]
    runtime = Path(root) / "runtime"
    env = dict(base["env_overrides"])
    env.update({"HF_HUB_CACHE": str(runtime / "hf"), "MPLCONFIGDIR": str(runtime / "matplotlib"), "YOLO_CONFIG_DIR": str(runtime / "yolo"), "UV_CACHE_DIR": str(runtime / "uv-cache")})
    for path in (runtime / "hf", runtime / "matplotlib", runtime / "yolo", runtime / "uv-cache"):
        path.mkdir(parents=True, exist_ok=True)
    return {"command": command, "working_dir": str(Path(install_dir) / "source"), "env_overrides": env, "endpoint": f"http://127.0.0.1:{port}",
            "startup_timeout_seconds": 300, "runtime_identity": "forge_webui", "forge_sha": FORGE_SHA}


def port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) != 0


class OwnedForge:
    """Starts and stops exactly one Forge through WebUIProcessManager; never adopts or kills anything else."""

    def __init__(self, profile: dict[str, Any], *, manager_factory: Any = None, lock_factory: Any = None) -> None:
        self.profile = profile
        self._manager_factory = manager_factory
        self._lock_factory = lock_factory
        self.manager: Any = None
        self._lock: Any = None

    @property
    def base_url(self) -> str:
        return str(self.profile["endpoint"])

    def start(self) -> dict[str, Any]:
        from urllib.parse import urlparse

        port = urlparse(self.base_url).port
        if not port_is_free(int(port)):
            raise RuntimeError(f"port {port} is occupied: an external runtime is never adopted or stopped")
        if self._manager_factory is None:
            from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager
            from src.utils.single_instance import SingleInstanceLock

            self._lock_factory = self._lock_factory or SingleInstanceLock
            self._manager_factory = lambda p: WebUIProcessManager(WebUIProcessConfig(
                command=list(p["command"]), working_dir=p["working_dir"], env_overrides=p["env_overrides"],
                startup_timeout_seconds=float(p["startup_timeout_seconds"]), base_url=p["endpoint"], runtime_identity="forge_webui"))
        if self._lock_factory is not None:
            self._lock = self._lock_factory()
            if not self._lock.acquire():
                raise RuntimeError("another StableNew instance holds the application lock; nothing was started")
        began = time.monotonic()
        self.manager = self._manager_factory(self.profile)
        self.manager.start()
        return {"started_at": began, "pid": self.manager.pid, "owns_process": self.manager.owns_process}

    def process_tree_pids(self) -> list[int]:
        import psutil

        pid = getattr(self.manager, "pid", None)
        if not pid or not psutil.pid_exists(pid):
            return []
        root = psutil.Process(pid)
        return [root.pid, *(p.pid for p in root.children(recursive=True))]

    def stop(self) -> dict[str, Any]:
        import psutil

        pids = self.process_tree_pids() if self.manager is not None and self.manager.owns_process else []
        if self.manager is not None:
            self.manager.stop()
        if self._lock is not None:
            self._lock.release()
        return {"owned_pids": pids, "survivors": [p for p in pids if psutil.pid_exists(p)]}
