"""PR-IMG-COMFY-381: resolve the SDXL checkpoint, LoRA and VAE files StableNew selected to files ComfyUI can load.

Forge and ComfyUI keep separate model folders, so a name that is valid for Forge says nothing about ComfyUI. StableNew
never downloads, copies or moves a model. A file is accepted only when **both** hold:

1. the ``AssetRegistry`` (the single local identity authority) knows the model by name and has its SHA-256; and
2. a file in a folder the managed ComfyUI searches (its own ``models/<kind>`` or an ``extra_model_paths`` entry) has that
   exact SHA-256 (a file that is the very file the registry scanned reuses the registry's cached hash; any other file is
   hashed once per size/mtime).

The fix for a missing file is configuration, and the message says so: add the Forge model folder to ComfyUI's
``extra_model_paths.yaml``. Nothing here starts a runtime.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.image_backends.comfy_sdxl_profile import SdxlComfyError
from src.image_backends.forge_klein_profile import _model_key

_SUFFIXES = (".safetensors", ".sft", ".ckpt", ".pt", ".pth")
#: asset kind -> (``AssetKind`` value, Comfy model folder kind)
_KINDS: Mapping[str, tuple[str, str]] = {
    "checkpoint": ("checkpoint", "checkpoints"),
    "lora": ("lora", "loras"),
    "vae": ("vae", "vae"),
}
EXTRA_FOLDER_KINDS = ("checkpoints", "loras")


class SdxlAssetError(SdxlComfyError):
    """A selected model cannot be resolved to a registry-verified file ComfyUI can load."""


@dataclass(frozen=True, slots=True)
class ResolvedModelFile:
    kind: str
    requested: str
    #: The file name as a ``/object_info`` combo lists it (relative to the Comfy model folder, forward slashes).
    comfy_name: str
    path: str
    sha256: str

    def evidence(self) -> dict[str, str]:
        return {
            "requested": self.requested,
            "comfy_name": self.comfy_name,
            "path": self.path,
            "sha256": self.sha256,
        }


RegistryShas = Callable[[str, str], tuple[dict[str, Path], dict[Path, str]]]


def _registry_view(registry: Any, kind: str, key: str) -> tuple[set[str], dict[str, str]]:
    """(registry SHA-256s recorded for this model name, {resolved scanned path: its verified SHA-256})."""

    from src.assets import AssetKind

    asset_kind = AssetKind(_KINDS[kind][0])
    shas: set[str] = set()
    verified: dict[str, str] = {}
    for record in registry.cached_snapshot().records_for(asset_kind):
        for location in record.locations:
            if location.kind is not asset_kind or _model_key(location.path.name) != key:
                continue
            shas.add(str(record.sha256))
            try:
                known = registry.verified_sha256(location.path)
            except Exception:  # noqa: BLE001 - an unverifiable cache entry is simply not trusted
                known = None
            if known:
                verified[str(Path(location.path).resolve()).lower()] = str(known)
    return shas, verified


class SdxlAssetResolver:
    """Resolve names to registry-verified ComfyUI files; every collaborator is injectable for hermetic tests."""

    def __init__(
        self,
        *,
        registry: Any = None,
        folders: Callable[[], Mapping[str, Sequence[Path]]] | None = None,
        hasher: Callable[[Path], str] | None = None,
    ) -> None:
        self._registry = registry
        self._folders = folders
        self._hasher = hasher

    def _registry_obj(self) -> Any:
        if self._registry is None:
            from src.assets import AssetRegistry

            self._registry = AssetRegistry()
        return self._registry

    def _model_folders(self) -> Mapping[str, Sequence[Path]]:
        if self._folders is not None:
            return self._folders()
        from src.image_backends.comfy_image_readiness import comfy_model_folders

        return comfy_model_folders(EXTRA_FOLDER_KINDS)

    def _hash(self, path: Path) -> str:
        if self._hasher is not None:
            return self._hasher(path)
        from src.image_backends.comfy_image_readiness import cached_sha256

        return cached_sha256(path)

    def resolve(self, kind: str, name: str) -> ResolvedModelFile:
        if kind not in _KINDS:
            raise ValueError(f"unknown model kind {kind!r}")
        folder_kind = _KINDS[kind][1]
        key = _model_key(name)
        label = {"checkpoint": "checkpoint", "lora": "LoRA", "vae": "VAE"}[kind]
        if not key:
            raise SdxlAssetError(f"A {label} name is required")
        try:
            shas, verified = _registry_view(self._registry_obj(), kind, key)
        except Exception as exc:  # noqa: BLE001 - absent evidence is a refusal, never a guess
            raise SdxlAssetError(
                f"The asset registry could not be read for {label} '{name}': {exc}"
            ) from exc
        if not shas:
            raise SdxlAssetError(
                f"{label} '{name}' is not in the asset registry, so StableNew cannot verify it for ComfyUI. "
                "Scan the model folders first."
            )
        if len(shas) > 1:
            raise SdxlAssetError(
                f"{label} '{name}' matches several different files in the asset registry; rename one so the name is unique."
            )
        (sha,) = shas
        try:
            roots = list(dict.fromkeys(Path(p) for p in self._model_folders().get(folder_kind, ())))
        except (OSError, ValueError) as exc:
            raise SdxlAssetError(f"ComfyUI's model folders cannot be read: {exc}") from exc
        candidates: list[tuple[Path, Path]] = []
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if (
                    path.is_file()
                    and path.suffix.lower() in _SUFFIXES
                    and _model_key(path.name) == key
                ):
                    candidates.append((root, path))
        for root, path in candidates:
            known = verified.get(str(path.resolve()).lower())
            try:
                actual = known or self._hash(path)
            except OSError:
                continue
            if actual == sha:
                comfy_name = str(path.relative_to(root)).replace(os.sep, "/")
                return ResolvedModelFile(kind, name, comfy_name, str(path), sha)
        searched = ", ".join(str(root) for root in roots) or f"no {folder_kind} folder"
        found = (
            f"{len(candidates)} file(s) with that name have a different SHA-256"
            if candidates
            else "no file with that name"
        )
        raise SdxlAssetError(
            f"ComfyUI cannot load {label} '{name}': {found} in its {folder_kind} folders ({searched}). StableNew never "
            f"copies models; add the folder holding the registry's file to ComfyUI's extra_model_paths.yaml "
            f"({folder_kind}), or switch the Image backend to Forge."
        )

    def resolve_all(
        self, checkpoint: str, loras: Sequence[str], vae: str
    ) -> tuple[ResolvedModelFile, tuple[ResolvedModelFile, ...], ResolvedModelFile | None]:
        return (
            self.resolve("checkpoint", checkpoint),
            tuple(self.resolve("lora", name) for name in loras),
            self.resolve("vae", vae) if vae else None,
        )


__all__ = ["EXTRA_FOLDER_KINDS", "ResolvedModelFile", "SdxlAssetError", "SdxlAssetResolver"]
