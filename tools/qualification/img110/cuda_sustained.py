"""Run a bounded Torch-only CUDA sustained control for IMG-110 qualification."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil
import torch


def write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def mib(value: int) -> float:
    return round(value / (1024 * 1024), 2)


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


def checkpoint(record: dict[str, Any], output: Path, stage: str, started: float) -> None:
    record["stage"] = stage
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    record["allocated_mib"] = mib(torch.cuda.memory_allocated())
    record["reserved_mib"] = mib(torch.cuda.memory_reserved())
    record["peak_allocated_mib"] = mib(torch.cuda.max_memory_allocated())
    record["peak_reserved_mib"] = mib(torch.cuda.max_memory_reserved())
    write_record(output, record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--size", type=int, default=8192)
    parser.add_argument("--sample-seconds", type=float, default=5.0)
    args = parser.parse_args()

    started = time.monotonic()
    record: dict[str, Any] = {
        "success": False,
        "seconds_requested": args.seconds,
        "size": args.size,
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "samples": [],
    }
    try:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable")
        record["device_name"] = torch.cuda.get_device_name(0)
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        left = torch.full((args.size, args.size), 0.001, device="cuda")
        right = torch.full((args.size, args.size), 0.002, device="cuda")
        checkpoint(record, args.output, "allocated", started)

        deadline = time.monotonic() + args.seconds
        next_sample = time.monotonic()
        iterations = 0
        while time.monotonic() < deadline:
            product = left @ right
            if not bool(torch.isfinite(product).all().item()):
                raise RuntimeError("non-finite result in sustained matrix multiply")
            del product
            iterations += 1
            now = time.monotonic()
            if now >= next_sample:
                torch.cuda.synchronize()
                record["samples"].append(
                    {
                        "at_seconds": round(now - started, 3),
                        "iterations": iterations,
                        "gpu": gpu_sample(),
                        "system_ram_mib": round(psutil.virtual_memory().used / (1024 * 1024), 2),
                    }
                )
                checkpoint(record, args.output, "running", started)
                next_sample = now + args.sample_seconds
        torch.cuda.synchronize()
        record["iterations"] = iterations
        del right, left
        torch.cuda.empty_cache()
        checkpoint(record, args.output, "freed", started)
        record["success"] = True
    except BaseException as exc:
        record["exception_type"] = type(exc).__name__
        record["exception"] = str(exc)
    finally:
        try:
            checkpoint(record, args.output, "complete", started)
        except BaseException as flush_exc:
            record["flush_exception"] = f"{type(flush_exc).__name__}: {flush_exc}"
            write_record(args.output, record)
    print(json.dumps(record, indent=2))
    return 0 if record["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
