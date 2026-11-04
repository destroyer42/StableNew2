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
    raise KeyError(f"no runner for advanced journey {journey.key!r}")
