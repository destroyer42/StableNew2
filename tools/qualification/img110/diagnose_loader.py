"""Capture non-inference Diffusers loader diagnostics for a local Ideogram snapshot."""

from __future__ import annotations

import argparse
import json
import traceback
import warnings
from pathlib import Path
from typing import Any

import torch
from diffusers import DiffusionPipeline, Ideogram4Pipeline


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--model", type=Path, required=True)
    result.add_argument(
        "--pattern",
        choices=("diffusion_device_map", "ideogram_device_map", "cpu_init"),
        required=True,
    )
    return result


def meta_parameters(pipe: Any) -> list[str]:
    remaining: list[str] = []
    for component_name, component in pipe.components.items():
        if not isinstance(component, torch.nn.Module):
            continue
        for parameter_name, parameter in component.named_parameters():
            if parameter.is_meta:
                remaining.append(f"{component_name}.{parameter_name}")
                if len(remaining) == 20:
                    return remaining
    return remaining


def main() -> int:
    args = parser().parse_args()
    if not args.model.is_dir():
        raise SystemExit(f"missing local model directory: {args.model}")
    pipeline_class: type[DiffusionPipeline]
    kwargs: dict[str, Any] = {
        "local_files_only": True,
        "torch_dtype": torch.bfloat16,
    }
    if args.pattern == "diffusion_device_map":
        pipeline_class = DiffusionPipeline
        kwargs["device_map"] = "cuda"
    elif args.pattern == "ideogram_device_map":
        pipeline_class = Ideogram4Pipeline
        kwargs["device_map"] = "cuda"
    else:
        pipeline_class = Ideogram4Pipeline

    details: dict[str, Any] = {
        "pattern": args.pattern,
        "pipeline_class": pipeline_class.__name__,
        "model": str(args.model),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "diffusers": __import__("diffusers").__version__,
        "success": False,
    }
    pipe: Any = None
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            pipe = pipeline_class.from_pretrained(args.model, **kwargs)
        details["warnings"] = [str(item.message) for item in captured]
        details["meta_parameter_examples"] = meta_parameters(pipe)
        details["success"] = True
    except BaseException as exc:  # qualification evidence must retain upstream errors
        details["exception_type"] = type(exc).__name__
        details["exception"] = str(exc)
        details["traceback_tail"] = traceback.format_exc().splitlines()[-12:]
        if pipe is not None:
            details["meta_parameter_examples"] = meta_parameters(pipe)
    finally:
        if pipe is not None:
            del pipe
        torch.cuda.empty_cache()
        details["vram_free_mib_after"] = round(
            (torch.cuda.mem_get_info()[0] if torch.cuda.is_available() else 0) / (1024 * 1024), 2
        )
        print(json.dumps(details, indent=2))
    return 0 if details["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
