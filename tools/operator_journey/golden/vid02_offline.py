"""VID-02 offline physical lane (QUAL-922): the operator's own motion assets to a usable driving video, with no inference.

Reached only through ``physical.real_executor`` after the frozen plan, the owner authorization naming its digest, passing
readiness and the typed launch.  It starts no backend, loads no model and submits no job (the plan gate declines any
submission).  Every operator-controlled value comes from the frozen target (``offline.read_offline_inputs``): the Blender
executable and its identity, the asset directory with the SHA-256 of every file in it, the Batch Convert render profile, the
Prepare Motion Source window and the workflow that receives the driving clip.

Unlike the simulated lane there is no synthetic content here: the assets are the operator's, the conversion is a real
CPU Blender render, and the lane-B stand-in clip is not used at all, so nothing in this lane can be confused with a fixture.
Journey steps: Motion Library, Batch Convert Motion (dry run, render profile, confirm, convert the sample), independent
inspection of each converted MP4, restart and reopen the library, Use as Driving Video, Prepare Motion Source, readiness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.operator_journey.golden import blender_gate, offline
from tools.operator_journey.golden.media import inspect_video, sha256_file
from tools.operator_journey.golden.session import (
    GoldenRun,
    JourneyAbort,
    JourneyHold,
    JourneyNoGo,
    file_identity,
)
from tools.operator_journey.golden.vid02 import (
    _convert_sample,
    _has_button,
    _toplevel,
    _use_as_driving_video,
)
from tools.operator_journey.tk_driver import iter_widgets

#: Bound for one Prepare Motion Source (the product's own deadline is 420 s).
PREPARE_TIMEOUT_SECONDS = 480.0


def _guard(run: GoldenRun) -> None:
    """Stop as NO-GO when the resource monitor has tripped (polled inside every long wait)."""

    reason = run.config.extras.get("abort_check")
    reason = reason() if callable(reason) else None
    if reason:
        raise JourneyNoGo(str(reason))


def _originals(frozen: offline.OfflineInputs) -> dict[str, dict[str, Any]]:
    """Identity of every original now on disk, keyed by relative path and by file name (for provenance lookups)."""

    result: dict[str, dict[str, Any]] = {}
    for path in offline.asset_listing(frozen.asset_directory):
        identity = file_identity(Path(path))
        relative = Path(path).relative_to(frozen.asset_directory.resolve()).as_posix()
        result[relative] = identity
        result.setdefault(Path(path).name, identity)
    return result


def _live_hashes(frozen: offline.OfflineInputs) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for path in offline.asset_listing(frozen.asset_directory):
        try:
            hashes[path] = sha256_file(Path(path))
        except OSError:
            hashes[path] = None
    return hashes


def _verify_blender(run: GoldenRun, frozen: offline.OfflineInputs) -> Any:
    """Verify the planned Blender against its frozen identity; a different executable, hash or version is a HOLD."""

    qualification = blender_gate.qualify_blender(frozen.blender_executable)
    if not qualification.verified or qualification.install is None:
        raise JourneyHold(qualification.hold_reason())
    install = qualification.install
    executable = Path(frozen.blender_executable)
    identity = {
        "executable": str(executable),
        "sha256": sha256_file(executable),
        "version": ".".join(str(part) for part in install.version),
        "version_text": install.version_text,
    }
    run.ev.observe("blender_identity", identity)
    mismatch = [
        f"{key}: plan {planned!r}, live {identity[key]!r}"
        for key, planned in (("sha256", frozen.blender_sha256), ("version", frozen.blender_version))
        if identity[key] != planned
    ]
    run.check(
        "identity",
        "blender_identity_matches_the_plan",
        not mismatch,
        "; ".join(mismatch),
    )
    if mismatch:
        raise JourneyHold(
            "the Blender executable no longer matches the frozen plan: " + "; ".join(mismatch)
        )
    return install


def _apply_render_profile(run: GoldenRun, dialog: Any, frozen: offline.OfflineInputs) -> None:
    """Type the frozen render profile into the Batch dialog's own controls and confirm the dialog holds exactly it."""

    from src.gui.views import motion_batch_dialog as mbd

    d, profile = run.driver, frozen.render_profile

    def label_for(items: list[tuple[str, str]], key: str) -> str:
        wanted = str(profile[key])
        found = next((text for text, value in items if value == wanted), None)
        if found is None:
            raise JourneyHold(
                f"the plan asks for {key} {wanted!r}, which Batch Convert Motion does not offer "
                f"({[value for _text, value in items]})"
            )
        return found

    for variable, items, key in (
        (dialog.policy_var, mbd._POLICY_ITEMS, "profile_policy"),
        (dialog.camera_var, mbd._CAMERA_ITEMS, "camera"),
        (dialog.mode_var, mbd._MODE_ITEMS, "camera_mode"),
        (dialog.root_var, mbd._ROOT_ITEMS, "root_motion"),
        (dialog.orient_var, mbd._ORIENT_ITEMS, "orientation"),
    ):
        d.set_variable(variable, label_for(items, key), label=f"Batch: {key}")
    d.set_variable(dialog.start_var, str(profile["start_seconds"]), label="Batch: Start (s)")
    legal = [int(n) for n in dialog.session.view().legal_frames]
    frames = int(profile["frames"])
    if frames not in legal:
        raise JourneyHold(
            f"the plan asks for {frames} frames, which the dialog does not offer ({legal})"
        )
    d.select_combobox(dialog.frames_combo, str(frames), label="Batch: Longest clip")
    d.pump(0.4)
    options = dialog.session.options
    held = {
        "profile_policy": options.profile_policy,
        "camera": options.camera,
        "camera_mode": options.camera_mode,
        "root_motion": options.root_motion,
        "orientation": options.orientation,
        "start_seconds": options.start_seconds,
        "frames": options.frames,
    }
    run.ev.observe(
        "render_profile", {"frozen": dict(profile), "dialog": held, "legal_frames": legal}
    )
    differences = [
        f"{key}: plan {profile[key]!r}, dialog {held[key]!r}"
        for key in offline.RENDER_PROFILE_KEYS
        if not _same(profile[key], held[key])
    ]
    run.check(
        "batch", "dialog_holds_the_frozen_render_profile", not differences, "; ".join(differences)
    )


