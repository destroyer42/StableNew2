"""VID-02: motion assets to a usable driving video, through visible controls and without any GPU work.

Lane A (Batch Convert Motion): a test-owned folder of disposable motion assets (two valid BVH animations long enough for the
workflow's shortest clip, a placeholder FBX, a nested folder, a stray text file and an empty BVH) is scanned in the dry-run
inventory.  The conversion needs Blender.  The isolated workspace has no Blender registration by design, so an executable is
supplied explicitly (``--blender`` / ``STABLENEW_JOURNEY_BLENDER``), verified with the product's bounded version check and
registered inside the workspace only.  With a verified Blender the journey confirms the inventory, converts the sample through
the dialog, then inspects the published MP4s and their provenance on its own, and checks that the Motion Library registered
them.  Without one the lane is a precise HOLD (why is in the evidence) and nothing is faked.

Lane B (pre-rendered video, clearly labelled): a small H.264 clip that the journey writes with FFmpeg stands in for the
output a conversion would produce.  It is imported into the Motion Library, found again after a restart and handed to
the workflow with Use as Driving Video.  That proves registration, identity and hand-off, not conversion, and it never
substitutes for Lane A.
"""

from __future__ import annotations

import json
import math
import tkinter as tk
from pathlib import Path
from typing import Any

from tools.operator_journey.golden import blender_gate
from tools.operator_journey.golden.media import inspect_video, sha256_file
from tools.operator_journey.golden.session import (
    GoldenRun,
    JourneyAbort,
    JourneyHold,
    file_identity,
)
from tools.operator_journey.golden.vid01 import WORKFLOW_ID, WORKFLOW_VERSION, make_reference_image
from tools.operator_journey.golden.video_fixture import fixture_video_runtime
from tools.operator_journey.tk_driver import iter_widgets

CLIP_NAME = "golden_vid02_driving"
#: Long enough (2 s at the converter's 24 fps) for every legal clip length the workflows accept.
BVH_FRAMES = 49
BVH_FRAME_TIME = 1.0 / 24.0
#: Wall-clock bound for the sample conversion (a real Blender render of a few short clips).
CONVERSION_TIMEOUT_SECONDS = 900.0

#: name, parent, offset: a small full-body skeleton so the renderer has a real rig to draw.
_JOINTS = (
    ("Hips", None, (0, 0, 0)),
    ("Spine", "Hips", (0, 10, 0)),
    ("Chest", "Spine", (0, 12, 0)),
    ("Neck", "Chest", (0, 12, 0)),
    ("Head", "Neck", (0, 8, 0)),
    ("LeftArm", "Chest", (6, 10, 0)),
    ("LeftForeArm", "LeftArm", (12, 0, 0)),
    ("RightArm", "Chest", (-6, 10, 0)),
    ("RightForeArm", "RightArm", (-12, 0, 0)),
    ("LeftUpLeg", "Hips", (4, -2, 0)),
    ("LeftLeg", "LeftUpLeg", (0, -18, 0)),
    ("RightUpLeg", "Hips", (-4, -2, 0)),
    ("RightLeg", "RightUpLeg", (0, -18, 0)),
)


