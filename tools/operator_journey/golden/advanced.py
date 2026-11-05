"""Simulated runners for the advanced journeys (PR-TEST-JOURNEYS-832).

Imports are deferred: application modules need the isolated workspace redirect before they load.
"""

from __future__ import annotations

from tools.operator_journey.evidence import JourneyEvidence
from tools.operator_journey.golden.definitions import JourneyDef
from tools.operator_journey.golden.session import RunConfig


def run_advanced(journey: JourneyDef, config: RunConfig) -> JourneyEvidence:
    from tools.operator_journey.golden.fixtures import make_fake_a1111, seed_declared_sdxl
    from tools.operator_journey.golden.session import run_journey_body

    if journey.key == "recovery":
        from tools.operator_journey.golden.ops01 import run_ops01

        return run_journey_body(
            journey.id,
            run_ops01,
            config,
            mode_label="simulated",
            fake_a1111_factory=lambda: make_fake_a1111(extra_models=("operator-journey-alt",)),
            workspace_hook=seed_declared_sdxl,
        )
    if journey.key == "prompt-model":
        from tools.operator_journey.golden.fixtures import seed_declared_checkpoints
        from tools.operator_journey.golden.img02 import run_img02

        models = ("operator-journey-alt", "operator-journey-legacy", "flux-2-klein-4b-fp8")

        def declare(workspace, fake_a, _fake_c) -> None:
            seed_declared_checkpoints(
                workspace,
                {
                    fake_a.model: "sdxl",
                    "operator-journey-alt": "sdxl",
                    "operator-journey-legacy": "stable-diffusion-v1",
                },
            )

        return run_journey_body(
            journey.id,
            run_img02,
            config,
            mode_label="simulated",
            fake_a1111_factory=lambda: make_fake_a1111(extra_models=models),
            workspace_hook=declare,
        )
    if journey.key == "learning-profile":
        from tools.operator_journey.golden.fixtures import seed_declared_checkpoints
        from tools.operator_journey.golden.lrn02 import run_lrn02

        def declare_verified(workspace, fake_a, _fake_c) -> None:
            seed_declared_checkpoints(workspace, {fake_a.model: "sdxl"}, verified=(fake_a.model,))

        return run_journey_body(
            journey.id,
            run_lrn02,
            config,
            mode_label="simulated",
            fake_a1111_factory=make_fake_a1111,
            workspace_hook=declare_verified,
        )
    if journey.key == "storyboard":
        from tools.operator_journey.fake_comfy import FakeComfy
        from tools.operator_journey.golden.vid01 import WORKFLOW_ID, WORKFLOW_VERSION
        from tools.operator_journey.golden.vid03 import run_vid03

        def make_comfy() -> FakeComfy:
            from src.video.workflow_registry import build_default_workflow_registry

            return FakeComfy(build_default_workflow_registry().get(WORKFLOW_ID, WORKFLOW_VERSION))

        return run_journey_body(
            journey.id,
            run_vid03,
            config,
            mode_label="simulated",
            fake_a1111_factory=make_fake_a1111,
            fake_comfy_factory=make_comfy,
            workspace_hook=seed_declared_sdxl,
        )
    if journey.key == "image-edit":
        from tools.operator_journey.golden.fixtures import seed_declared_checkpoints
        from tools.operator_journey.golden.img03 import run_img03

        def declare_verified_sdxl(workspace, fake_a, _fake_c) -> None:
            # A masked edit needs a registry-resolved SDXL base: the declared family plus a verified digest.
            seed_declared_checkpoints(workspace, {fake_a.model: "sdxl"}, verified=(fake_a.model,))

        return run_journey_body(
            journey.id,
            run_img03,
            config,
            mode_label="simulated",
            fake_a1111_factory=lambda: make_fake_a1111(forge=True),
            workspace_hook=declare_verified_sdxl,
            # Masked edits are Forge-only: the isolated workspace selects the Forge identity (loopback Forge fake).
            settings_extra={"webui_runtime_identity": "forge_webui"},
        )
    raise KeyError(f"no runner for advanced journey {journey.key!r}")
