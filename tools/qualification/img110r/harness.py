"""Shared run scaffolding for the official and Diffusers IMG-110R runners.

One ``Harness`` = one fresh process = one evidence record.  It owns the incremental JSON
record, the flushed telemetry trail, the step timeline and the exception/poison handling,
so both runners measure identically and the runtime under test is the only variable.
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from types import TracebackType
from typing import Any

from tools.qualification.img110r.caption import caption_sha256
from tools.qualification.img110r.common import (
    LEVELS,
    PRESETS,
    RunRecord,
    Telemetry,
    is_context_poisoning,
    mib,
    query_gpu,
    sha256_file,
)


def package_versions(names: tuple[str, ...]) -> dict[str, str]:
    import importlib.metadata as metadata
    import platform

    found = {name: metadata.version(name) for name in names}
    found["python"] = platform.python_version()
    return found


def validate_image(image: Any, width: int, height: int) -> dict[str, Any]:
    import numpy as np

    array = np.asarray(image.convert("RGB"), dtype=np.float32)
    spread = float(array.std())
    return {
        "width": image.width,
        "height": image.height,
        "pixel_mean": round(float(array.mean()), 2),
        "pixel_std": round(spread, 2),
        "valid": image.size == (width, height) and spread > 8.0,
    }


class Harness:
    def __init__(
        self,
        torch: Any,
        *,
        run_id: str,
        runtime: str,
        family: str,
        level: int,
        out_dir: Path,
        model: dict[str, str],
        packages: dict[str, str],
        vram_cap_mib: int | None,
    ) -> None:
        self.torch = torch
        spec = LEVELS[level]
        steps = PRESETS[spec.preset][0]
        self.level = spec
        self.record = RunRecord(
            run_id=run_id,
            runtime=runtime,
            family=family,
            level=level,
            width=spec.width,
            height=spec.height,
            preset=spec.preset,
            steps=steps,
            vram_cap_mib=vram_cap_mib,
            prompt_sha256=caption_sha256(),
            model=model,
            packages=packages,
            stage="started",
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        self.result_path = out_dir / f"{run_id}.json"
        self.image_path = out_dir / f"{run_id}.png"
        self.timeline: dict[str, Any] = {"step_seconds": []}
        self._started = time.monotonic()
        self.step_starts: list[float] = []
        self.step_ends: list[float] = []
        baseline = query_gpu()
        self.record.gpu_baseline = {
            "name": torch.cuda.get_device_name(0),
            "torch_cuda": torch.version.cuda,
            "vram_used_mib": baseline.vram_used_mib,
            "vram_total_mib": baseline.vram_total_mib,
            "vram_free_mib": baseline.vram_total_mib - baseline.vram_used_mib,
            "temp_c": baseline.temp_c,
        }
        if vram_cap_mib:
            torch.cuda.set_per_process_memory_fraction(
                min(1.0, vram_cap_mib / baseline.vram_total_mib)
            )
        self.telemetry = Telemetry(
            out_dir / f"{run_id}_telemetry.csv",
            lambda: (mib(torch.cuda.memory_allocated()), mib(torch.cuda.memory_reserved())),
        )
        self.exit_code = 1

    # -- time/stage helpers --------------------------------------------------------------
    def now(self) -> float:
        return round(time.monotonic() - self._started, 3)

    def sync(self) -> None:
        self.torch.cuda.synchronize()

    def stage(self, name: str) -> None:
        self.telemetry.stage = self.record.stage = name
        self.flush()

    def flush(self) -> None:
        self.record.timing = {**self.timeline, "elapsed_s": self.now()}
        self.record.write(self.result_path)

    # -- step instrumentation ------------------------------------------------------------
    def step_began(self) -> None:
        self.sync()
        self.step_starts.append(time.monotonic())
        if len(self.step_starts) == 1:
            self.timeline["first_step_started_s"] = self.now()
            self.stage("denoising")

    def step_ended(self) -> None:
        self.sync()
        self.step_ends.append(time.monotonic())
        self.timeline["step_seconds"] = [
            round(end - begin, 3)
            for begin, end in zip(self.step_starts, self.step_ends, strict=False)
        ]
        if len(self.step_ends) == 1:
            self.timeline["first_step_done_s"] = self.now()
            self.timeline["first_step_seconds"] = self.timeline["step_seconds"][0]
            self.flush()

    def mark_seconds(self, key: str, began: float) -> None:
        self.sync()
        self.timeline[key] = round(time.monotonic() - began, 3)

    # -- outcome ------------------------------------------------------------------------
    def succeed(self, image: Any) -> None:
        self.torch.cuda.synchronize()
        image.save(self.image_path)
        self.record.output = {
            "path": str(self.image_path),
            "sha256": sha256_file(self.image_path),
            **validate_image(image, self.level.width, self.level.height),
        }
        self.record.success = True
        self.record.stage = "complete"
        self.exit_code = 0

    def __enter__(self) -> Harness:
        self.telemetry.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        record = self.record
        if exc is not None:
            record.exception_type = type(exc).__name__
            record.exception = str(exc)[:2500]
            frames = traceback.extract_tb(tb)
            record.failing_operation = " <- ".join(
                f"{Path(f.filename).name}:{f.lineno} {f.name}: {f.line}"
                for f in reversed(frames[-4:])
            )
            if is_context_poisoning(record.exception_type, record.exception):
                record.context_poisoned = True
                self.exit_code = 3
            if record.stage == "denoising" and self.step_ends:
                record.stage = "complete_failed_after_step"
        self.timeline["total_s"] = self.now()
        if not record.context_poisoned:  # never touch a possibly poisoned CUDA context
            try:
                record.peaks["torch_max_allocated_mib"] = mib(
                    self.torch.cuda.max_memory_allocated()
                )
                record.peaks["torch_max_reserved_mib"] = mib(self.torch.cuda.max_memory_reserved())
            except Exception as error:  # noqa: BLE001
                record.notes.append(f"torch peak stats unavailable: {error}")
        self.telemetry.__exit__(exc_type, exc, tb)
        record.peaks.update(self.telemetry.peaks.as_dict())
        self.flush()
        print(record.to_json())
        return exc is not None  # every failure is recorded as evidence; exit code carries it
