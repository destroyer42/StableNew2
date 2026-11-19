"""The offline physical lane: what a frozen plan target for a journey with no generative inference must carry.

A GPU journey (IMG-01, VID-01, LRN-01) is gated by its runtime and its model.  An *offline* journey (today only VID-02,
Batch Convert Motion through Blender, the Motion Library and Prepare Motion Source) runs no model and starts no backend, so
it has neither.  Its frozen target instead binds what the operator controls and what could change the outcome:

* ``blender``: the executable's path, SHA-256 and version (the converter is an owner-installed program, so its identity is
  part of the evidence);
* ``asset_directory`` and ``source_assets``: the test-owned folder and the SHA-256 of **every** file in it, so a changed,
  added or removed original is a HOLD before anything runs;
* ``inputs.render_profile`` and ``inputs.frame_window``: the Batch Convert settings and the Prepare Motion Source window;
* ``inputs.driving_workflow``: the workflow that receives the driving clip (hand-off and preparation read its contract; the
  workflow is never run).

Offline-ness belongs to the **journey definition** (``definitions.OFFLINE_KEYS``), never to a target flag: a GPU journey
whose target says ``"lane": "offline"`` is still refused for lacking its runtime and model.  Nothing here weakens a gate
for a GPU journey.  Pure logic: no display, no Blender, no network, no ``src`` import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.operator_journey.golden.definitions import OFFLINE_KEYS

LANE = "offline"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
#: Keys the Batch Convert dialog exposes as "Settings for every file"; ``frames`` and ``start_seconds`` are free entries.
RENDER_PROFILE_KEYS = (
    "profile_policy",
    "camera",
    "camera_mode",
    "root_motion",
    "orientation",
    "start_seconds",
    "frames",
)
WINDOW_KEYS = ("start", "end", "convert")
#: The driving-video workflow whose contract Prepare Motion Source applies (never executed by this lane).
DRIVING_WORKFLOW = {"id": "wan22_fun_control_5b_canny_i2v_v1", "version": "1.0.0"}
DEFAULT_RENDER_PROFILE: dict[str, Any] = {
    "profile_policy": "auto",
    "camera": "front",
    "camera_mode": "static",
    "root_motion": "preserve",
    "orientation": "portrait",
    "start_seconds": "0",
    "frames": 17,
}
DEFAULT_FRAME_WINDOW: dict[str, Any] = {"start": 0.0, "end": None, "convert": False}


def is_offline(journey_key: str) -> bool:
    """True only for a journey whose *definition* is offline (never decided by the target)."""

    return journey_key in OFFLINE_KEYS


def default_inputs() -> dict[str, Any]:
    """The operator inputs ``build_plan`` freezes into an offline target when the spec omits them."""

    return {
        "render_profile": dict(DEFAULT_RENDER_PROFILE),
        "frame_window": dict(DEFAULT_FRAME_WINDOW),
        "driving_workflow": dict(DRIVING_WORKFLOW),
    }


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.match(value))


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def offline_problems(journey: str, target: dict[str, Any]) -> list[str]:
    """Every way an offline target is malformed (structural only; nothing is observed)."""

    problems: list[str] = []
    if target.get("lane") != LANE:
        problems.append(f'{journey}: an offline journey must declare "lane": "offline"')
    if target.get("runtime") or target.get("model"):
        problems.append(
            f"{journey}: an offline journey declares no runtime or model (it runs no inference and starts no backend)"
        )
    if int(target.get("job_count") or 0) != 0:
        problems.append(f"{journey}: an offline journey submits no job (job_count must be 0)")
    blender = target.get("blender")
    if not isinstance(blender, dict) or not (
        str(blender.get("executable") or "").strip()
        and str(blender.get("version") or "").strip()
        and _is_sha256(blender.get("sha256"))
    ):
        problems.append(
            f"{journey}: the Blender identity (executable, version and SHA-256) is required"
        )
    directory = str(target.get("asset_directory") or "").strip()
    if not directory:
        problems.append(f"{journey}: the asset directory is required")
    assets = target.get("source_assets")
    if not isinstance(assets, list) or not assets:
        problems.append(f"{journey}: the SHA-256 of every source asset is required")
    else:
        seen: set[str] = set()
        for asset in assets:
            path = str(asset.get("path") or "") if isinstance(asset, dict) else ""
            if not path or not _is_sha256(asset.get("sha256")):
                problems.append(f"{journey}: every source asset needs a path and a SHA-256")
                break
            if path in seen:
                problems.append(f"{journey}: source asset {path} is listed twice")
                break
            seen.add(path)
            if directory and not _inside(path, directory):
                problems.append(f"{journey}: source asset {path} is outside the asset directory")
                break
    problems += _input_problems(journey, target.get("inputs"))
    return problems


def _inside(path: str, directory: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(directory).resolve())
        return True
    except (ValueError, OSError):
        return False


def _input_problems(journey: str, inputs: Any) -> list[str]:
    if not isinstance(inputs, dict):
        return [f"{journey}: the plan does not bind the render profile and frame window"]
    problems: list[str] = []
    profile = inputs.get("render_profile")
    if not isinstance(profile, dict):
        problems.append(f"{journey}: inputs.render_profile is required")
    else:
        missing = [k for k in RENDER_PROFILE_KEYS if profile.get(k) in (None, "")]
        if missing:
            problems.append(f"{journey}: render_profile missing: {', '.join(missing)}")
        frames = profile.get("frames")
        if "frames" not in missing and (
            isinstance(frames, bool) or not isinstance(frames, int) or frames < 1
        ):
            problems.append(f"{journey}: render_profile.frames must be a positive integer")
        start = _number(profile.get("start_seconds"))
        if "start_seconds" not in missing and (start is None or start < 0):
            problems.append(f"{journey}: render_profile.start_seconds must be a number >= 0")
    window = inputs.get("frame_window")
    if not isinstance(window, dict) or "start" not in window or "convert" not in window:
        problems.append(f"{journey}: inputs.frame_window needs start, end and convert")
    else:
        start = _number(window.get("start"))
        end = window.get("end")
        if start is None or start < 0:
            problems.append(f"{journey}: frame_window.start must be a number >= 0")
        if end is not None and (
            _number(end) is None or (start is not None and _number(end) <= start)
        ):
            problems.append(f"{journey}: frame_window.end must be null or greater than start")
        if not isinstance(window.get("convert"), bool):
            problems.append(f"{journey}: frame_window.convert must be true or false")
    workflow = inputs.get("driving_workflow")
    if not (isinstance(workflow, dict) and workflow.get("id") and workflow.get("version")):
        problems.append(f"{journey}: inputs.driving_workflow needs an id and a version")
    return problems


@dataclass(frozen=True, slots=True)
class OfflineInputs:
    """The frozen values an offline journey reads: nothing operator-controlled comes from a constant in the code."""

    blender_executable: str
    blender_version: str
    blender_sha256: str
    asset_directory: Path
    assets: dict[str, str]  # path -> SHA-256
    render_profile: dict[str, Any]
    window_start: str
    window_end: str
    window_convert: bool
    workflow_id: str
    workflow_version: str


def read_offline_inputs(target: dict[str, Any]) -> OfflineInputs:
    """Parse a *valid* offline target; ``ValueError`` (naming every problem) otherwise."""

    problems = offline_problems("motion-assets", target)
    if problems:
        raise ValueError("; ".join(problems))
    inputs = target["inputs"]
    window = inputs["frame_window"]
    blender = target["blender"]
    return OfflineInputs(
        blender_executable=str(blender["executable"]),
        blender_version=str(blender["version"]),
        blender_sha256=str(blender["sha256"]),
        asset_directory=Path(str(target["asset_directory"])),
        assets={str(a["path"]): str(a["sha256"]) for a in target["source_assets"]},
        render_profile=dict(inputs["render_profile"]),
        window_start=_text(window["start"]),
        window_end="" if window.get("end") is None else _text(window["end"]),
        window_convert=bool(window["convert"]),
        workflow_id=str(inputs["driving_workflow"]["id"]),
        workflow_version=str(inputs["driving_workflow"]["version"]),
    )


def _text(value: Any) -> str:
    number = float(value)
    return str(int(number)) if number == int(number) else repr(number)


def _key(path: str | Path) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def asset_listing(directory: str | Path) -> list[str]:
    """Every file under the asset directory (recursive), as sorted resolved paths; empty when it is not a directory.

    Read-only.  Frozen into the plan's environment so an added or removed file is a HOLD, not a silent change."""

    root = Path(str(directory))
    if not str(directory).strip() or not root.is_dir():
        return []
    return sorted(_key(p) for p in root.rglob("*") if p.is_file())


