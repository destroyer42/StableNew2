"""P4-2D: the record a Learning operator previews is the record that runs.

Preview compiles through the same assembly boundary as Run (``njr_compiler.compile_njr`` with a ``FROZEN`` draft), so
the executable record is identical.  Only four things may legitimately differ between the two compiles: the minted
``job_id``, the ``output_plan`` (Preview has no output folder yet), and the two ``metadata`` mappings (Run adds the
controller's experiment bookkeeping).  Everything else, including prompts, configuration, backend options, stages, seed
and embeddings, must be equal.  The goldens pin the bytes of each Run record; these tests pin Preview against Run, and
pin that a compile-policy change after the freeze cannot reach a frozen record.
"""

from __future__ import annotations

import copy
import itertools
import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.gui.controllers import learning_controller
from src.learning import baseline_authoring as authoring
from src.learning import model_comparison, prompt_model_matrix
from src.learning.experiment_execution import thaw_snapshot
from src.learning.learning_njr import assemble_txt2img_njr
from src.pipeline import njr_compiler
from src.pipeline.job_models_v2 import NormalizedJobRecord
from tests.golden.conftest import ASSETS
from tests.golden.test_njr_golden_learning import _bench
from tests.learning_v2.test_model_comparison_140 import KLEIN, SDXL, controller_for
from tests.learning_v2.test_model_comparison_compat_158 import shared_baseline, study
from tests.learning_v2.test_prompt_model_matrix_710 import PEER
from tests.learning_v2.test_prompt_model_matrix_710 import build as build_matrix
from tests.learning_v2.test_prompt_model_matrix_710 import variant as matrix_variant


@pytest.fixture
def asset_copier(tmp_path: Path) -> Callable[..., Path]:
    def copy(name: str, target: str | None = None) -> Path:
        destination = tmp_path / (target or name)
        shutil.copyfile(ASSETS / name, destination)
        return destination

    return copy


@pytest.fixture
def uuid_stub(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Replace the ``uuid`` name inside the given modules with a counter, as the golden suite does."""

    counter = itertools.count(1)

    def install(*modules: object) -> None:
        stub = SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=f"{next(counter):032x}"))
        for module in modules:
            monkeypatch.setattr(module, "uuid", stub)

    return install


def executable(record: NormalizedJobRecord) -> dict[str, Any]:
    """The record minus the four parts that may legitimately differ between Preview and Run."""

    data = copy.deepcopy(record.to_dict())
    data.pop("job_id")
    data.pop("output_plan")
    data["workload"].pop("metadata")
    data["provenance"].pop("metadata")
    return data


def test_ordinary_run_records_match_what_preview_froze(
    tmp_path: Path,
    asset_copier: Callable[..., Path],
    uuid_stub: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uuid_stub(learning_controller)
    bench = _bench(tmp_path, asset_copier, monkeypatch)
    experiment = bench.preview()
    frozen = thaw_snapshot(experiment.execution_snapshot_json)["variant_effective_settings"]
    plan = bench.controller.learning_state.plan
    assert len(frozen) == len(plan) > 1

    for variant in plan:
        first = bench.controller._build_variant_njr(variant, experiment)
        second = bench.controller._build_variant_njr(variant, experiment)
        preview = next(entry for entry in frozen if entry["value"] == variant.param_value)

        # What Preview showed is what the record carries (the strict parity rule Run enforces itself).
        assert (
            authoring.parity_mismatches(
                preview["settings"], authoring.stage_values_from_record(first, "txt2img")
            )
            == []
        )
        # Compiling again for admission yields the same executable record (the identity is minted per compile).
        assert executable(first) == executable(second)
        assert first.to_dict()["workload"] == second.to_dict()["workload"]


def test_matrix_preview_compile_equals_run_compile() -> None:
    snapshot = build_matrix(models=(SDXL, PEER))
    for index, value in enumerate(snapshot["variant_values"]):
        cell = prompt_model_matrix.frozen_cell(snapshot, value)
        # Preview compiles the cell with the defaults the freeze step uses; Run recompiles it and compares digests.
        preview = prompt_model_matrix._cell_record(
            snapshot, cell, matrix_variant(snapshot, index), job_id="cell"
        )
        run = prompt_model_matrix.materialize_njr(
            snapshot,
            matrix_variant(snapshot, index),
            metadata_factory=lambda config: {},
            output_dir="output",
            filename_template="{seed}",
            job_id="cell",
        )
        assert preview.to_dict() == run.to_dict()


def test_model_comparison_arm_records_match_between_preview_and_run(
    tmp_path: Path, uuid_stub: Callable[..., None]
) -> None:
    uuid_stub(model_comparison)
    experiment = study(tmp_path, models=[SDXL, KLEIN])
    controller = controller_for(experiment, shared_baseline())
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)

    for variant in controller.learning_state.plan:
        # verify_arms_admissible is the Preview-time compile of each arm through the Run boundary.
        preview = model_comparison.materialize_njr(
            snapshot,
            SimpleNamespace(param_value=variant.param_value, executed_config=None),
            metadata_factory=lambda config: {},
            output_dir="output",
            filename_template="{seed}",
        )
        run = controller._build_variant_njr(variant, experiment)
        assert executable(preview) == executable(run)


def _frozen_assembly() -> NormalizedJobRecord:
    config = {
        "prompt": "a lighthouse",
        "negative_prompt": "blurry",
        "backend_options": {"backend": "unit"},
        "txt2img": {
            "model": "model-a.safetensors",
            "vae": "",
            "steps": 12,
            "cfg_scale": 5.5,
            "sampler_name": "Euler a",
            "scheduler": "normal",
            "seed": 77,
        },
    }
    return assemble_txt2img_njr(
        job_id="frozen-1",
        display_name="frozen study",
        positive="a lighthouse",
        negative="blurry",
        config=config,
        metadata={"study": "unit"},
        backend_options={"backend": "unit"},
        images_per_prompt=2,
        output_dir="out",
        filename_template="{seed}",
        variant_index=0,
        variant_total=1,
        context=None,
    )


def test_a_frozen_arm_whose_prompt_differs_from_its_config_is_refused_with_the_route_message() -> (
    None
):
    with pytest.raises(ValueError, match="^Unit study NJR does not match frozen execution$"):
        assemble_txt2img_njr(
            job_id="frozen-2",
            display_name="frozen study",
            positive="a different prompt",
            negative="blurry",
            config={
                "prompt": "a lighthouse",
                "negative_prompt": "blurry",
                "backend_options": {},
                "txt2img": {
                    "model": "m",
                    "steps": 1,
                    "cfg_scale": 1.0,
                    "sampler_name": "s",
                    "scheduler": "n",
                    "seed": 1,
                },
            },
            metadata={},
            backend_options={},
            images_per_prompt=1,
            output_dir="",
            filename_template="{seed}",
            variant_index=0,
            variant_total=1,
            context=None,
            mismatch_message="Unit study NJR does not match frozen execution",
        )


def test_a_changed_compile_policy_after_the_freeze_does_not_alter_a_frozen_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _frozen_assembly().to_dict()

    def policy_changed(
        config: Any,
    ) -> Any:  # a policy that would rewrite the frozen values if it ever ran
        raise AssertionError("a FROZEN draft must never run the compile policy")

    monkeypatch.setattr(njr_compiler, "apply_model_compile_policy", policy_changed)
    monkeypatch.setattr(njr_compiler, "prepare_effective_config", policy_changed)
    monkeypatch.setattr(njr_compiler, "canonicalize_intent_config", policy_changed)

    assert _frozen_assembly().to_dict() == before
