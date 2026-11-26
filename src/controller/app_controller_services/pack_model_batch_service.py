"""N5: packs x models batch builder - plan, count, estimate and queue one named batch on the existing path.

One *cell* is one PromptPack compiled for one checkpoint. Every cell compiles through the same
``PromptPackNormalizedJobBuilder`` the Pipeline tab's Preview uses, from the Pipeline tab's working settings with the
checkpoint, the model's saved recipe (``pack_model_batch_recipes``; owner decision 3, which the owner can turn off per
batch) and the batch's ADetailer and upscale choices applied. So the totals the summary shows are the records Queue
submits, not an estimate. Queue goes through ``PipelineController._submit_normalized_jobs`` (sorting by
the canonical checkpoint key, freezing N1 warnings) into ``JobService.submit_njrs``: there is no second queue.

Each queued NJR records its batch in ``provenance.metadata["batch"]`` (``BATCH_SCHEMA``). The stamp is added at Queue
time, so compiling a plan stays deterministic, and it is additive provenance like N1's accepted warnings, so the job's
plan is unchanged. ``batch_identity`` reads it back for the phone review gateway and Learning.

Planning reads pack files and compiles: run it off the Tk thread (``request_batch_plan``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from src.contracts import PackJobEntry
from src.controller.app_controller_services.pack_draft_service import (
    build_pack_config,
    build_pack_entries,
)
from src.controller.app_controller_services.pack_model_batch_recipes import (
    ModelRecipe,
    capture_recipe_context,
    replaced_by_pack,
    resolve_recipes,
    with_recipe,
)
from src.image_backends.model_policy_warnings import shown_model_warnings
from src.pipeline.policy_warnings import PolicyWarning, pending_warnings, with_provenance_metadata
from src.services.duration_stats_service import STAGE_FALLBACK_SECONDS
from src.utils.checkpoint_identity import checkpoint_key

log = logging.getLogger(__name__)

BATCH_METADATA_KEY = "batch"
BATCH_SCHEMA = "stablenew.batch.v1"
#: Above this many images the summary adds a size line (warn, don't block: Queue stays enabled).
LARGE_BATCH_IMAGES = 500
_DEFAULT_STAGE_SECONDS = 30.0

CompileEntries = Callable[[list[PackJobEntry]], list[Any]]


@dataclass(frozen=True)
class BatchRequest:
    """What the owner picked: PromptPacks, checkpoints, a name and optional ADetailer/upscale choices."""

    name: str
    pack_ids: tuple[str, ...]
    models: tuple[str, ...]
    #: ``None`` keeps the Pipeline tab's current choice for that stage.
    adetailer: bool | None = None
    upscale: bool | None = None
    #: ``True``: a model with a saved recipe uses it. ``False``: every model uses the Pipeline tab's settings.
    use_recipes: bool = True

    def problems(self) -> list[str]:
        problems: list[str] = []
        if not self.pack_ids:
            problems.append("Pick at least one PromptPack.")
        if not self.models:
            problems.append("Pick at least one model.")
        keys = [checkpoint_key(model) for model in self.models]
        if len(set(keys)) != len(keys):
            problems.append("The same model is picked twice.")
        return problems


@dataclass(frozen=True)
class BatchBase:
    """The Pipeline tab's working settings, captured on the GUI thread (as Add to Job captures them)."""

    draft_config: Any
    stage_flags: Mapping[str, bool]
    randomizer_metadata: Mapping[str, Any]
    #: ``pack_model_batch_recipes.RecipeContext`` (``None`` when saved recipes cannot be read).
    recipe_context: Any = None


@dataclass(frozen=True)
class PackSource:
    """One PromptPack's rows and saved settings, or why it could not be read."""

    pack_id: str
    pack: Any = None
    pack_config: Mapping[str, Any] | None = None
    rows: tuple[Mapping[str, str], ...] = ()
    problem: str = ""

    @property
    def pack_name(self) -> str:
        return str(getattr(self.pack, "name", "") or self.pack_id)


