"""The one naming authority for outputs (NAME-INFO): short model names, stage paths and what a file says it was made by.

Every surface that names or describes an output uses this module: the phone's and the desktop's "More info", and the
names of new files. Existing files are never renamed.

A checkpoint's short name is derived from its N12 stem by dropping version, precision and family markers; a video
workflow uses the short map. Both maps are data (``config/output_model_names.json``), with an optional untracked
``config/output_model_names.local.json`` over it so an owner edit never makes the checkout dirty.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.utils.checkpoint_identity import checkpoint_key, checkpoint_stem
from src.utils.image_metadata import extract_embedded_metadata

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
    #: The checkpoint of the latest txt2img or img2img in the chain (else the first named): what made the picture.
    model: str = ""
    job_id: str = ""
    #: The ``prompt_pack`` block, carried forward through reprocess jobs.
    pack: str = ""
    prompt_number: int | None = None
    variant: int | None = None


_GENERATIVE = ("txt2img", "img2img")
#: The embedded metadata key that carries pack, prompt number and variant with a picture.
PACK_BLOCK = "prompt_pack"


def _recorded_model(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in ("", "unknown", "none", "automatic") else text


def _number(value: Any) -> int | None:
    return value if type(value) is int and 1 <= value <= 9999 else None


def pack_block(pack: str, prompt_number: int | None, variant: int | None) -> dict[str, Any]:
    """The ``prompt_pack`` block of an image's metadata; empty when there is no pack."""

    if not pack:
        return {}
    block: dict[str, Any] = {"name": pack}
    if _number(prompt_number):
        block["prompt_number"] = prompt_number
    if _number(variant):
        block["variant"] = variant
    return block


def original_source(config: Any, fallback: Any = None) -> Any:
    """A video job's input as the operator chose it. Source preparation hands the backend a resized copy that carries
    no StableNew record, so who made the picture is read from the original (``source_preparation`` in the job's frozen
    stage config)."""

    for section in config.values() if isinstance(config, Mapping) else ():
        prepared = section.get("source_preparation") if isinstance(section, Mapping) else None
        if isinstance(prepared, Mapping) and prepared.get("original_source_path"):
            return prepared["original_source_path"]
    return fallback


def recorded_naming(payload: Any) -> RecordedNaming:
    """Stages, model, job and pack of an embedded StableNew image payload (empty for any other mapping)."""

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
    current = payload.get("stage") or manifest.get("stage")
    chain = [(entry.get("stage"), entry.get("model")) for entry in entries]
    chain.append((current, generation.get("model") or manifest.get("model")))
    named = [
        (stage_id(stage), found) for stage, model in chain if (found := _recorded_model(model))
    ]
    model = next(
        (found for stage, found in reversed(named) if stage in _GENERATIVE),
        named[0][1] if named else "",
    )
    block = payload.get(PACK_BLOCK)
    block = block if isinstance(block, Mapping) else {}
    return RecordedNaming(
        stage_ids(stage for stage, _model in chain),
        model,
        str(payload.get("job_id") or "").strip(),
        str(block.get("name") or ""),
        _number(block.get("prompt_number")),
        _number(block.get("variant")),
    )


# -- names of new files and folders -----------------------------------------------------------------------------------

#: Longest file stem; the run folder's length can lower it further.
STEM_LIMIT = 96
_STEM_FLOOR = 56
#: Room kept for ``\\manifests\\`` and the longest manifest suffix, under a 250-character path.
_PATH_LIMIT = 250
_PATH_RESERVE = len("/manifests/") + len(".prompt_optimizer_v3.json")
_FOLDER_PACK_LIMIT = 28
_FOLDER_MODEL_LIMIT = 20
_UNSAFE = re.compile(r"[^A-Za-z0-9.+-]+")
#: A file named by ``file_stem`` (its name only): what may be shown to, and uploaded by, another machine.
DESCRIPTIVE_NAME = re.compile(
    r"[0-9]{8}-[0-9]{4}_[A-Za-z0-9._+-]{1,120}\.(png|jpe?g|webp|mp4|webm)"
)


def safe_part(value: Any, limit: int) -> str:
    """One name part: letters, digits, ``.``, ``+`` and ``-`` only, so ``_`` always separates parts."""

    return _UNSAFE.sub("-", str(value or "")).strip("-.")[:limit].rstrip("-.")


