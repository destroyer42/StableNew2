"""Shared journey definitions: one description of each operator journey, used by every mode and by the plan."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JourneyDef:
    key: str  # CLI name
    id: str  # evidence / plan id
    title: str
    runtime_kind: str  # backend a physical run needs: "forge" or "comfy"
    steps: tuple[str, ...]
    simulated_acceptance: tuple[str, ...]
    physical_acceptance: tuple[str, ...]


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

JOURNEYS = {j.key: j for j in (IMG_01, VID_01, LRN_01)}
ORDER = ("image", "video", "learning")


def select(choice: str) -> list[JourneyDef]:
    return [JOURNEYS[k] for k in ORDER] if choice == "all" else [JOURNEYS[choice]]
