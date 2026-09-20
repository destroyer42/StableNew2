"""Disposable, test-owned StableNew workspace for one operator journey.

Every mutable authority the journey can reach (SQLite repository, Learning
records/experiments, UI state, presets/settings, PromptPacks, outputs, logs) is
redirected to a per-run directory through the existing path seams.  A guard
snapshots the user's real data and the tracked Git tree before the run and fails
the journey if either changes.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
# Directories whose contents belong to the operator, never to a journey.
_PROTECTED_DIRS = ("state", "data", "presets", "config", "packs")
_ENV_KEYS = (
    "STABLENEW_OUTPUT_DIR",
    "STABLENEW_WEBUI_BASE_URL",
    "STABLENEW_PROMPTPACK_DIR",
    "STABLENEW_INITIAL_RESOURCE_GRACE_SEC",
    "PYTEST_CURRENT_TEST",
    "STABLENEW_TEST_MODE",
    "STABLENEW_NO_WEBUI",
)
# Test-mode switches change production behavior (in-memory queue, no WebUI); a
# journey exercises the real product configuration even when a test launched it.
_TEST_MODE_ENV = ("PYTEST_CURRENT_TEST", "STABLENEW_TEST_MODE", "STABLENEW_NO_WEBUI")


def repo_sha(repo_root: Path = REPO_ROOT) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, timeout=15
        ).strip()
    except Exception:
        return "unknown"


def _git_status(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=repo_root, text=True, timeout=30
        )
    except Exception as exc:  # pragma: no cover - environment specific
        return f"git-status-unavailable: {exc}"


def _tree_signature(root: Path) -> dict[str, list[int]]:
    signature: dict[str, list[int]] = {}
    if not root.exists():
        return signature
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        signature[path.relative_to(root).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return signature


@dataclass
class UserDataGuard:
    """Detect mutation of the operator's real data or tracked repository files."""

    repo_root: Path = REPO_ROOT
    _before: dict[str, Any] = field(default_factory=dict)

    def _snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {"git_status": _git_status(self.repo_root)}
        for name in _PROTECTED_DIRS:
            snapshot[name] = _tree_signature(self.repo_root / name)
        output = self.repo_root / "output"
        snapshot["output_top_level"] = (
            sorted(entry.name for entry in output.iterdir()) if output.exists() else []
        )
        return snapshot

    def capture(self) -> None:
        self._before = self._snapshot()

    def violations(self) -> list[str]:
        after = self._snapshot()
        problems: list[str] = []
        if after["git_status"] != self._before.get("git_status"):
            problems.append("git status changed during the journey")
        for key in (*_PROTECTED_DIRS, "output_top_level"):
            if after[key] != self._before.get(key):
                changed = _diff_keys(self._before.get(key), after[key])
                problems.append(f"protected data changed in {key}/: {changed}")
        return problems


def _diff_keys(before: Any, after: Any) -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = set(before) | set(after)
        return sorted(k for k in keys if before.get(k) != after.get(k))[:10]
    return sorted(set(before or []) ^ set(after or []))[:10]


@dataclass
class OperatorWorkspace:
    """Paths and patches for one isolated journey; use via ``activate()``."""

    root: Path
    webui_base_url: str
    repo_root: Path = REPO_ROOT
    # None keeps StableNew's production startup probe grace (the ~15-30 s it takes
    # to connect to WebUI); a number overrides it through the existing env seam.
    startup_grace_sec: float | None = None

    @property
    def presets_dir(self) -> Path:
        return self.root / "presets"

    @property
    def packs_dir(self) -> Path:
        return self.root / "packs"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def records_path(self) -> Path:
        return self.root / "data" / "learning" / "learning_records.jsonl"

    def prepare(self) -> None:
        for directory in (
            self.presets_dir,
            self.packs_dir,
            self.output_dir,
            self.state_dir,
            self.records_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        settings = {
            "webui_base_url": self.webui_base_url,
            "webui_autostart_enabled": False,
            "comfy_autostart_enabled": False,
            "output_dir": str(self.output_dir),
        }
        (self.presets_dir / "settings.json").write_text(json.dumps(settings, indent=2), "utf-8")

    def config_manager(self) -> Any:
        from src.utils.config import ConfigManager

        return ConfigManager(presets_dir=self.presets_dir, packs_dir=self.packs_dir)

    @contextmanager
    def activate(self) -> Iterator[OperatorWorkspace]:
        """Redirect the process-wide path authorities to this workspace."""

        from src.state.workspace_paths import workspace_paths
        from src.utils.config import ConfigManager

        self.prepare()
        saved_root = workspace_paths._root
        saved_defaults = ConfigManager.__init__.__defaults__
        saved_env = {key: os.environ.get(key) for key in _ENV_KEYS}
        saved_cwd = os.getcwd()
        workspace_paths._root = self.root.resolve()
        # Learning/queue jobs default their output to the cwd-relative "output"
        # directory, so the journey also runs from inside its workspace.
        os.chdir(self.root)
        # Many call sites build ``ConfigManager()``; redirect its defaults so
        # none of them can read or write the operator's real presets/packs.
        ConfigManager.__init__.__defaults__ = (str(self.presets_dir), str(self.packs_dir))
        os.environ.update(
            {
                "STABLENEW_OUTPUT_DIR": str(self.output_dir),
                "STABLENEW_WEBUI_BASE_URL": self.webui_base_url,
                "STABLENEW_PROMPTPACK_DIR": str(self.packs_dir),
            }
        )
        if self.startup_grace_sec is not None:
            os.environ["STABLENEW_INITIAL_RESOURCE_GRACE_SEC"] = str(self.startup_grace_sec)
        else:
            os.environ.pop("STABLENEW_INITIAL_RESOURCE_GRACE_SEC", None)
        for key in _TEST_MODE_ENV:
            os.environ.pop(key, None)
        try:
            yield self
        finally:
            os.chdir(saved_cwd)
            workspace_paths._root = saved_root
            ConfigManager.__init__.__defaults__ = saved_defaults
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def archive_workspace(
    workspace: OperatorWorkspace, evidence: Any, run_dir: Path, *, discard: bool
) -> None:
    """Copy the durable proof (short names) into the evidence dir, then optionally drop the workspace."""

    import shutil

    target = run_dir / "artifacts"
    target.mkdir(parents=True, exist_ok=True)
    for index, variant in enumerate(evidence.variants):
        for key, suffix in (("artifact", ".png"), ("manifest", ".json")):
            source = Path(str(variant.get(key) or ""))
            if source.is_file():
                shutil.copy2(
                    source,
                    target / f"v{index}_{'image' if key == 'artifact' else 'manifest'}{suffix}",
                )
    for source, name in (
        (workspace.records_path, "learning_records.jsonl"),
        (workspace.state_dir / "jobs.sqlite3", "jobs.sqlite3"),
    ):
        if source.is_file():
            shutil.copy2(source, target / name)
    if discard:
        shutil.rmtree(workspace.root, ignore_errors=True)