def make_bvh(frames: int = BVH_FRAMES, *, sway: float = 1.0) -> str:
    """A valid BVH animation: a skeleton that sways and steps for ``frames`` frames at 24 fps."""

    children: dict[str | None, list[tuple[str, tuple[int, int, int]]]] = {}
    for name, parent, offset in _JOINTS:
        children.setdefault(parent, []).append((name, offset))
    lines = ["HIERARCHY"]

    def emit(name: str, offset: tuple[int, int, int], depth: int) -> None:
        pad = "  " * depth
        root = depth == 0
        lines.append(f"{pad}{'ROOT' if root else 'JOINT'} {name}")
        lines.append(f"{pad}{{")
        lines.append(f"{pad}  OFFSET {offset[0]} {offset[1]} {offset[2]}")
        lines.append(
            f"{pad}  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation"
            if root
            else f"{pad}  CHANNELS 3 Zrotation Xrotation Yrotation"
        )
        kids = children.get(name, [])
        for kid, kid_offset in kids:
            emit(kid, kid_offset, depth + 1)
        if not kids:
            lines.append(f"{pad}  End Site")
            lines.append(f"{pad}  {{")
            lines.append(f"{pad}    OFFSET 0 4 0")
            lines.append(f"{pad}  }}")
        lines.append(f"{pad}}}")

    emit("Hips", (0, 0, 0), 0)
    lines += ["MOTION", f"Frames: {frames}", f"Frame Time: {BVH_FRAME_TIME:.7f}"]
    for frame in range(frames):
        phase = 2.0 * math.pi * frame / 24.0
        values: list[float] = [0.0, 90.0 + 1.5 * math.sin(2 * phase), 0.0]  # hips position
        values += [4.0 * sway * math.sin(phase), 0.0, 3.0 * sway * math.sin(phase)]  # hips rotation
        for name, _parent, _offset in _JOINTS[1:]:
            side = -1.0 if name.startswith("Right") else 1.0
            swing = 25.0 * sway * math.sin(phase + (math.pi if "Leg" in name else 0.0)) * side
            if name.endswith(("Arm", "UpLeg")):
                values += [0.0, swing, 0.0]
            elif name.endswith(("ForeArm", "Leg")):
                values += [0.0, max(0.0, swing) * 0.6, 0.0]
            else:
                values += [2.0 * sway * math.sin(phase), 0.0, 0.0]
        lines.append(" ".join(f"{value:.4f}" for value in values))
    return "\n".join(lines) + "\n"


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
    files["walk.bvh"].write_text(make_bvh(sway=1.0), encoding="utf-8")
    files["run.bvh"].write_text(make_bvh(sway=1.6), encoding="utf-8")
    files["dance.fbx"].write_bytes(
        b"Kaydara FBX Binary  \x00disposable operator-journey placeholder"
    )
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
        ImageDraw.Draw(frame).ellipse(
            [40 + index * 12, 300, 140 + index * 12, 400], fill=(240, 200, 80)
        )
        target = frames / f"f{index:03d}.png"
        frame.save(target)
        images.append(target)
    if not VideoCreator().create_video_from_images(images, path, fps=24, require_all_frames=True):
        raise JourneyHold("FFmpeg could not encode the pre-rendered clip used for lane B")
    return path


def _toplevel(root: tk.Misc, kind: type) -> Any:
    return next((w for w in iter_widgets(root) if isinstance(w, kind) and w.winfo_exists()), None)


def _published_clip(directory: Path) -> Path | None:
    clips = sorted(directory.glob("*.mp4"))
    return clips[0] if clips else None


def _inspect_conversion(
    result: Any, originals: dict[str, dict[str, Any]], library_root: Path
) -> dict[str, Any]:
    """What an independent look at one converted clip finds: the MP4, its record, its source and its library entry."""

    from src.video.motion_conversion.conversion_service import PROVENANCE_NAME
    from src.video.motion_library.store import MotionLibraryStore

    name = Path(result.relative_path).name
    directory = Path(result.directory) if result.directory else Path()
    clip = _published_clip(directory) if result.directory and directory.is_dir() else None
    record: dict[str, Any] = {}
    if result.directory and (directory / PROVENANCE_NAME).is_file():
        try:
            loaded = json.loads((directory / PROVENANCE_NAME).read_text(encoding="utf-8"))
            record = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            record = {}
    media = inspect_video(clip) if clip is not None else {"valid": False, "error": "no mp4"}
    store = MotionLibraryStore(library_root)
    asset = store.get(result.asset_id) if result.asset_id else None
    derivation = asset.derivation if asset is not None else None
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    return {
        "source_name": name,
        "relative_path": result.relative_path,
        "directory": str(directory) if result.directory else "",
        "clip": str(clip) if clip is not None else "",
        "reported_sha256": result.output_sha256,
        "independent_sha256": sha256_file(clip) if clip is not None else "",
        "reported_frames": result.frames,
        "media": media,
        "provenance_source_sha256": str(source.get("sha256", "")),
        "original_sha256": originals.get(name, {}).get("sha256", ""),
        "asset_id": result.asset_id,
        "asset_sha256": asset.sha256 if asset is not None else "",
        "asset_derivation_source_sha256": derivation.source_sha256
        if derivation is not None
        else "",
        "within_library": bool(
            clip is not None and library_root.resolve() in clip.resolve().parents
        ),
    }


