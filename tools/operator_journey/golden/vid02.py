"""VID-02: motion assets to a usable driving video, through visible controls and without any GPU work.

Lane A (Batch Convert Motion): a test-owned folder of disposable motion assets (two BVH files, a placeholder FBX, a
nested folder, a stray text file and an empty BVH) is scanned in the dry-run inventory.  The conversion itself needs
Blender; none is installed on a host that cannot run it, so the lane stops there as a HOLD and never fakes a render.

Lane B (pre-rendered video, clearly labelled): a small H.264 clip that the journey writes with FFmpeg stands in for the
output a conversion would produce.  It is imported into the Motion Library, found again after a restart and handed to
the workflow with Use as Driving Video.  That proves registration, identity and hand-off, not conversion quality.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from tools.operator_journey.golden.media import inspect_video
from tools.operator_journey.golden.session import (
    GoldenRun,
    JourneyAbort,
    JourneyHold,
    file_identity,
)
from tools.operator_journey.golden.vid01 import WORKFLOW_ID, WORKFLOW_VERSION, make_reference_image
from tools.operator_journey.golden.video_fixture import fixture_video_runtime
from tools.operator_journey.tk_driver import iter_widgets

_BVH = (
    "HIERARCHY\nROOT Hips\n{\n  OFFSET 0 0 0\n  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation\n"
    "  JOINT Spine\n  {\n    OFFSET 0 10 0\n    CHANNELS 3 Zrotation Xrotation Yrotation\n    End Site\n    {\n"
    "      OFFSET 0 10 0\n    }\n  }\n}\nMOTION\nFrames: 4\nFrame Time: 0.0333333\n"
    "0 0 0 0 0 0 0 0 0\n0 1 0 0 0 0 0 0 0\n0 2 0 0 0 0 0 0 0\n0 3 0 0 0 0 0 0 0\n"
)
CLIP_NAME = "golden_vid02_driving"


def _write_assets(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "nested").mkdir(exist_ok=True)
    files = {
        "walk.bvh": root / "walk.bvh",
        "run.bvh": root / "run.bvh",
        "dance.fbx": root / "nested" / "dance.fbx",
        "empty.bvh": root / "empty.bvh",
        "notes.txt": root / "notes.txt",
    }
    files["walk.bvh"].write_text(_BVH, encoding="utf-8")
    files["run.bvh"].write_text(_BVH.replace("Frames: 4", "Frames: 4 "), encoding="utf-8")
    files["dance.fbx"].write_bytes(b"Kaydara FBX Binary  \x00disposable operator-journey placeholder")
    files["empty.bvh"].write_bytes(b"")
    files["notes.txt"].write_text("not a motion asset", encoding="utf-8")
    return files


def _make_clip(path: Path) -> Path:
    from PIL import Image, ImageDraw

    from src.pipeline.video import VideoCreator

    frames = path.parent / "clip_frames"
    frames.mkdir(parents=True, exist_ok=True)
    images = []
    for index in range(24):
        frame = Image.new("RGB", (480, 832), (30, 30, 60))
        ImageDraw.Draw(frame).ellipse([40 + index * 12, 300, 140 + index * 12, 400], fill=(240, 200, 80))
        target = frames / f"f{index:03d}.png"
        frame.save(target)
        images.append(target)
    if not VideoCreator().create_video_from_images(images, path, fps=24, require_all_frames=True):
        raise JourneyHold("FFmpeg could not encode the pre-rendered clip used for lane B")
    return path


def _toplevel(root: tk.Misc, kind: type) -> Any:
    return next((w for w in iter_widgets(root) if isinstance(w, kind) and w.winfo_exists()), None)


def run_vid02(run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None) -> None:
    from src.gui.views.motion_batch_dialog import MotionBatchDialog
    from src.pipeline.video import VideoCreator
    from src.video.workflow_registry import build_default_workflow_registry

    if physical is not None:
        raise JourneyAbort("VID-02 has no physical lane")
    if not VideoCreator().ffmpeg_available:
        raise JourneyHold("FFmpeg is not available on this host, so the pre-rendered clip cannot be produced")
    ev = run.ev
    hold_reason = ""
    assets = _write_assets(run.ws.root / "motion_assets")
    originals = {name: file_identity(path) for name, path in assets.items()}
    library_root = run.ws.root / "motion_library"
    library_root.mkdir(parents=True, exist_ok=True)
    clip = _make_clip(run.ws.root / "prerendered" / f"{CLIP_NAME}.mp4")
    clip_identity = file_identity(clip)
    ev.observe("prerendered_clip", {"path": str(clip), "sha256": clip_identity["sha256"], "media": inspect_video(clip)})
    source_image = make_reference_image(run.ws.root / "reference" / "motion_target.png")
    spec = build_default_workflow_registry().get(WORKFLOW_ID, WORKFLOW_VERSION)

    with fixture_video_runtime(run.fake_comfy, spec):
        run.boot_app()
        d, w = run.driver, run.window
        tab = w.video_workflow_tab
        d.select_tab(w.center_notebook, "Video Workflow - Adv")
        panel = tab.motion_library_panel

        # 1. Choose the library folder (a test-owned directory), then Lane A: Batch Convert Motion.
        run.answer_file(str(library_root))
        d.invoke(panel.choose_button, label="Motion Library: Choose library folder...")
        d.wait_until(lambda: "ibrary" in panel.status_var.get(), timeout=20, description="the library folder is accepted", evidence=lambda: panel.status_var.get())
        run.snap("library_chosen")
        d.invoke(panel.batch_button, label="Motion Library: Batch Convert Motion...")
        dialog = d.wait_until(lambda: _toplevel(run.root, MotionBatchDialog), timeout=15, description="Batch Convert Motion opens")
        d.pump(1.0)
        run.snap("batch_open")
        blender_text = str(dialog.session.view().blender_text)
        ev.observe("batch_initial", {"blender": blender_text, "status": dialog.status_var.get()})
        run.check("batch", "dialog_states_the_blender_situation", bool(blender_text.strip()), f"{blender_text!r}")

        run.answer_file(str(run.ws.root / "motion_assets"))
        d.invoke(dialog.folder_button, label="Batch: Choose folder...")
        d.wait_until(lambda: dialog.session.inventory is not None, timeout=60, description="the dry-run inventory is shown", evidence=lambda: dialog.status_var.get())
        d.pump(0.5)
        run.snap("batch_inventory")
        inventory_lines = [str(line) for line in dialog.session.view().inventory_lines]
        ev.observe("batch_inventory", {"lines": inventory_lines, "status": dialog.status_var.get(), "estimate": list(dialog.session.view().estimate_lines)})
        text = "\n".join(inventory_lines)
        run.check("batch", "inventory_counts_two_convertible_and_three_ineligible", "Will convert: 2" in text and "Not eligible (no rig, no animation, unsupported or unreadable): 3" in text, text[:400])
        run.check("batch", "ineligible_files_say_why", "Not a BVH file" in text and "unrecognized header" in text, text[:600])
        run.check("batch", "scan_converted_nothing", not (library_root.exists() and any(library_root.rglob("*.mp4"))), "an mp4 appeared during the dry run")
        run.check("batch", "originals_untouched_by_the_scan", {n: file_identity(p) for n, p in assets.items()} == originals, "an original changed during the scan")

        # Conversion needs Blender: if none is registered the actions must be unavailable and say why.
        blender_ready = dialog.session.install is not None
        sample_blocked = dialog.sample_button.instate(["disabled"])
        ev.observe("conversion_lane", {"blender_registered": blender_ready, "sample_disabled": sample_blocked, "status": dialog.status_var.get()})
        if not blender_ready:
            run.check("batch", "conversion_is_unavailable_without_blender", sample_blocked, "Convert sample is enabled although no Blender is registered")
            run.check("batch", "unavailability_is_explained", "lender" in (dialog.status_var.get() + blender_text), f"{dialog.status_var.get()!r}")
            hold_reason = "Blender is not installed or registered on this host: the conversion lane (Convert sample / Convert remaining) is HOLD and no render was faked; lane B used a labelled pre-rendered clip"
        d.invoke(d.find_button(dialog, "Close"), label="Batch: Close") if _has_button(dialog, "Close") else dialog.destroy()
        d.pump(0.4)
        run.check("batch", "no_job_was_queued", not run.job_rows() and not run.submissions.calls, f"{run.submissions.calls}")
        run.check("batch", "originals_still_identical_after_the_dialog", {n: file_identity(p) for n, p in assets.items()} == originals, "an original changed")

        # 2. Lane B: import the pre-rendered clip (clearly a stand-in for a conversion's output).
        run.answer_file(str(clip))
        d.invoke(panel.import_file_button, label="Motion Library: Import video...")
        d.wait_until(lambda: len(panel.tree.get_children()) >= 1, timeout=60, description="the library lists the imported clip", evidence=lambda: panel.status_var.get())
        d.pump(0.8)
        run.snap("library_imported")
        rows = list(panel.tree.get_children())
        row_values = [tuple(str(v) for v in panel.tree.item(i, "values")) for i in rows]
        ev.observe("library_rows", row_values)
        run.check("library", "clip_is_listed_once", len(rows) == 1, f"{row_values}")
        run.check("library", "listed_by_its_name", CLIP_NAME in " ".join(row_values[0]) if row_values else False, f"{row_values}")
        run.check("library", "import_left_the_original_clip_unchanged", file_identity(clip) == clip_identity, "the source clip changed")
        asset_id = rows[0]

        # 3. Restart: the library and the asset identity survive.
        run.shutdown_app()
        run.boot_app()
        d, w = run.driver, run.window
        tab = w.video_workflow_tab
        d.select_tab(w.center_notebook, "Video Workflow - Adv")
        panel = tab.motion_library_panel
        d.wait_until(lambda: panel.tree.exists(asset_id), timeout=30, description="the reopened library lists the clip", evidence=lambda: panel.status_var.get())
        run.snap("library_reopened")
        run.check("library", "asset_identity_survives_restart", panel.tree.exists(asset_id), f"{list(panel.tree.get_children())}")

        # 4. Use as Driving Video: the workflow receives the library clip, with its identity.
        run.answer_file(str(source_image))
        d.invoke(d.find_button(tab, "Browse..."), label="Source image Browse")
        d.wait_until(lambda: Path(tab.source_image_var.get()).resolve() == source_image.resolve(), timeout=10, description="the source image is shown")
        fun = next((v for v in tab.workflow_combo.cget("values") if "Fun Control" in str(v)), None)
        if fun is None:
            raise JourneyHold("the workflow picker offers no driving-video workflow")
        d.select_combobox(tab.workflow_combo, str(fun), label="Workflow")
        d.pump(0.6)
        d.select_tree_row(panel.tree, asset_id, label="Motion Library row")
        d.wait_until(lambda: not panel.use_button.instate(["disabled"]), timeout=15, description="Use as Driving Video becomes available")
        run.snap("clip_selected")
        d.invoke(panel.use_button, label="Use as Driving Video")
        d.pump(1.0)
        driving = str(tab.pose_video_var.get())
        ev.observe("driving_video", driving)
        run.snap("driving_set")
        run.check("handoff", "driving_video_field_points_at_the_library_clip", bool(driving) and Path(driving).name.endswith(".mp4"), f"{driving!r}")
        run.check("handoff", "driving_clip_is_the_imported_file", bool(driving) and Path(driving).exists() and file_identity(Path(driving))["sha256"] == clip_identity["sha256"], f"{driving!r}")
        run.check("handoff", "hand_off_queued_nothing", not run.job_rows() and not run.submissions.calls, f"{run.submissions.calls}")

        # 5. The target workflow's readiness, as the operator sees it.
        readiness = getattr(tab, "motion_readiness_panel", None)
        shown = ""
        if readiness is not None:
            d.pump(2.0)
            shown = " | ".join(
                str(wd.cget("text")) for wd in iter_widgets(readiness) if isinstance(wd, (tk.Label,)) or wd.winfo_class() == "TLabel"
            )
        ev.observe("target_readiness", shown[:1500])
        run.check("readiness", "readiness_is_shown_for_the_target_workflow", bool(shown.strip()), "no readiness text")

        run.checkpoint("vid02_done")
        run.shutdown_app()
    if hold_reason and not ev.failed_checks:
        ev.hold_reason = hold_reason  # lane A stops here; lane B's checks above still stand
    if not ev.checks:
        raise JourneyAbort("no checks recorded")


def _has_button(parent: tk.Misc, text: str) -> bool:
    try:
        return any(w.winfo_class() == "TButton" and str(w.cget("text")) == text for w in iter_widgets(parent))
    except tk.TclError:
        return False

