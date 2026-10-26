"""Toolkit-neutral Prompt x Model results: the same ``GridModel`` the Two-Axis Grid view and contact sheet render.

Rows are prompt candidates, columns are models. Cells come from the frozen snapshot by ``cell_id``; images come only from
the variant that owns the admitted job. Prompt text and model names are withheld whenever content visibility hides them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.learning.experiment_execution import snapshot_digest, thaw_snapshot
from src.learning.grid_results import GridModel, _cell_model, _hidden, _redact
from src.learning.prompt_model_matrix import STUDY_TYPE, frozen_cell, visibility_prompt


def build_matrix_model(
    experiment: Any,
    plan: Sequence[Any],
    rating_details: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    visibility_mode: Any = "nsfw",
) -> GridModel:
    snapshot_json = str(getattr(experiment, "execution_snapshot_json", "") or "")
    snapshot = thaw_snapshot(snapshot_json)
    if snapshot.get("study_type") != STUDY_TYPE:
        raise ValueError("The current experiment is not a Prompt x Model Matrix")
    study = snapshot[STUDY_TYPE]
    ratings = dict(rating_details or {})
    hidden = _hidden(
        {"prompt_text": visibility_prompt(experiment), "negative_prompt_text": ""},
        str(getattr(experiment, "name", "") or ""),
        visibility_mode,
    )
    owners: dict[str, Any] = {}
    for variant in plan:
        cell = frozen_cell(snapshot, variant.param_value)
        if cell["cell_id"] in owners:
            raise ValueError("Two variants claim the same matrix cell")
        owners[cell["cell_id"]] = variant
    images = int(snapshot["images_per_value"])
    cells = tuple(
        _cell_model(
            cell,
            f"Prompt {cell['prompt_label']} | {cell['model_label']}",
            owners.get(cell["cell_id"]),
            ratings,
            hidden,
            images,
        )
        for cell in sorted(study["cells"], key=lambda item: item["index"])
    )
    names = ", ".join(f"{m['label']} = {m['selected_model']}" for m in study["models"])
    return GridModel(
        experiment_id=str(snapshot["experiment_id"]),
        snapshot_sha256=snapshot_digest(snapshot_json),
        title=_redact(f"{getattr(experiment, 'name', '')} [{snapshot['experiment_id']}]", hidden),
        subtitle=(
            f"Prompt x Model Matrix | {_redact(names, hidden)} | "
            f"common requested seed {(snapshot.get('seed_policy') or {}).get('requested_base_seed')}"
        ),
        x_variable="Model",
        y_variable="Prompt",
        x_labels=tuple(model["label"] for model in study["models"]),
        y_labels=tuple(f"Prompt {prompt['label']}" for prompt in study["prompts"]),
        cells=cells,
        hidden=hidden,
        planned_total=int(study["total_images"]),
        completed_total=sum(cell.completed for cell in cells),
    )
