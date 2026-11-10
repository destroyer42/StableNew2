"""VID-01: reference image -> Wan2.2 TI2V video -> in-app preview -> History, through visible controls."""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from pathlib import Path
from tkinter import ttk
from typing import Any

from tools.operator_journey.golden.gui import select_history_row
from tools.operator_journey.golden.img01 import read_njr
from tools.operator_journey.golden.media import inspect_image, inspect_video, sha256_file
from tools.operator_journey.golden.provenance import settings_report, text_identity
from tools.operator_journey.golden.session import GoldenRun, JourneyAbort, JourneyHold
from tools.operator_journey.golden.video_fixture import fixture_video_runtime

WORKFLOW_ID = "wan22_ti2v_5b_i2v_v1"
WORKFLOW_VERSION = "1.3.0"
MOTION_PROMPT = "the lighthouse beam slowly sweeps across the water"
SEED = 7001


def make_reference_image(path: Path) -> Path:
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 640), (30, 60, 110))
    ImageDraw.Draw(image).polygon(
        [(300, 560), (340, 560), (330, 200), (310, 200)], fill=(235, 235, 235)
    )
    image.save(path)
    return path


def run_vid01(
    run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None
) -> None:
    from src.video.workflow_registry import build_default_workflow_registry

    ev = run.ev
    # A physical run reads every operator-controlled value from its frozen plan and touches no fake backend.
    frozen = physical or {}
    frozen_settings, frozen_inputs = frozen.get("settings") or {}, frozen.get("inputs") or {}
    frozen_workflow = frozen.get("workflow") or {}
    workflow_id = str(frozen_workflow.get("id") or WORKFLOW_ID)
    workflow_version = str(frozen_workflow.get("version") or WORKFLOW_VERSION)
    motion_prompt = str(frozen_inputs.get("motion_prompt") or MOTION_PROMPT)
    seed = int(frozen_settings.get("seed", SEED))
    from src.pipeline.video import VideoCreator

    if (
        not VideoCreator().ffmpeg_available
    ):  # the product's own encoder needs it; a missing tool is a HOLD, never a fake PASS
        raise JourneyHold(
            "FFmpeg is not available on this host, so the video encoder cannot produce the clip"
        )
    spec = build_default_workflow_registry().get(workflow_id, workflow_version)
    run.require(
        "workflow",
        "workflow_is_approved",
        spec.governance_state == "approved",
        f"{workflow_id} {workflow_version} is {spec.governance_state}",
    )
    assets = frozen.get("source_assets") or []
    if assets:
        source_image = Path(str(assets[0]["path"]))
        if not source_image.is_file() or sha256_file(source_image) != assets[0].get("sha256"):
            raise JourneyHold(
                f"the planned source image {source_image} is missing or changed since freezing"
            )
    else:
        source_image = make_reference_image(run.ws.root / "reference" / "lighthouse.png")
    source_sha = sha256_file(source_image)
    ev.observe("reference_image_sha256", source_sha)
    ev.observe("workflow", {"id": workflow_id, "version": workflow_version})

    fixture_cm = fixture_video_runtime(run.fake_comfy, spec) if simulated else nullcontext({})
    with fixture_cm as fixture:
        if simulated:
            ev.observe(
                "comfy_runtime",
                {"base_url": run.fake_comfy.base_url, "command_flags": fixture["command"][4:]},
                source="simulated_fixture",
            )
            ev.observe(
                "resource_probes",
                {"ram_gb": 24.0, "vram_mib": [12282.0, 11000.0], "asset_integrity": "skipped"},
                source="simulated_fixture",
            )
        run.boot_app()
        d, w = run.driver, run.window
        tab = w.video_workflow_tab

        # 1-2. Video Workflow tab; choose the reference image through the file dialog.
        d.select_tab(w.center_notebook, "Video Workflow - Adv")
        run.answer_file(str(source_image))
        d.invoke(d.find_button(tab, "Browse..."), label="Source image Browse")
        d.wait_until(
            lambda: Path(tab.source_image_var.get()).resolve() == source_image.resolve(),
            timeout=10,
            description="the chosen source image is shown",
        )
        run.snap("source")

        # 3-4. Engine, motion prompt, length.
        if not tab.advanced_section.is_expanded():
            # The engine and its settings are filled in for the task; an operator who wants a specific one opens
            # the Settings editor with "Change".
            d.invoke(tab.suggested_line.change_button, label="Settings: Change")
            d.pump(0.5)
        labels = [str(v) for v in tab.workflow_combo.cget("values")]
        wanted = next((v for v in labels if "TI2V-5B" in v), None)
        if wanted is None:
            raise JourneyHold(
                f"the picker does not offer {workflow_id} {workflow_version}: {labels}"
            )
        d.select_combobox(tab.workflow_combo, wanted, label="Engine")
        d.type_in_text(tab.prompt_text, motion_prompt, label="Motion prompt")
        lengths = [str(v) for v in tab.frame_count_combo.cget("values")]
        run.require("length", "legal_lengths_offered", bool(lengths), "no frame counts offered")
        wanted_frames = frozen_settings.get("frames")
        chosen_length = lengths[0]
        if wanted_frames is not None:
            chosen_length = next(
                (
                    v
                    for v in lengths
                    if re.match(r"\d+", v)
                    and int(re.match(r"\d+", v).group()) == int(wanted_frames)
                ),
                "",
            )
            if not chosen_length:
                raise JourneyHold(
                    f"the plan asks for {wanted_frames} frames, which the GUI does not offer ({lengths})"
                )
        d.select_combobox(tab.frame_count_combo, chosen_length, label="Length")
        ev.observe("requested_length", chosen_length)
        if tab.seed_var.get() != str(seed):
            d.set_variable(tab.seed_var, str(seed), label="Seed")
        # Smoothing is suggested whenever RIFE is installed.  This journey proves the workflow's own clip, so it
        # runs unsmoothed on every host unless the frozen plan asks for smoothing.
        wanted_smooth = bool(frozen_settings.get("smooth", False))
        if bool(tab.smooth_var.get()) != wanted_smooth:
            d.invoke(tab.smooth_check, label="Smooth motion")
        ev.observe("requested_smoothing", wanted_smooth)

        # 5-6. Source preparation and readiness are shown; Queue must be enabled by the real gates.
        d.pump(1.0)
        ev.observe("source_summary", str(tab.source_summary_var.get()))
        ev.observe("queue_block_reason", str(tab.queue_block_reason_var.get()))
        d.wait_until(
            lambda: tab.queue_workflow_button.instate(["!disabled"]),
            timeout=30,
            description="Queue Video Workflow is enabled by the readiness gates",
            evidence=lambda: str(tab.queue_block_reason_var.get()),
        )
        run.snap("ready")
        # Preview Frozen Plan switches the tab into its one-source batch mode, which by design disables the
        # single-image Queue button; this journey takes the single-image path and only records the offer.
        ev.observe("frozen_plan_preview_offered", bool(tab.frozen_plan_button.winfo_ismapped()))
        run.check(
            "submit",
            "nothing_queued_before_submit",
            not run.submissions.calls,
            f"{run.submissions.calls}",
        )

        # 7-8. Submit and observe.
        d.invoke(tab.queue_workflow_button, label="Queue Video Workflow")
        run.assert_plan_agreed()
        rows = run.wait_jobs_terminal(1, description="the video job reaches a terminal state")
        run.snap("queue_done")
        job = rows[0]
        ev.observe("job_row", job)
        run.require(
            "execute",
            "job_completed",
            job["status"] == "completed",
            f"{job['status']}: {job['error_message']}",
        )
        run.check(
            "execute",
            "submitted_once_through_job_service",
            len(run.submissions.calls) == 1,
            f"{run.submissions.calls}",
        )
        if run.fake_comfy is not None:
            run.check(
                "execute",
                "one_generation_request",
                len(run.fake_comfy.prompts) == 1,
                f"{len(run.fake_comfy.prompts)} /prompt requests",
            )
            run.check(
                "execute",
                "backend_received_source_image",
                len(run.fake_comfy.uploads) >= 1,
                "no image upload seen",
            )

        # NJR carries the visible intent and the exact workflow identity.
        njr = read_njr(run.repository_path, job["job_id"])
        blob = json.dumps(njr, default=str)
        run.check(
            "njr",
            "workflow_identity_in_njr",
            workflow_id in blob and workflow_version in blob,
            "workflow missing",
        )
        run.check(
            "njr", "motion_prompt_in_njr", motion_prompt in blob, "motion prompt missing from NJR"
        )
        run.check("njr", "seed_in_njr", str(seed) in blob, "seed missing from NJR")
        run.check(
            "njr",
            "source_identity_in_njr",
            source_sha in blob or source_image.name in blob,
            "source image identity missing from NJR",
        )

        # 9-10. The clip: a real, decodable video with frame count, fps and geometry.
        videos = [
            Path(r)
            for r in job["artifact_references"]
            if Path(r).suffix.lower() in {".mp4", ".webm", ".mov"}
        ]
        run.require(
            "artifact",
            "video_artifact_recorded",
            len(videos) >= 1,
            f"refs {job['artifact_references']}",
        )
        media = inspect_video(videos[0])
        ev.observe("video_media", media)
        run.check("artifact", "video_decodes", media["valid"], str(media.get("error")))
        # The expected clip length is read from the frozen NJR (and, in the simulated lane, the request the loopback
        # backend received); a physical run has no fake to read.
        frames_requested = (
            (((njr.get("normalized_job") or njr).get("workload") or {}).get("config") or {})
            .get("video_workflow", {})
            .get("frame_count")
        )
        if run.fake_comfy is not None and run.fake_comfy.prompts:
            sent = run.fake_comfy.prompts[0].get("prompt", {})
            frames_requested = next(
                (
                    n["inputs"]["length"]
                    for n in sent.values()
                    if isinstance((n.get("inputs") or {}).get("length"), int)
                ),
                frames_requested,
            )
        run.check(
            "artifact",
            "decoded_frames_match_generated_frames",
            frames_requested is not None and media.get("decoded_frames") == frames_requested,
            f"decoded {media.get('decoded_frames')} vs requested {frames_requested}",
        )
        requested = {
            "workflow": f"{workflow_id} {workflow_version}",
            "length": int(re.match(r"\d+", chosen_length).group()),
            "seed": seed,
            "motion_prompt": text_identity(motion_prompt),
        }
        observed = {
            "length": frames_requested,
            "workflow": None,
            "seed": None,
            "motion_prompt": None,
        }
        for key, value in (
            (
                "workflow",
                f"{workflow_id} {workflow_version}"
                if workflow_id in blob and workflow_version in blob
                else None,
            ),
            ("seed", seed if str(seed) in blob else None),
            ("motion_prompt", text_identity(motion_prompt) if motion_prompt in blob else None),
        ):
            observed[key] = value  # read back from the frozen NJR
        ev.observe("requested_settings", requested)
        ev.observe(
            "observed_settings",
            {**observed, "from": "frozen NJR and the request received by the loopback backend"},
        )
        ev.observe("settings_report", settings_report(requested, observed))
        if simulated:
            ev.observe(
                "fixture_video_generator",
                "FakeComfy synthetic PNG frames encoded by StableNet's frame encoder",
                source="simulated_fixture",
            )

        # 11. History shows the clip in-app.
        d.select_tab(w.center_notebook, "Pipeline")
        panel = select_history_row(run, job["job_id"])
        if not panel.show_artifact_var.get():
            d.invoke(
                d.find(panel, (ttk.Checkbutton,), text="Show media"), label="History Show media"
            )
        d.wait_until(
            lambda: panel._shown_artifact_kind == "video",
            timeout=20,
            description="History shows the recorded clip as video",
        )
        run.snap("history")
        run.check(
            "history",
            "history_video_is_the_job_clip",
            Path(str(panel._shown_artifact_path)).resolve() == videos[0].resolve(),
            f"{panel._shown_artifact_path} != {videos[0]}",
        )

        # 12. Send to Movie Clips without submitting another job.
        before = len(run.submissions.calls)
        if panel.movie_clips_btn.instate(["!disabled"]):
            d.invoke(panel.movie_clips_btn, label="History: Movie Clips")
            d.pump(1.0)
            run.check(
                "handoff",
                "movie_clips_handoff_submits_nothing",
                len(run.submissions.calls) == before,
                f"{len(run.submissions.calls) - before} extra submissions",
            )
        else:
            ev.observe("movie_clips_handoff", "button not enabled for this record")
        run.checkpoint("vid01_done")
        run.shutdown_app()
    if not ev.checks:
        raise JourneyAbort("no checks recorded")


__all__ = ["run_vid01", "inspect_image"]
