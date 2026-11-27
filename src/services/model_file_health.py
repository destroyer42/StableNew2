"""DESK-QUICK: one list of every model with missing files.

Read-only and presence-only: it asks whether each pinned file exists (and takes the model picker's own block text),
never hashing, loading, downloading or starting a runtime. A place it cannot look is reported as *not checked*, never
as missing and never as fine. Covered: the checkpoints the picker offers (exact profiles and real picker blocks) and
the newest offered version of every ComfyUI video workflow. Blocking file I/O: call it off the Tk thread.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.checkpoint_identity import checkpoint_key

logger = logging.getLogger(__name__)

#: The ComfyUI model folder each stock loader node reads.
LOADER_FOLDERS = {
    "UNETLoader": "diffusion_models",
    "CLIPLoader": "text_encoders",
    "DualCLIPLoader": "text_encoders",
    "VAELoader": "vae",
    "LoraLoaderModelOnly": "loras",
    "CLIPVisionLoader": "clip_vision",
}
_EXTRA_FOLDER_KINDS = ("loras", "clip_vision")


@dataclass(frozen=True)
class ModelFileProblem:
    kind: str  # "image" or "video"
    model: str
    problems: tuple[str, ...]


@dataclass(frozen=True)
class ModelFileHealth:
    entries: tuple[ModelFileProblem, ...] = ()
    #: What could not be looked at, in operator words.
    unchecked: tuple[str, ...] = ()

    def missing_for(self, model: str) -> tuple[str, ...]:
        key = checkpoint_key(model)
        return tuple(
            problem
            for entry in self.entries
            if entry.kind == "image" and checkpoint_key(entry.model) == key
            for problem in entry.problems
        )

    def lines(self) -> list[str]:
        lines: list[str] = []
        for kind, title in (("image", "Image models"), ("video", "Video workflows")):
            found = [entry for entry in self.entries if entry.kind == kind]
            if found:
                lines.append(f"{title} with missing files:")
                for entry in found:
                    lines.append(f"  {entry.model}")
                    lines.extend(f"    - {problem}" for problem in entry.problems)
                lines.append("")
        if not self.entries:
            lines.extend(["No missing model files found in what could be checked.", ""])
        if self.unchecked:
            lines.append("Not checked:")
            lines.extend(f"  - {note}" for note in self.unchecked)
        return lines


def _profile_modules(name: str) -> tuple[Any, ...]:
    """The separate files an exact Forge profile checkpoint needs, identified by its name."""

    from src.image_backends.forge_klein_profile import is_klein_transformer_name, latest_klein_profile
    from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1, is_zimage_transformer_name

    if is_klein_transformer_name(name):
        return tuple(latest_klein_profile().modules)
    if is_zimage_transformer_name(name):
        return tuple(ZIMAGE_PROFILE_V1.modules)
    return ()


def _image_problems(
    image_models: Iterable[Any], webui_root: Path | None, unchecked: list[str]
) -> list[ModelFileProblem]:
    found: list[ModelFileProblem] = []
    for entry in image_models:
        name = str(getattr(entry, "name", "") or "")
        picker = getattr(entry, "picker", None)
        if not name or getattr(picker, "excluded", False):
            continue
        # The picker's real blocks already name what is missing and where it goes (Qwen-Image, FLUX.1).
        refusal = "" if getattr(picker, "warning", False) else str(getattr(picker, "refusal", ""))
        problems = [refusal] if refusal else []
        modules = () if problems else _profile_modules(name)
        if modules and webui_root is None:
            unchecked.append(f"{name}: the WebUI folder is not known.")
        elif modules and webui_root is not None:
            for asset in modules:
                folder = webui_root / "models" / asset.models_subdir
                if not (folder / asset.filename).is_file():
                    problems.append(f"{asset.filename} is missing; it goes in {folder}")
        if problems:
            found.append(ModelFileProblem("image", name, tuple(problems)))
    return found


def _video_problems(
    specs: Sequence[Any],
    folders: Mapping[str, Sequence[Path]] | None,
    unchecked: list[str],
) -> list[ModelFileProblem]:
    if specs and folders is None:
        unchecked.append("Video workflows: the ComfyUI model folders are not known.")
        return []
    found: list[ModelFileProblem] = []
    for spec in specs:
        model = f"{spec.display_name} {spec.workflow_version}"
        problems: list[str] = []
        for dependency in spec.dependency_specs:
            if dependency.dependency_kind != "model_file" or not dependency.required:
                continue
            folder = LOADER_FOLDERS.get(str(dependency.version_hint).partition(".")[0])
            if folder is None or folders is None or folder not in folders:
                unchecked.append(f"{model}: {dependency.locator} (unknown model folder).")
            elif not any((root / dependency.locator).is_file() for root in folders[folder]):
                problems.append(f"{dependency.locator} is missing from ComfyUI's {folder} folders")
        if problems:
            found.append(ModelFileProblem("video", model, tuple(problems)))
    return found


def find_missing_model_files(
    *,
    image_models: Iterable[Any] = (),
    webui_root: Path | None = None,
    video_specs: Sequence[Any] = (),
    comfy_folders: Mapping[str, Sequence[Path]] | None = None,
) -> ModelFileHealth:
    unchecked: list[str] = []
    entries = _image_problems(image_models, webui_root, unchecked)
    entries += _video_problems(video_specs, comfy_folders, unchecked)
    return ModelFileHealth(tuple(entries), tuple(dict.fromkeys(unchecked)))


def collect_model_file_health(
    image_models: Iterable[Any], webui_root: Path | None
) -> ModelFileHealth:
    """The application's own sources: the offered video workflows and the configured ComfyUI model folders."""

    from src.image_backends.comfy_image_readiness import comfy_model_folders
    from src.video.workflow_registry import (
        build_default_workflow_registry,
        latest_spec_per_workflow,
    )

    specs = latest_spec_per_workflow(
        list(build_default_workflow_registry().list_offerable_specs("comfy"))
    )
    try:
        folders: Mapping[str, Sequence[Path]] | None = comfy_model_folders(
            extra_kinds=_EXTRA_FOLDER_KINDS
        )
    except (OSError, ValueError) as exc:
        logger.info("ComfyUI model folders are unavailable: %s", exc)
        folders = None
    if webui_root is not None and not (webui_root / "models").is_dir():
        webui_root = None
    return find_missing_model_files(
        image_models=image_models,
        webui_root=webui_root,
        video_specs=specs,
        comfy_folders=folders,
    )


__all__ = [
    "LOADER_FOLDERS",
    "ModelFileHealth",
    "ModelFileProblem",
    "collect_model_file_health",
    "find_missing_model_files",
]
