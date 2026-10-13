"""Bounded safetensors-header evidence for ControlNet weights (PR-IMG-CNET-210).

A ControlNet only works with the checkpoint family it was trained for. Whether a *file name* says "sdxl" is a hint, not
evidence, so this module reads the one bounded safetensors header (``read_tensor_table``: no tensor, no hash, no pickle)
and classifies the architecture family from tensor shapes alone:

* the cross-attention key projection (``...attn2.to_k.weight``) has the text-context width as its second dimension:
  SD 1.x = 768, SD 2.x = 1024, SDXL = 2048;
* SDXL's added-conditioning embedding takes a 2816-wide input (``label_emb.0.0.weight`` in the original layout,
  ``add_embedding.linear_1.weight`` in the diffusers layout).

Anything else (T2I adapters, LLLite, non-safetensors, unreadable headers) is ``unverified``: never guessed. This is
observational evidence, not a model qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.assets.checkpoint_structure import read_tensor_table

STATUS_SDXL = "sdxl"
STATUS_NOT_SDXL = "not_sdxl"
STATUS_UNVERIFIED = "unverified"

_WEIGHT_SUFFIXES = (".safetensors", ".sft", ".pth", ".pt", ".ckpt", ".bin")
_SDXL_CONTEXT = 2048
_SDXL_ADM = 2816
_OTHER_CONTEXTS = frozenset({768, 1024})
_ADM_KEYS = ("label_emb.0.0.weight", "add_embedding.linear_1.weight")


@dataclass(frozen=True, slots=True)
class ControlNetEvidence:
    status: str
    #: Short, content-free reason (shape facts only; never a path).
    detail: str
    #: ``"safetensors_header"`` when a header was read, else ``"none"`` (file not found, unsupported container, ...).
    source: str = "none"


def name_key(value: str) -> str:
    """Case-insensitive identity of a ControlNet model name: no path, no ``[hash]`` suffix, no weight extension."""

    base = str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if base.endswith("]") and " [" in base:
        base = base[: base.rindex(" [")]
    lowered = base.strip().lower()
    for suffix in _WEIGHT_SUFFIXES:
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def classify_controlnet_shapes(shapes: dict[str, list[int]]) -> ControlNetEvidence:
    """Family evidence from tensor shapes alone (pure)."""

    contexts = {
        shape[1]
        for name, shape in shapes.items()
        if name.endswith("attn2.to_k.weight") and len(shape) == 2
    }
    adm = {
        shape[1]
        for name, shape in shapes.items()
        if name.endswith(_ADM_KEYS) and len(shape) == 2
    }
    if _SDXL_CONTEXT in contexts or _SDXL_ADM in adm:
        if contexts - {_SDXL_CONTEXT} or (adm and adm != {_SDXL_ADM}):
            return ControlNetEvidence(STATUS_UNVERIFIED, "contradictory SDXL markers", "safetensors_header")
        return ControlNetEvidence(STATUS_SDXL, "SDXL cross-attention/conditioning widths", "safetensors_header")
    if contexts and contexts <= _OTHER_CONTEXTS and not adm:
        width = ", ".join(str(item) for item in sorted(contexts))
        return ControlNetEvidence(
            STATUS_NOT_SDXL, f"text-context width {width} (SD 1.x/2.x family)", "safetensors_header"
        )
    return ControlNetEvidence(STATUS_UNVERIFIED, "no recognizable SD architecture markers", "safetensors_header")


def inspect_controlnet_file(path: Path) -> ControlNetEvidence:
    """Header-only family evidence for one ControlNet weight file (never raises)."""

    if path.suffix.lower() not in {".safetensors", ".sft"}:
        return ControlNetEvidence(STATUS_UNVERIFIED, "not a safetensors file; architecture cannot be read safely")
    try:
        shapes, _dtypes, _metadata = read_tensor_table(path)
    except (OSError, ValueError):
        return ControlNetEvidence(STATUS_UNVERIFIED, "safetensors header is unreadable")
    return classify_controlnet_shapes(shapes)


def locate_controlnet_file(controlnet_root: Path | None, model_name: str) -> Path | None:
    """The single weight file in the ControlNet folder a model name identifies, or ``None`` (absent or ambiguous)."""

    key = name_key(model_name)
    if controlnet_root is None or not key or not controlnet_root.is_dir():
        return None
    matches = [
        path
        for path in controlnet_root.rglob("*")
        if path.suffix.lower() in _WEIGHT_SUFFIXES and name_key(path.name) == key and path.is_file()
    ]
    return matches[0] if len(matches) == 1 else None


def controlnet_evidence_for_name(controlnet_root: Path | None, model_name: str) -> ControlNetEvidence:
    path = locate_controlnet_file(controlnet_root, model_name)
    if path is None:
        return ControlNetEvidence(
            STATUS_UNVERIFIED, "the weight file was not found (or is ambiguous) in models/ControlNet"
        )
    return inspect_controlnet_file(path)


@dataclass(frozen=True, slots=True)
class ControlNetModelOption:
    """One installed ControlNet weight the editor may offer (a stat-only listing: no hashing, header read on demand)."""

    name: str
    evidence: ControlNetEvidence


def list_controlnet_models(controlnet_root: Path | None, *, limit: int = 500) -> list[ControlNetModelOption]:
    """Installed ControlNet weights with header-derived SDXL evidence, sorted by name (worker-side)."""

    if controlnet_root is None or not controlnet_root.is_dir():
        return []
    paths = sorted(
        (
            path
            for path in controlnet_root.rglob("*")
            if path.suffix.lower() in _WEIGHT_SUFFIXES and path.is_file()
        ),
        key=lambda item: str(item).lower(),
    )[:limit]
    return [ControlNetModelOption(path.stem, inspect_controlnet_file(path)) for path in paths]


__all__ = [
    "ControlNetEvidence",
    "ControlNetModelOption",
    "STATUS_NOT_SDXL",
    "STATUS_SDXL",
    "STATUS_UNVERIFIED",
    "classify_controlnet_shapes",
    "controlnet_evidence_for_name",
    "inspect_controlnet_file",
    "list_controlnet_models",
    "locate_controlnet_file",
    "name_key",
]
