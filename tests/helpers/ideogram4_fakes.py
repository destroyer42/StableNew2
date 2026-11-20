"""Hermetic stand-ins for torch, Diffusers and Transformers used by the PR-IMG-120 tests.

They model only what the residency policy depends on: which device each component is on, the order of loads and
moves, forward pre-hooks, the release pipeline's call shape (one conditional and one unconditional transformer call per
step), and the CUDA memory API. The fake pipeline asserts the residency invariants itself, so a policy regression fails
the test at the moment the real model would spill or OOM.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from src.image_backends.diffusers_residency import LoaderClasses

GIB = 1024**3


class FakeOutOfMemoryError(RuntimeError):
    pass


@dataclass
class FakeCuda:
    free_bytes: int = 11_600 * 1024 * 1024
    total_bytes: int = 12_282 * 1024 * 1024
    available: bool = True
    fraction: float | None = None
    empty_cache_calls: int = 0
    OutOfMemoryError: type = FakeOutOfMemoryError

    def is_available(self) -> bool:
        return self.available

    def mem_get_info(self) -> tuple[int, int]:
        return self.free_bytes, self.total_bytes

    def set_per_process_memory_fraction(self, fraction: float) -> None:
        self.fraction = fraction

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1

    def reset_peak_memory_stats(self) -> None:
        return None

    def max_memory_allocated(self) -> int:
        return 9 * GIB

    def max_memory_reserved(self) -> int:
        return 10 * GIB


class FakeGenerator:
    def __init__(self, device: str) -> None:
        self.device = device
        self.seed: int | None = None

    def manual_seed(self, seed: int) -> FakeGenerator:
        self.seed = seed
        return self


class FakeTorch:
    bfloat16 = "bfloat16"

    def __init__(self, cuda: FakeCuda | None = None) -> None:
        self.cuda = cuda or FakeCuda()

    @staticmethod
    def device(name: str) -> str:
        return name

    @staticmethod
    @contextlib.contextmanager
    def no_grad() -> Iterator[None]:
        yield

    Generator = FakeGenerator


class FakeModule:
    def __init__(self, name: str, world: FakeWorld) -> None:
        self.name = name
        self.device = "cpu"
        self.world = world
        self.hooks: list[Callable[[Any, Any], None]] = []

    def to(self, device: Any) -> FakeModule:
        self.device = str(device)
        self.world.events.append(f"{self.device}:{self.name}")
        if self.world.max_gpu_components is not None:
            on_gpu = [m for m in self.world.modules.values() if m.device == "cuda"]
            assert len(on_gpu) <= self.world.max_gpu_components, [m.name for m in on_gpu]
        return self

    def register_forward_pre_hook(self, hook: Callable[[Any, Any], None]) -> None:
        self.hooks.append(hook)

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        for hook in self.hooks:
            hook(self, args)
        self.world.check_forward(self)
        return f"{self.name}-output"


@dataclass
class FakeWorld:
    """Shared state of one fake model load."""

    events: list[str] = field(default_factory=list)
    modules: dict[str, FakeModule] = field(default_factory=dict)
    loads: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    forwards: list[str] = field(default_factory=list)
    token_count: int = 287
    fail_on_step: int | None = None
    oom_on_step: int | None = None
    max_gpu_components: int | None = 2  # VAE + one transformer, or the text encoder alone
    calls: list[dict[str, Any]] = field(default_factory=list)

    def module(self, name: str) -> FakeModule:
        module = FakeModule(name, self)
        self.modules[name] = module
        return module

    def on_gpu(self, *names: str) -> list[str]:
        return [n for n in names if n in self.modules and self.modules[n].device == "cuda"]

    def check_forward(self, module: FakeModule) -> None:
        self.forwards.append(module.name)
        assert module.device == "cuda", f"{module.name} ran on {module.device}"
        transformers = self.on_gpu("transformer", "unconditional_transformer")
        assert transformers == [module.name], f"resident transformers at forward: {transformers}"
        assert self.on_gpu("text_encoder") == [], (
            "the text encoder stayed on the GPU during denoising"
        )


class FakeTokenizer:
    def __init__(self, world: FakeWorld) -> None:
        self.world = world

    def apply_chat_template(
        self, messages: Any, *, add_generation_prompt: bool, tokenize: bool
    ) -> str:
        assert add_generation_prompt and not tokenize
        return "<chat>" + messages[0]["content"][0]["text"]

    def __call__(
        self, text: str, *, return_tensors: str, add_special_tokens: bool
    ) -> dict[str, Any]:
        @dataclass
        class _Ids:
            shape: tuple[int, int]

        return {"input_ids": _Ids((1, self.world.token_count))}


class FakeImage:
    def __init__(self, image: Image.Image) -> None:
        self.images = [image]


class FakePipe:
    def __init__(self, world: FakeWorld, parts: dict[str, FakeModule]) -> None:
        self.world = world
        self.text_encoder = parts["text_encoder"]
        self.transformer = parts["transformer"]
        self.unconditional_transformer = parts["unconditional_transformer"]
        self.vae = world.module("vae")
        self.tokenizer = FakeTokenizer(world)

    @property
    def _execution_device(self) -> str:  # replaced by the residency manager
        return "cpu"

    def encode_prompt(
        self, *, prompt: str, grid_h: int, grid_w: int, max_sequence_length: int, device: Any
    ) -> str:
        assert self.text_encoder.device == "cuda", "encode ran without the text encoder on the GPU"
        assert self.world.on_gpu("transformer", "unconditional_transformer") == []
        self.world.events.append(f"encode:{max_sequence_length}:{grid_h}x{grid_w}")
        return "embeddings"

    def __call__(self, prompt: str, **kwargs: Any) -> FakeImage:
        self.world.calls.append(dict(kwargs, prompt=prompt))
        assert self._execution_device == "cuda"
        assert (
            self.encode_prompt(
                prompt=prompt, grid_h=0, grid_w=0, max_sequence_length=0, device="cuda"
            )
            == "embeddings"
        )
        assert len(kwargs["guidance_schedule"]) == kwargs["num_inference_steps"]
        for step in range(1, kwargs["num_inference_steps"] + 1):
            if self.world.oom_on_step == step:
                raise FakeOutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")
            if self.world.fail_on_step == step:
                raise RuntimeError("fake failure")
            self.transformer()
            self.unconditional_transformer()
        assert self.vae.device == "cuda"
        seed = kwargs["generator"].seed
        colour = (seed % 256, (seed // 256) % 256, 7)
        return FakeImage(Image.new("RGB", (kwargs["width"], kwargs["height"]), colour))


def fake_loader(
    world: FakeWorld | None = None, torch: FakeTorch | None = None
) -> Callable[[], tuple[Any, LoaderClasses]]:
    world = world or FakeWorld()
    torch = torch or FakeTorch()

    class _Component:
        @staticmethod
        def from_pretrained(repo: str, *, subfolder: str, **kwargs: Any) -> FakeModule:
            world.loads.append((subfolder, dict(kwargs, repo=repo)))
            assert world.on_gpu(*world.modules) == [], (
                "a component was still on the GPU during loading"
            )
            return world.module(subfolder)

    class _Pipeline:
        @staticmethod
        def from_pretrained(repo: str, **kwargs: Any) -> FakePipe:
            world.loads.append(
                ("pipeline", {k: v for k, v in kwargs.items() if not isinstance(v, FakeModule)})
            )
            return FakePipe(world, {k: v for k, v in kwargs.items() if isinstance(v, FakeModule)})

    def load() -> tuple[Any, LoaderClasses]:
        return torch, LoaderClasses(_Pipeline, _Component, _Component)

    load.world = world  # type: ignore[attr-defined]
    load.torch = torch  # type: ignore[attr-defined]
    return load
