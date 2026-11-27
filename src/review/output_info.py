"""NAME-INFO: what "More info" says about one output, for the phone and the desktop Review.

Derived read-only from the file's own embedded metadata, its run manifest and the job's immutable NJR snapshot; names
and stage paths come from ``src/pipeline/output_naming.py``. A reprocess or clip job has no prompt pack of its own, so
the pack and prompt are taken from the job of its input image, a few hops back at most. Nothing is written, every read
is bounded, and no path is ever part of the result.

Blocking file and database work: call it from a worker, never from Tk.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.pipeline.output_naming import (
    RecordedNaming,
    model_short_name,
    recorded_naming,
    stage_ids,
    stage_text,
    workflow_short_name,
)
from src.utils.checkpoint_identity import checkpoint_stem
from src.utils.image_metadata import extract_embedded_metadata

log = logging.getLogger(__name__)

#: Read errors that leave a field out; anything else is a defect and is raised.
_UNREADABLE = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    RecursionError,
    sqlite3.Error,
)
_MANIFEST_LIMIT = 8 * 1024 * 1024
_IMAGE_LIMIT = 64 * 1024 * 1024
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
#: How far back a reprocess or clip looks for the job that had the prompt pack.
MAX_HOPS = 4
_SEGMENT_SUFFIX = re.compile(r"_seg\d+$")

#: The fields of an output's info, in the order they are shown.
INFO_FIELDS = (
    "stage_path",
    "model",
    "model_name",
    "pack",
    "prompt_number",
    "variant",
    "made_at",
    "seed",
    "batch",
)

BatchIdentity = Callable[[Any], Mapping[str, Any] | None]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _image_payload(path: Path) -> Mapping[str, Any]:
    try:
        if (
            path.suffix.lower() not in _IMAGE_SUFFIXES
            or not 0 < path.stat().st_size <= _IMAGE_LIMIT
        ):
            return {}
        read = extract_embedded_metadata(path)
    except _UNREADABLE:
        return {}
    return _mapping(read.payload) if read.status == "ok" else {}


def _run_manifest(path: Path) -> Mapping[str, Any]:
    """``<run folder>/manifests/<file stem>.json``; the run folder is the file's folder or the one above it."""

    for folder in (path.parent, path.parent.parent):
        try:
            candidate = folder / "manifests" / f"{path.stem}.json"
            if candidate.is_file() and candidate.stat().st_size <= _MANIFEST_LIMIT:
                return _mapping(json.loads(candidate.read_bytes()))
        except _UNREADABLE:
            log.debug("Output info could not read a run manifest")
    return {}


def _recorded_job_id(value: Any, depth: int = 0) -> str:
    if depth < 6 and isinstance(value, Mapping):
        own = value.get("job_id")
        if isinstance(own, str) and own:
            return own
        for inner in value.values():
            if found := _recorded_job_id(inner, depth + 1):
                return found
    return ""


def _seed_text(*values: Any) -> str:
    for value in values:
        text = str(value).strip() if value is not None and not isinstance(value, bool) else ""
        if re.fullmatch(r"[0-9]{1,19}", text):
            return text  # -1 means "random" and says nothing about this output
    return ""


def _enabled_stages(job: Mapping[str, Any]) -> tuple[str, ...]:
    stages = job.get("stages")
    listed = stages if isinstance(stages, (list, tuple)) else []
    return stage_ids(
        stage.get("stage_type")
        for stage in listed
        if isinstance(stage, Mapping) and stage.get("enabled", True)
    )


def _is_svd(job: Mapping[str, Any]) -> bool:
    stages = job.get("stages")
    return any(
        _mapping(stage).get("stage_type") == "svd_native"
        for stage in (stages if isinstance(stages, (list, tuple)) else [])
    )


