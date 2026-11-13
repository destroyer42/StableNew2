"""P4-2A golden NJRs for every Learning compile route (assessment sites S6, S7 and the V5 re-identification).

Routes: ordinary strict txt2img, ordinary legacy (non-strict, X13), a non-txt2img variant (built by
``ReprocessJobBuilder`` and re-identified), Model Comparison, Two-Axis Grid and Prompt x Model Matrix.  The records come
from the real ``LearningController._build_variant_njr`` over frozen snapshots; identities are injected.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.gui.controllers import learning_controller
from src.learning import baseline_authoring as authoring
from src.learning import model_comparison, ordinary_snapshot, prompt_model_matrix, two_axis_grid
from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from tests.golden.test_njr_golden_p4_2 import assert_golden
from tests.golden.test_njr_golden_reprocess_video import mask_environment_digests
from tests.learning_v2.test_learning_independent_baseline_650 import Bench
from tests.learning_v2.test_model_comparison_140 import KLEIN, SDXL, controller_for
from tests.learning_v2.test_model_comparison_compat_158 import shared_baseline, study
from tests.learning_v2.test_prompt_model_matrix_710 import PEER
from tests.learning_v2.test_prompt_model_matrix_710 import build as build_matrix
from tests.learning_v2.test_prompt_model_matrix_710 import variant as matrix_variant
from tests.learning_v2.test_two_axis_grid_270 import grid_controller, grid_experiment

_MTIME_NS = 1_700_000_000_000_000_000


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 1, 2, 3, 4, 5)

    @classmethod
    def utcnow(cls) -> datetime:  # type: ignore[override]
        return datetime(2026, 1, 2, 3, 4, 5)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every snapshot timestamp on a Learning compile path (baseline copy, experiment stamp) reads one fixed clock."""

    for module in (
        authoring,
        model_comparison,
        ordinary_snapshot,
        prompt_model_matrix,
        two_axis_grid,
    ):
        monkeypatch.setattr(module, "datetime", _FixedClock)


def _bench(
    tmp_path: Path, copy_asset: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> Bench:
    bench = Bench(tmp_path)

    def image(name: str = "source.png") -> str:
        path = copy_asset("blue_64.png", name)
        os.utime(
            path, ns=(_MTIME_NS, _MTIME_NS)
        )  # the frozen source identity records the file's mtime
        return str(path)

    bench.image = image  # type: ignore[method-assign]
    return bench


def _records(controller: Any, experiment: Any) -> list[dict[str, Any]]:
    return [
        controller._build_variant_njr(variant, experiment).to_dict()
        for variant in controller.learning_state.plan
    ]


def test_learning_ordinary_strict_txt2img(
    tmp_path: Path,
    copy_asset: Callable[..., Path],
    deterministic_uuid: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deterministic_uuid(learning_controller)
    bench = _bench(tmp_path, copy_asset, monkeypatch)
    experiment = bench.preview()
    assert_golden("learning_ordinary_strict", _records(bench.controller, experiment), tmp_path)


def test_learning_ordinary_legacy_txt2img(
    tmp_path: Path,
    copy_asset: Callable[..., Path],
    deterministic_uuid: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A snapshot frozen before ``baseline_authoring`` still compiles with the historical defaults (X13)."""

    deterministic_uuid(learning_controller)
    bench = _bench(tmp_path, copy_asset, monkeypatch)
    experiment = bench.preview()
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    snapshot.pop("baseline_authoring")
    experiment.execution_snapshot_json = freeze_snapshot(snapshot)
    assert_golden("learning_ordinary_legacy", _records(bench.controller, experiment), tmp_path)


def test_learning_non_txt2img_variant(
    tmp_path: Path,
    copy_asset: Callable[..., Path],
    deterministic_uuid: Callable[..., None],
    fixed_reprocess_ids: Callable[[], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deterministic_uuid(learning_controller)
    bench = _bench(tmp_path, copy_asset, monkeypatch)
    experiment = bench.preview(stage="img2img", variable="Denoise Strength", values=(0.3, 0.5, 0.2))
    # The frozen snapshot records the temp source path, so its own digest follows the temp directory.
    assert_golden(
        "learning_non_txt2img_variant",
        mask_environment_digests(_records(bench.controller, experiment)),
        tmp_path,
    )


def test_learning_model_comparison_arms(
    tmp_path: Path, deterministic_uuid: Callable[..., None]
) -> None:
    deterministic_uuid(model_comparison)
    experiment = study(tmp_path, models=[SDXL, KLEIN])
    controller = controller_for(experiment, shared_baseline())
    assert_golden(
        "learning_model_comparison",
        mask_environment_digests(_records(controller, experiment)),
        tmp_path,
    )


def test_learning_two_axis_grid_cells(
    tmp_path: Path, deterministic_uuid: Callable[..., None]
) -> None:
    deterministic_uuid(two_axis_grid)
    experiment = grid_experiment()
    controller = grid_controller(experiment)
    records = _records(controller, controller.learning_state.current_experiment)
    assert len(records) == 9
    assert_golden("learning_two_axis_grid", records, tmp_path)


def test_learning_prompt_model_matrix_cells(tmp_path: Path) -> None:
    snapshot = build_matrix(models=(SDXL, PEER))
    records = [
        prompt_model_matrix.materialize_njr(
            snapshot,
            matrix_variant(snapshot, index),
            metadata_factory=lambda config: {},
            output_dir="out",
            filename_template="{seed}",
            job_id=f"matrix-{index}",
        ).to_dict()
        for index in range(len(snapshot["variant_values"]))
    ]
    assert len(records) == 6
    assert_golden("learning_prompt_model_matrix", records, tmp_path)


@pytest.mark.parametrize("name", ["learning_ordinary_strict", "learning_ordinary_legacy"])
def test_learning_strict_and_legacy_differ_only_where_x13_says(name: str) -> None:
    from tests.golden.test_njr_golden_p4_2 import GOLDEN_DIR

    assert (GOLDEN_DIR / f"{name}.json").exists()
