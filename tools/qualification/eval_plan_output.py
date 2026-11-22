"""Resolve omitted plan output arguments without changing existing write boundaries."""

from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from src.state.eval_plans_paths import initialize_eval_plans
from src.state.workspace_paths import workspace_paths
from src.utils.config import ConfigManager


def configured_eval_plans_root() -> Path:
    settings_dir = workspace_paths.root / "presets"
    settings = ConfigManager(settings_dir).load_settings() if settings_dir.is_dir() else {}
    output = settings.get("output_dir")
    override = settings.get("eval_plans_dir")
    return workspace_paths.eval_plans_root(
        output_root=output if isinstance(output, str) else None,
        override=override if isinstance(override, str) else None,
    )


def plan_output(
    parser: ArgumentParser,
    explicit: str | Path | None,
    tool: str,
    *,
    filename: str | None = None,
) -> Path:
    if explicit is not None:
        return Path(explicit)
    root = configured_eval_plans_root()
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    destination = root / "qualification" / tool / f"{stamp}_{uuid4().hex[:8]}"
    if filename:
        destination /= filename
    if any(path.resolve().is_relative_to(workspace_paths.root) for path in (root, destination)):
        parser.error(
            "--out is required with the current settings. Set eval_plans_dir to a folder "
            f"outside the repository to default to qualification/{tool}/ (current root: {root})."
        )
    initialize_eval_plans(root)
    return destination