def _row_of(panel: Any, text: str) -> str | None:
    for row in panel.tree.get_children():
        if text in " ".join(str(v) for v in panel.tree.item(row, "values")):
            return str(row)
    return None


def _use_as_driving_video(
    run: GoldenRun, tab: Any, panel: Any, row: str, *, phase: str, expected_sha256: str, label: str
) -> None:
    d = run.driver
    d.select_tree_row(panel.tree, row, label=f"Motion Library row ({label})")
    d.wait_until(
        lambda: not panel.use_button.instate(["disabled"]),
        timeout=15,
        description=f"Use as Driving Video becomes available ({label})",
    )
    run.snap(f"clip_selected_{phase}")
    d.invoke(panel.use_button, label=f"Use as Driving Video ({label})")
    d.pump(1.0)
    driving = str(tab.pose_video_var.get())
    run.ev.observe(f"driving_video_{phase}", driving)
    run.snap(f"driving_set_{phase}")
    run.check(
        phase,
        "driving_video_field_points_at_the_library_clip",
        bool(driving) and Path(driving).name.endswith(".mp4"),
        f"{driving!r}",
    )
    run.check(
        phase,
        "driving_clip_is_the_expected_file",
        bool(driving)
        and Path(driving).exists()
        and file_identity(Path(driving))["sha256"] == expected_sha256,
        f"{driving!r}",
    )
    run.check(
        phase,
        "hand_off_queued_nothing",
        not run.job_rows() and not run.submissions.calls,
        f"{run.submissions.calls}",
    )


