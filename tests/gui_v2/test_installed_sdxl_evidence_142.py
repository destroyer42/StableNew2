"""Metadata-free installed-checkpoint reproduction through selected Tk Preview."""

import json

import pytest

from tests.assets.checkpoint_fixtures import tensor_checkpoint
from tests.gui_v2.test_model_comparison_readiness_142 import complete
from tests.gui_v2.test_model_comparison_readiness_142 import operator as operator_fixture

operator = operator_fixture


@pytest.mark.parametrize(
    "names",
    [
        ("albedobaseXL_v31Large", "realvisxlV50_v50Bakedvae"),
        ("albedobaseXL_v31Large", "flux-2-klein-4b-fp8"),
    ],
)
def test_installed_metadata_free_selected_preview(operator, names):
    paths = [
        tensor_checkpoint(operator.webui / "models" / "Stable-diffusion" / f"{name}.safetensors")
        for name in names
    ]
    operator.select(names, paths=paths)
    operator.view._on_build_preview()
    complete(operator)
    assert operator.view.feedback_var.get() == "Model Comparison preview ready"
    snapshot = json.loads(
        operator.controller.learning_state.current_experiment.execution_snapshot_json
    )
    arms = snapshot["model_comparison"]["arms"]
    assert len({arm["source_intent_sha256"] for arm in arms}) == 1
    assert arms[0]["checkpoint_evidence"]["family_evidence"][0]["source"] == "safetensors_structure"
    assert names[0] in operator.view.summary_var.get()


def test_hidden_names_are_removed_from_ready_summary(operator):
    paths = [
        tensor_checkpoint(operator.webui / f"{name}.safetensors") for name in ("first", "second")
    ]
    operator.select(paths=paths)
    operator.view._on_build_preview()
    complete(operator)
    assert "first" in operator.view.summary_var.get()
    operator.state.set_content_visibility_mode("sfw")
    assert "first" not in operator.view.summary_var.get()
    assert "safetensors_structure" in operator.view.summary_var.get()


def test_hidden_names_are_omitted_from_failure_feedback(operator):
    from tests.assets.checkpoint_fixtures import checkpoint

    paths = [
        checkpoint(operator.webui / f"{name}.safetensors")
        for name in ("private-first", "private-second")
    ]
    operator.select(("private-first", "private-second"), paths=paths)
    operator.state.set_content_visibility_mode("sfw")
    operator.view._on_build_preview()
    complete(operator)
    assert "Model 1" in operator.view.feedback_var.get()
    assert "private-first" not in operator.view.feedback_var.get()


def test_structural_preview_run_never_reinspects_or_adapts(operator, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from src.assets import AssetRegistry
    from src.learning.execution_controller import LearningExecutionController

    paths = [
        tensor_checkpoint(operator.webui / f"{name}.safetensors") for name in ("first", "second")
    ]
    operator.select(paths=paths)
    operator.view._on_build_preview()
    complete(operator)
    assert operator.view.feedback_var.get() == "Model Comparison preview ready"
    for path in paths:
        path.write_bytes(b"changed after Preview")
    for method in ("inspect_checkpoint", "refresh", "cached_snapshot"):
        monkeypatch.setattr(
            AssetRegistry, method, lambda *a, **k: pytest.fail("live evidence at Run")
        )
    monkeypatch.setattr(
        "src.pipeline.resolution_layer.adapt_pack_intent",
        lambda *a, **k: pytest.fail("adaptation at Run"),
    )
    (operator.view._resolve_packs_dir() / "study.json").write_text("changed after Preview")
    service = SimpleNamespace(
        submit_njrs=Mock(side_effect=lambda records, policy: [r.job_id for r in records])
    )
    operator.controller.execution_controller = LearningExecutionController(
        operator.controller.learning_state, service
    )
    operator.controller.pipeline_controller = object()
    operator.controller.run_plan()
    assert service.submit_njrs.call_count == 1
    records = service.submit_njrs.call_args.args[0]
    assert len(records) == 2
    assert all(
        record.workload.metadata["model_comparison"]["checkpoint_evidence"]["checkpoint_structure"][
            "architecture"
        ]
        == "sdxl_base"
        for record in records
    )
