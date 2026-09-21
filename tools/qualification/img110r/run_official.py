"""One Ideogram 4 NF4 sample through the OFFICIAL ``ideogram-oss/ideogram4`` reference code.

Run inside the disposable reference environment (never the production ``.venv``):

    <ref-python> -m tools.qualification.img110r.run_official --mode staged --level 1 ...

Modes
-----
as_shipped  the official ``run_inference.py`` path verbatim: ``Ideogram4Pipeline.from_pretrained``
            puts the two transformers *and* the Qwen3-VL text encoder on the GPU together
            (about 15 GiB of NF4 weights).
staged_swap  as ``staged`` but only one transformer is GPU-resident at a time: a forward
            pre-hook swaps the conditional and unconditional transformers between the GPU and
            host memory around each call (the official loop runs unchanged, only residency
            differs).
staged      the same official classes and denoising loop, but the text encoder is used first
            and released before the transformers are loaded.  Only *residency* differs: the
            text features are computed once by the official ``_encode_text`` and handed back to
            the official ``__call__`` unchanged, so the maths and the sampler are the official
            ones.
"""

from __future__ import annotations

import argparse
import gc
import time
from pathlib import Path
from typing import Any

from tools.qualification.img110r.caption import caption_json
from tools.qualification.img110r.common import (
    LEVELS,
    OFFICIAL_REPO,
    OFFICIAL_REVISION,
    PRESETS,
    SEED,
    query_gpu,
)
from tools.qualification.img110r.harness import Harness, package_versions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("as_shipped", "staged", "staged_swap"), required=True)
    parser.add_argument("--level", type=int, choices=sorted(LEVELS), required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--vram-cap-mib",
        type=int,
        help="Torch allocator cap so exceeding physical VRAM raises an explicit OOM instead of "
        "silently spilling into shared system memory (WDDM sysmem fallback).",
    )
    args = parser.parse_args()

    import torch
    from huggingface_hub import HfApi
    from ideogram4 import PRESETS as OFFICIAL_PRESETS
    from ideogram4 import pipeline_ideogram4 as pipeline_module
    from ideogram4.modeling_ideogram4 import Ideogram4Config

    level = LEVELS[args.level]
    preset = OFFICIAL_PRESETS[level.preset]
    ours = PRESETS[level.preset]
    harness = Harness(
        torch,
        run_id=args.run_id,
        runtime=f"official-{args.mode.replace('_', '-')}",
        family="official",
        level=level.number,
        out_dir=args.out_dir,
        model={"repo": OFFICIAL_REPO, "revision": OFFICIAL_REVISION},
        packages=package_versions(
            ("torch", "transformers", "accelerate", "bitsandbytes", "ideogram-4", "safetensors")
        ),
        vram_cap_mib=args.vram_cap_mib,
    )
    # The official loader always reads ``main``; require it to still be the revision we recorded.
    head = HfApi().model_info(OFFICIAL_REPO).sha
    if head != OFFICIAL_REVISION:
        raise SystemExit(f"{OFFICIAL_REPO} main moved to {head}; re-pin before running")
    harness.record.notes.append(
        "presets match official registry: "
        f"{(preset.num_steps, tuple(preset.guidance_schedule), preset.mu, preset.std) == ours}"
    )
    prompt = caption_json()
    device = torch.device("cuda")
    dtype = torch.bfloat16
    config = pipeline_module.Ideogram4PipelineConfig(weights_repo=OFFICIAL_REPO)
    timeline = harness.timeline
    with harness:
        harness.stage("loading")
        load_started = time.monotonic()
        if args.mode == "as_shipped":
            pipe = pipeline_module.Ideogram4Pipeline.from_pretrained(
                config=config, device=device, dtype=dtype
            )
        else:
            tokenizer, text_encoder = pipeline_module._load_qwen3_vl(
                OFFICIAL_REPO,
                device,
                dtype,
                tokenizer_subfolder=config.tokenizer_subfolder,
                text_encoder_subfolder=config.text_encoder_subfolder,
            )
            harness.mark_seconds("text_encoder_load_s", load_started)
            pipe = pipeline_module.Ideogram4Pipeline(
                conditional_transformer=None,
                unconditional_transformer=None,
                text_encoder=text_encoder,
                text_tokenizer=tokenizer,
                autoencoder=None,
                config=config,
                device=device,
                dtype=dtype,
            )
            harness.stage("text_encoding")
            encode_started = time.monotonic()
            pipe._verify_prompts([prompt], raise_on_issues=True)
            inputs = pipe._build_inputs([prompt], height=level.height, width=level.width)
            with torch.no_grad():
                features = pipe._encode_text(
                    inputs["token_ids"], inputs["text_position_ids"], inputs["indicator"]
                )
            harness.mark_seconds("text_encode_s", encode_started)
            timeline["text_tokens"] = int(inputs["max_text_tokens"])
            pipe.text_encoder = text_encoder = None  # release the encoder before the transformers
            gc.collect()
            torch.cuda.empty_cache()
            timeline["vram_after_text_encoder_release_mib"] = query_gpu().vram_used_mib
            harness.stage("loading_transformers")
            stage_started = time.monotonic()
            transformer_config = Ideogram4Config()
            for attribute, index in (
                ("conditional_transformer", config.conditional_index_filename),
                ("unconditional_transformer", config.unconditional_index_filename),
            ):
                state = pipeline_module._load_indexed_or_single_state_dict(OFFICIAL_REPO, index)
                # The official loader first builds a full float32 skeleton on the host (about 2x
                # the model in RAM); a bf16 default halves that without changing loaded values.
                torch.set_default_dtype(torch.bfloat16)
                try:
                    module = pipeline_module._build_transformer(
                        transformer_config, state, device, dtype
                    )
                finally:
                    torch.set_default_dtype(torch.float32)
                setattr(pipe, attribute, module)
                del state
                gc.collect()
                if args.mode == "staged_swap":
                    module.to("cpu")
                    torch.cuda.empty_cache()
            weights = pipeline_module.hf_hub_download(
                repo_id=OFFICIAL_REPO, filename=config.autoencoder_filename
            )
            pipe.autoencoder = pipeline_module._load_autoencoder(weights, device, dtype)
            harness.mark_seconds("transformer_load_s", stage_started)
            pipe._encode_text = lambda *_a, **_k: features  # official features, computed above
        harness.mark_seconds("load_s", load_started)
        timeline["vram_after_load_mib"] = query_gpu().vram_used_mib
        harness.flush()

        original_encode, original_decode = pipe._encode_text, pipe._decode
        generate_started = 0.0

        def timed_encode(*a: Any, **k: Any) -> Any:
            began = time.monotonic()
            out = original_encode(*a, **k)
            if args.mode == "as_shipped":
                harness.mark_seconds("text_encode_s", began)
            return out

        def timed_decode(*a: Any, **k: Any) -> Any:
            harness.sync()
            timeline["denoise_total_s"] = round(time.monotonic() - generate_started, 3)
            harness.stage("decoding")
            began = time.monotonic()
            out = original_decode(*a, **k)
            harness.mark_seconds("decode_s", began)
            return out

        pipe._encode_text, pipe._decode = timed_encode, timed_decode
        conditional, unconditional = pipe.conditional_transformer, pipe.unconditional_transformer

        def swap(bring: Any, park: Any) -> None:
            began = time.monotonic()
            park.to("cpu")
            bring.to(device)
            timeline["swap_seconds"] = round(
                timeline.get("swap_seconds", 0.0) + time.monotonic() - began, 3
            )

        # step_began is registered first so the per-step time includes the transformer swaps.
        conditional.register_forward_pre_hook(lambda _module, _inputs: harness.step_began())
        if args.mode == "staged_swap":
            conditional.register_forward_pre_hook(lambda _m, _i: swap(conditional, unconditional))
            unconditional.register_forward_pre_hook(lambda _m, _i: swap(unconditional, conditional))
        pipe.unconditional_transformer.register_forward_hook(
            lambda _module, _inputs, _output: harness.step_ended()
        )
        torch.cuda.reset_peak_memory_stats()
        generate_started = time.monotonic()
        images = pipe(
            prompt,
            height=level.height,
            width=level.width,
            num_steps=preset.num_steps,
            guidance_schedule=preset.guidance_schedule,
            mu=preset.mu,
            std=preset.std,
            seed=SEED,
            raise_on_caption_issues=True,
        )
        harness.mark_seconds("generate_total_s", generate_started)
        harness.succeed(images[0])
    return harness.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