@dataclass(frozen=True)
class BatchCell:
    """One PromptPack compiled for one checkpoint: its records, or why it is not queued."""

    pack_id: str
    pack_name: str
    model: str
    records: tuple[Any, ...] = ()
    problem: str = ""
    #: Recipe settings the PromptPack's own saved settings replaced in this cell.
    replaced: tuple[str, ...] = ()

    @property
    def jobs(self) -> int:
        return len(self.records)

    @property
    def images(self) -> int:
        return sum(images_for(record) for record in self.records)


@dataclass(frozen=True)
class BatchPlan:
    """Everything the summary shows and Queue submits."""

    request: BatchRequest
    cells: tuple[BatchCell, ...]
    warnings: tuple[PolicyWarning, ...] = ()
    eta_seconds: float = 0.0
    eta_jobs_from_history: int = 0
    recipes: Mapping[str, ModelRecipe] = field(default_factory=dict)

    @property
    def records(self) -> list[Any]:
        return [record for cell in self.cells for record in cell.records]

    @property
    def jobs(self) -> int:
        return sum(cell.jobs for cell in self.cells)

    @property
    def images(self) -> int:
        return sum(cell.images for cell in self.cells)

    @property
    def queueable(self) -> bool:
        return self.jobs > 0

    def summary_lines(self) -> list[str]:
        request = self.request
        lines = [
            f'Batch "{request.name}": {len(request.pack_ids)} pack(s) x {len(request.models)} model(s) = '
            f"{len(self.cells)} combination(s)",
            f"Jobs: {self.jobs}    Images: {self.images}    Estimated time: {format_duration(self.eta_seconds)}",
        ]
        if self.jobs:
            if self.eta_jobs_from_history == self.jobs:
                lines.append("Time estimate from recent runs with the same stages.")
            elif self.eta_jobs_from_history:
                lines.append(
                    f"Time estimate: {self.eta_jobs_from_history} of {self.jobs} job(s) from recent runs with the "
                    "same stages; the rest use per-stage defaults."
                )
            else:
                lines.append(
                    "Time estimate uses per-stage defaults (no recent runs with the same stages)."
                )
        if self.images > LARGE_BATCH_IMAGES:
            lines.append(
                f"This is a large batch ({self.images} images). It still queues as one batch."
            )
        lines.append("")
        if not request.use_recipes:
            lines.append(
                "Settings: the Pipeline tab's settings for every model (saved recipes off)."
            )
        else:
            lines.append("Settings per model (a saved recipe is used where the model has one):")
            lines.extend(
                f"  {(self.recipes.get(model) or ModelRecipe(model)).describe()}"
                for model in request.models
            )
        lines.append("")
        for cell in self.cells:
            label = f"{cell.pack_name} / {cell.model}"
            if cell.problem:
                lines.append(f"  {label}: not queued. {cell.problem}")
            else:
                lines.append(f"  {label}: {cell.jobs} job(s), {cell.images} image(s)")
                if cell.replaced:
                    lines.append(
                        "    The pack's saved settings replace the recipe's "
                        + ", ".join(cell.replaced)
                        + "."
                    )
        if self.warnings:
            lines.append("")
            lines.append("Warnings (queueing accepts them for every job in this batch):")
            lines.extend(f"  - {warning.text()}" for warning in self.warnings)
        return lines


def images_for(record: Any) -> int:
    """Images one NJR generates: its per-request batch size (``loop_count`` is already one NJR per run)."""

    try:
        return max(1, int(getattr(record, "images_per_prompt", 1) or 1))
    except (TypeError, ValueError):
        return 1


def format_duration(seconds: float) -> str:
    minutes = max(0, int(round(float(seconds) / 60.0)))
    if minutes < 1:
        return "under a minute"
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"about {rest} min"
    return f"about {hours} h {rest} min" if rest else f"about {hours} h"


