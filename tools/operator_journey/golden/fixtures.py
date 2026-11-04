"""Backend + workspace fixtures for simulated golden-path runs (loopback fakes at the HTTP boundary only)."""

from __future__ import annotations

from tools.operator_journey.fake_a1111 import FakeA1111
from tools.operator_journey.fixtures import seed_sdxl_checkpoint_evidence
from tools.operator_journey.journeys.learning_lora_strength import model_base


def make_fake_a1111(**kwargs) -> FakeA1111:
    return FakeA1111(**kwargs)


def seed_declared_sdxl(workspace, fake_a, _fake_c) -> None:
    """Declare the fake's checkpoint SDXL in the isolated AssetRegistry cache (a fixture, never a real model)."""

    if fake_a is not None:
        seed_sdxl_checkpoint_evidence(workspace, model_base(fake_a.title(fake_a.model)))
