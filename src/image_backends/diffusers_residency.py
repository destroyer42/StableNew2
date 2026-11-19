"""The PR-IMG-110R Ideogram 4 residency policy as product code (PR-IMG-120, section 7).

On a 12 GiB card the 15 GiB of NF4 weights can never be resident at once. The measured policy that works:

1. cap the Torch caching allocator, so real exhaustion is an explicit OOM instead of a silent spill into shared memory;
2. load the text encoder and both transformers **one at a time**, each parked in host memory before the next
   (``Ideogram4Pipeline.from_pretrained`` alone would put every component on the GPU and OOM under the cap);
3. put the text encoder on the GPU, encode the caption **once**, and release the encoder before any transformer arrives;
4. keep the VAE on the GPU and swap the conditional and unconditional transformers around each call, so **exactly one**
   ~4.9 GiB transformer is resident at a time.

This module runs only inside the contained child (``diffusers_ideogram4_worker``); the application process never imports
torch for it. ``torch`` and the Diffusers/Transformers classes are injected, so the whole sequence is exercised in CI with
fakes and no GPU. Step progress uses a forward pre-hook, never ``callback_on_step_end`` (110R: the release pipeline's
callback path depends on interpreter-specific ``locals()`` semantics).
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.image_backends.diffusers_ideogram4_profile import Ideogram4Residency

MIB = 1024 * 1024

#: Child result codes (``result.json`` ``code``); the parent maps them to operator messages.
CODE_OK = "ok"
CODE_VRAM_INSUFFICIENT = "vram_insufficient"
CODE_OUT_OF_MEMORY = "out_of_memory"
CODE_CAPTION_TOO_LONG = "caption_too_long"
CODE_CAPTION_INVALID = "caption_invalid"
CODE_RUNTIME_MISSING = "runtime_missing"
CODE_REQUEST_INVALID = "request_invalid"
CODE_FAILED = "failed"


class ResidencyRefusal(RuntimeError):
    """The residency policy cannot be met; ``code`` is one of the child result codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AllocatorCapDecision:
    free_mib: int
    total_mib: int
    cap_mib: int
    fraction: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "free_mib": self.free_mib,
            "total_mib": self.total_mib,
            "cap_mib": self.cap_mib,
            "fraction": round(self.fraction, 6),
        }


