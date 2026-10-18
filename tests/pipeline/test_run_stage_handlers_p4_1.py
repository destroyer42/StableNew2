"""Stage handlers extracted from ``PipelineRunner.run_njr`` (roadmap P4-1)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.run_stage_handlers import (
    ADETAILER_SPEC,
    IMG2IMG_SPEC,
    UPSCALE_SPEC,
    PerImageStageHandler,
    StageRunContext,
    Txt2ImgHandler,
    VideoStageHandler,
    resolve_stage_handler,
)
from tests.pipeline.test_pipeline_runner import _minimal_normalized_record


@pytest.fixture(autouse=True)
def isolated_runtime_endpoints(monkeypatch):
    # run_njr tests use fake executors: a live operator Forge/Comfy must never affect them.
    from src.api import healthcheck
    from src.video import comfy_healthcheck

    monkeypatch.setattr(healthcheck, "probe_webui_endpoint", lambda *a, **k: "free")
    monkeypatch.setattr(comfy_healthcheck, "probe_comfy_endpoint", lambda *a, **k: "free")


class _FakeRunner:
    """Just the runner surface the handlers use."""

    def __init__(self, *, produce: bool = True) -> None:
        self.produce = produce
        self.calls: list[dict[str, Any]] = []
        self.overrides_applied: list[str] = []

    def _stage_config_for_njr(self, njr, stage_name):
        return {"stage": stage_name}

    def _selected_stage_model(self, stage_name, config, njr=None):
        return "model"

    def _selected_stage_vae(self, stage_name, config, njr=None):
        return None

    def _resolve_refinement_policy_service(self, preference):
        service = Mock()
        service.build_bundle.return_value = {"applied_overrides": {"k": 1}, "mode": "m"}
        return service, ["note"]

    def _apply_adetailer_refinement_overrides(self, config, overrides):
        self.overrides_applied.append("adetailer")

    def _apply_upscale_refinement_overrides(self, config, overrides):
        self.overrides_applied.append("upscale")

    def _execute_image_backend(self, **kwargs):
        self.calls.append(kwargs)
        if not self.produce:
            return None
        return {"path": f"out_{len(self.calls)}.png"}


def _njr(*, reprocess: bool) -> Any:
    njr = SimpleNamespace(
        prompt_pack_row_index=0,
        variant_index=0,
        matrix_slot_values=None,
        prompt_pack_name="pack",
        pack_name=None,
        input_image_paths=["a.png", "b.png"] if reprocess else [],
        start_stage="upscale" if reprocess else None,
        images_per_prompt=1,
        config={},
        extra_metadata={},
    )
    return njr


def _ctx(runner, *, reprocess=False, intent=None, metadata=None, client=None) -> StageRunContext:
    return StageRunContext(
        runner=runner,
        njr=_njr(reprocess=reprocess),
        plan=SimpleNamespace(jobs=[]),
        run_dir=Path("run"),
        image_backend_id="forge_webui",
        cancel_token=None,
        survivor_telemetry=None,
        prompt="p",
        negative_prompt="n",
        adaptive_refinement_intent=intent or {},
        learning_context=None,
        client=client,
        metadata=metadata if metadata is not None else {},
    )


STAGE = SimpleNamespace(stage_name="x", prompt_text="stage prompt")


# --- registry -------------------------------------------------------------------------------------


def test_the_registry_resolves_image_stages_video_stages_and_nothing_else() -> None:
    never_video = lambda name: False  # noqa: E731
    assert isinstance(resolve_stage_handler("txt2img", never_video), Txt2ImgHandler)
    for name in ("img2img", "adetailer", "upscale"):
        assert isinstance(resolve_stage_handler(name, never_video), PerImageStageHandler)
    assert isinstance(
        resolve_stage_handler("svd_native", lambda n: n == "svd_native"), VideoStageHandler
    )
    assert resolve_stage_handler("mystery", never_video) is None


# --- skipping --------------------------------------------------------------------------------------


@pytest.mark.parametrize("spec", [IMG2IMG_SPEC, ADETAILER_SPEC, UPSCALE_SPEC])
def test_a_per_image_stage_with_no_input_images_is_skipped(spec) -> None:
    runner = _FakeRunner()
    assert PerImageStageHandler(spec).run(_ctx(runner), STAGE, []) is None
    assert runner.calls == []


def test_a_video_stage_with_no_input_images_is_skipped() -> None:
    assert (
        VideoStageHandler().run(_ctx(_FakeRunner()), SimpleNamespace(stage_name="svd_native"), [])
        is None
    )


# --- per-image behaviour ---------------------------------------------------------------------------


def test_every_input_image_is_processed_and_the_outputs_feed_the_next_stage() -> None:
    runner = _FakeRunner()
    ctx = _ctx(runner)
    out = PerImageStageHandler(IMG2IMG_SPEC).run(ctx, STAGE, ["in1.png", "in2.png", "in3.png"])
    assert out == ["out_1.png", "out_2.png", "out_3.png"]
    assert [call["input_image_path"] for call in runner.calls] == [
        Path("in1.png"),
        Path("in2.png"),
        Path("in3.png"),
    ]
    assert len(ctx.variants) == 3
    assert all(call["stage_name"] == "img2img" and call["prompt"] == "p" for call in runner.calls)


def test_a_missing_output_is_kept_as_a_variant_but_does_not_feed_the_next_stage() -> None:
    runner = _FakeRunner(produce=False)
    ctx = _ctx(runner)
    assert PerImageStageHandler(IMG2IMG_SPEC).run(ctx, STAGE, ["in.png"]) == []
    assert ctx.variants == [None]


@pytest.mark.parametrize(
    ("spec", "before", "between"),
    [(IMG2IMG_SPEC, 0, 0), (ADETAILER_SPEC, 1, 1), (UPSCALE_SPEC, 1, 0)],
)
def test_reprocess_jobs_free_vram_only_where_the_stage_always_did(
    spec, before, between, monkeypatch
) -> None:
    monkeypatch.setattr("src.pipeline.run_stage_handlers.time.sleep", lambda _s: None)
    client = Mock()
    runner = _FakeRunner()
    ctx = _ctx(runner, reprocess=True, client=client)
    # two images: "before image 2" frees once (with a settle), "between images" frees once after image 1.
    PerImageStageHandler(spec).run(ctx, STAGE, ["a.png", "b.png"])
    assert client.free_vram.call_count == before + between
    if before + between:
        client.free_vram.assert_called_with(unload_model=True)


def test_reprocess_outputs_carry_the_original_input_stem() -> None:
    runner = _FakeRunner()
    ctx = _ctx(runner, reprocess=True)
    PerImageStageHandler(UPSCALE_SPEC).run(ctx, STAGE, ["a.png", "b.png"])
    names = [call["image_name"] for call in runner.calls]
    assert "_a" in names[0] and "_b" in names[1]


def _refinement_intent(mode: str) -> dict[str, Any]:
    return {"enabled": True, "mode": mode, "detector_preference": "null"}


def _refinement_metadata() -> dict[str, Any]:
    return {"adaptive_refinement": {"prompt_intent": {"subject": "s"}, "detector_notes": []}}


def test_adetailer_records_decisions_without_a_stage_name_and_upscale_with_one() -> None:
    adetailer_runner = _FakeRunner()
    adetailer_ctx = _ctx(
        adetailer_runner, intent=_refinement_intent("adetailer"), metadata=_refinement_metadata()
    )
    PerImageStageHandler(ADETAILER_SPEC).run(adetailer_ctx, STAGE, ["a.png"])
    (decision,) = adetailer_ctx.metadata["adaptive_refinement"]["image_decisions"]
    assert list(decision) == ["input_image_path", "output_path", "decision_bundle"]
    assert decision["output_path"] == "out_1.png"
    assert adetailer_runner.overrides_applied == ["adetailer"]
    assert (
        adetailer_runner.calls[0]["stage_config"]["adaptive_refinement"]["intent"]["mode"]
        == "adetailer"
    )

    upscale_runner = _FakeRunner(produce=False)
    upscale_ctx = _ctx(
        upscale_runner, intent=_refinement_intent("full"), metadata=_refinement_metadata()
    )
    PerImageStageHandler(UPSCALE_SPEC).run(upscale_ctx, STAGE, ["a.png"])
    (decision,) = upscale_ctx.metadata["adaptive_refinement"]["image_decisions"]
    assert list(decision) == ["stage_name", "input_image_path", "output_path", "decision_bundle"]
    assert decision["stage_name"] == "upscale" and decision["output_path"] is None
    assert upscale_runner.overrides_applied == ["upscale"]


def test_refinement_modes_gate_which_stage_consults_the_policy() -> None:
    # "adetailer" mode refines adetailer only; upscale needs "full"; img2img never refines.
    for spec, mode, expected in (
        (ADETAILER_SPEC, "adetailer", True),
        (UPSCALE_SPEC, "adetailer", False),
        (UPSCALE_SPEC, "full", True),
        (IMG2IMG_SPEC, "full", False),
    ):
        runner = _FakeRunner()
        ctx = _ctx(runner, intent=_refinement_intent(mode), metadata=_refinement_metadata())
        PerImageStageHandler(spec).run(ctx, STAGE, ["a.png"])
        assert bool(ctx.metadata["adaptive_refinement"].get("image_decisions")) is expected, (
            spec.stage_name,
            mode,
        )
        config = runner.calls[0]["stage_config"]
        assert ("adaptive_refinement" in config) is expected


def test_the_per_image_config_is_a_copy_so_refinement_never_leaks_between_images() -> None:
    runner = _FakeRunner()
    ctx = _ctx(runner, intent=_refinement_intent("full"), metadata=_refinement_metadata())
    PerImageStageHandler(UPSCALE_SPEC).run(ctx, STAGE, ["a.png", "b.png"])
    first, second = (call["stage_config"] for call in runner.calls)
    assert first is not second
    assert first["adaptive_refinement"] is not second["adaptive_refinement"]


# --- orchestration through run_njr -----------------------------------------------------------------


def _runner_with_fake_pipeline() -> tuple[PipelineRunner, Mock]:
    runner = PipelineRunner(Mock(), Mock())
    pipeline = Mock()
    pipeline.client = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": "output.png"}
    runner._pipeline = pipeline
    return runner, pipeline


def test_run_njr_names_the_failing_stage_in_its_error_event() -> None:
    runner, pipeline = _runner_with_fake_pipeline()
    pipeline.run_txt2img_stage.side_effect = RuntimeError("backend exploded")
    result = runner.run_njr(_minimal_normalized_record(), cancel_token=None)
    assert result.success is False
    assert "backend exploded" in (result.error or "")
    error_event = result.stage_events[-1]
    assert error_event["phase"] == "error" and error_event["stage"] == "txt2img"


def test_a_failure_before_any_stage_runs_is_reported_against_the_pipeline() -> None:
    runner, _pipeline = _runner_with_fake_pipeline()
    runner._reprocess_inputs = Mock(side_effect=FileNotFoundError("missing input"))  # type: ignore[method-assign]
    result = runner.run_njr(_minimal_normalized_record(), cancel_token=None)
    assert result.success is False
    assert result.stage_events[-1]["stage"] == "pipeline"
    assert "missing input" in (result.error or "")


def test_run_njr_is_orchestration_only() -> None:
    import inspect

    lines = inspect.getsource(PipelineRunner.run_njr).splitlines()
    assert len(lines) < 200, f"run_njr grew to {len(lines)} lines; put stage logic in a handler"
