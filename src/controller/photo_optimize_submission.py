"""Extracted Photo Optimize preparation/admission from AppController; existing authorities only."""

from __future__ import annotations

from src.photo_optimize.submission import describe_photo_plan, prepare_photo_plan


def prepare(
    controller,
    store,
    *,
    assets,
    stages,
    batch_size=1,
    prompt_delta="",
    negative_prompt_delta="",
    prompt_mode="append",
    negative_prompt_mode="append",
    pipeline_defaults_snapshot=None,
):
    fallback = (pipeline_defaults_snapshot or controller.build_photo_optimize_defaults())["config"]
    return prepare_photo_plan(
        assets=assets,
        stages=stages,
        fallback_config=fallback,
        store=store,
        batch_size=batch_size,
        prompt_delta=prompt_delta,
        negative_prompt_delta=negative_prompt_delta,
        prompt_mode=prompt_mode,
        negative_prompt_mode=negative_prompt_mode,
    )


def submit(controller, plan):
    summary = describe_photo_plan(plan)
    tab = getattr(getattr(controller, "main_window", None), "photo_optimize_tab", None)
    show = getattr(tab, "show_submission_summary", None)
    if callable(show):
        controller._ui_dispatch(lambda: show(summary))
    controller._ui_dispatch(lambda: controller._append_log(summary))
    return controller._submit_reprocess_njrs(plan.jobs, source="photo_optimize_tab")
