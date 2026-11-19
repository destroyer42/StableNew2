"""Shared journey definitions: one description of each operator journey, used by every mode and by the plan."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JourneyDef:
    key: str  # CLI name
    id: str  # evidence / plan id
    title: str
    runtime_kind: (
        str  # backend a physical run needs: "forge" or "comfy" ("none" for an offline lane)
    )
    steps: tuple[str, ...]
    simulated_acceptance: tuple[str, ...]
    physical_acceptance: tuple[str, ...]
    physical: bool = True  # False: simulated lane only; a physical run is refused, not attempted
    #: True: the physical lane runs no inference and starts no backend (no model, no runtime, no GPU work), so its plan
    #: target carries no model or runtime (see ``golden.offline``).  Only the definition can make a journey offline.
    offline: bool = False


IMG_01 = JourneyDef(
    key="image",
    id="IMG-01",
    title="Prompt to generated image",
    runtime_kind="forge",
    steps=(
        "Launch StableNew",
        "Navigate to Prompt",
        "Enter a positive and a negative prompt",
        "Select a compatible model",
        "Inspect the applied generation profile",
        "Adjust a supported setting (steps, seed)",
        "Navigate to Pipeline",
        "Preview the effective generation plan",
        "Submit through the normal GUI (Add to Queue)",
        "Observe the queue and execution",
        "Open the resulting image",
        "Open the corresponding History record",
        "Verify prompt, settings and provenance",
    ),
    simulated_acceptance=(
        "deterministic image with verified identity",
        "frozen NJR reflects the visible intent",
        "canonical queue and runner execute once",
        "History and artifact references agree",
    ),
    physical_acceptance=(
        "requested and effective model",
        "prompt, settings and seed",
        "actual image dimensions",
        "output hash",
        "execution duration and resource telemetry",
        "final job status",
        "runtime ownership and teardown evidence",
    ),
)

VID_01 = JourneyDef(
    key="video",
    id="VID-01",
    title="Reference image to generated video",
    runtime_kind="comfy",
    steps=(
        "Navigate to Video Workflow",
        "Select a verified local reference image through the file dialog",
        "Select a supported workflow",
        "Configure the motion prompt and a legal length",
        "Inspect source preparation and resource readiness",
        "Preview the frozen plan where the workflow offers it",
        "Submit the job",
        "Observe execution",
        "Open and play the resulting video",
        "Inspect frame count, FPS, geometry and provenance",
        "Verify History",
        "Optionally send the clip to Movie Clips without submitting another job",
    ),
    simulated_acceptance=(
        "decodable synthetic MP4 from the deterministic backend fixture",
        "normal GUI submission and canonical execution",
        "artifact recorded, in-app preview and History",
    ),
    physical_acceptance=(
        "reference image SHA-256",
        "exact workflow id and version",
        "seed and prompt",
        "frames and fps",
        "generated video hash and decode verification",
        "runtime identity",
        "peak VRAM, host memory and commit",
        "execution and teardown evidence",
    ),
)

LRN_01 = JourneyDef(
    key="learning",
    id="LRN-01",
    title="Designed experiment to evaluation",
    runtime_kind="forge",
    steps=(
        "Navigate to Learning",
        "Select a valid experiment type",
        "Choose a verified model",
        "Establish the controlled baseline",
        "Vary one supported parameter",
        "Build Preview",
        "Inspect the experimental variants",
        "Queue the variants (Run Experiment)",
        "Observe completed jobs",
        "Open comparison / review",
        "Assign ratings",
        "Save findings",
        "Close and reopen the application",
        "Verify job associations and ratings persist",
    ),
    simulated_acceptance=(
        "only the intended variable changes",
        "fixed parameters stay fixed",
        "seeds and backend readback agree",
        "each variant maps to its recorded job",
        "ratings saved and preserved across close and reopen",
        "no automatic recommendation or publication",
    ),
    physical_acceptance=(
        "two actual generated images (or the experiment's validated minimum)",
        "true backend settings",
        "completed artifact identities",
        "no recommendation inferred from generation success",
    ),
)

# --- advanced journeys (PR-TEST-JOURNEYS-832) --------------------------------------------------------------------------
# Simulated lane only unless ``physical`` is True.  IMG-03 has a gated physical lane (QUAL-921) and VID-02 an offline one
# (QUAL-922); every other advanced journey stays simulated-only until a physical lane for it is separately built.  A physical
# lane is a capability of the harness, never an authorization: each run still needs a frozen plan, an owner authorization of
# its digest and a launch.

IMG_02 = JourneyDef(
    key="prompt-model",
    id="IMG-02",
    title="PromptPack, model profiles and effective settings",
    runtime_kind="forge",
    steps=(
        "Create and save a PromptPack in the Prompt tab",
        "Reopen and edit the saved PromptPack",
        "Select a compatible image model",
        "Inspect the model-specific generation profile",
        "Change to a second compatible model and profile",
        "Verify sampler, scheduler, steps, CFG and dimensions follow the active profile",
        "Verify model-aware prompting and incompatible-setting notices",
        "Preview the effective job (nothing is submitted)",
        "Submit through the normal queue",
        "Inspect the output and History",
    ),
    simulated_acceptance=(
        "PromptPack identity survives save and reopen",
        "the model and profile on screen match the frozen NJR",
        "the effective prompts follow the model-specific policy",
        "no setting leaks from the previous model selection",
        "no submission happens during Preview",
        "completed artifacts carry the PromptPack provenance",
    ),
    physical_acceptance=(),
    physical=False,
)

IMG_03 = JourneyDef(
    key="image-edit",
    id="IMG-03",
    title="History iteration and image editing",
    runtime_kind="forge",
    steps=(
        "Open a completed image from History",
        "Navigate to Review",
        "Select a supported edit action",
        "Apply a masked edit",
        "Inspect the frozen preview and source selection",
        "Submit through the canonical queue",
        "Open the edited result",
        "Compare with Parent",
        "Verify provenance and original-asset preservation",
        "Optional (frozen inputs): extend the canvas through Review's Extend Canvas and queue the outpaint",
        "Optional (frozen inputs): Regenerate with Changes from History, edit the draft, Preview, Add to Queue",
        "Optional (frozen inputs): Replay the source job from History and compare it with its recorded parent",
    ),
    simulated_acceptance=(
        "the source image is byte-identical after the edit",
        "mask geometry is frozen in the NJR",
        "the edit has a new job identity with parent lineage",
        "Review compares the parent and the edit",
        "unsupported operations refuse honestly",
        "no prior artifact or History entry is overwritten",
        "the outpaint keeps every original pixel at its frozen bounding box",
        "Regenerate with Changes queues exactly the edited draft with parent lineage",
        "a replay is a new NJR whose recorded parent is the replayed job",
    ),
    physical_acceptance=(
        "source SHA-256",
        "protected region byte-identical",
        "edited region changed",
        "mask geometry frozen in the NJR",
        "new job identity with parent lineage",
        "Compare with Parent shows the right pair",
        "model and runtime identity",
        "peak VRAM, host RAM and commit",
        "teardown evidence",
    ),
)

VID_02 = JourneyDef(
    key="motion-assets",
    id="VID-02",
    title="Motion assets to a usable driving video",
    runtime_kind="none",  # offline: the simulated lane borrows a loopback Comfy fake; a physical run needs no backend
    steps=(
        "Open Video Workflow, Motion Library",
        "Launch Batch Convert Motion",
        "Select a test-owned directory of motion assets",
        "Inspect the dry-run inventory",
        "Select a legal render profile",
        "Convert the assets through the installed Blender capability",
        "Verify the output MP4",
        "Register the videos in the Motion Library",
        "Reopen the library and find them",
        "Use as Driving Video",
        "Prepare Motion Source where compatible",
        "Verify the accepted frame window and provenance",
        "Inspect the target workflow's readiness",
    ),
    simulated_acceptance=(
        "originals are byte-identical",
        "no generative GPU execution is triggered",
        "a missing or incompatible source refuses with an actionable message",
        "source and derivative identities survive restart",
    ),
    physical_acceptance=(
        "originals byte-identical",
        "Blender executable identity and version",
        "converted MP4 hash and decode",
        "library entries survive a restart",
        "driving-clip SHA-256 recorded in the job record",
        "Prepare Motion Source output content-addressed, with the frame window recorded",
        "no generative GPU execution",
    ),
    physical=True,
    offline=True,
)

VID_03 = JourneyDef(
    key="storyboard",
    id="VID-03",
    title="Persistent Storyboard to finished sequence",
    runtime_kind="comfy",
    steps=(
        "Select a source image",
        "Choose a supported sequence workflow",
        "Create a three-shot Storyboard with distinct motion prompts",
        "Save the draft",
        "Close and reopen StableNew",
        "Open the draft",
        "Reorder a shot",
        "Preview the Sequence Summary",
        "Submit the sequence",
        "Observe segment progress and the finished movie",
        "Inspect History and lineage",
        "Reopen the saved Storyboard",
    ),
    simulated_acceptance=(
        "Save, Preview and Reopen submit nothing",
        "reorder preserves prompts, seeds and anchors",
        "one sequence submission creates one canonical NJR and queue job",
        "segment outputs and the assembled movie decode",
        "an unsupported sequence workflow refuses accurately",
    ),
    physical_acceptance=(),
    physical=False,
)

LRN_02 = JourneyDef(
    key="learning-profile",
    id="LRN-02",
    title="Learning evidence to explicit profile reuse",
    runtime_kind="forge",
    steps=(
        "Create a controlled experiment",
        "Preview settings and variants",
        "Execute the variants",
        "Review and rate the outputs",
        "Reopen the experiment",
        "Inspect the qualification evidence",
        "Attempt profile publication (refused while unqualified)",
        "Publish a profile only when policy establishes eligibility",
        "Explicitly select the resulting profile in Base Generation",
        "Preview a new job",
        "Verify the selected profile in the frozen NJR",
    ),
    simulated_acceptance=(
        "only the intended variable changes",
        "ratings survive restart",
        "the evidence gate refuses unqualified findings",
        "publication creates an immutable revision and never applies or favourites it",
        "a later job uses the profile only by operator choice",
        "fixture evidence never enters the owner's profile store",
    ),
    physical_acceptance=(),
    physical=False,
)

OPS_01 = JourneyDef(
    key="recovery",
    id="OPS-01",
    title="Failed backend and safe operator recovery",
    runtime_kind="forge",
    steps=(
        "Submit a healthy control job",
        "Backend unavailable before dispatch",
        "Backend unavailable during preparation",
        "Changed model identity",
        "Resource preflight refusal",
        "Ambiguous generation dispatch",
        "Cancellation before dispatch",
        "Application close while work is pending",
        "Reopen and reconcile the recorded failure",
    ),
    simulated_acceptance=(
        "clear visible error messages",
        "correct queue and History status",
        "no duplicated submitted work",
        "no automatic replay of an ambiguous POST",
        "no external runtime adopted, killed or restarted",
        "no orphaned application-owned child or GUI worker",
        "no completed artifact mutated",
    ),
    physical_acceptance=(),
    physical=False,
)

ADVANCED_ORDER = (
    "prompt-model",
    "image-edit",
    "motion-assets",
    "storyboard",
    "learning-profile",
    "recovery",
)
JOURNEYS = {
    j.key: j for j in (IMG_01, VID_01, LRN_01, IMG_02, IMG_03, VID_02, VID_03, LRN_02, OPS_01)
}
#: Journeys whose physical lane is offline: no model, no runtime and no generative GPU work.
OFFLINE_KEYS = frozenset(j.key for j in JOURNEYS.values() if j.offline)
ORDER = (
    "image",
    "video",
    "learning",
)  # "all" stays the three PR-830 journeys so its baselines stay comparable


def select(choice: str) -> list[JourneyDef]:
    if choice == "all":
        return [JOURNEYS[k] for k in ORDER]
    if choice == "advanced":
        return [JOURNEYS[k] for k in ADVANCED_ORDER]
    return [JOURNEYS[choice]]