def _same(planned: Any, seen: Any) -> bool:
    try:
        return float(planned) == float(seen)
    except (TypeError, ValueError):
        return str(planned) == str(seen)


def _pick_driving_workflow(run: GoldenRun, tab: Any, frozen: offline.OfflineInputs) -> None:
    """Select the frozen driving-video workflow in the engine picker (it is only read and prepared for, never run)."""

    d = run.driver
    if not tab.advanced_section.is_expanded():
        d.invoke(tab.suggested_line.change_button, label="Settings: Change")
        d.pump(0.5)
    # The picker lists display labels; the tab keeps the label <-> workflow id tables and the registry record per id.
    record = getattr(tab, "_workflow_map", {}).get(frozen.workflow_id) or {}
    label = getattr(tab, "_workflow_id_to_label", {}).get(frozen.workflow_id)
    choice = (
        label
        if label in [str(v) for v in tab.workflow_combo.cget("values")]
        and str(record.get("workflow_version") or "") == frozen.workflow_version
        else None
    )
    if choice is None:
        raise JourneyHold(
            f"the engine picker offers no {frozen.workflow_id} {frozen.workflow_version} to receive the driving video"
        )
    d.select_combobox(tab.workflow_combo, choice, label="Engine")
    d.pump(0.6)


def _prepare_motion_source(
    run: GoldenRun, tab: Any, frozen: offline.OfflineInputs, clip: dict[str, Any], workspace: Path
) -> None:
    """Prepare Motion Source with the frozen window; the output is content-addressed and the window is recorded."""

    from src.gui.view_contracts import video_motion_prep_contract as prep_contract

    d, ev, panel = run.driver, run.ev, tab.motion_prep_panel
    d.wait_until(
        lambda: panel.last_view is not None and panel.last_view.available,
        timeout=20,
        description="Prepare Motion Source is offered for the driving-video workflow",
        evidence=lambda: panel.status_var.get(),
    )
    d.set_variable(panel.start_var, frozen.window_start, label="Prepare: Start (s)")
    d.set_variable(panel.end_var, frozen.window_end, label="Prepare: End (s)")
    d.set_variable(panel.convert_var, frozen.window_convert, label="Prepare: convert frame rate")
    run.snap("prepare_configured")
    d.invoke(panel.prepare_button, label="Prepare Motion Source")

    def finished() -> bool:
        _guard(run)
        view = panel.last_view
        return view is not None and view.state in (
            prep_contract.STATE_READY,
            prep_contract.STATE_ERROR,
            prep_contract.STATE_CANCELLED,
        )

    d.wait_until(
        finished,
        timeout=PREPARE_TIMEOUT_SECONDS,
        description="Prepare Motion Source finishes",
        evidence=lambda: panel.status_var.get(),
    )
    d.pump(1.0)
    run.snap("prepare_done")
    view = panel.last_view
    state = tab.get_video_workflow_state(for_submission=True)
    record = state.get(prep_contract.PREPARED_FIELD)
    ev.observe(
        "prepare_motion_source",
        {
            "state": view.state if view is not None else None,
            "status": panel.status_var.get(),
            "detail": panel.detail_var.get(),
            "blocked": state.get(prep_contract.BLOCKED_FIELD),
        },
    )
    run.check(
        "prepare",
        "motion_source_was_prepared",
        bool(record) and view is not None and view.state == prep_contract.STATE_READY,
        f"{panel.status_var.get()!r}: {state.get(prep_contract.BLOCKED_FIELD)!r}",
    )
    if not record:
        return
    original, derived = record["original"], record["derived"]
    derived_path = Path(str(derived["path"]))
    media = (
        inspect_video(derived_path)
        if derived_path.is_file()
        else {"valid": False, "path": str(derived_path)}
    )
    independent = sha256_file(derived_path) if derived_path.is_file() else ""
    ev.observe("video_media", media, source="observed")
    ev.observe(
        "prepared_record",
        {
            "original_sha256": original["sha256"],
            "derived_path": str(derived_path),
            "derived_sha256": derived["sha256"],
            "independent_sha256": independent,
            "settings": record.get("settings"),
            "plan": record.get("plan"),
            "frames": derived.get("frames"),
        },
    )
    for name, passed, detail in prepared_findings(
        record,
        frozen,
        clip_sha=str(clip["independent_sha256"]),
        clip_sha_after=file_identity(Path(clip["clip"])).get("sha256", ""),
        workspace=workspace,
        independent_sha=independent,
        media=media,
    ):
        run.check("prepare", name, passed, detail)


