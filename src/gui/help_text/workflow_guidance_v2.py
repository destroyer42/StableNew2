from __future__ import annotations

from src.gui.widgets.action_explainer_panel_v2 import ActionExplainerContent


REVIEW_DEFAULT_WORKFLOW_HINT = (
    "Review is the canonical advanced reprocess workspace. Use Learning when the goal is evidence capture, "
    "batch triage, or discovered/imported group review instead of immediate reprocessing."
)


def build_review_action_guidance() -> ActionExplainerContent:
    return ActionExplainerContent(
        title="Review Actions",
        summary=(
            "Use Review when you need deliberate, metadata-aware decisions about existing images. Use Learning "
            "when the goal is rating evidence, discovered/imported group triage, or staged batch decisions rather "
            "than immediate reprocessing."
        ),
        bullets=(
            "Import Selected to Learning copies the chosen review items into staged curation evidence so they can drive later decisions without reprocessing immediately.",
            "Import Recent Job opens a picker for a recent run when you want to start from history instead of the current folder selection.",
            "Reprocess Selected queues only the selected images with the stage toggles and prompt edits shown here.",
            "Reprocess All uses the current Review settings across the full loaded set, so confirm the effective settings box before clicking it.",
        ),
    )


def build_discovered_review_guidance() -> ActionExplainerContent:
    return ActionExplainerContent(
        title="When To Use Discovered Review",
        summary=(
            "Use Discovered Review Inbox for grouped scans or imported review batches that should be compared together. "
            "Use direct Review when you already know which individual image needs prompt edits, metadata inspection, or a deliberate reprocess path."
        ),
        bullets=(
            "Scan Folder is for outputs the system found on disk and grouped into a compare-first inbox.",
            "Imported review flows are best when Review or history already identified images that should become Learning evidence instead of being reprocessed immediately.",
            "Open a group here when you want side-by-side ratings across related outputs before deciding what advances.",
            "Move to Staged Curation after the group needs downstream refine, face-triage, or upscale decisions.",
        ),
    )


def build_staged_queue_guidance() -> ActionExplainerContent:
    return ActionExplainerContent(
        title="Queue Now vs Review",
        summary=(
            "Use Staged Curation after a discovered or imported group needs batch triage and downstream routing. Use Queue Now for bulk stage submission after the batch is already triaged. Use direct Review when one candidate needs careful prompt or stage changes first."
        ),
        bullets=(
            "Queue Refine Now submits every candidate marked To Refine in one bulk pass.",
            "Queue Face Now submits every candidate marked To Face for face-triage work without opening them one by one.",
            "Queue Upscale Now submits every candidate marked To Upscale using the current staged decisions.",
            "If one candidate needs custom edits before queueing, open it in Review instead of using the bulk Queue Now path.",
        ),
    )


def build_staged_review_guidance() -> ActionExplainerContent:
    return ActionExplainerContent(
        title="Single-Candidate Review Edits",
        summary=(
            "These buttons open one selected candidate in Review so you can inspect metadata, adjust prompts, and then queue a deliberate reprocess path. Stay in Staged Curation when the goal is batch triage across the whole group."
        ),
        bullets=(
            "Choose this path when one candidate needs custom edits instead of the batch-wide Queue Now behavior.",
            "The selected candidate must already be marked for the matching derived stage.",
            "Compare Latest Derived helps you inspect the most recent derived result before deciding whether to queue again.",
        ),
    )


def get_staged_queue_runtime_guidance(refine_count: int, face_count: int, upscale_count: int) -> str:
    return (
        "Queue Now is the bulk staged-curation path after triage: "
        f"refine={refine_count}, face={face_count}, upscale={upscale_count}. "
        "Open one candidate in Review instead when it needs custom prompt or stage edits first."
    )


def get_staged_review_runtime_guidance(selected_target: str | None, marked_count: int | None = None) -> str:
    if selected_target is None:
        return (
            "Edit in Review stays single-candidate so you can make deliberate prompt or stage edits before anything is queued. "
            "Use Queue Now instead when the whole marked set is ready for bulk submission."
        )

    target_label = selected_target.replace("_", " ")
    if marked_count is None:
        return (
            "Edit in Review opens the selected candidate only. Select one candidate marked for a derived stage when you need deliberate edits instead of the bulk Queue Now path."
        )

    return (
        f"Edit in Review opens only the selected {target_label} candidate for deliberate edits. "
        f"Queue {target_label} now would enqueue {marked_count} marked candidate(s) in bulk."
    )


def get_review_handoff_hint(image_count: int) -> str:
    if image_count == 1:
        return (
            "Staged Curation handoff: deliberate single-candidate edit in Review. Use Queue Now in Learning when the full marked set is ready for bulk throughput."
        )
    return (
        "Staged Curation handoff loaded in Review. Stay here for deliberate per-image edits; use Queue Now in Learning when the goal is bulk throughput for the marked set."
    )


def build_svd_workflow_guidance() -> ActionExplainerContent:
    return ActionExplainerContent(
        title="When To Use SVD",
        summary=(
            "Choose SVD when you have one strong still image and want a short native animation. Use Video Workflow when anchors, authored workflow logic, or secondary motion should shape the motion plan. Use Movie Clips when you already have frames or outputs to assemble."
        ),
        bullets=(
            "Motion bucket controls how much movement the clip tries to introduce; lower values usually stay steadier and higher values push more motion.",
            "Noise aug adds variation before animation; low values preserve the source image more closely.",
            "Output Route decides where the finished clip lands so later tabs can pick it up more easily.",
            "Face cleanup, interpolation, and frame upscale are postprocess steps. Turn them on only when the base SVD clip needs that extra pass.",
        ),
    )


def build_video_workflow_guidance() -> ActionExplainerContent:
    return ActionExplainerContent(
        title="When To Use Video Workflow",
        summary=(
            "Choose Video Workflow when a named workflow, optional anchors, or secondary motion should drive the motion plan. Use SVD for a quick single-image animation, and use Movie Clips when you already have a set of frames or outputs to assemble into a clip."
        ),
        bullets=(
            "Workflow picks the authored generation recipe and capability limits for this job.",
            "End Anchor and Mid Anchors are for workflows that need guide images across the sequence; leave them empty when the selected workflow does not require them.",
            "Secondary motion is most useful when the base image already reads clearly and the shot needs more guided movement than a simple SVD pass would provide.",
            "Output Route decides whether the resulting artifacts should be easier to pick up in reprocess-oriented areas or in clip-assembly flows.",
        ),
    )


def build_movie_clips_guidance() -> ActionExplainerContent:
    return ActionExplainerContent(
        title="When To Use Movie Clips",
        summary=(
            "Choose Movie Clips when you already have an ordered image sequence or a compatible workflow/SVD output bundle and want explicit clip assembly control. Use SVD or Video Workflow first when the system still needs to generate new motion."
        ),
        bullets=(
            "FPS controls playback speed. Higher values make the clip play faster and smoother if enough frames exist.",
            "Codec and Quality affect export compatibility and file size rather than generation semantics.",
            "Mode controls how the clip is assembled for output, so confirm it before building if the destination matters.",
            "Use Latest Video Output is the fastest handoff when another video tab already produced frames you want to package into a clip.",
        ),
    )