def short_id(job_id: Any) -> str:
    """Eight characters that name a job: the start of a hexadecimal id, else a hash of it."""

    text = str(job_id or "").strip()
    head = text.replace("-", "")[:8].lower()
    if len(head) == 8 and re.fullmatch(r"[0-9a-f]{8}", head):
        return head
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def stage_token(names: Iterable[Any]) -> str:
    """``txt2img+adetailer``; a stage repeated in a row is written once with its count."""

    counted: list[tuple[str, int]] = []
    for stage in stage_ids(names):
        if counted and counted[-1][0] == stage:
            counted[-1] = (stage, counted[-1][1] + 1)
        else:
            counted.append((stage, 1))
    return "+".join(stage if times == 1 else f"{stage}x{times}" for stage, times in counted)


@dataclass(frozen=True)
class OutputName:
    """The parts of one new file's name. ``engine`` and ``source_model`` are for clips."""

    started: datetime
    stages: tuple[str, ...]
    job_id: str
    model: str = ""
    pack: str = ""
    prompt_number: int | None = None
    variant: int | None = None
    engine: str = ""
    source_model: str = ""

    def stem(self, *, run_dir: Path | None = None, suffix: str = "") -> str:
        """``{date-time}_{stages}_{model}_{pack}_p{NN}v{NN}_{id}``; a clip reads
        ``{date-time}_clip-{engine}_from-{source model}_{pack}_p{NN}_{id}``. Unknown parts are left out. ``suffix``
        (``_i02``, ``_seg01``) is kept whole, and so are the date, the numbers and the id: long names are shortened
        in the pack and model parts."""

        video = bool(self.engine)
        stages = stage_token(self.stages) or "output"
        if video:
            stages = safe_part(f"{stages}-{self.engine}", 40)
            source = safe_part(self.source_model, 24)
            model = f"from-{source}" if source else ""
        else:
            model = safe_part(self.model, 24)
        numbers = f"p{self.prompt_number:02d}" if self.prompt_number else ""
        if numbers and self.variant and not video:
            numbers += f"v{self.variant:02d}"
        parts = [f"{self.started:%Y%m%d-%H%M}", stages, model, safe_part(self.pack, 32)]
        tail = [numbers, short_id(self.job_id)]
        limit = STEM_LIMIT
        if run_dir is not None:
            room = _PATH_LIMIT - _PATH_RESERVE - len(str(Path(run_dir).absolute()))
            limit = max(_STEM_FLOOR, min(STEM_LIMIT, room))
        limit -= len(suffix)

        def joined() -> str:
            return "_".join(part for part in [*parts, *tail] if part)

        # The pack gives way first, then the model; the stage path only if nothing else is left to shorten.
        for index, floor in ((3, 12), (2, 12), (3, 6), (2, 6), (1, 8)):
            while len(joined()) > limit and len(parts[index]) > floor:
                parts[index] = parts[index][:-1].rstrip("-.+")
        stem = joined()
        return stem + suffix


def run_folder_label(pack: str, model: str, job_id: str = "") -> str:
    """``{pack}_{model}``, plus the job's short id when the folder belongs to this job alone (``job_id``)."""

    parts = [safe_part(pack, _FOLDER_PACK_LIMIT), safe_part(model, _FOLDER_MODEL_LIMIT)]
    if job_id or not any(parts):
        parts.append(short_id(job_id))
    return "_".join(part for part in parts if part)


def read_image_naming(path: Any) -> RecordedNaming:
    """``recorded_naming`` of a file on disk; empty when it is missing, unreadable or has no StableNew record."""

    if not path:
        return RecordedNaming()
    try:
        read = extract_embedded_metadata(Path(path))
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return RecordedNaming()
    return recorded_naming(read.payload) if read.status == "ok" else RecordedNaming()


_VIDEO_STAGES = frozenset({"animatediff", "svd_native", "video_workflow"})


def _enabled_stage_types(njr: Any) -> list[str]:
    return [
        str(stage.stage_type)
        for stage in getattr(njr, "stage_chain", None) or ()
        if getattr(stage, "enabled", True)
    ]


def _job_source(njr: Any) -> Any:
    inputs = getattr(njr, "input_image_paths", None) or ()
    return original_source(getattr(njr, "config", None), inputs[0] if inputs else None)


def _job_checkpoint(njr: Any) -> str:
    config = getattr(njr, "config", None)
    section = config.get("txt2img") if isinstance(config, Mapping) else None
    section = section if isinstance(section, Mapping) else {}
    return _recorded_model(
        section.get("model") or section.get("sd_model_checkpoint") or getattr(njr, "base_model", "")
    )