def prepared_findings(
    record: dict[str, Any],
    frozen: offline.OfflineInputs,
    *,
    clip_sha: str,
    clip_sha_after: str,
    workspace: Path,
    independent_sha: str,
    media: dict[str, Any],
) -> list[tuple[str, bool, str]]:
    """What a Prepare Motion Source record must show (pure: the caller supplies every independent observation)."""

    original, derived = record["original"], record["derived"]
    derived_path = Path(str(derived["path"]))
    requested = (record.get("settings") or {}).get("requested") or {}
    plan = record.get("plan") or {}
    end = None if not frozen.window_end else float(frozen.window_end)
    end_recorded = requested.get("end") is None if end is None else _same(end, requested.get("end"))
    frames = int(derived.get("frames") or -1)
    return [
        (
            "preparation_names_the_driving_clip",
            original["sha256"] == clip_sha,
            f"{original['sha256']} vs {clip_sha}",
        ),
        (
            "output_is_content_addressed",
            bool(independent_sha)
            and independent_sha == derived["sha256"]
            and derived_path.stem == independent_sha
            and derived_path.parent.name == "prepared_driving_videos"
            and workspace.resolve() in derived_path.resolve().parents,
            f"{derived_path} / {derived['sha256']} / {independent_sha}",
        ),
        (
            "frame_window_is_recorded",
            _same(frozen.window_start, requested.get("start"))
            and end_recorded
            and int(plan.get("window_frames") or 0) >= 1
            and len(plan.get("source_indices") or []) == frames,
            f"requested {requested}; plan {plan}",
        ),
        (
            "prepared_clip_decodes",
            bool(media.get("valid")) and int(media.get("decoded_frames") or 0) == frames,
            f"{media}",
        ),
        (
            "preparation_left_the_driving_clip_unchanged",
            clip_sha_after == clip_sha,
            "the library clip changed",
        ),
    ]