def default_batch_name(
    pack_names: Sequence[str], model_count: int, *, today: date | None = None
) -> str:
    day = (today or date.today()).isoformat()
    if not pack_names:
        return day
    extra = f" +{len(pack_names) - 1}" if len(pack_names) > 1 else ""
    return f"{day} {pack_names[0]}{extra} x {model_count} model(s)"


def with_model(config: Mapping[str, Any], model: str) -> dict[str, Any]:
    """``config`` with every checkpoint field set to ``model`` (the recipe is applied before, in ``with_recipe``)."""

    result = dict(config)
    txt2img = dict(result.get("txt2img") or {})
    txt2img["model"] = model
    if "model_name" in txt2img:
        txt2img["model_name"] = model
    result["txt2img"] = txt2img
    for key in ("model", "model_name"):
        if key in result:
            result[key] = model
    return result


def cell_stage_flags(base: BatchBase, request: BatchRequest) -> dict[str, bool]:
    flags = {str(key): bool(value) for key, value in base.stage_flags.items()}
    if request.adetailer is not None:
        flags["adetailer"] = bool(request.adetailer)
    if request.upscale is not None:
        flags["upscale"] = bool(request.upscale)
    return flags


def compile_cells(
    request: BatchRequest,
    base: BatchBase,
    sources: Sequence[PackSource],
    compile_entries: CompileEntries,
    recipes: Mapping[str, ModelRecipe] | None = None,
) -> tuple[BatchCell, ...]:
    """Compile every pack x model cell; a cell that cannot compile is reported, never dropped silently."""

    recipes = recipes if request.use_recipes and recipes else {}
    flags = cell_stage_flags(base, request)
    randomizer = dict(base.randomizer_metadata)
    cells: list[BatchCell] = []
    for source in sources:
        for model in request.models:
            cell = BatchCell(source.pack_id, source.pack_name, model)
            if source.problem:
                cells.append(replace(cell, problem=source.problem))
                continue
            try:
                config = build_pack_config(
                    deepcopy(with_recipe(base.draft_config, recipes.get(model))),
                    deepcopy(dict(source.pack_config or {})),
                    flags,
                    randomizer,
                )
                entries = build_pack_entries(
                    source.pack_id,
                    source.pack,
                    [dict(row) for row in source.rows],
                    with_model(config, model),
                    dict(flags),
                    dict(randomizer),
                )
                if not entries:
                    cells.append(replace(cell, problem="The pack has no prompts."))
                    continue
                records = tuple(compile_entries(entries))
            except Exception as exc:  # noqa: BLE001 - one cell's refusal is shown and the rest still plan
                log.info("[batch] %s / %s did not compile: %s", source.pack_id, model, exc)
                cells.append(replace(cell, problem=str(exc) or type(exc).__name__))
                continue
            cells.append(
                replace(
                    cell,
                    records=records,
                    problem="" if records else "It compiled no jobs.",
                    replaced=replaced_by_pack(recipes.get(model), records),
                )
            )
    return tuple(cells)


def collect_warnings(records: Iterable[Any]) -> tuple[PolicyWarning, ...]:
    """Every N1 warning the batch's jobs carry, once each (picker-shown model warnings and compile warnings)."""

    found: dict[tuple[str, str], PolicyWarning] = {}
    for record in records:
        for warning in (*shown_model_warnings(record), *pending_warnings(record)):
            found.setdefault(warning.key, warning)
    return tuple(found.values())


