"""One Ideogram 4 NF4 sample through the current release ``diffusers.Ideogram4Pipeline``.

Run inside the disposable Diffusers environment (never the production ``.venv``):

    <dfz-python> -m tools.qualification.img110r.run_diffusers --mode cpu_offload --level 1 ...

Modes
-----
cuda         ``pipe.to("cuda")``: every component resident (the IMG-110 configuration).
cpu_offload  the documented ``enable_model_cpu_offload()``.
staged       text encoder on the GPU first, released after the (public) ``encode_prompt``;
             then the two transformers and the VAE are moved to the GPU.  Only residency
             differs from ``cuda``; the pipeline's own denoising loop runs unchanged.
staged_swap  as ``staged`` but only one transformer is GPU-resident at a time: forward pre-hooks
             swap the conditional and unconditional transformers between host memory and the
             GPU around each call (``enable_model_cpu_offload`` chains its offloads in a fixed
             text_encoder -> transformer -> unconditional_transformer -> vae order and never
             parks the unconditional transformer when the conditional one returns next step).
group_leaf   diagnostic only: ``enable_group_offload(leaf_level)`` (the IMG-110 R6 path).

``--max-seq fit`` sets ``max_sequence_length`` to the prompt's exact token count, matching the
official reference (which pads only to the prompt); ``default`` keeps Diffusers' 2048.
"""

from __future__ import annotations

import argparse
import gc
import time
from pathlib import Path
from typing import Any