def run_vid02_offline(run: GoldenRun, target: dict[str, Any]) -> None:
    from src.gui.views.motion_batch_dialog import MotionBatchDialog
    from src.pipeline.video import VideoCreator
    from src.video.motion_conversion import batch as bt
    from src.video.motion_library.store import MotionLibraryStore

    try:
        frozen = offline.read_offline_inputs(target)
    except ValueError as exc:
        raise JourneyHold(f"the frozen target is not a valid offline VID-02 target: {exc}") from exc
    if run.fake_comfy is not None or run.fake_a1111 is not None:
        raise JourneyAbort("an offline physical run is given no fake backend and starts none")
    if not VideoCreator().ffmpeg_available:
        raise JourneyHold(
            "FFmpeg is not available on this host, so the converted MP4 cannot be decoded or prepared"
        )
    ev = run.ev

    # 1. The originals are exactly what the plan froze; a changed, added or removed file is a HOLD, never a silent run.
    drift = offline.directory_problems(frozen.assets, _live_hashes(frozen))
    if drift:
        raise JourneyHold(
            "the asset directory no longer matches the frozen plan: " + "; ".join(drift[:5])
        )
    originals = _originals(frozen)
    ev.observe(
        "source_assets",
        {
            "directory": str(frozen.asset_directory),
            "files": dict(sorted(frozen.assets.items())),
        },
    )

    # 2. The planned Blender, verified and registered inside the disposable workspace only.
    install = _verify_blender(run, frozen)
    ev.observe(
        "blender_registration_staged",
        {"setting": str(blender_gate.stage_registration(install, run.ws.root))},
    )
    library_root = run.ws.root / "motion_library"
    library_root.mkdir(parents=True, exist_ok=True)
    converted: list[dict[str, Any]] = []

    run.boot_app()
    d, w = run.driver, run.window
    tab = w.video_workflow_tab
    d.select_tab(w.center_notebook, "Video Workflow - Adv")
    if tab.current_task() != "follow_clip":
        d.invoke(tab.task_selector.buttons["follow_clip"], label="Make: Follow a driving clip")
        d.pump(0.5)
    panel = tab.motion_library_panel

    # 3. Motion Library folder, then Batch Convert Motion: dry run, frozen render profile, confirm, convert the sample.
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
        "dialog_recognises_the_planned_blender",
        dialog.session.install is not None and ".".join(map(str, install.version)) in blender_text,
        f"{blender_text!r} / {dialog.status_var.get()!r}",
    )
    _apply_render_profile(run, dialog, frozen)
    run.answer_file(str(frozen.asset_directory))
    d.invoke(dialog.folder_button, label="Batch: Choose folder...")
    d.wait_until(
        lambda: dialog.session.inventory is not None,
        timeout=60,
        description="the dry-run inventory is shown",
        evidence=lambda: dialog.status_var.get(),
    )
    d.pump(0.5)
    run.snap("batch_inventory")
    inventory = dialog.session.inventory
    sample = inventory.sample() if inventory is not None else ()
    ev.observe(
        "batch_inventory",
        {
            "lines": [str(line) for line in dialog.session.view().inventory_lines],
            "status": dialog.status_var.get(),
            "estimate": list(dialog.session.view().estimate_lines),
        },
    )
    run.check(
        "batch",
        "inventory_finds_something_to_convert",
        bool(sample),
        "the dry run found no eligible motion asset in the frozen directory",
    )
    run.check(
        "batch",
        "scan_converted_nothing",
        not any(library_root.rglob("*.mp4")),
        "an mp4 appeared during the dry run",
    )
    run.check(
        "originals",
        "originals_untouched_by_the_scan",
        _originals(frozen) == originals,
        "an original changed during the scan",
    )
    if sample and dialog.session.install is not None:
        converted = _convert_sample(
            run,
            dialog,
            bt,
            {
                path: Path(identity["path"])
                for path, identity in originals.items()
                if "path" in identity
            },
            originals,
            library_root,
            panel,
            synthetic=False,
        )
    _guard(run)
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
        "originals",
        "originals_still_identical_after_the_conversion",
        _originals(frozen) == originals,
        "an original changed",
    )
    for item in converted:
        if item.get("media"):
            ev.observe("video_media", item["media"], source="observed")
    converted_ids = [str(c["asset_id"]) for c in converted if c.get("asset_id")]
    run.check(
        "conversion",
        "at_least_one_clip_was_converted",
        bool(converted_ids),
        "no converted clip was registered in the Motion Library",
    )

    # 4. Restart: the library and every converted asset's identity survive.
    run.shutdown_app()
    run.boot_app()
    d, w = run.driver, run.window
    tab = w.video_workflow_tab
    d.select_tab(w.center_notebook, "Video Workflow - Adv")
    if tab.current_task() != "follow_clip":
        d.invoke(tab.task_selector.buttons["follow_clip"], label="Make: Follow a driving clip")
        d.pump(0.5)
    panel = tab.motion_library_panel
    if converted_ids:
        d.wait_until(
            lambda: all(panel.tree.exists(asset_id) for asset_id in converted_ids),
            timeout=30,
            description="the reopened library lists the converted clips",
            evidence=lambda: panel.status_var.get(),
        )
        run.snap("library_reopened")
        store = MotionLibraryStore(library_root)
        reread = {
            str(c["asset_id"]): (
                store.get(str(c["asset_id"])).sha256 if store.get(str(c["asset_id"])) else ""
            )
            for c in converted
            if c.get("asset_id")
        }
        ev.observe("library_after_restart", reread)
        run.check(
            "library",
            "converted_assets_survive_restart",
            all(panel.tree.exists(asset_id) for asset_id in converted_ids)
            and all(
                reread[str(c["asset_id"])] == c["independent_sha256"]
                for c in converted
                if c.get("asset_id")
            ),
            f"{converted_ids} vs {list(panel.tree.get_children())}; {reread}",
        )

        # 5. Use as Driving Video: the job record carries the clip's SHA-256 (nothing is previewed or queued).
        first = converted[0]
        _pick_driving_workflow(run, tab, frozen)
        _use_as_driving_video(
            run,
            tab,
            panel,
            str(first["asset_id"]),
            phase="handoff",
            expected_sha256=str(first["independent_sha256"]),
            label="converted clip",
        )
        record = tab.get_video_workflow_state(for_submission=True)
        binding = record.get("motion_library_asset") or {}
        ev.observe(
            "driving_job_record",
            {"pose_video_path": record.get("pose_video_path"), "binding": binding},
        )
        run.check(
            "handoff",
            "driving_clip_sha256_is_recorded_in_the_job_record",
            binding.get("sha256") == first["independent_sha256"]
            and binding.get("asset_id") == first["asset_id"],
            f"{binding} vs {first['independent_sha256']}",
        )

        # 6. Prepare Motion Source with the frozen window.
        _prepare_motion_source(run, tab, frozen, first, run.ws.root)

    # 7. The target workflow's readiness, as the operator sees it.
    readiness = getattr(tab, "motion_readiness_panel", None)
    shown = ""
    if readiness is not None:
        d.pump(2.0)
        shown = " | ".join(
            str(wd.cget("text"))
            for wd in iter_widgets(readiness)
            if wd.winfo_class() in ("TLabel", "Label")
        )
    ev.observe("target_readiness", shown[:1500])
    run.check(
        "readiness",
        "readiness_is_shown_for_the_target_workflow",
        bool(shown.strip()),
        "no readiness text",
    )

    # 8. No generative GPU execution: no job, no backend, and the monitor never saw the plan's limits crossed.
    peaks = run.config.extras.get("resource_peaks")
    ev.observe("resource_peaks", peaks() if callable(peaks) else None)
    run.check(
        "gpu",
        "no_generative_execution",
        not run.job_rows()
        and not run.submissions.calls
        and run.fake_comfy is None
        and run.fake_a1111 is None
        and not getattr(run.submissions, "mismatches", []),
        f"jobs {run.job_rows()}; submissions {run.submissions.calls}",
    )
    _guard(run)
    run.checkpoint("vid02_offline_done")
    run.shutdown_app()
    if not ev.checks:
        raise JourneyAbort("no checks recorded")


__all__ = ["run_vid02_offline"]