def estimate_seconds(records: Iterable[Any], stats: Any = None) -> tuple[float, int]:
    """Summed per-job estimate and how many jobs it took from recent history (the Queue's ETA source)."""

    total = 0.0
    from_history = 0
    for record in records:
        chain = tuple(getattr(record, "stage_chain_labels", ()) or ("txt2img",))
        estimate = None
        if stats is not None:
            try:
                estimate = stats.get_estimate_for_chain(chain)
            except Exception:  # noqa: BLE001 - an unreadable history estimate falls back to defaults
                estimate = None
        if estimate is not None:
            from_history += 1
            total += float(estimate)
        else:
            total += sum(
                STAGE_FALLBACK_SECONDS.get(stage.lower(), _DEFAULT_STAGE_SECONDS) for stage in chain
            )
    return total, from_history


def build_plan(
    request: BatchRequest,
    cells: Sequence[BatchCell],
    stats: Any = None,
    recipes: Mapping[str, ModelRecipe] | None = None,
) -> BatchPlan:
    records = [record for cell in cells for record in cell.records]
    eta, from_history = estimate_seconds(records, stats)
    return BatchPlan(
        request=request,
        cells=tuple(cells),
        warnings=collect_warnings(records),
        eta_seconds=eta,
        eta_jobs_from_history=from_history,
        recipes=dict(recipes or {}) if request.use_recipes else {},
    )


def stamp_batch(plan: BatchPlan, batch_id: str | None = None) -> list[Any]:
    """Every queueable record with its batch identity in provenance (re-frozen; plan and job id unchanged)."""

    identity = batch_id or str(uuid.uuid4())
    queueable = [cell for cell in plan.cells if cell.records]
    stamped: list[Any] = []
    for cell in queueable:
        recipe = plan.recipes.get(cell.model)
        for record in cell.records:
            metadata = dict(record.extra_metadata or {})
            metadata[BATCH_METADATA_KEY] = {
                "schema": BATCH_SCHEMA,
                "batch_id": identity,
                "name": plan.request.name,
                "cell": {
                    "pack_id": cell.pack_id,
                    "pack_name": cell.pack_name,
                    "model": cell.model,
                    "model_key": checkpoint_key(cell.model),
                    "recipe": recipe.provenance()
                    if recipe is not None and recipe.applies
                    else None,
                    "recipe_replaced_by_pack": list(cell.replaced),
                },
                "settings": "model_recipes" if plan.request.use_recipes else "pipeline_tab",
                "cells": len(queueable),
                "jobs": plan.jobs,
            }
            stamped.append(with_provenance_metadata(record, metadata))
    return stamped


def batch_identity(source: Any) -> dict[str, Any] | None:
    """The batch an NJR (or a stored NJR snapshot) was queued in, or ``None``."""

    if isinstance(source, Mapping):
        job = (
            source.get("normalized_job")
            if isinstance(source.get("normalized_job"), Mapping)
            else source
        )
        metadata = (
            (job.get("provenance") or {}).get("metadata") if isinstance(job, Mapping) else None
        )
    else:
        metadata = getattr(source, "extra_metadata", None)
    batch = (metadata or {}).get(BATCH_METADATA_KEY) if isinstance(metadata, Mapping) else None
    if isinstance(batch, Mapping) and batch.get("schema") == BATCH_SCHEMA and batch.get("batch_id"):
        return dict(batch)
    return None


# -- the application seam (AppController); controllers stay at their ratcheted size -----------------------------


def capture_batch_base(app: Any) -> BatchBase:
    """GUI thread: the working settings Add to Job would use."""

    try:
        recipe_context = capture_recipe_context(app)
    except Exception:  # noqa: BLE001 - without the profile service every model uses the Pipeline settings
        log.info("[batch] saved recipes are unavailable", exc_info=True)
        recipe_context = None
    return BatchBase(
        draft_config=app._capture_pack_draft_config(),
        stage_flags=dict(app._build_stage_flags()),
        randomizer_metadata=dict(app._build_randomizer_metadata()),
        recipe_context=recipe_context,
    )