def run_vid02(
    run: GoldenRun, *, simulated: bool = True, physical: dict[str, Any] | None = None
) -> None:
    from src.gui.views.motion_batch_dialog import MotionBatchDialog
    from src.pipeline.video import VideoCreator
    from src.video.motion_conversion import batch as bt
    from src.video.workflow_registry import build_default_workflow_registry

    if physical is not None:
        raise JourneyAbort("VID-02 has no physical lane")
    if not VideoCreator().ffmpeg_available:
        raise JourneyHold(
            "FFmpeg is not available on this host, so the pre-rendered clip cannot be produced"
        )
    ev = run.ev
    hold_reason = ""
    assets = _write_assets(run.ws.root / "motion_assets")
    originals = {name: file_identity(path) for name, path in assets.items()}
    library_root = run.ws.root / "motion_library"
    library_root.mkdir(parents=True, exist_ok=True)
    clip = _make_clip(run.ws.root / "prerendered" / f"{CLIP_NAME}.mp4")
    clip_identity = file_identity(clip)
    ev.observe(
        "prerendered_clip",
        {"path": str(clip), "sha256": clip_identity["sha256"], "media": inspect_video(clip)},
    )
    source_image = make_reference_image(run.ws.root / "reference" / "motion_target.png")
    spec = build_default_workflow_registry().get(WORKFLOW_ID, WORKFLOW_VERSION)

    # Lane A needs Blender.  The workspace has none by design; an explicit executable is verified with the product's
    # bounded version check and registered inside the workspace only.  Nothing is searched for or installed.
    qualification = blender_gate.qualify_blender(
        blender_gate.supplied_executable(run.config.extras)
    )
    ev.observe(
        "blender_qualification",
        {
            "state": qualification.state,
            "detail": qualification.detail,
            "candidate": qualification.candidate,
            "install": qualification.install.to_record() if qualification.install else None,
        },
    )
    if qualification.verified and qualification.install is not None:
        staged = blender_gate.stage_registration(qualification.install, run.ws.root)
        ev.observe("blender_registration_staged", {"setting": str(staged)})
    converted: list[dict[str, Any]] = []

    with fixture_video_runtime(run.fake_comfy, spec):
        run.boot_app()
        d, w = run.driver, run.window
        tab = w.video_workflow_tab
        d.select_tab(w.center_notebook, "Video Workflow - Adv")
        # The Motion Library and the driving clip belong to the "Follow a driving clip" task.
        if tab.current_task() != "follow_clip":
            d.invoke(tab.task_selector.buttons["follow_clip"], label="Make: Follow a driving clip")
            d.pump(0.5)
        panel = tab.motion_library_panel

        # 1. Choose the library folder (a test-owned directory), then Lane A: Batch Convert Motion.
        run.answer_file(str(library_root))
        d.invoke(panel.choose_button, label="Motion Library: Choose library folder...")
        d.wait_until(
            lambda: "ibrary" in panel.status_var.get(),
            timeout=20,
            description="the library folder is accepted",
            evidence=lambda: panel.status_var.get(),
        )
        run.snap("library_chosen")
        d.invoke(panel.batch_button, label="Motion Library: Batch Convert Motion...")
        dialog = d.wait_until(
            lambda: _toplevel(run.root, MotionBatchDialog),
            timeout=15,
            description="Batch Convert Motion opens",
        )
        # The dialog checks the remembered Blender on a worker; wait for that to settle before reading its situation.
        d.wait_until(
            lambda: not dialog.session.busy,
            timeout=90,
            description="the dialog has checked Blender",
            evidence=lambda: dialog.status_var.get(),
        )
        d.pump(1.0)
        run.snap("batch_open")
        blender_text = str(dialog.session.view().blender_text)
        ev.observe("batch_initial", {"blender": blender_text, "status": dialog.status_var.get()})
        run.check(
            "batch",
            "dialog_states_the_blender_situation",
            bool(blender_text.strip()),
            f"{blender_text!r}",
        )
        if qualification.verified:
            # The shortest legal clip keeps the real render short; chosen before the scan so the scan is not stale.
            legal = [int(n) for n in dialog.session.view().legal_frames]
            frames = min(legal) if legal else 0
            ev.observe("conversion_frames", {"legal": legal, "chosen": frames})
            if frames:
                d.select_combobox(dialog.frames_combo, str(frames), label="Batch: Longest clip")

        run.answer_file(str(run.ws.root / "motion_assets"))
        d.invoke(dialog.folder_button, label="Batch: Choose folder...")
        d.wait_until(
            lambda: dialog.session.inventory is not None,
            timeout=60,
            description="the dry-run inventory is shown",
            evidence=lambda: dialog.status_var.get(),
        )
        d.pump(0.5)
        run.snap("batch_inventory")
        inventory_lines = [str(line) for line in dialog.session.view().inventory_lines]
        ev.observe(
            "batch_inventory",
            {
                "lines": inventory_lines,
                "status": dialog.status_var.get(),
                "estimate": list(dialog.session.view().estimate_lines),
            },
        )
        text = "\n".join(inventory_lines)
        run.check(
            "batch",
            "inventory_counts_two_convertible_and_three_ineligible",
            "Will convert: 2" in text
            and "Not eligible (no rig, no animation, unsupported or unreadable): 3" in text,
            text[:400],
        )
        run.check(
            "batch",
            "ineligible_files_say_why",
            "Not a BVH file" in text and "unrecognized header" in text,
            text[:600],
        )
        run.check(
            "batch",
            "scan_converted_nothing",
            not (library_root.exists() and any(library_root.rglob("*.mp4"))),
            "an mp4 appeared during the dry run",
        )
        run.check(
            "batch",
            "originals_untouched_by_the_scan",
            {n: file_identity(p) for n, p in assets.items()} == originals,
            "an original changed during the scan",
        )

        # Conversion needs Blender: with none registered the actions must be unavailable and say why.
        blender_ready = dialog.session.install is not None
        sample_blocked = dialog.sample_button.instate(["disabled"])
        ev.observe(
            "conversion_lane",
            {
                "blender_registered": blender_ready,
                "sample_disabled": sample_blocked,
                "status": dialog.status_var.get(),
            },
        )
        if not qualification.verified:
            run.check(
                "batch",
                "conversion_is_unavailable_without_blender",
                sample_blocked and not blender_ready,
                "Convert sample is enabled although no Blender is registered",
            )
            run.check(
                "batch",
                "unavailability_is_explained",
                "lender" in (dialog.status_var.get() + blender_text),
                f"{dialog.status_var.get()!r}",
            )
            hold_reason = qualification.hold_reason()
        else:
            run.check(
                "conversion",
                "dialog_recognises_the_verified_blender",
                blender_ready
                and qualification.install is not None
                and ".".join(map(str, qualification.install.version)) in blender_text,
                f"{blender_text!r} / {dialog.status_var.get()!r}",
            )
            if blender_ready:
                converted = _convert_sample(run, dialog, bt, assets, originals, library_root, panel)

        d.invoke(d.find_button(dialog, "Close"), label="Batch: Close") if _has_button(
            dialog, "Close"
        ) else dialog.destroy()
        d.pump(0.4)
        run.check(
            "batch",
            "no_job_was_queued",
            not run.job_rows() and not run.submissions.calls,
            f"{run.submissions.calls}",
        )
        run.check(
            "batch",
            "originals_still_identical_after_the_dialog",
            {n: file_identity(p) for n, p in assets.items()} == originals,
            "an original changed",
        )

        # 2. Lane B: import the pre-rendered clip (clearly a stand-in for a conversion's output, never lane A's evidence).
        known_rows = set(panel.tree.get_children())
        run.answer_file(str(clip))
        d.invoke(panel.import_file_button, label="Motion Library: Import video...")
        d.wait_until(
            lambda: _row_of(panel, CLIP_NAME) is not None,
            timeout=60,
            description="the library lists the imported clip",
            evidence=lambda: panel.status_var.get(),
        )
        d.pump(0.8)
        run.snap("library_imported")
        rows = list(panel.tree.get_children())
        row_values = [tuple(str(v) for v in panel.tree.item(i, "values")) for i in rows]
        ev.observe("library_rows", row_values)
        lane_b_rows = [
            r for r in rows if CLIP_NAME in " ".join(str(v) for v in panel.tree.item(r, "values"))
        ]
        run.check("library_lane_b", "clip_is_listed_once", len(lane_b_rows) == 1, f"{row_values}")
        run.check(
            "library_lane_b",
            "import_added_exactly_one_row",
            len(set(rows) - known_rows) == 1,
            f"{row_values}",
        )
        run.check(
            "library_lane_b",
            "import_left_the_original_clip_unchanged",
            file_identity(clip) == clip_identity,
            "the source clip changed",
        )
        lane_b_id = lane_b_rows[0] if lane_b_rows else ""
        converted_ids = [str(c["asset_id"]) for c in converted if c.get("asset_id")]

        # 3. Restart: the library and every asset identity survive.
        run.shutdown_app()
        run.boot_app()
        d, w = run.driver, run.window
        tab = w.video_workflow_tab
        d.select_tab(w.center_notebook, "Video Workflow - Adv")
        # The Motion Library and the driving clip belong to the "Follow a driving clip" task.
        if tab.current_task() != "follow_clip":
            d.invoke(tab.task_selector.buttons["follow_clip"], label="Make: Follow a driving clip")
            d.pump(0.5)
        panel = tab.motion_library_panel
        d.wait_until(
            lambda: bool(lane_b_id) and panel.tree.exists(lane_b_id),
            timeout=30,
            description="the reopened library lists the clip",
            evidence=lambda: panel.status_var.get(),
        )
        run.snap("library_reopened")
        run.check(
            "library_lane_b",
            "asset_identity_survives_restart",
            panel.tree.exists(lane_b_id),
            f"{list(panel.tree.get_children())}",
        )
        if converted_ids:
            run.check(
                "library_lane_a",
                "converted_assets_survive_restart",
                all(panel.tree.exists(asset_id) for asset_id in converted_ids),
                f"{converted_ids} vs {list(panel.tree.get_children())}",
            )

        # 4. Use as Driving Video: the workflow receives the library clip, with its identity.
        run.answer_file(str(source_image))
        d.invoke(d.find_button(tab, "Browse..."), label="Source image Browse")
        d.wait_until(
            lambda: Path(tab.source_image_var.get()).resolve() == source_image.resolve(),
            timeout=10,
            description="the source image is shown",
        )
        if not tab.advanced_section.is_expanded():
            # The engine and its settings are filled in for the task; an operator who wants a specific one opens
            # the Settings editor with "Change".
            d.invoke(tab.suggested_line.change_button, label="Settings: Change")
            d.pump(0.5)
        fun = next((v for v in tab.workflow_combo.cget("values") if "Fun Control" in str(v)), None)
        if fun is None:
            raise JourneyHold("the engine picker offers no driving-video workflow")
        d.select_combobox(tab.workflow_combo, str(fun), label="Engine")
        d.pump(0.6)
        if converted:
            first = converted[0]
            _use_as_driving_video(
                run,
                tab,
                panel,
                str(first["asset_id"]),
                phase="handoff_lane_a",
                expected_sha256=str(first["independent_sha256"]),
                label="converted clip",
            )
        _use_as_driving_video(
            run,
            tab,
            panel,
            lane_b_id,
            phase="handoff_lane_b",
            expected_sha256=clip_identity["sha256"],
            label="pre-rendered clip",
        )

        # 5. The target workflow's readiness, as the operator sees it.
        readiness = getattr(tab, "motion_readiness_panel", None)
        shown = ""
        if readiness is not None:
            d.pump(2.0)
            shown = " | ".join(
                str(wd.cget("text"))
                for wd in iter_widgets(readiness)
                if isinstance(wd, (tk.Label,)) or wd.winfo_class() == "TLabel"
            )
        ev.observe("target_readiness", shown[:1500])
        run.check(
            "readiness",
            "readiness_is_shown_for_the_target_workflow",
            bool(shown.strip()),
            "no readiness text",
        )

        run.checkpoint("vid02_done")
        run.shutdown_app()
    if qualification.verified and not converted and not ev.failed_checks:
        # A verified Blender whose conversion never ran must not read as PASS.
        run.check(
            "conversion",
            "a_real_conversion_completed",
            False,
            "Blender was verified and registered but no conversion completed",
        )
    if hold_reason and not ev.failed_checks:
        ev.hold_reason = hold_reason  # lane A stops here; lane B's checks above still stand
    if not ev.checks:
        raise JourneyAbort("no checks recorded")


