"""VID-03: persistent Storyboard to a finished multi-shot sequence, through visible controls and the canonical queue.

A three-shot Storyboard (distinct motion prompts and seeds, a keyframe anchor on the last shot) is saved, the
application is closed and reopened, the draft is opened, a shot is reordered, the sequence summary is previewed and the
sequence is submitted as one job.  Save, Preview and Open never submit; a revised shot never reuses its stale
downstream segments; a workflow that cannot run a sequence refuses with a reason.  The Comfy runtime is the loopback
fixture, so the clips are synthetic and nothing here claims real video quality.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from tools.operator_journey.golden.gui import select_history_row
from tools.operator_journey.golden.img01 import read_njr
from tools.operator_journey.golden.media import inspect_video
from tools.operator_journey.golden.session import GoldenRun, JourneyAbort, JourneyHold, file_identity
from tools.operator_journey.golden.video_fixture import fixture_video_runtime
from tools.operator_journey.golden.vid01 import (
    WORKFLOW_ID,
    WORKFLOW_VERSION,
    make_reference_image,
)

PROMPTS = (
    "the lighthouse beam slowly sweeps across the water",
    "clouds roll in and the sea darkens",
    "dawn breaks over the calm harbour",
)
FORM_PROMPT = "a lighthouse on a rocky coast"
SEEDS = ("1111", "2222", "3333")
CLIP_NAME = "golden_vid03"
REVISED_CLIP = "golden_vid03_revised"
REVISED_PROMPT = "a storm gathers and the lamp burns brighter"
TITLE = "VID-03 lighthouse storyboard"


def _wait_status(run: GoldenRun, panel: Any, needle: str, *, description: str, timeout: float = 60) -> str:
    run.driver.wait_until(
        lambda: needle in panel.status_var.get(), timeout=timeout, description=description,
        evidence=lambda: panel.status_var.get(),
    )
    return str(panel.status_var.get())


def _rows(panel: Any) -> list[dict[str, Any]]:
    return [
        {"prompt": r.prompt_var.get(), "seed": r.seed_var.get(), "keyframe": r.keyframe_var.get(), "shot_id": r.shot_id, "length": r.length_var.get()}
        for r in panel._rows
    ]


def _open_workflow_tab(run: GoldenRun, source_image: Path, form_prompt: str = "") -> Any:
    d, w = run.driver, run.window
    tab = w.video_workflow_tab
    d.select_tab(w.center_notebook, "Video Workflow - Adv")
    run.answer_file(str(source_image))
    d.invoke(d.find_button(tab, "Browse..."), label="Source image Browse")
    d.wait_until(lambda: Path(tab.source_image_var.get()).resolve() == source_image.resolve(), timeout=10, description="the chosen source image is shown")
    labels = [str(v) for v in tab.workflow_combo.cget("values")]
    wanted = next((v for v in labels if "TI2V-5B" in v), None)
    if wanted is None:
        raise JourneyHold(f"the picker does not offer {WORKFLOW_ID} {WORKFLOW_VERSION}: {labels}")
    d.select_combobox(tab.workflow_combo, wanted, label="Workflow")
    d.pump(0.6)
    if form_prompt:
        d.type_in_text(tab.prompt_text, form_prompt, label="Motion prompt (form)")
    return tab


def run_vid03(run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None) -> None:
    from src.pipeline.video import VideoCreator
    from src.video.workflow_registry import build_default_workflow_registry

    if physical is not None:
        raise JourneyAbort("VID-03 has no physical lane")
    if not VideoCreator().ffmpeg_available:
        raise JourneyHold("FFmpeg is not available on this host, so the video encoder cannot produce the clip")
    ev = run.ev
    spec = build_default_workflow_registry().get(WORKFLOW_ID, WORKFLOW_VERSION)
    source_image = make_reference_image(run.ws.root / "reference" / "lighthouse.png")
    anchor_image = run.ws.root / "reference" / "dawn_anchor.png"
    _make_anchor(anchor_image)
    with fixture_video_runtime(run.fake_comfy, spec) if simulated else nullcontext({}):
        run.boot_app()
        d = run.driver
        tab = _open_workflow_tab(run, source_image, FORM_PROMPT)
        panel = tab.sequence_panel
        comfy = run.fake_comfy

        # 1-4. Author a three-shot Storyboard: distinct prompts and seeds, an anchor on the last shot.
        d.set_variable(tab.seed_var, SEEDS[0], label="Form seed (shot 1)")
        d.invoke(panel.add_button, label="Add shot")
        d.wait_until(lambda: len(panel._rows) == 3, timeout=10, description="the panel offers a third shot")
        lengths = [str(v) for v in panel._rows[0].length_combo.cget("values")]
        run.require("storyboard", "legal_lengths_offered", bool(lengths), "no sequence lengths offered")
        for index, row in enumerate(panel._rows):
            d.set_variable(row.prompt_var, PROMPTS[index], label=f"Shot {index + 1} motion prompt")
            d.select_combobox(row.length_combo, lengths[0], label=f"Shot {index + 1} length")
            d.set_variable(row.seed_var, SEEDS[index], label=f"Shot {index + 1} seed")
        run.answer_file(str(anchor_image))
        d.invoke(panel._rows[2].browse_button, label="Shot 3 keyframe Browse")
        d.wait_until(lambda: Path(panel._rows[2].keyframe_var.get()).name == anchor_image.name, timeout=10, description="the anchor is shown")
        d.set_variable(panel.title_var, TITLE, label="Storyboard title")
        d.set_variable(panel.clip_name_var, CLIP_NAME, label="Clip name")
        authored = _rows(panel)
        run.snap("authored")
        d.invoke(d.find_button(panel, "Save"), label="Storyboard: Save")
        saved_path = d.wait_until(
            lambda: next(iter(sorted(panel.store.root.glob("*.json"))), None),
            timeout=30,
            description="the Storyboard draft is saved",
            evidence=lambda: panel.status_var.get(),
        )
        saved_identity = file_identity(Path(saved_path))
        saved_doc = json.loads(Path(saved_path).read_text(encoding="utf-8"))
        ev.observe("storyboard_saved", {"path": str(saved_path), "sha256": saved_identity["sha256"], "shots": len(saved_doc.get("shots", []))})
        run.check("persist", "draft_saved_inside_the_isolated_workspace", str(run.ws.root.resolve()).lower() in str(Path(saved_path).resolve()).lower(), f"{saved_path}")
        run.check("persist", "draft_holds_three_shots_with_prompts", len(saved_doc.get("shots", [])) == 3 and all(p in json.dumps(saved_doc) for p in PROMPTS), f"{saved_doc.get('shots')}")
        run.check("persist", "saving_submitted_no_job", not run.submissions.calls and not run.job_rows(), f"{run.submissions.calls} {len(run.job_rows())}")
        run.check("persist", "saving_sent_nothing_to_the_backend", not comfy.prompts, f"{len(comfy.prompts)} /prompt requests")

        # 5-7. Close and reopen StableNew; the draft is independent of any job; open it from the file dialog.
        run.shutdown_app()
        run.boot_app()
        d = run.driver
        tab = _open_workflow_tab(run, source_image, FORM_PROMPT)
        panel = tab.sequence_panel
        run.check("persist", "reopened_app_starts_without_the_draft", _rows(panel) != authored, "the draft survived without being opened")
        run.answer_file(str(saved_path))
        d.invoke(d.find_button(panel, "Open"), label="Storyboard: Open")
        d.wait_until(lambda: len(panel._rows) == 3 and panel._rows[0].prompt_var.get() == PROMPTS[0], timeout=20, description="the saved draft is shown", evidence=lambda: panel.status_var.get())
        reopened = _rows(panel)
        run.snap("reopened")
        keys = ("prompt", "seed", "shot_id")
        run.check("persist", "reopened_draft_matches_what_was_saved", [{k: r[k] for k in keys} for r in reopened] == [{k: r[k] for k in keys} for r in authored] or [(r["prompt"], r["seed"]) for r in reopened] == [(r["prompt"], r["seed"]) for r in authored], f"{reopened} vs {authored}")
        run.check("persist", "anchor_survives_reopen", Path(reopened[2]["keyframe"]).name == anchor_image.name, f"{reopened[2]['keyframe']!r}")
        run.check("persist", "opening_submitted_nothing", not run.submissions.calls and not run.job_rows(), f"{run.submissions.calls}")

        # 8. Reorder shot 1 below shot 2: prompts, seeds, identities and the anchor travel with their shots.
        before_ids = {r["prompt"]: (r["seed"], r["shot_id"]) for r in reopened}
        d.invoke(panel._rows[0].down_button, label="Shot 1 Move Down")
        d.pump(0.4)
        reordered = _rows(panel)
        ev.observe("reordered", reordered)
        run.check("reorder", "order_changed", [r["prompt"] for r in reordered] == [PROMPTS[1], PROMPTS[0], PROMPTS[2]], f"{[r['prompt'] for r in reordered]}")
        run.check("reorder", "seeds_and_shot_ids_travel_with_their_prompts", {r["prompt"]: (r["seed"], r["shot_id"]) for r in reordered} == before_ids, f"{reordered}")
        run.check("reorder", "anchor_stays_on_its_shot", Path(reordered[2]["keyframe"]).name == anchor_image.name and not reordered[0]["keyframe"] and not reordered[1]["keyframe"], f"{reordered}")
        d.invoke(d.find_button(panel, "Save"), label="Storyboard: Save")
        d.wait_until(lambda: file_identity(Path(saved_path))["sha256"] != saved_identity["sha256"], timeout=20, description="the reordered draft is saved", evidence=lambda: panel.status_var.get())
        reordered_identity = file_identity(Path(saved_path))

        # 9. Preview the sequence summary (read-only): nothing is submitted.
        d.invoke(d.find_button(panel, "Preview Sequence Summary"), label="Preview Sequence Summary")
        summary = _wait_status(run, panel, "admission checks", description="the sequence summary is shown")
        ev.observe("sequence_summary", summary)
        run.snap("summary")
        run.check("preview", "summary_names_three_shots", "3" in summary, f"{summary!r}")
        run.check("preview", "preview_submitted_nothing", not run.submissions.calls and not run.job_rows() and not comfy.prompts, f"{run.submissions.calls}")

        # 10-11. Submit the sequence: one job, one NJR, one segment request per shot.
        d.invoke(panel.queue_button, label="Queue Sequence")
        d.wait_until(lambda: len(run.job_rows()) >= 1, timeout=60, description="the sequence job is queued", evidence=lambda: panel.status_var.get())
        run.assert_plan_agreed()
        rows = run.wait_jobs_terminal(1, description="the sequence job reaches a terminal state")
        job = rows[0]
        ev.observe("sequence_job", job)
        run.snap("queue_done")
        run.require("execute", "sequence_completed", job["status"] == "completed", f"{job['status']}: {job['error_message']}")
        run.check("execute", "one_job_one_submission", len(rows) == 1 and len(run.submissions.calls) == 1, f"{len(rows)} rows, {run.submissions.calls}")
        run.check("execute", "one_segment_request_per_shot", len(comfy.prompts) == 3, f"{len(comfy.prompts)} /prompt requests")
        njr = read_njr(run.repository_path, job["job_id"])
        blob = json.dumps(njr, default=str)
        positions = [blob.find(p) for p in (PROMPTS[1], PROMPTS[0], PROMPTS[2])]
        run.check("njr", "shots_frozen_in_the_reordered_order", all(p >= 0 for p in positions) and positions == sorted(positions), f"{positions}")
        run.check("njr", "workflow_identity_in_njr", WORKFLOW_ID in blob and WORKFLOW_VERSION in blob, "workflow missing")
        run.check("persist", "queueing_did_not_rewrite_the_saved_draft", file_identity(Path(saved_path))["sha256"] == reordered_identity["sha256"], "the Storyboard file changed on submit")
        videos = [Path(r) for r in job["artifact_references"] if Path(r).suffix.lower() in {".mp4", ".webm", ".mov"}]
        ev.observe("sequence_artifacts", [str(v) for v in videos])
        run.require("artifact", "movie_recorded", bool(videos), f"{job['artifact_references']}")
        finished = max(videos, key=lambda p: p.stat().st_size if p.exists() else 0)
        movie = inspect_video(finished)
        ev.observe("movie_media", movie)
        run.check("artifact", "assembled_movie_decodes", movie["valid"], str(movie.get("error")))
        segment_media = [inspect_video(v) for v in videos]
        run.check("artifact", "every_recorded_clip_decodes", all(m["valid"] for m in segment_media), f"{[m.get('error') for m in segment_media]}")

        # 12. History and lineage.
        d.select_tab(run.window.center_notebook, "Pipeline")
        history = select_history_row(run, job["job_id"])
        entry = history._entries.get(job["job_id"])
        run.check("history", "history_record_completed", entry is not None and str(entry.status).lower().endswith("completed"), f"{entry!r}")
        run.snap("history")

        # 13. A revised shot never silently reuses its stale downstream segments.
        d.select_tab(run.window.center_notebook, "Video Workflow - Adv")
        requests_before = len(comfy.prompts)
        d.set_variable(panel._rows[1].prompt_var, REVISED_PROMPT, label="Shot 2 motion prompt (revised)")
        d.set_variable(panel.clip_name_var, REVISED_CLIP, label="Clip name")
        d.invoke(panel.queue_button, label="Queue Sequence (revised)")
        d.wait_until(lambda: len(run.job_rows()) >= 2, timeout=60, description="the revised sequence is queued", evidence=lambda: panel.status_var.get())
        run.wait_jobs_terminal(2, description="the revised sequence reaches a terminal state")
        revised_requests = len(comfy.prompts) - requests_before
        second = next(r for r in run.job_rows() if r["job_id"] != job["job_id"])
        ev.observe("revised_requests", revised_requests)
        run.check("revise", "revised_sequence_completed", second["status"] == "completed", f"{second['status']}: {second['error_message']}")
        run.check("revise", "revised_shot_and_everything_after_it_regenerated", revised_requests >= 2, f"{revised_requests} segment requests after revising shot 2 of 3")
        inputs = {str(source_image.resolve()).lower(), str(anchor_image.resolve()).lower()}
        generated = lambda row: {r for r in row["artifact_references"] if Path(r).resolve().as_posix().lower() not in {Path(i).as_posix() for i in inputs} and "prepared_video_sources" not in r}  # noqa: E731
        shared = sorted(generated(second) & generated(job))
        ev.observe("revised_shared_artifacts", shared)
        run.check("revise", "no_artifact_of_the_first_run_reused", not shared, f"the revised job recorded the first run's artifacts: {shared[:3]}")

        # Unsupported sequencing refuses accurately (Fun Control is experimental and not a sequence workflow).
        labels = [str(v) for v in tab.workflow_combo.cget("values")]
        fun = next((v for v in labels if "Fun Control" in v), None)
        if fun is not None:
            submitted = len(run.submissions.calls)
            d.select_combobox(tab.workflow_combo, fun, label="Workflow")
            d.pump(0.6)
            d.invoke(d.find_button(panel, "Preview Sequence Summary"), label="Preview Sequence Summary")
            d.pump(2.0)
            fun_preview = str(panel.status_var.get())
            d.invoke(panel.queue_button, label="Queue Sequence (Fun Control)")
            d.pump(3.0)
            fun_queue = str(panel.status_var.get())
            ev.observe("fun_control_refusal", {"preview": fun_preview, "queue": fun_queue})
            run.snap("fun_control")
            run.check("refuse", "fun_control_sequence_not_submitted", len(run.submissions.calls) == submitted and len(run.job_rows()) == 2, f"{run.submissions.calls}")
            run.check("refuse", "refusal_gives_a_reason", bool((fun_preview + fun_queue).strip()) and fun_queue != "", f"preview={fun_preview!r} queue={fun_queue!r}")

        # Reopen the saved Storyboard once more (still a draft, still independent of the jobs).
        run.answer_file(str(saved_path))
        d.invoke(d.find_button(panel, "Open"), label="Storyboard: Open")
        d.pump(1.5)
        run.check("persist", "saved_draft_reopens_after_the_jobs", [r["prompt"] for r in _rows(panel)] == [PROMPTS[1], PROMPTS[0], PROMPTS[2]], f"{_rows(panel)}")
        run.check("persist", "reopening_submitted_nothing_more", len(run.job_rows()) == 2, f"{len(run.job_rows())} jobs")
        run.checkpoint("vid03_done")
        run.shutdown_app()
    if not ev.checks:
        raise JourneyAbort("no checks recorded")


def _make_anchor(path: Path) -> None:
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (480, 832), (200, 150, 90))
    ImageDraw.Draw(image).ellipse([140, 316, 340, 516], fill=(250, 220, 120))
    image.save(path)
