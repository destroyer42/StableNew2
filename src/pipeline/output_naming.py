"""The one naming authority for outputs (NAME-INFO): short model names, stage paths and what a file says it was made by.

Every surface that names or describes an output uses this module: the phone's and the desktop's "More info", and the
names of new files. Existing files are never renamed.

A checkpoint's short name is derived from its N12 stem by dropping version, precision and family markers; a video
workflow uses the short map. Both maps are data (``config/output_model_names.json``), with an optional untracked
``config/output_model_names.local.json`` over it so an owner edit never makes the checkout dirty.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.utils.checkpoint_identity import checkpoint_key, checkpoint_stem

log = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
NAMES_FILE = "output_model_names.json"
LOCAL_NAMES_FILE = "output_model_names.local.json"
SHORT_NAME_LIMIT = 24
_NAMES_LIMIT = 256 * 1024

#: Stage ids a file can have been through, in display form.
STAGE_LABELS = {
    "txt2img": "txt2img",
    "img2img": "img2img",
    "adetailer": "ADetailer",
    "upscale": "upscale",
    "clip": "clip",
    "storyboard": "storyboard",
    "movie": "movie",
}
_STAGE_ALIASES = {
    "upscaled": "upscale",
    "svd_native": "clip",
    "video_workflow": "clip",
    "animatediff": "clip",
    "movie_assembly": "movie",
}
MAX_STAGES = 8

_VERSION = re.compile(r"v\d+(\.\d+)*[a-z]?|\d+\.\d+", re.IGNORECASE)
_PRECISION = re.compile(r"(fp|bf|int)\d+[a-z]*|\d+fp|q\d+(_[a-z0-9]+)?", re.IGNORECASE)
_MARKERS = frozenset({"pruned", "ema", "emaonly", "scaled", "nsfw", "sfw", "sdxl", "xl"})
#: Attached to the end of a name (``photoMomentumSDXLNSFW``, ``ultriumV93``). Family markers only as written in capitals:
#: ``realvisxl`` stays a word.
_ATTACHED = re.compile(r"(SDXL|NSFW|SFW|XL|[Vv]\d+(\.\d+)?)$")


def _read_names(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    try:
        raw = path.read_bytes()
        data = json.loads(raw) if len(raw) <= _NAMES_LIMIT else {}
    except FileNotFoundError:
        return {}, {}
    except (OSError, ValueError, RecursionError):
        log.warning("Output model names in %s could not be read", path.name)
        return {}, {}
    if not isinstance(data, Mapping):
        return {}, {}

    def section(name: str) -> dict[str, str]:
        listed = data.get(name)
        if not isinstance(listed, Mapping):
            return {}
        return {
            str(key): str(value)
            for key, value in listed.items()
            if isinstance(value, str) and value.strip()
        }

    return {checkpoint_key(key): value for key, value in section("checkpoints").items()}, section(
        "workflows"
    )


@lru_cache(maxsize=4)
def model_names(config_dir: Path = CONFIG_DIR) -> tuple[dict[str, str], dict[str, str]]:
    """``(checkpoint key -> short name, workflow id -> short name)``, the local file winning."""

    checkpoints, workflows = _read_names(config_dir / NAMES_FILE)
    local_checkpoints, local_workflows = _read_names(config_dir / LOCAL_NAMES_FILE)
    return {**checkpoints, **local_checkpoints}, {**workflows, **local_workflows}


def _derived(stem: str) -> str:
    tokens = [token for token in re.split(r"[_\s\-()\[\]]+", stem) if token]
    kept = tokens[:1] + [
        token
        for token in tokens[1:]
        if not (
            _VERSION.fullmatch(token) or _PRECISION.fullmatch(token) or token.lower() in _MARKERS
        )
    ]
    words = []
    for token in kept:
        while (found := _ATTACHED.search(token)) and found.start() >= 3:
            token = token[: found.start()].rstrip(".")
        words.append(token)
    if not words:
        return ""
    return words[0] + "".join(word[0].upper() + word[1:] for word in words[1:])


def model_short_name(name: Any) -> str:
    """A checkpoint's short name (``photoMomentumSDXLNSFW_v20`` -> ``photoMomentum``); ``""`` when there is none."""

    key = checkpoint_key(name)
    if not key or key in ("unknown", "none", "automatic"):
        return ""
    known = model_names()[0].get(key)
    if known:
        return known[:SHORT_NAME_LIMIT]
    return _derived(checkpoint_stem(name))[:SHORT_NAME_LIMIT]


def workflow_short_name(workflow_id: Any) -> str:
    """A video workflow's short name (``A14B``, ``Animate-2``); an unlisted id loses its version suffix."""

    text = str(workflow_id or "").strip()
    if not text:
        return ""
    known = model_names()[1].get(text)
    if known:
        return known[:SHORT_NAME_LIMIT]
    return re.sub(r"_v\d+$", "", text).replace("_", "-")[:SHORT_NAME_LIMIT]


def stage_id(name: Any) -> str:
    """The stage id of a recorded or configured stage name, or ``""`` for one that is not a stage."""

    text = str(name or "").strip().lower()
    text = _STAGE_ALIASES.get(text, text)
    return text if text in STAGE_LABELS else ""


def stage_ids(names: Iterable[Any]) -> tuple[str, ...]:
    return tuple(found for name in names if (found := stage_id(name)))[-MAX_STAGES:]


def stage_text(names: Iterable[Any]) -> str:
    """``txt2img → ADetailer → upscale``."""

    return " → ".join(STAGE_LABELS[stage] for stage in stage_ids(names))


@dataclass(frozen=True)
class RecordedNaming:
    """What an image's embedded metadata says made it."""

    stages: tuple[str, ...] = ()
    #: The checkpoint of the first stage in the chain: the one that made the picture.
    model: str = ""
    job_id: str = ""


def _recorded_model(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in ("", "unknown", "none", "automatic") else text


def recorded_naming(payload: Any) -> RecordedNaming:
    """Stages, model and job of an embedded StableNew image payload (empty for any other mapping)."""

    if not isinstance(payload, Mapping):
        return RecordedNaming()
    history = payload.get("stage_history")
    entries = (
        [item for item in history if isinstance(item, Mapping)] if isinstance(history, list) else []
    )
    manifest = payload.get("stage_manifest")
    manifest = manifest if isinstance(manifest, Mapping) else {}
    generation = payload.get("generation")
    generation = generation if isinstance(generation, Mapping) else {}
    stages = stage_ids(
        [*(entry.get("stage") for entry in entries), payload.get("stage") or manifest.get("stage")]
    )
    candidates = [
        *(entry.get("model") for entry in entries),
        generation.get("model"),
        manifest.get("model"),
    ]
    model = next((found for value in candidates if (found := _recorded_model(value))), "")
    return RecordedNaming(stages, model, str(payload.get("job_id") or "").strip())


__all__ = [
    "CONFIG_DIR",
    "RecordedNaming",
    "STAGE_LABELS",
    "model_names",
    "model_short_name",
    "recorded_naming",
    "stage_id",
    "stage_ids",
    "stage_text",
    "workflow_short_name",
]
