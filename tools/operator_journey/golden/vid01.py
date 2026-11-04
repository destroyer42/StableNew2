"""VID-01: reference image -> Wan2.2 TI2V video -> in-app preview -> History, through visible controls."""

from __future__ import annotations

import json
from pathlib import Path
from tkinter import ttk
from typing import Any

from tools.operator_journey.golden.gui import select_history_row
from tools.operator_journey.golden.img01 import read_njr
from tools.operator_journey.golden.media import inspect_image, inspect_video, sha256_file
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
    spec = build_default_workflow_registry().get(WORKFLOW_ID, WORKFLOW_VERSION)
    run.require(
        "workflow",
        "workflow_is_approved",
        spec.governance_state == "approved",
        f"{WORKFLOW_ID} {WORKFLOW_VERSION} is {spec.governance_state}",
    )
    source_image = make_reference_image(run.ws.root / "reference" / "lighthouse.png")
    source_sha = sha256_file(source_image)
    ev.observe("reference_image_sha256", source_sha)
    ev.observe("workflow", {"id": WORKFLOW_ID, "version": WORKFLOW_VERSION})

    with fixture_video_runtime(run.fake_comfy, spec) as fixture:
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

        # 3-4. Workflow, motion prompt, length.
        labels = [str(v) for v in tab.workflow_combo.cget("values")]
        wanted = next((v for v in labels if "TI2V-5B" in v), None)
        if wanted is None:
            raise JourneyHold(
                f"the picker does not offer {WORKFLOW_ID} {WORKFLOW_VERSION}: {labels}"
            )
        d.select_combobox(tab.workflow_combo, wanted, label="Workflow")
        d.type_in_text(tab.prompt_text, MOTION_PROMPT, label="Motion prompt")
        lengths = [str(v) for v in tab.frame_count_combo.cget("values")]
        run.require("length", "legal_lengths_offered", bool(lengths), "no frame counts offered")
        d.select_combobox(tab.frame_count_combo, lengths[0], label="Length (smallest legal)")
        ev.observe("requested_length", lengths[0])
        if tab.seed_var.get() != str(SEED):
            d.set_variable(tab.seed_var, str(SEED), label="Seed")

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
            WORKFLOW_ID in blob and WORKFLOW_VERSION in blob,
            "workflow missing",
        )
        run.check(
            "njr", "motion_prompt_in_njr", MOTION_PROMPT in blob, "motion prompt missing from NJR"
        )
        run.check("njr", "seed_in_njr", str(SEED) in blob, "seed missing from NJR")
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
        sent = run.fake_comfy.prompts[0].get("prompt", {})
        frames_requested = next(
            (
                n["inputs"]["length"]
                for n in sent.values()
                if isinstance((n.get("inputs") or {}).get("length"), int)
            ),
            None,
        )
        run.check(
            "artifact",
            "decoded_frames_match_generated_frames",
            frames_requested is not None and media.get("decoded_frames") == frames_requested,
            f"decoded {media.get('decoded_frames')} vs requested {frames_requested}",
        )
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
