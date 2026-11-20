"""PR-IMG-120: the 110R staged-swap residency policy, exercised against hermetic fakes (no torch, no GPU)."""

from __future__ import annotations

import pytest

from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1 as P
from src.image_backends.diffusers_residency import (
    CODE_CAPTION_TOO_LONG,
    CODE_VRAM_INSUFFICIENT,
    MIB,
    GenerationSettings,
    ResidencyRefusal,
    StagedSwapResidency,
    guidance_matches_steps,
    is_out_of_memory,
    plan_allocator_cap,
)
from src.image_backends.ideogram4_caption import resolve_caption
from tests.helpers.ideogram4_fakes import (
    FakeCuda,
    FakeOutOfMemoryError,
    FakeTorch,
    FakeWorld,
    fake_loader,
)


def _settings(steps: int = 12, seeds: tuple[int, ...] = (7,)) -> GenerationSettings:
    preset = P.preset_for_steps(steps)
    return GenerationSettings(
        caption_json=resolve_caption("A teapot.").caption_json,
        width=768,
        height=1024,
        steps=steps,
        guidance_schedule=preset.diffusers_guidance(),
        mu=preset.mu,
        std=preset.std,
        seeds=seeds,
    )


def _manager(world: FakeWorld | None = None, cuda: FakeCuda | None = None, progress=None):
    loader = fake_loader(world, FakeTorch(cuda))
    torch, classes = loader()
    ticks = iter(range(10_000))
    manager = StagedSwapResidency(
        torch=torch,
        classes=classes,
        repo_id=P.repo_id,
        revision=P.revision,
        policy=P.residency,
        progress=progress,
        clock=lambda: float(next(ticks)),
    )
    return manager, loader.world, torch


def test_allocator_cap_is_min_of_cap_and_free_minus_margin_and_refuses_below_requirement() -> None:
    total = 12_282 * MIB
    assert plan_allocator_cap(11_600 * MIB, total, P.residency).cap_mib == 11_200
    tight = plan_allocator_cap(10_800 * MIB, total, P.residency)
    assert tight.cap_mib == 10_800 - 256 and tight.fraction == pytest.approx(10_544 / 12_282)
    with pytest.raises(ResidencyRefusal) as refused:
        plan_allocator_cap(10_700 * MIB, total, P.residency)
    assert refused.value.code == CODE_VRAM_INSUFFICIENT and "10445 MiB" in str(refused.value)
    with pytest.raises(ResidencyRefusal):
        plan_allocator_cap(1, 0, P.residency)


def test_full_sequence_keeps_exactly_one_transformer_resident_and_encodes_once() -> None:
    events: list[dict] = []
    manager, world, torch = _manager(progress=events.append)
    images = manager.run(_settings(steps=12, seeds=(7, 8)))

    # 1. allocator cap applied before anything is loaded.
    assert torch.cuda.fraction == pytest.approx(11_200 / 12_282)
    assert manager.log.events[0] == "cap:11200"
    # 2. components loaded one at a time, from the local pinned snapshot, each parked on the CPU.
    assert [name for name, _ in world.loads] == [
        "text_encoder",
        "transformer",
        "unconditional_transformer",
        "pipeline",
    ]
    for _name, kwargs in world.loads:
        assert kwargs["revision"] == P.revision and kwargs["local_files_only"] is True
    # 3. the encoder ran once with the exact token count and was released before any transformer arrived.
    encodes = [e for e in world.events if e.startswith("encode:")]
    assert encodes == ["encode:287:64x48"]
    log = manager.log.events
    assert log.index("released:text_encoder") < log.index("gpu:transformer")
    # 4. VAE stays on the GPU; one transformer per forward; two forwards per step per image.
    assert world.modules["vae"].device == "cuda"
    assert manager.log.resident_at_forward == [1] * (2 * 12 * 2)
    assert (
        world.forwards.count("transformer") == 24
        and world.forwards.count("unconditional_transformer") == 24
    )
    assert manager.log.swaps == 48
    # Each image used its own seed, the exact preset schedule and the exact token count; no step callback.
    assert [call["generator"].seed for call in world.calls] == [7, 8]
    for call in world.calls:
        assert call["guidance_schedule"] == list(P.preset_for_steps(12).diffusers_guidance())
        assert (call["mu"], call["std"], call["max_sequence_length"]) == (0.5, 1.75, 287)
        assert "callback_on_step_end" not in call
    assert [image.size for image in images] == [(768, 1024), (768, 1024)]
    # Progress: loading, encoding, then per-step denoising events with image/step counters.
    phases = [e["phase"] for e in events]
    assert phases[:4] == ["loading", "loading", "loading", "encoding"]
    denoise = [e for e in events if e["phase"] == "denoising"]
    assert denoise[0] == {"phase": "denoising", "image": 1, "images": 2, "step": 1, "steps": 12}
    assert denoise[-1] == {"phase": "denoising", "image": 2, "images": 2, "step": 12, "steps": 12}
    assert set(manager.log.timings) == {"load_s", "text_encode_s", "generate_s"}
    assert manager.peak_memory() == {
        "torch_allocated_peak_mib": 9216.0,
        "torch_reserved_peak_mib": 10240.0,
    }


def test_too_little_free_memory_refuses_before_loading() -> None:
    manager, world, _ = _manager(cuda=FakeCuda(free_bytes=10_600 * MIB))
    with pytest.raises(ResidencyRefusal) as refused:
        manager.run(_settings())
    assert refused.value.code == CODE_VRAM_INSUFFICIENT and world.loads == []
    manager, world, _ = _manager(cuda=FakeCuda(available=False))
    with pytest.raises(ResidencyRefusal, match="No CUDA GPU"):
        manager.run(_settings())


def test_caption_over_the_token_limit_refuses_before_the_encoder_moves() -> None:
    manager, world, _ = _manager(world=FakeWorld(token_count=2049))
    with pytest.raises(ResidencyRefusal) as refused:
        manager.run(_settings())
    assert refused.value.code == CODE_CAPTION_TOO_LONG
    assert world.modules["text_encoder"].device == "cpu" and not any(
        e.startswith("encode:") for e in world.events
    )


def test_out_of_memory_during_denoising_is_recognised() -> None:
    manager, _world, torch = _manager(world=FakeWorld(oom_on_step=3))
    with pytest.raises(FakeOutOfMemoryError) as raised:
        manager.run(_settings())
    assert is_out_of_memory(torch, raised.value)
    assert is_out_of_memory(object(), RuntimeError("CUDA out of memory. Tried to allocate"))
    assert not is_out_of_memory(torch, RuntimeError("fake failure"))


def test_a_policy_regression_is_caught_by_the_fakes() -> None:
    """If the swap hooks were missing, both transformers would end up resident and the fakes would fail."""

    manager, world, _ = _manager()
    manager.apply_allocator_cap()
    pipe = manager.load()
    embeddings = manager.encode(_settings())
    pipe.vae.to("cuda")
    pipe.transformer.to("cuda")
    world.max_gpu_components = None
    pipe.unconditional_transformer.to("cuda")
    with pytest.raises(AssertionError, match="resident transformers"):
        pipe.transformer()
    assert embeddings == "embeddings"


def test_guidance_length_check() -> None:
    assert guidance_matches_steps(P.preset_for_steps(20).diffusers_guidance(), 20)
    assert not guidance_matches_steps((7.0,) * 19, 20)
    assert not guidance_matches_steps(("7",) * 20, 20)
