"""P4-2A refusal baselines: one table per route family, frozen as observed on unchanged ``main``.

For each family and each of four unsupported requests (an exact profile's unsupported request, an enabled retired
stage, an empty txt2img prompt, a missing input image) the table records what the compiler did (``accepted``, or the
exact exception type and message) and, when a record came out, what the real ``JobService.submit_njrs`` did with it.
That pair is the *point of refusal*: assessment finding X3 (the same request refused at compile on one route and only
at admission, or not at all, on another) is visible here and is frozen, not fixed.  A case a route cannot express is
recorded as ``not_applicable`` with the reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.controller.reprocess_admission import submit_reprocess_njrs
from src.pipeline.cli_njr_builder import build_cli_njr
from src.pipeline.history_variation_compiler import HistoryVariationDraft, compile_history_variation
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.video.movie_assembly_compiler import (
    AssemblyIntentClip,
    MovieAssemblyIntent,
    VideoFacts,
    freeze_movie_assembly,
)
from tests.golden.route_records import admit as admit_record
from tests.golden.route_records import observe, real_job_service
from tests.golden.test_njr_golden_derivation import prompt_pack_parent
from tests.golden.test_njr_golden_generation import (
    _entry,
    _pack_builder,
    generic_builder,
    generic_config,
    zimage_config,
    zimage_pack,
)
from tests.golden.test_njr_golden_p4_2 import assert_golden
from tests.golden.test_njr_golden_reprocess_video import (
    CapturingJobService,
    video_controller,
    video_form,
)
from tests.learning_v2.test_learning_independent_baseline_650 import Bench
from tests.pipeline.test_animatediff_retirement import _enabled_animatediff_njr
from tests.pipeline.test_history_variation_compiler_610a import _source as variation_source
from tests.pipeline.test_prompt_pack_job_builder import _write_native_pack

ZIMAGE_MODEL = zimage_config()["model"]


def _dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def scrub(node: Any, tmp_path: Path) -> Any:
    """Messages embed temp paths mid-string; make them machine-independent before they are compared."""

    if isinstance(node, dict):
        return {key: scrub(value, tmp_path) for key, value in node.items()}
    if isinstance(node, str):
        for prefix in sorted({str(tmp_path), tmp_path.as_posix()}, key=len, reverse=True):
            node = node.replace(prefix, "<tmp>")
        return node.replace("\\", "/")
    return node


def not_applicable(reason: str) -> dict[str, str]:
    return {"outcome": "not_applicable", "reason": reason}


def first(value: Any) -> NormalizedJobRecord:
    return value[0] if isinstance(value, (list, tuple)) else value


def case(tmp_path: Path, build: Callable[[], Any], name: str) -> dict[str, Any]:
    """Compile, then (when a record came out) admit it through the real JobService."""

    built: list[NormalizedJobRecord] = []
    result: dict[str, Any] = {"compile": observe(lambda: built.append(first(build())))}
    if built:
        with real_job_service(tmp_path / f"queue-{name}") as service:
            result["admission"] = admit_record(service, built[0])
    else:
        result["admission"] = {"outcome": "not_reached"}
    return result


def with_enabled_animatediff(record: NormalizedJobRecord) -> NormalizedJobRecord:
    return replace(record, stages=(*record.stages, StageConfig("animatediff", enabled=True)))


def test_refusals_generic(tmp_path: Path) -> None:
    table = {
        "exact_profile_unsupported": case(
            tmp_path,
            lambda: generic_builder().build_jobs(
                base_config=zimage_config(prompt="A teapot <lora:adapter:1>")
            ),
            "g1",
        ),
        "retired_stage_requested_by_config": case(
            tmp_path,
            lambda: generic_builder().build_jobs(
                base_config=generic_config(
                    animatediff={"enabled": True},
                    pipeline={"txt2img_enabled": True, "animatediff_enabled": True},
                )
            ),
            "g2",
        ),
        "retired_stage_on_a_built_record": case(
            tmp_path,
            lambda: with_enabled_animatediff(
                generic_builder().build_jobs(base_config=generic_config())[0]
            ),
            "g3",
        ),
        "empty_txt2img_prompt": case(
            tmp_path,
            lambda: generic_builder().build_jobs(base_config=generic_config(prompt="")),
            "g4",
        ),
        "missing_input_image": not_applicable("the generic route has no input image"),
    }
    assert_golden("refusals_generic", scrub(table, tmp_path), tmp_path)


def test_refusals_prompt_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def pack(**changes: Any) -> Callable[[], Any]:
        def build() -> Any:
            (tmp_path / "pack").mkdir(exist_ok=True)
            builder, manager = _pack_builder(tmp_path / "pack")
            path = _write_native_pack(
                manager.packs_dir / "refusal-pack.json", text=changes.pop("text", "A knight")
            )
            return builder.build_jobs([_entry(path, **changes)])

        return build

    def exact() -> Any:
        (tmp_path / "exact").mkdir(exist_ok=True)
        builder, entry, _path, _original = zimage_pack(
            tmp_path / "exact", monkeypatch, text="A portrait <lora:adapter:1>"
        )
        return builder.build_jobs([entry])

    table = {
        "exact_profile_unsupported": case(tmp_path, exact, "p1"),
        "retired_stage_requested_by_flag": case(
            tmp_path,
            pack(stage_flags={"txt2img": True, "animatediff": True}, prompt_text="A knight"),
            "p2",
        ),
        "retired_stage_on_a_built_record": case(
            tmp_path,
            lambda: with_enabled_animatediff(prompt_pack_parent(_dir(tmp_path / "p3"))),
            "p3",
        ),
        "empty_txt2img_prompt": case(tmp_path, pack(text="", prompt_text=""), "p4"),
        "missing_input_image": not_applicable("a PromptPack job has no input image"),
    }
    assert_golden("refusals_prompt_pack", scrub(table, tmp_path), tmp_path)


def test_refusals_cli(tmp_path: Path) -> None:
    def cli(prompt: str = "a cat", **config: Any) -> Callable[[], Any]:
        return lambda: build_cli_njr(
            prompt=prompt,
            batch_size=1,
            run_name="refusal",
            config={"txt2img": {"model": "m.safetensors", "steps": 4, "cfg_scale": 5.0}, **config},
        )

    zimage = zimage_config(prompt="A teapot <lora:adapter:1>")
    table = {
        "exact_profile_unsupported": case(
            tmp_path,
            lambda: build_cli_njr(
                prompt=zimage["prompt"],
                batch_size=1,
                run_name="refusal",
                config={
                    "txt2img": {k: v for k, v in zimage.items() if k != "backend_options"},
                    "backend_options": zimage["backend_options"],
                },
            ),
            "c1",
        ),
        "retired_stage_requested_by_config": case(
            tmp_path,
            cli(animatediff={"enabled": True}, pipeline={"animatediff_enabled": True}),
            "c2",
        ),
        "empty_txt2img_prompt": case(tmp_path, cli(prompt=""), "c3"),
        "missing_input_image": not_applicable("the CLI builder takes no input image"),
        "queue_admission": not_applicable(
            "the CLI runs runner.run_njr directly and never crosses JobService.submit_njrs (X14)"
        ),
    }
    # The CLI never reaches the queue; the "admission" half of each case is the same JobService check, run for evidence.
    assert_golden("refusals_cli", scrub(table, tmp_path), tmp_path)


def test_refusals_reprocess(tmp_path: Path, copy_asset: Callable[..., Path]) -> None:
    source = copy_asset("blue_64.png", "in/first.png")

    def reprocess(
        *,
        stages: list[Any] | None = None,
        prompt: str = "p",
        path: Path = source,
        model: str | None = "sdxl.safetensors",
    ) -> Callable[[], Any]:
        return lambda: ReprocessJobBuilder(id_fn=lambda: "refusal-1").build_reprocess_job(
            input_image_paths=[str(path)],
            stages=stages or ["img2img"],
            config={"img2img": {"denoising_strength": 0.4}},
            output_dir=str(tmp_path / "output"),
            prompt=prompt,
            model=model,
        )

    def through_reprocess_wrapper() -> Any:
        job = reprocess(model=ZIMAGE_MODEL)()
        return submit_reprocess_njrs(CapturingJobService(), [job])

    table = {
        "exact_profile_unsupported_img2img_at_builder": case(
            tmp_path, reprocess(model=ZIMAGE_MODEL), "r1"
        ),
        "exact_profile_unsupported_img2img_at_reprocess_wrapper": {
            "wrapper": observe(through_reprocess_wrapper)
        },
        "retired_stage": case(tmp_path, reprocess(stages=["animatediff"]), "r2"),
        "empty_prompt_img2img": case(tmp_path, reprocess(prompt=""), "r3"),
        "missing_input_image": case(tmp_path, reprocess(path=tmp_path / "absent.png"), "r4"),
    }
    assert_golden("refusals_reprocess", scrub(table, tmp_path), tmp_path)


def test_refusals_history(tmp_path: Path) -> None:
    source = variation_source()
    (tmp_path / "exact").mkdir()
    unsupported = prompt_pack_parent(tmp_path / "exact")
    table = {
        "exact_profile_unsupported_replay": case(
            tmp_path,
            lambda: compile_replay_intent(ReplayIntent(unsupported), id_fn=lambda: "h-1"),
            "h1",
        ),
        "retired_stage_replay": case(
            tmp_path,
            lambda: compile_replay_intent(
                ReplayIntent(_enabled_animatediff_njr()), id_fn=lambda: "h-2"
            ),
            "h2",
        ),
        "variation_of_an_enabled_animatediff_record": case(
            tmp_path,
            lambda: compile_history_variation(
                HistoryVariationDraft.from_source(_enabled_animatediff_njr()),
                id_fn=lambda: "h-3",
            ),
            "h3",
        ),
        "empty_prompt_variation": case(
            tmp_path,
            lambda: compile_history_variation(
                HistoryVariationDraft.from_source(source).with_edits(positive_prompt=""),
                id_fn=lambda: "h-4",
            ),
            "h4",
        ),
        "missing_input_image_variation_of_an_input_job": case(
            tmp_path,
            lambda: compile_history_variation(
                HistoryVariationDraft.from_source(
                    variation_source(input_image_paths=("absent.png",))
                ),
                id_fn=lambda: "h-5",
            ),
            "h5",
        ),
    }
    assert_golden("refusals_history", scrub(table, tmp_path), tmp_path)


def test_refusals_learning(tmp_path: Path, copy_asset: Callable[..., Path]) -> None:
    def learning(**design: Any) -> Callable[[], Any]:
        def build() -> Any:
            bench = Bench(tmp_path / f"bench-{len(design)}-{sorted(design)}")
            bench.tmp_path.mkdir(parents=True, exist_ok=True)
            experiment = bench.preview(**design)
            return bench.controller._build_variant_njr(
                bench.controller.learning_state.plan[0], experiment
            )

        return build

    table = {
        "empty_txt2img_prompt": case(tmp_path, learning(prompt=""), "l1"),
        "missing_input_image": case(
            tmp_path,
            learning(
                stage="img2img",
                variable="Denoise Strength",
                values=(0.3, 0.5, 0.2),
                input_image_path=str(tmp_path / "absent.png"),
            ),
            "l2",
        ),
        "exact_profile_unsupported": not_applicable(
            "Learning's exact-profile refusal happens at freeze time for frozen-arm studies; no ordinary-study request "
            "reaches it"
        ),
        "retired_stage": not_applicable(
            "a Learning experiment stage is txt2img, img2img, adetailer or upscale"
        ),
    }
    assert_golden("refusals_learning", scrub(table, tmp_path), tmp_path)


def test_refusals_video(tmp_path: Path, copy_asset: Callable[..., Path]) -> None:
    controller, _service = video_controller(tmp_path)
    source = copy_asset("portrait_480x832.png", "in/portrait.png")

    def workflow(path: Path = source, **form: Any) -> Callable[[], Any]:
        def build() -> Any:
            frozen = controller._njr_builder.freeze_inputs(path, video_form(**form))
            return controller._njr_builder.build_job(video_form(**form), frozen).njr

        return build

    def movie(*paths: Path) -> Callable[[], Any]:
        return lambda: freeze_movie_assembly(
            MovieAssemblyIntent(
                clips=tuple(AssemblyIntentClip(str(path), 0.5) for path in paths), fps=8
            ),
            video_probe=lambda _path: VideoFacts(8, 8, 1.0, None),
            audio_probe=lambda _path: None,
        )

    table = {
        "workflow_missing_input_image": case(tmp_path, workflow(tmp_path / "absent.png"), "v1"),
        "workflow_empty_prompt": case(tmp_path, workflow(prompt=""), "v2"),
        "movie_clips_missing_input_clip": case(
            tmp_path, movie(tmp_path / "absent-1.png", tmp_path / "absent-2.png"), "v3"
        ),
        "exact_profile_unsupported": not_applicable("video routes carry no image model profile"),
        "retired_stage": not_applicable("video routes carry no AnimateDiff stage"),
    }
    assert_golden("refusals_video", scrub(table, tmp_path), tmp_path)
