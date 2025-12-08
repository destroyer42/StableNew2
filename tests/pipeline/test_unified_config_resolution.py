from types import SimpleNamespace

from src.pipeline.resolution_layer import UnifiedConfigResolver


def _dummy_snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        model_name="mock-model",
        sampler_name="Euler a",
        scheduler_name="ddim",
        steps=20,
        cfg_scale=7.5,
        width=640,
        height=480,
        batch_size=2,
        batch_count=1,
        seed_value=42,
    )


def test_resolves_stage_flags_and_counts() -> None:
    snapshot = _dummy_snapshot()
    resolver = UnifiedConfigResolver()
    resolved = resolver.resolve(
        config_snapshot=snapshot,
        stage_flags={"txt2img": True, "img2img": True, "upscale": False},
        batch_count=3,
        seed_value=999,
    )
    assert resolved.batch_count == 3
    assert resolved.seed == 999
    assert "img2img" in resolved.enabled_stage_names()
    assert resolved.model_name == "mock-model"


def test_final_size_override_is_respected() -> None:
    snapshot = _dummy_snapshot()
    resolver = UnifiedConfigResolver()
    final_size = (1024, 1024)
    resolved = resolver.resolve(
        config_snapshot=snapshot,
        final_size_override=final_size,
    )
    assert resolved.final_size == final_size