def plan_allocator_cap(
    free_bytes: int, total_bytes: int, policy: Ideogram4Residency
) -> AllocatorCapDecision:
    """``min(cap, free - margin)``; refuse when that is below the measured requirement."""

    free_mib, total_mib = int(free_bytes // MIB), int(total_bytes // MIB)
    if total_mib <= 0:
        raise ResidencyRefusal(CODE_VRAM_INSUFFICIENT, "The GPU reported no memory")
    cap = min(policy.allocator_cap_mib, free_mib - policy.cap_margin_mib)
    if cap < policy.min_allocator_cap_mib:
        raise ResidencyRefusal(
            CODE_VRAM_INSUFFICIENT,
            f"Only {free_mib} MiB of GPU memory is free inside the model process; Ideogram 4 needs an allocator "
            f"budget of {policy.min_allocator_cap_mib} MiB. Close other GPU applications and try again.",
        )
    return AllocatorCapDecision(free_mib, total_mib, cap, min(1.0, cap / total_mib))


@dataclass(frozen=True, slots=True)
class LoaderClasses:
    """The library entry points the residency sequence uses (real ones in the child, fakes in tests)."""

    pipeline: Any  # diffusers.Ideogram4Pipeline
    transformer: Any  # diffusers.Ideogram4Transformer2DModel
    text_encoder: Any  # transformers.Qwen3VLModel


@dataclass(frozen=True, slots=True)
class GenerationSettings:
    caption_json: str
    width: int
    height: int
    steps: int
    guidance_schedule: tuple[float, ...]
    mu: float
    std: float
    seeds: tuple[int, ...]


@dataclass
class ResidencyLog:
    """What happened, in order (for the manifest and for the tests' residency assertions)."""

    events: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    swaps: int = 0
    swap_seconds: float = 0.0
    #: Number of transformers on the GPU at each transformer forward (the policy requires 1 every time).
    resident_at_forward: list[int] = field(default_factory=list)


class StagedSwapResidency:
    """Load, encode once, then denoise with one transformer resident at a time (the 110R ``staged_swap`` policy)."""

    COMPONENT_ORDER = ("text_encoder", "transformer", "unconditional_transformer")

    def __init__(
        self,
        *,
        torch: Any,
        classes: LoaderClasses,
        repo_id: str,
        revision: str,
        policy: Ideogram4Residency,
        progress: Callable[[dict[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        device: str = "cuda",
    ) -> None:
        self._torch = torch
        self._classes = classes
        self._repo_id = repo_id
        self._revision = revision
        self._policy = policy
        self._progress = progress or (lambda _event: None)
        self._clock = clock
        self._device_name = device
        self.log = ResidencyLog()
        self.cap: AllocatorCapDecision | None = None
        self.token_count: int | None = None
        self._pipe: Any = None
        self._gpu_transformers: set[str] = set()
        self._state: dict[str, int] = {"step": 0, "image": 0}

    # -- residency primitives ---------------------------------------------------------------------------------

    def _device(self) -> Any:
        return self._torch.device(self._device_name)

    def _move(self, module: Any, name: str, *, to_gpu: bool) -> None:
        module.to(self._device() if to_gpu else "cpu")
        self.log.events.append(f"{'gpu' if to_gpu else 'cpu'}:{name}")
        if name in ("transformer", "unconditional_transformer"):
            (self._gpu_transformers.add if to_gpu else self._gpu_transformers.discard)(name)

    def _release_cache(self) -> None:
        gc.collect()
        self._torch.cuda.empty_cache()

    def _mark(self, key: str, started: float) -> None:
        self.log.timings[key] = round(self._clock() - started, 3)

    # -- sequence ---------------------------------------------------------------------------------------------

    def apply_allocator_cap(self) -> AllocatorCapDecision:
        cuda = self._torch.cuda
        if not cuda.is_available():
            raise ResidencyRefusal(
                CODE_VRAM_INSUFFICIENT, "No CUDA GPU is available to the model process"
            )
        free_bytes, total_bytes = cuda.mem_get_info()
        decision = plan_allocator_cap(int(free_bytes), int(total_bytes), self._policy)
        cuda.set_per_process_memory_fraction(decision.fraction)
        self.cap = decision
        self.log.events.append(f"cap:{decision.cap_mib}")
        return decision

    def load(self) -> Any:
        """Load the NF4 components one at a time, parking each in host memory before the next."""

        started = self._clock()
        kwargs = {
            "revision": self._revision,
            "torch_dtype": self._torch.bfloat16,
            "local_files_only": True,
        }
        parts: dict[str, Any] = {}
        for name in self.COMPONENT_ORDER:
            self._progress({"phase": "loading", "component": name})
            cls = (
                self._classes.text_encoder if name == "text_encoder" else self._classes.transformer
            )
            module = cls.from_pretrained(self._repo_id, subfolder=name, **kwargs)
            self.log.events.append(f"load:{name}")
            self._move(module, name, to_gpu=False)
            self._release_cache()
            parts[name] = module
        self._pipe = self._classes.pipeline.from_pretrained(self._repo_id, **parts, **kwargs)
        self.log.events.append("load:pipeline")
        self._mark("load_s", started)
        return self._pipe

    def count_tokens(self, caption_json: str) -> int:
        tokenizer = self._pipe.tokenizer
        messages = [{"role": "user", "content": [{"type": "text", "text": caption_json}]}]
        text = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        count = int(
            tokenizer(text, return_tensors="pt", add_special_tokens=False)["input_ids"].shape[1]
        )
        if count > self._policy.max_text_tokens:
            raise ResidencyRefusal(
                CODE_CAPTION_TOO_LONG,
                f"The caption is {count} tokens; Ideogram 4 accepts at most {self._policy.max_text_tokens}",
            )
        self.token_count = count
        return count

    def encode(self, settings: GenerationSettings) -> Any:
        """Encoder to the GPU, encode once, encoder back to host memory before any transformer arrives."""

        pipe = self._pipe
        max_len = self.count_tokens(settings.caption_json)
        grid_h, grid_w = settings.height // 16, settings.width // 16
        self._progress({"phase": "encoding"})
        self._move(pipe.text_encoder, "text_encoder", to_gpu=True)
        started = self._clock()
        with self._torch.no_grad():
            embeddings = pipe.encode_prompt(
                prompt=settings.caption_json,
                grid_h=grid_h,
                grid_w=grid_w,
                max_sequence_length=max_len,
                device=self._device(),
            )
        self._mark("text_encode_s", started)
        self._move(pipe.text_encoder, "text_encoder", to_gpu=False)
        self._release_cache()
        self.log.events.append("released:text_encoder")
        return embeddings

    def prepare_denoise(self, embeddings: Any, total_steps: int, image_count: int) -> None:
        """VAE resident, transformers on the host, swap + progress hooks installed, encoder output cached."""

        pipe = self._pipe
        device = self._device()
        self._move(pipe.vae, "vae", to_gpu=True)
        pipe.encode_prompt = lambda *_a, **_k: embeddings
        # Components are deliberately split across devices, so pin the execution device to the GPU.
        pipe.__class__ = type(
            "StableNewIdeogram4Pipeline",
            (type(pipe),),
            {"_execution_device": property(lambda _self: device)},
        )
        conditional, unconditional = pipe.transformer, pipe.unconditional_transformer
        state = self._state

        def swap(bring: Any, bring_name: str, park: Any, park_name: str) -> None:
            began = self._clock()
            self._move(park, park_name, to_gpu=False)
            self._move(bring, bring_name, to_gpu=True)
            self.log.swaps += 1
            self.log.swap_seconds = round(self.log.swap_seconds + self._clock() - began, 3)

        def before_conditional(_module: Any, _inputs: Any) -> None:
            state["step"] += 1
            self._progress(
                {
                    "phase": "denoising",
                    "image": state["image"] + 1,
                    "images": image_count,
                    "step": state["step"],
                    "steps": total_steps,
                }
            )
            swap(conditional, "transformer", unconditional, "unconditional_transformer")
            self.log.resident_at_forward.append(len(self._gpu_transformers))

        def before_unconditional(_module: Any, _inputs: Any) -> None:
            swap(unconditional, "unconditional_transformer", conditional, "transformer")
            self.log.resident_at_forward.append(len(self._gpu_transformers))

        conditional.register_forward_pre_hook(before_conditional)
        unconditional.register_forward_pre_hook(before_unconditional)

    def generate(self, settings: GenerationSettings) -> list[Any]:
        """Run the release pipeline's own denoising loop once per seed; returns PIL images in seed order."""

        pipe = self._pipe
        images: list[Any] = []
        started = self._clock()
        for index, seed in enumerate(settings.seeds):
            self._state.update(step=0, image=index)
            generator = self._torch.Generator(self._device_name).manual_seed(int(seed))
            result = pipe(
                settings.caption_json,
                height=settings.height,
                width=settings.width,
                num_inference_steps=settings.steps,
                guidance_schedule=list(settings.guidance_schedule),
                mu=settings.mu,
                std=settings.std,
                max_sequence_length=self.token_count,
                generator=generator,
            )
            images.append(result.images[0])
            self.log.events.append(f"image:{index}")
        self._mark("generate_s", started)
        return images

    def run(self, settings: GenerationSettings) -> list[Any]:
        self.apply_allocator_cap()
        self.load()
        embeddings = self.encode(settings)
        self.prepare_denoise(embeddings, settings.steps, len(settings.seeds))
        return self.generate(settings)

    def peak_memory(self) -> dict[str, float]:
        cuda = self._torch.cuda
        try:
            return {
                "torch_allocated_peak_mib": round(cuda.max_memory_allocated() / MIB, 1),
                "torch_reserved_peak_mib": round(cuda.max_memory_reserved() / MIB, 1),
            }
        except Exception:  # noqa: BLE001 - observational only
            return {}


def is_out_of_memory(torch: Any, exc: BaseException) -> bool:
    oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None)
    return (isinstance(oom_type, type) and isinstance(exc, oom_type)) or "out of memory" in str(
        exc
    ).lower()


def guidance_matches_steps(schedule: Sequence[float], steps: int) -> bool:
    return len(schedule) == steps and all(isinstance(value, (int, float)) for value in schedule)


__all__ = [
    "CODE_CAPTION_INVALID",
    "CODE_CAPTION_TOO_LONG",
    "CODE_FAILED",
    "CODE_OK",
    "CODE_OUT_OF_MEMORY",
    "CODE_REQUEST_INVALID",
    "CODE_RUNTIME_MISSING",
    "CODE_VRAM_INSUFFICIENT",
    "AllocatorCapDecision",
    "GenerationSettings",
    "LoaderClasses",
    "ResidencyLog",
    "ResidencyRefusal",
    "StagedSwapResidency",
    "guidance_matches_steps",
    "is_out_of_memory",
    "plan_allocator_cap",
]
