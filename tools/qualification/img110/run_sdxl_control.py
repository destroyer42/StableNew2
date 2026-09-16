"""Run one ordinary local SDXL Diffusers control sample for IMG-110."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil
import torch
from diffusers import StableDiffusionXLPipeline


def gpu_sample() -> str:
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


def mib(value: int) -> float:
    return round(value / (1024 * 1024), 2)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def checkpoint(record: dict[str, Any], output: Path, stage: str, started: float) -> None:
    record["stage"] = stage
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    record["allocated_mib"] = mib(torch.cuda.memory_allocated())
    record["reserved_mib"] = mib(torch.cuda.memory_reserved())
    record["peak_allocated_mib"] = mib(torch.cuda.max_memory_allocated())
    record["peak_reserved_mib"] = mib(torch.cuda.max_memory_reserved())
    record["system_ram_mib"] = round(psutil.virtual_memory().used / (1024 * 1024), 2)
    record["gpu"] = gpu_sample()
    write_record(output, record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=25)
    args = parser.parse_args()

    if not args.model.is_dir():
        raise SystemExit(f"model directory does not exist: {args.model}")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_image = args.output_dir / "sdxl-control-1024x1024-seed0.png"
    output_json = args.output_dir / "sdxl-control-1024x1024-seed0.json"
    started = time.monotonic()
    record: dict[str, Any] = {
        "success": False,
        "model": str(args.model),
        "pipeline": "StableDiffusionXLPipeline",
        "dtype": "float16",
        "variant": "fp16",
        "prompt": args.prompt,
        "seed": args.seed,
        "steps": args.steps,
        "width": 1024,
        "height": 1024,
        "callbacks": [],
    }
    pipeline: StableDiffusionXLPipeline | None = None
    try:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        checkpoint(record, output_json, "before_load", started)
        load_started = time.monotonic()
        pipeline = StableDiffusionXLPipeline.from_pretrained(
            args.model,
            torch_dtype=torch.float16,
            variant="fp16",
            local_files_only=True,
        )
        record["load_cpu_seconds"] = round(time.monotonic() - load_started, 3)
        checkpoint(record, output_json, "loaded_cpu", started)
        pipeline.to("cuda")
        record["load_cuda_seconds"] = round(time.monotonic() - load_started, 3)
        checkpoint(record, output_json, "loaded_cuda", started)

        def callback(
            _pipeline: StableDiffusionXLPipeline,
            step: int,
            _timestep: int,
            callback_kwargs: dict[str, Any],
        ) -> dict[str, Any]:
            record["callbacks"].append(
                {
                    "step": step,
                    "at_seconds": round(time.monotonic() - started, 3),
                    "gpu": gpu_sample(),
                    "system_ram_mib": round(psutil.virtual_memory().used / (1024 * 1024), 2),
                }
            )
            checkpoint(record, output_json, "denoising", started)
            return callback_kwargs

        inference_started = time.monotonic()
        result = pipeline(
            args.prompt,
            width=1024,
            height=1024,
            num_inference_steps=args.steps,
            generator=torch.Generator("cuda").manual_seed(args.seed),
            callback_on_step_end=callback,
        )
        record["inference_seconds"] = round(time.monotonic() - inference_started, 3)
        result.images[0].save(output_image)
        record["output_path"] = str(output_image)
        record["output_sha256"] = sha256(output_image)
        record["success"] = True
        checkpoint(record, output_json, "generated", started)
    except BaseException as exc:
        record["exception_type"] = type(exc).__name__
        record["exception"] = str(exc)
    finally:
        if pipeline is not None:
            del pipeline
        if "exception_type" not in record:
            try:
                torch.cuda.empty_cache()
            except BaseException as cleanup_exc:
                record["cleanup_exception"] = f"{type(cleanup_exc).__name__}: {cleanup_exc}"
        try:
            checkpoint(record, output_json, "complete", started)
        except BaseException as flush_exc:
            record["flush_exception"] = f"{type(flush_exc).__name__}: {flush_exc}"
            write_record(output_json, record)
    print(json.dumps(record, indent=2))
    return 0 if record["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
