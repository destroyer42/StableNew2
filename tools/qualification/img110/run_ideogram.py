"""Run one reproducible, local-only Ideogram 4 qualification sample.

This is qualification tooling only.  It never imports StableNew application
code or registers an image backend.  Model and output paths must be supplied
explicitly and are expected to be outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil
import torch
from diffusers import Ideogram4Pipeline


@dataclass
class Sample:
    at_seconds: float
    allocated_mib: float
    reserved_mib: float
    system_ram_mib: float


def mib(value: int) -> float:
    return round(value / (1024 * 1024), 2)


def gpu_memory() -> tuple[float, float]:
    return (
        mib(torch.cuda.memory_allocated()),
        mib(torch.cuda.memory_reserved()),
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gpu_driver_sample() -> str:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free,memory.used,utilization.gpu,temperature.gpu,power.draw,pstate",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=48)
    parser.add_argument("--label", default="ideogram")
    parser.add_argument(
        "--strategy",
        choices=("cuda", "model_cpu", "group_cpu", "sequential_cpu"),
        default="cuda",
    )
    parser.add_argument("--cancel-after-step", type=int)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")
    if args.width % 16 or args.height % 16:
        raise SystemExit("width and height must be multiples of 16")
    if not args.model.is_dir():
        raise SystemExit(f"model directory does not exist: {args.model}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    samples: list[Sample] = []
    callback_steps: list[dict[str, Any]] = []
    sampling = True
    output_path = args.output_dir / (
        f"{args.label}-{args.strategy}-{args.width}x{args.height}-seed{args.seed}.png"
    )
    evidence_path = args.output_dir / f"{output_path.stem}.json"
    result: dict[str, Any] = {
        "model": str(args.model),
        "strategy": args.strategy,
        "seed": args.seed,
        "width": args.width,
        "height": args.height,
        "steps": args.steps,
        "success": False,
        "callbacks": callback_steps,
    }

    def flush(stage: str) -> None:
        result["stage"] = stage
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["samples"] = [asdict(sample) for sample in samples]
        evidence_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    def collect() -> None:
        while sampling:
            allocated, reserved = gpu_memory()
            samples.append(
                Sample(
                    at_seconds=round(time.monotonic() - started, 3),
                    allocated_mib=allocated,
                    reserved_mib=reserved,
                    system_ram_mib=round(psutil.virtual_memory().used / (1024 * 1024), 2),
                )
            )
            time.sleep(0.5)

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    flush("before_load")
    try:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        load_started = time.monotonic()
        pipe = Ideogram4Pipeline.from_pretrained(
            args.model,
            torch_dtype=torch.bfloat16,
            local_files_only=True,
        )
        if args.strategy == "cuda":
            pipe.to("cuda")
        elif args.strategy == "model_cpu":
            pipe.enable_model_cpu_offload()
        elif args.strategy == "group_cpu":
            pipe.enable_group_offload(torch.device("cuda"), offload_type="leaf_level")
        else:
            pipe.enable_sequential_cpu_offload()
        result["load_seconds"] = round(time.monotonic() - load_started, 3)
        flush("loaded")

        def callback(_pipe: Any, step: int, _timestep: int, callback_kwargs: dict[str, Any]) -> dict[str, Any]:
            callback_steps.append(
                {
                    "step": step,
                    "at_seconds": round(time.monotonic() - started, 3),
                    "gpu": gpu_driver_sample(),
                    "system_ram_mib": round(psutil.virtual_memory().used / (1024 * 1024), 2),
                }
            )
            flush("denoising")
            if args.cancel_after_step is not None and step >= args.cancel_after_step:
                raise InterruptedError(f"qualification cancellation injected at inference step {step}")
            return callback_kwargs

        generate_started = time.monotonic()
        image = pipe(
            args.prompt,
            height=args.height,
            width=args.width,
            num_inference_steps=args.steps,
            prompt_upsampling=False,
            generator=torch.Generator("cuda").manual_seed(args.seed),
            callback_on_step_end=callback,
        ).images[0]
        result["generation_seconds"] = round(time.monotonic() - generate_started, 3)
        image.save(output_path)
        result.update(
            success=True,
            output_path=str(output_path),
            artifact_sha256=sha256(output_path),
            callback_count=len(callback_steps),
        )
    except BaseException as exc:  # record qualification failures, then clean GPU state
        result.update(exception_type=type(exc).__name__, exception=str(exc))
    finally:
        if "pipe" in locals():
            del pipe
        sampling = False
        thread.join(timeout=2)
        if "exception_type" not in result:
            result["peak_allocated_mib"] = mib(torch.cuda.max_memory_allocated())
            result["peak_reserved_mib"] = mib(torch.cuda.max_memory_reserved())
            torch.cuda.empty_cache()
        result["unload_seconds"] = round(time.monotonic() - started, 3)
        flush("complete")
        print(json.dumps(result, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