from tools.qualification.img110r.caption import caption_json
from tools.qualification.img110r.common import (
    DIFFUSERS_REPO,
    DIFFUSERS_REVISION,
    LEVELS,
    PRESETS,
    SEED,
    diffusers_guidance,
    query_gpu,
)
from tools.qualification.img110r.harness import Harness, package_versions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("cuda", "cpu_offload", "staged", "staged_swap", "group_leaf"),
        required=True,
    )
    parser.add_argument("--level", type=int, choices=sorted(LEVELS), required=True)
    parser.add_argument("--max-seq", choices=("default", "fit"), default="fit")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--vram-cap-mib", type=int)
    args = parser.parse_args()

    import torch
    from diffusers import Ideogram4Pipeline

    level = LEVELS[args.level]
    steps, _official_order, mu, std = PRESETS[level.preset]
    harness = Harness(
        torch,
        run_id=args.run_id,
        runtime=f"diffusers-{args.mode.replace('_', '-')}-seq{args.max_seq}",
        family="diffusers",
        level=level.number,
        out_dir=args.out_dir,
        model={"repo": DIFFUSERS_REPO, "revision": DIFFUSERS_REVISION},
        packages=package_versions(
            ("torch", "transformers", "accelerate", "bitsandbytes", "diffusers", "safetensors")
        ),
        vram_cap_mib=args.vram_cap_mib,
    )
    prompt = caption_json()
    timeline = harness.timeline
    with harness:
        harness.stage("loading")
        load_started = time.monotonic()
        loader_kwargs: dict[str, Any] = {
            "revision": DIFFUSERS_REVISION,
            "torch_dtype": torch.bfloat16,
            "local_files_only": True,
        }
        parts: dict[str, Any] = {}
        if args.mode in ("staged", "staged_swap"):
            # ``Ideogram4Pipeline.from_pretrained`` places every bitsandbytes NF4 component on the
            # GPU at once (about 15 GiB), which cannot fit a 12 GiB card.  Load the three NF4
            # components one at a time and park each in host memory before the next.
            from diffusers import Ideogram4Transformer2DModel
            from transformers import Qwen3VLModel

            for key, cls in (
                ("text_encoder", Qwen3VLModel),
                ("transformer", Ideogram4Transformer2DModel),
                ("unconditional_transformer", Ideogram4Transformer2DModel),
            ):
                module = cls.from_pretrained(DIFFUSERS_REPO, subfolder=key, **loader_kwargs)
                module.to("cpu")
                gc.collect()
                torch.cuda.empty_cache()
                parts[key] = module
        pipe = Ideogram4Pipeline.from_pretrained(DIFFUSERS_REPO, **parts, **loader_kwargs)
        harness.record.notes.append(
            f"from_pretrained (host) {time.monotonic() - load_started:.1f}s"
        )
        max_sequence_length = 2048
        if args.max_seq == "fit":
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            text = pipe.tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False
            )
            max_sequence_length = int(
                pipe.tokenizer(text, return_tensors="pt", add_special_tokens=False)[
                    "input_ids"
                ].shape[1]
            )
        timeline["max_sequence_length"] = max_sequence_length
        grid_h, grid_w = level.height // 16, level.width // 16

        original_encode = pipe.encode_prompt
        cached: dict[str, Any] = {}

        def timed_encode(*a: Any, **k: Any) -> Any:
            began = time.monotonic()
            out = original_encode(*a, **k)
            harness.mark_seconds("text_encode_s", began)
            return out

        pipe.encode_prompt = timed_encode
        if args.mode == "cuda":
            pipe.to("cuda")
        elif args.mode == "cpu_offload":
            pipe.enable_model_cpu_offload()
        elif args.mode == "group_leaf":
            pipe.enable_group_offload(torch.device("cuda"), offload_type="leaf_level")
        else:  # staged
            device = torch.device("cuda")
            pipe.text_encoder.to(device)
            harness.stage("text_encoding")
            encode_started = time.monotonic()
            with torch.no_grad():
                cached["value"] = original_encode(
                    prompt=prompt,
                    grid_h=grid_h,
                    grid_w=grid_w,
                    max_sequence_length=max_sequence_length,
                    device=device,
                )
            harness.mark_seconds("text_encode_s", encode_started)
            pipe.text_encoder.to("cpu")  # released from the GPU before the transformers arrive
            gc.collect()
            torch.cuda.empty_cache()
            timeline["vram_after_text_encoder_release_mib"] = query_gpu().vram_used_mib
            harness.stage("loading_transformers")
            stage_started = time.monotonic()
            resident = (
                ("vae",)
                if args.mode == "staged_swap"
                else (
                    "transformer",
                    "unconditional_transformer",
                    "vae",
                )
            )
            for name in resident:
                getattr(pipe, name).to(device)
            harness.mark_seconds("transformer_load_s", stage_started)
            pipe.encode_prompt = lambda *_a, **_k: cached["value"]
            if args.mode == "staged_swap":
                # Components are deliberately split across devices, so pin the execution device.
                pipe.__class__ = type(
                    "CudaExecutionIdeogram4Pipeline",
                    (type(pipe),),
                    {"_execution_device": property(lambda _self: device)},
                )
        harness.mark_seconds("load_s", load_started)
        timeline["vram_after_load_mib"] = query_gpu().vram_used_mib
        harness.flush()

        step_state = {"generate_started": 0.0}
        # Step timing uses module hooks, not ``callback_on_step_end``: on Python 3.11 the release
        # pipeline's callback path (``locals()`` inside a dict comprehension) raises KeyError.
        pipe.transformer.register_forward_pre_hook(lambda _module, _inputs: harness.step_began())
        pipe.unconditional_transformer.register_forward_hook(
            lambda _module, _inputs, _output: harness.step_ended()
        )
        if args.mode == "staged_swap":
            conditional, unconditional = pipe.transformer, pipe.unconditional_transformer

            def swap(bring: Any, park: Any) -> None:
                began = time.monotonic()
                park.to("cpu")
                bring.to(device)
                timeline["swap_seconds"] = round(
                    timeline.get("swap_seconds", 0.0) + time.monotonic() - began, 3
                )

            conditional.register_forward_pre_hook(lambda _m, _i: swap(conditional, unconditional))
            unconditional.register_forward_pre_hook(lambda _m, _i: swap(unconditional, conditional))

        original_decode = pipe.vae.decode

        def timed_decode(*a: Any, **k: Any) -> Any:
            harness.sync()
            timeline["denoise_total_s"] = round(
                time.monotonic() - step_state["generate_started"], 3
            )
            harness.stage("decoding")
            began = time.monotonic()
            out = original_decode(*a, **k)
            harness.mark_seconds("decode_s", began)
            return out

        pipe.vae.decode = timed_decode
        torch.cuda.reset_peak_memory_stats()
        step_state["generate_started"] = time.monotonic()
        result = pipe(
            prompt,
            height=level.height,
            width=level.width,
            num_inference_steps=steps,
            guidance_schedule=diffusers_guidance(level.preset),
            mu=mu,
            std=std,
            max_sequence_length=max_sequence_length,
            generator=torch.Generator("cuda").manual_seed(SEED),
        )
        harness.mark_seconds("generate_total_s", step_state["generate_started"])
        harness.succeed(result.images[0])
    return harness.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
