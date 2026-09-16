"""Run the bounded Torch-only CUDA sanity control for IMG-110 qualification."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import torch


def write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def memory_mib(value: int) -> float:
    return round(value / (1024 * 1024), 2)


def checkpoint(record: dict[str, Any], output: Path, stage: str, started: float) -> None:
    record["stage"] = stage
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    record["allocated_mib"] = memory_mib(torch.cuda.memory_allocated())
    record["reserved_mib"] = memory_mib(torch.cuda.memory_reserved())
    record["peak_allocated_mib"] = memory_mib(torch.cuda.max_memory_allocated())
    record["peak_reserved_mib"] = memory_mib(torch.cuda.max_memory_reserved())
    write_record(output, record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=4096)
    args = parser.parse_args()

    started = time.monotonic()
    record: dict[str, Any] = {
        "success": False,
        "size": args.size,
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
    }
    try:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable")
        record["device_name"] = torch.cuda.get_device_name(0)
        record["device_capability"] = torch.cuda.get_device_capability(0)
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        checkpoint(record, args.output, "cuda_ready", started)

        torch.manual_seed(110)
        identity = torch.eye(args.size, device="cuda", dtype=torch.float32)
        values = torch.arange(
            args.size * args.size,
            device="cuda",
            dtype=torch.float32,
        ).reshape(args.size, args.size)
        checkpoint(record, args.output, "allocated", started)

        product = identity @ values
        torch.cuda.synchronize()
        record["finite"] = bool(torch.isfinite(product).all().item())
        record["exact_identity_product"] = bool(torch.equal(product, values))
        checkpoint(record, args.output, "matmul_synchronized", started)
        if not record["finite"] or not record["exact_identity_product"]:
            raise RuntimeError("CUDA matrix multiply result did not match the expected value")

        del product, values, identity
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