def _convert_sample(
    run: GoldenRun,
    dialog: Any,
    bt: Any,
    assets: dict[str, Path],
    originals: dict[str, dict[str, Any]],
    library_root: Path,
    panel: Any,
) -> list[dict[str, Any]]:
    """Lane A with a verified Blender: confirm, convert the sample through the dialog, inspect what it published."""

    d, ev = run.driver, run.ev
    session = dialog.session
    inventory = session.inventory
    sample = inventory.sample() if inventory is not None else ()
    frames = int(session.settings().frames)
    eligible = [
        {
            "relative_path": e.relative_path,
            "disposition": e.disposition,
            "route": e.route,
            "profile": e.profile,
            "animation_frames": BVH_FRAMES,
            "seconds_supplied": round((BVH_FRAMES - 1) * BVH_FRAME_TIME, 3),
            "frames_requested": frames,
        }
        for e in sample
    ]
    ev.observe("conversion_sample", eligible)
    run.check(
        "conversion",
        "sample_is_eligible_for_the_renderer",
        len(sample) == 2
        and all(e.disposition == bt.DISP_CONVERT and e.route and e.profile for e in sample)
        and frames <= BVH_FRAMES,
        f"{eligible}",
    )
    run.check(
        "conversion",
        "convert_is_blocked_until_the_operator_confirms",
        dialog.sample_button.instate(["disabled"]) and not session.confirmed,
        "Convert sample was enabled before the confirmation",
    )
    d.invoke(dialog.confirm_check, label="Batch: confirm count, destination and disk budget")
    d.pump(0.4)
    run.snap("batch_confirmed")
    run.check(
        "conversion",
        "confirmation_enables_the_sample",
        session.confirmed and not dialog.sample_button.instate(["disabled"]),
        f"{dialog.status_var.get()!r}",
    )
    d.invoke(dialog.sample_button, label="Batch: Convert sample")
    d.wait_until(
        lambda: session.summary is not None and not session.busy,
        timeout=CONVERSION_TIMEOUT_SECONDS,
        description="the sample conversion finishes",
        evidence=lambda: (dialog.status_var.get(), session.view().progress_text),
    )
    d.pump(1.0)
    run.snap("batch_converted")
    summary = session.summary
    results = list(summary.results) if summary is not None else []
    ev.observe(
        "conversion_summary",
        {
            "status": dialog.status_var.get(),
            "result_lines": list(session.view().result_lines),
            "results": [
                {
                    "path": r.relative_path,
                    "status": r.status,
                    "kind": r.kind,
                    "reason": r.reason,
                    "frames": r.frames,
                    "seconds": round(r.seconds, 2),
                    "diagnostic_path": r.diagnostic_path,
                }
                for r in results
            ],
        },
    )
    ok_results = [r for r in results if r.ok]
    run.check(
        "conversion",
        "a_real_conversion_completed",
        bool(summary)
        and len(ok_results) == len(sample)
        and not summary.failures
        and dialog.status_var.get() == "Finished.",
        f"{dialog.status_var.get()!r}: "
        + "; ".join(f"{r.relative_path}: {r.status} {r.kind} {r.reason}" for r in results),
    )
    inspected = [_inspect_conversion(r, originals, library_root) for r in ok_results]
    ev.observe("conversion_outputs", inspected)
    for item in inspected:
        name = item["source_name"]
        media = item["media"]
        run.check(
            "conversion",
            f"{name}: published_clip_decodes",
            bool(media.get("valid"))
            and int(media.get("decoded_frames") or 0) >= int(item["reported_frames"] or 1)
            and int(media.get("width") or 0) > 0,
            f"{media}",
        )
        run.check(
            "conversion",
            f"{name}: output_identity_matches_the_record",
            bool(item["independent_sha256"])
            and item["independent_sha256"] == item["reported_sha256"],
            f"{item['independent_sha256']} vs {item['reported_sha256']}",
        )
        run.check(
            "conversion",
            f"{name}: provenance_names_the_original",
            bool(item["original_sha256"])
            and item["provenance_source_sha256"] == item["original_sha256"],
            f"{item['provenance_source_sha256']} vs {item['original_sha256']}",
        )
        run.check(
            "conversion",
            f"{name}: published_inside_the_test_library",
            bool(item["within_library"]),
            f"{item['clip']}",
        )
        run.check(
            "library_lane_a",
            f"{name}: registered_with_source_and_derivative_identities",
            bool(item["asset_id"])
            and item["asset_sha256"] == item["independent_sha256"]
            and item["asset_derivation_source_sha256"] == item["original_sha256"],
            f"{item['asset_sha256']} / {item['asset_derivation_source_sha256']}",
        )
    d.wait_until(
        lambda: all(panel.tree.exists(str(i["asset_id"])) for i in inspected) and bool(inspected),
        timeout=30,
        description="the library lists the converted clips",
        evidence=lambda: list(panel.tree.get_children()),
    )
    run.check(
        "conversion",
        "originals_preserved_by_the_conversion",
        {n: file_identity(p) for n, p in assets.items()} == originals,
        "an original changed during the conversion",
    )
    run.check(
        "library_lane_a",
        "library_lists_each_converted_clip",
        len(inspected) == len(sample)
        and all(panel.tree.exists(str(i["asset_id"])) for i in inspected),
        f"{list(panel.tree.get_children())}",
    )
    return inspected


def _has_button(parent: tk.Misc, text: str) -> bool:
    try:
        return any(
            w.winfo_class() == "TButton" and str(w.cget("text")) == text
            for w in iter_widgets(parent)
        )
    except tk.TclError:
        return False