def _is_storyboard(job: Mapping[str, Any]) -> bool:
    stages = job.get("stages")
    for stage in stages if isinstance(stages, (list, tuple)) else []:
        plan = _mapping(_mapping(_mapping(stage).get("extra")).get("sequence_metadata"))
        if plan.get("storyboard"):
            return True
    config = _mapping(_mapping(job.get("workload")).get("config"))
    return any(
        _mapping(_mapping(section).get("sequence_metadata")).get("storyboard")
        for section in config.values()
        if isinstance(section, Mapping)
    )


def _pack_of(job: Mapping[str, Any]) -> tuple[str, int | None, int | None] | None:
    """``(pack, prompt number, variant)`` when this job had a prompt pack of its own."""

    source = _mapping(job.get("source"))
    provenance = _mapping(job.get("provenance"))
    if source.get("kind") == "prompt_pack":
        pack = str(source.get("display_name") or source.get("id") or "")
        row = source.get("row_index")
        variant = provenance.get("variant_index")
    else:
        learning = _mapping(_mapping(provenance.get("metadata")).get("learning"))
        chosen = _mapping(learning.get("prompt_source"))
        if chosen.get("prompt_source") != "pack":
            return None
        pack = str(chosen.get("selected_prompt_pack_name") or "")
        row = chosen.get("selected_prompt_index")
        variant = _mapping(provenance.get("learning_context")).get("variant_index")
    if not pack:
        return None
    return (
        pack,
        int(row or 0) + 1 if isinstance(row, (int, type(None))) else None,
        int(variant) + 1 if isinstance(variant, int) else None,
    )


def _job_model(job: Mapping[str, Any]) -> str:
    stages = job.get("stages")
    for stage in stages if isinstance(stages, (list, tuple)) else []:
        if model := str(_mapping(stage).get("model") or ""):
            return model
    config = _mapping(_mapping(job.get("workload")).get("config"))
    for section in (config, _mapping(config.get("txt2img")), _mapping(config.get("img2img"))):
        if model := str(section.get("model") or section.get("sd_model_checkpoint") or ""):
            return model
    return ""


def _input_path(job: Mapping[str, Any], manifest: Mapping[str, Any]) -> Path | None:
    paths = _mapping(job.get("workload")).get("input_image_paths")
    first = paths[0] if isinstance(paths, (list, tuple)) and paths else None
    text = str(manifest.get("source_image_path") or first or "")
    return Path(text) if text else None