def load_pack_sources(
    app: Any, pack_ids: Sequence[str], read_rows: Callable[[Any], list[dict[str, str]]]
) -> list[PackSource]:
    sources: list[PackSource] = []
    for pack_id in pack_ids:
        pack = app._find_pack_by_id(pack_id)
        if pack is None:
            sources.append(PackSource(pack_id, problem="The PromptPack was not found."))
            continue
        try:
            pack_config = app._config_manager.load_pack_config(pack_id) or {}
            rows = tuple(read_rows(pack.path))
        except Exception as exc:  # noqa: BLE001 - an unreadable pack is one reported cell row
            sources.append(
                PackSource(pack_id, pack, problem=f"The PromptPack could not be read: {exc}")
            )
            continue
        sources.append(PackSource(pack_id, pack, pack_config, rows))
    return sources


def batch_compiler(app: Any) -> CompileEntries:
    """A batch-owned PromptPack compiler: the Preview compiler, without the Pipeline draft's selection review."""

    from src.controller.global_prompt_policy_service import overlay_current_policy
    from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder

    pipeline = app.pipeline_controller
    builder = PromptPackNormalizedJobBuilder(
        config_manager=pipeline._config_manager,
        job_builder=pipeline._job_builder,
        packs_dir=pipeline._config_manager.packs_dir,
        lora_selection_policy=True,
    )
    return lambda entries: builder.build_jobs(overlay_current_policy(pipeline, entries))


def plan_batch(app: Any, request: BatchRequest, base: BatchBase) -> BatchPlan:
    """Worker thread: read the packs, compile every cell, count, estimate and collect warnings."""

    from src.utils.file_io import read_prompt_pack

    sources = load_pack_sources(app, request.pack_ids, read_prompt_pack)
    recipes = resolve_recipes(base.recipe_context, request.models) if request.use_recipes else {}
    cells = compile_cells(request, base, sources, batch_compiler(app), recipes)
    return build_plan(request, cells, getattr(app, "duration_stats_service", None), recipes)


def request_batch_plan(
    app: Any,
    request: BatchRequest,
    *,
    on_result: Callable[[BatchPlan], None],
    on_error: Callable[[Exception], None],
) -> None:
    """GUI thread: capture the working settings now, then plan on a background task (results on the GUI thread)."""

    problems = request.problems()
    if problems:
        on_error(ValueError(" ".join(problems)))
        return
    try:
        base = capture_batch_base(app)
    except Exception as exc:  # noqa: BLE001 - the Pipeline settings could not be captured; nothing is planned
        on_error(exc)
        return
    app._background_tasks.submit(
        "batch:plan",
        lambda: plan_batch(app, request, base),
        on_result=on_result,
        on_error=on_error,
        name="PackModelBatchPlan",
        purpose="Compile every PromptPack x model cell of a batch before Queue",
    )


def submit_batch(app: Any, plan: BatchPlan, batch_id: str | None = None) -> int:
    """Queue the planned records as one batch through the existing submission path (all or none)."""

    if not plan.queueable:
        return 0
    records = stamp_batch(plan, batch_id)
    return int(
        app.pipeline_controller._submit_normalized_jobs(records, source="gui", prompt_source="pack")
    )


def submit_batch_async(
    app: Any,
    plan: BatchPlan,
    *,
    on_result: Callable[[int], None],
    on_error: Callable[[Exception], None],
) -> None:
    app._background_tasks.submit(
        "batch:queue",
        lambda: submit_batch(app, plan),
        on_result=on_result,
        on_error=on_error,
        name="PackModelBatchQueue",
        purpose="Admit a planned PromptPack x model batch through JobService.submit_njrs",
    )


__all__ = [
    "BATCH_METADATA_KEY",
    "BATCH_SCHEMA",
    "BatchBase",
    "BatchCell",
    "BatchPlan",
    "BatchRequest",
    "PackSource",
    "batch_identity",
    "build_plan",
    "compile_cells",
    "default_batch_name",
    "plan_batch",
    "request_batch_plan",
    "stamp_batch",
    "submit_batch",
    "submit_batch_async",
]
