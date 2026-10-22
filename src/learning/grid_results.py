"""Toolkit-neutral projection of a Two-Axis Grid experiment: cell coordinates, exact artifacts, placeholders.

The interactive grid and the contact sheet both render this model, so they cannot disagree about which image belongs
in which cell. Cells come from the frozen snapshot by ``cell_id``; images come only from the variant that owns the
admitted job (never a filename search or a neighbouring job). Hidden content never reaches the model's paths or text.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.experiment_execution import snapshot_digest, thaw_snapshot
from src.learning.two_axis_grid import STUDY_TYPE, frozen_cell

HIDDEN = "Hidden by content-visibility policy"
PLACEHOLDERS = {
    "pending": "Pending",
    "queued": "Queued",
    "running": "Running",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "requires_attention": "Requires attention",
    "uncontrolled": "Uncontrolled evidence",
}
MISSING = "Artifact missing"
NO_JOB = "No job recorded"
LEGEND = (
    ("Pending / Queued / Running", "The job has not finished; nothing is shown for it yet."),
    ("Failed / Cancelled", "The job ended without images; the cell keeps its position."),
    ("Artifact missing", "A recorded image file is no longer on disk."),
    (
        "Uncontrolled evidence",
        "Images exist but seed or variable read-back did not prove a controlled run.",
    ),
    (
        "Hidden by content-visibility policy",
        "Thumbnails and prompt-derived text are withheld in SFW mode.",
    ),
)


@dataclass(frozen=True)
class GridImage:
    path: str
    sample_index: int
    seed: int | None
    rating: int | None
    available: bool


@dataclass(frozen=True)
class GridCellModel:
    index: int
    row: int
    col: int
    cell_id: str
    label: str
    job_id: str
    status: str
    planned: int
    completed: int
    images: tuple[GridImage, ...]
    placeholder: str
    uncontrolled: bool
    rating_summary: str


@dataclass(frozen=True)
class GridModel:
    experiment_id: str
    snapshot_sha256: str
    title: str
    subtitle: str
    x_variable: str
    y_variable: str
    x_labels: tuple[str, ...]
    y_labels: tuple[str, ...]
    cells: tuple[GridCellModel, ...]
    hidden: bool
    planned_total: int
    completed_total: int

    @property
    def rows(self) -> int:
        return len(self.y_labels)

    @property
    def cols(self) -> int:
        return len(self.x_labels)

    @property
    def exportable(self) -> bool:
        return any(cell.job_id for cell in self.cells)

    def cell_at(self, row: int, col: int) -> GridCellModel:
        return self.cells[row * self.cols + col]


def _axis_label(variable: str, value: Any) -> str:
    short = {"CFG Scale": "CFG", "Steps": "Steps", "LoRA Strength": "LoRA"}.get(variable, variable)
    return f"{short} {value}"


def _hidden(snapshot: Mapping[str, Any], experiment_name: str, mode: Any) -> bool:
    from src.controller.content_visibility_resolver import ContentVisibilityResolver

    resolver = ContentVisibilityResolver(mode)
    subject = {
        "name": experiment_name,
        "prompt": str(snapshot.get("prompt_text") or ""),
        "negative_prompt": str(snapshot.get("negative_prompt_text") or ""),
    }
    return resolver.decide(subject, allow_redacted=True).redacted


def _redact(text: str, hidden: bool) -> str:
    from src.controller.content_visibility_resolver import REDACTED_TEXT

    return REDACTED_TEXT if hidden and text else text


def is_grid_experiment(experiment: Any) -> bool:
    raw = str(getattr(experiment, "execution_snapshot_json", "") or "")
    if not raw:
        return False
    try:
        return thaw_snapshot(raw).get("study_type") == STUDY_TYPE
    except ValueError:
        return False


def build_grid_model(
    experiment: Any,
    plan: Sequence[Any],
    rating_details: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    visibility_mode: Any = "nsfw",
) -> GridModel:
    snapshot_json = str(getattr(experiment, "execution_snapshot_json", "") or "")
    snapshot = thaw_snapshot(snapshot_json)
    if snapshot.get("study_type") != STUDY_TYPE:
        raise ValueError("The current experiment is not a Two-Axis Grid")
    grid = snapshot["two_axis_grid"]
    ratings = dict(rating_details or {})
    hidden = _hidden(snapshot, str(getattr(experiment, "name", "") or ""), visibility_mode)
    x_axis, y_axis = grid["x_axis"], grid["y_axis"]
    owners: dict[str, Any] = {}
    for variant in plan:
        cell = frozen_cell(snapshot, variant.param_value)
        if cell["cell_id"] in owners:
            raise ValueError("Two variants claim the same grid cell")
        owners[cell["cell_id"]] = variant
    cells: list[GridCellModel] = []
    for cell in sorted(grid["cells"], key=lambda item: item["index"]):
        variant = owners.get(cell["cell_id"])
        label = f"{_axis_label(x_axis['variable'], cell['x_value'])} | {_axis_label(y_axis['variable'], cell['y_value'])}"
        cells.append(
            _cell_model(cell, label, variant, ratings, hidden, int(snapshot["images_per_value"]))
        )
    source = snapshot.get("prompt_source") or {}
    context = snapshot.get("model_policy_context") or {}
    prompt_id = (
        f"PromptPack {source.get('selected_prompt_pack_name') or 'row'} row "
        f"{int(source.get('selected_prompt_index', 0) or 0) + 1}"
        if source.get("prompt_source") == "pack"
        else "custom prompt"
    )
    subtitle = (
        f"Two-Axis Grid | model {_redact(str(context.get('selected_model') or ''), hidden)} | "
        f"{_redact(prompt_id, hidden)} | common seed {(snapshot.get('seed_policy') or {}).get('requested_base_seed')}"
    )
    return GridModel(
        experiment_id=str(snapshot["experiment_id"]),
        snapshot_sha256=snapshot_digest(snapshot_json),
        title=_redact(f"{getattr(experiment, 'name', '')} [{snapshot['experiment_id']}]", hidden),
        subtitle=subtitle,
        x_variable=x_axis["variable"],
        y_variable=y_axis["variable"],
        x_labels=tuple(_axis_label(x_axis["variable"], value) for value in x_axis["values"]),
        y_labels=tuple(_axis_label(y_axis["variable"], value) for value in y_axis["values"]),
        cells=tuple(cells),
        hidden=hidden,
        planned_total=int(grid["total_images"]),
        completed_total=sum(cell.completed for cell in cells),
    )


def _cell_model(
    cell: Mapping[str, Any],
    label: str,
    variant: Any,
    ratings: Mapping[str, Mapping[str, Any]],
    hidden: bool,
    planned_default: int,
) -> GridCellModel:
    if variant is None:
        return GridCellModel(
            cell["index"],
            cell["row"],
            cell["col"],
            cell["cell_id"],
            label,
            "",
            "pending",
            planned_default,
            0,
            (),
            NO_JOB,
            False,
            "",
        )
    status = str(variant.status or "pending")
    refs = [str(ref) for ref in variant.image_refs]
    metadata = dict(getattr(variant, "execution_metadata", {}) or {})
    seeds = list(metadata.get("actual_all_seeds") or [])
    seeds = seeds if len(seeds) == len(refs) else []
    images: list[GridImage] = []
    for position, ref in enumerate(refs):
        detail = ratings.get(ref) or {}
        raw = int(detail.get("overall_rating") or 0)
        images.append(
            GridImage(
                ref,
                position,
                int(seeds[position]) if seeds else None,
                raw if raw > 0 else None,
                Path(ref).is_file(),
            )
        )
    uncontrolled = status == "uncontrolled" or (
        status == "completed" and metadata.get("controlled_evidence_valid") is False
    )
    available = [image for image in images if image.available]
    placeholder: str
    shown: tuple[GridImage, ...]
    if hidden:
        placeholder, shown = HIDDEN, ()
    elif available:
        placeholder, shown = "", tuple(images)
    elif status in {"completed", "uncontrolled"}:
        placeholder, shown = (
            (MISSING if refs or status == "completed" else PLACEHOLDERS["uncontrolled"]),
            tuple(images),
        )
    else:
        placeholder, shown = (
            PLACEHOLDERS.get(status, status.replace("_", " ").title()),
            tuple(images),
        )
    rated = [image.rating for image in images if image.rating]
    summary = f"{len(rated)}/{len(images) or variant.planned_images} rated" + (
        f", mean {sum(rated) / len(rated):.1f}" if rated else ""
    )
    return GridCellModel(
        cell["index"],
        cell["row"],
        cell["col"],
        cell["cell_id"],
        label,
        str(variant.job_id or ""),
        status,
        int(variant.planned_images or planned_default),
        int(variant.completed_images or 0),
        shown,
        placeholder,
        uncontrolled,
        summary,
    )