def info_rows(info: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The labelled lines of an info mapping, as the desktop shows them (the phone's ``moreinfo.js`` mirrors them)."""

    model, full = str(info.get("model") or ""), str(info.get("model_name") or "")
    prompt = ", ".join(
        f"{label} {info[key]}"
        for key, label in (("prompt_number", "prompt"), ("variant", "variant"))
        if info.get(key)
    )
    made = str(info.get("made_at") or "")
    if made:
        made = (
            datetime.fromisoformat(made.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )
    rows = (
        ("Path", info.get("stage_path")),
        ("Model", f"{model} ({full})" if model and full and model != full else full or model),
        ("Prompt pack", info.get("pack")),
        ("Prompt", prompt),
        ("Made", made),
        ("Seed", info.get("seed")),
        ("Batch", info.get("batch")),
    )
    return [(name, str(value)) for name, value in rows if value]


class OutputDescriber:
    """Describes outputs; ``repository`` is the job repository (read only) and may be absent."""

    def __init__(
        self, repository: Any = None, *, batch_identity: BatchIdentity | None = None
    ) -> None:
        self._repository = repository
        self._batch_identity = batch_identity

    def _job(self, job_id: str) -> Mapping[str, Any]:
        job_id = _SEGMENT_SUFFIX.sub("", str(job_id or ""))
        if not job_id or self._repository is None:
            return {}
        try:
            snapshot = _mapping(getattr(self._repository.get_job(job_id), "snapshot", None))
        except _UNREADABLE:
            log.debug("Output info could not read a job snapshot")
            return {}
        return _mapping(snapshot.get("normalized_job")) or snapshot

    def _batch_name(self, job: Mapping[str, Any]) -> str:
        if self._batch_identity is None or not job:
            return ""
        batch = self._batch_identity(job)
        name = batch.get("name") if batch else None
        return name if isinstance(name, str) else ""

    def _lineage_pack(
        self, job: Mapping[str, Any], source: Path | None
    ) -> tuple[str, int | None, int | None] | None:
        seen: set[str] = set()
        for _ in range(MAX_HOPS):
            if job and (found := _pack_of(job)):
                return found
            parent = str(_mapping(job.get("source")).get("parent_job_id") or "")
            if not parent and source is not None:
                parent = recorded_naming(_image_payload(source)).job_id
            if not parent or parent in seen:
                break
            seen.add(parent)
            job = self._job(parent)
            source = _input_path(job, {}) if job else None
            if not job:
                break
        return None

    def describe(
        self,
        path: Path,
        *,
        kind: str,
        made_at: datetime | None = None,
        model: str = "",
        workflow: str = "",
        seed: Any = None,
    ) -> dict[str, Any]:
        """The output's info fields (``INFO_FIELDS``); what is unknown is left out. ``model``, ``workflow`` and
        ``seed`` are what the caller already knows from the Output Library."""

        manifest = _run_manifest(path)
        payload = _image_payload(path) if kind == "image" else {}
        recorded = recorded_naming(payload)
        job_id = recorded.job_id or _recorded_job_id(manifest)
        job = self._job(job_id)
        source = _input_path(job, manifest)
        workflow = str(manifest.get("workflow_id") or workflow or "")
        if kind == "video":
            info = self._clip(job, manifest, source, workflow, model)
        else:
            info = self._image(job, recorded, model)
        if pack := self._lineage_pack(job, source):
            info["pack"], info["prompt_number"], info["variant"] = pack
        else:
            carried = (
                recorded
                if recorded.pack or source is None
                else recorded_naming(_image_payload(source))
            )
            if carried.pack:
                info["pack"] = carried.pack
                info["prompt_number"], info["variant"] = carried.prompt_number, carried.variant
        if made_at is not None:
            info["made_at"] = (
                made_at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
            )
        info["seed"] = _seed_text(
            manifest.get("actual_seed"),
            _mapping(payload.get("seeds")).get("final_seed"),
            _mapping(payload.get("generation")).get("seed"),
            manifest.get("seed"),
            seed,
            _mapping(job.get("provenance")).get("seed"),
        )
        info["batch"] = self._batch_name(job)
        return {name: info[name] for name in INFO_FIELDS if info.get(name)}

    @staticmethod
    def _image(job: Mapping[str, Any], recorded: RecordedNaming, model: str) -> dict[str, Any]:
        name = recorded.model or model or _job_model(job)
        return {
            "stage_path": stage_text(recorded.stages or _enabled_stages(job)),
            "model": model_short_name(name),
            "model_name": checkpoint_stem(name) if model_short_name(name) else "",
        }

    def _clip(
        self,
        job: Mapping[str, Any],
        manifest: Mapping[str, Any],
        source: Path | None,
        workflow: str,
        model: str,
    ) -> dict[str, Any]:
        stages = _enabled_stages(job)
        if "movie" in stages:
            return {"stage_path": stage_text(["movie"])}
        if not workflow and (manifest.get("model_id") or _is_svd(job)):
            workflow = "svd_native"
        engine = workflow_short_name(workflow) or model_short_name(model)
        path = "storyboard take" if _is_storyboard(job) else "clip"
        if engine:
            path = f"{path} ({engine})"
        if source is not None:
            made_by = model_short_name(recorded_naming(_image_payload(source)).model)
            if made_by:
                path = f"{path} from {made_by}"
        version = str(manifest.get("workflow_version") or "")
        if workflow == "svd_native":
            full = str(manifest.get("model_id") or model or "SVD")
        else:
            full = f"{workflow} {version}".strip()
        return {"stage_path": path, "model": engine, "model_name": full}


__all__ = ["INFO_FIELDS", "MAX_HOPS", "OutputDescriber", "info_rows"]