@dataclass(frozen=True)
class JobOutputNames:
    """The names of one job's new files and its run folder, from its frozen NJR, its input image's own record and the
    run's start time (local). A reprocess or clip job has no pack of its own: it takes its input's."""

    job_id: str
    started: datetime
    pack: str = ""
    prompt_number: int | None = None
    variant: int | None = None
    #: The job's own pack, as opposed to one read from its input.
    own_pack: bool = False
    #: The checkpoint of the job, or of its input when the job only edits it.
    model: str = ""
    earlier_stages: tuple[str, ...] = ()

    @classmethod
    def for_job(cls, njr: Any, started: datetime) -> JobOutputNames:
        given = read_image_naming(_job_source(njr))
        stages = _enabled_stage_types(njr)
        pack = str(getattr(njr, "prompt_pack_name", "") or "")
        generates = any(stage in _GENERATIVE for stage in stages)
        job_model = _job_checkpoint(njr)
        return cls(
            job_id=str(njr.job_id),
            started=started,
            pack=pack or given.pack,
            prompt_number=(getattr(njr, "prompt_pack_row_index", 0) or 0) + 1
            if pack
            else given.prompt_number,
            variant=(getattr(njr, "variant_index", 0) or 0) + 1 if pack else given.variant,
            own_pack=bool(pack),
            model=(job_model or given.model) if generates else (given.model or job_model),
            earlier_stages=tuple(stages),
        )

    def pack_block(self) -> dict[str, Any]:
        return pack_block(self.pack, self.prompt_number, self.variant)

    def folder_label(self, njr: Any) -> str:
        """``{pack}_{model}``; a job without a pack of its own keeps a folder to itself (its short id ends the name).
        A clip's folder names the model of its source picture."""

        stages = set(_enabled_stage_types(njr))
        if stages & _VIDEO_STAGES:
            given = read_image_naming(_job_source(njr))
            config = (getattr(njr, "config", None) or {}).get("video_workflow")
            workflow = config.get("workflow_id") if isinstance(config, Mapping) else None
            model = model_short_name(given.model) or workflow_short_name(
                workflow or ("svd_native" if "svd_native" in stages else "")
            )
        else:
            model = model_short_name(self.model)
        return run_folder_label(self.pack, model, "" if self.own_pack else self.job_id)

    def image_stem(
        self,
        stage: str,
        *,
        input_path: Any = None,
        stage_model: Any = None,
        run_dir: Path | None = None,
        suffix: str = "",
    ) -> str:
        given = read_image_naming(input_path)
        before = given.stages
        if not before and stage in self.earlier_stages:
            before = stage_ids(self.earlier_stages[: self.earlier_stages.index(stage)])
        if stage in _GENERATIVE:
            model = _recorded_model(stage_model) or self.model
        else:
            model = given.model or self.model or _recorded_model(stage_model)
        pack, number, variant = self.pack, self.prompt_number, self.variant
        if not self.own_pack and given.pack:
            pack, number, variant = given.pack, given.prompt_number, given.variant
        return OutputName(
            self.started,
            (*before, stage),
            self.job_id,
            model=model_short_name(model),
            pack=pack,
            prompt_number=number,
            variant=variant,
        ).stem(run_dir=run_dir, suffix=suffix)

    def clip_stem(
        self,
        *,
        workflow_id: Any,
        source_path: Any,
        storyboard: bool = False,
        run_dir: Path | None = None,
        suffix: str = "",
    ) -> str:
        given = read_image_naming(source_path)
        pack, number = (
            (given.pack, given.prompt_number) if given.pack else (self.pack, self.prompt_number)
        )
        return OutputName(
            self.started,
            ("storyboard" if storyboard else "clip",),
            self.job_id,
            pack=pack,
            prompt_number=number,
            engine=workflow_short_name(workflow_id) or "video",
            source_model=model_short_name(given.model),
        ).stem(run_dir=run_dir, suffix=suffix)


__all__ = [
    "CONFIG_DIR",
    "DESCRIPTIVE_NAME",
    "JobOutputNames",
    "OutputName",
    "PACK_BLOCK",
    "RecordedNaming",
    "STAGE_LABELS",
    "STEM_LIMIT",
    "model_names",
    "model_short_name",
    "original_source",
    "pack_block",
    "read_image_naming",
    "recorded_naming",
    "run_folder_label",
    "safe_part",
    "short_id",
    "stage_id",
    "stage_ids",
    "stage_text",
    "stage_token",
    "workflow_short_name",
]