def directory_problems(
    frozen_assets: dict[str, str], live_files: dict[str, str | None]
) -> list[str]:
    """Differences between the frozen asset list and the live directory (any difference is a HOLD).

    ``live_files`` maps every file now under the asset directory to its SHA-256 (``None`` when unreadable)."""

    planned = {_key(path): sha for path, sha in frozen_assets.items()}
    live_by_key = {_key(path): sha for path, sha in live_files.items()}
    problems: list[str] = []
    for path, sha in sorted(planned.items()):
        if path not in live_by_key:
            problems.append(f"{path}: frozen but no longer in the asset directory")
        elif live_by_key[path] != sha:
            problems.append(f"{path}: SHA-256 changed since the plan was frozen")
    for path in sorted(set(live_by_key) - set(planned)):
        problems.append(f"{path}: present in the asset directory but not in the frozen plan")
    return problems


__all__ = [
    "asset_listing",
    "DEFAULT_FRAME_WINDOW",
    "DEFAULT_RENDER_PROFILE",
    "DRIVING_WORKFLOW",
    "LANE",
    "OfflineInputs",
    "RENDER_PROFILE_KEYS",
    "WINDOW_KEYS",
    "default_inputs",
    "directory_problems",
    "is_offline",
    "offline_problems",
    "read_offline_inputs",
]
