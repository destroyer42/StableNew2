"""One provider per map type, behind one seam (PR-IMG-CNET-230).

Each provider turns the loaded, oriented source into an RGB map plus the exact method identity, auxiliary-file identity,
runtime versions and disclosed warnings. Canny is a pure CPU adapter; depth and OpenPose stage their hash-verified model
files and run one contained child process through the repository's bounded-process helper (``run_bounded``): a
wall-clock timeout, a stdout cap and cooperative cancellation that kills the child's whole tree. The child sees no GPU.

A provider that cannot run raises ``ProviderUnavailable`` with precise reason codes. Nothing falls back to another map
type or method, and nothing here starts a thread, a runtime, a job or a network request.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from src.conditioning.reference_map import auxiliary, canny, depth, pose
from src.conditioning.reference_map.contracts import (
    CODE_CANCELLED,
    CODE_INFERENCE,
    CODE_TIMEOUT,
    AuxiliaryFileIdentity,
    CancelCheck,
    MethodIdentity,
    ProviderUnavailable,
    ReferenceMapError,
)
from src.conditioning.reference_map.source import LoadedSource
from src.conditioning.reference_map.worker import (
    DEPTH_FILE,
    REQUEST_FILE,
    RESULT_FILE,
    SOURCE_FILE,
)
from src.utils.managed_process import ProcessOutcome, run_bounded

WORKER_PATH = Path(__file__).with_name("worker.py")
MAX_RESULT_BYTES = 8 * 1024 * 1024
WORKER_STDOUT_CAP = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = {"depth": 300.0, "openpose": 600.0}
_ENV_ALLOWLIST = (
    "SYSTEMROOT", "SYSTEMDRIVE", "PATH", "PATHEXT", "TEMP", "TMP", "TMPDIR",
    "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HOME", "LANG", "LC_ALL", "VIRTUAL_ENV",
)  # fmt: skip
_ENV_FORCED = {
    "CUDA_VISIBLE_DEVICES": "-1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONDONTWRITEBYTECODE": "1",
}


class ProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float,
        max_stdout_bytes: int,
        cancel: CancelCheck | None,
        env: Mapping[str, str],
    ) -> ProcessOutcome: ...


def bounded_runner(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    max_stdout_bytes: int,
    cancel: CancelCheck | None,
    env: Mapping[str, str],
) -> ProcessOutcome:
    return run_bounded(
        command,
        timeout_seconds=timeout_seconds,
        max_stdout_bytes=max_stdout_bytes,
        cancel=cancel,
        env=env,
    )


def worker_environment() -> dict[str, str]:
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env.update(_ENV_FORCED)
    return env


@dataclass(frozen=True, slots=True)
class Context:
    registry: Any
    cancel: CancelCheck
    runner: ProcessRunner = bounded_runner
    timeouts: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_TIMEOUT_SECONDS))
    interpreter: str = sys.executable
    temp_root: str | None = None

    def check(self) -> None:
        if self.cancel():
            raise ReferenceMapError(CODE_CANCELLED, "Cancelled.")


@dataclass(frozen=True, slots=True)
class Produced:
    rgb: np.ndarray
    method: MethodIdentity
    runtime: dict[str, str] = field(default_factory=dict)
    auxiliary: tuple[AuxiliaryFileIdentity, ...] = ()
    auxiliary_resource: str = ""
    warnings: tuple[str, ...] = ()


class Provider(Protocol):
    modality: str

    def availability(self) -> tuple[str, ...]:
        """Cheap runtime reason codes (nothing is imported or hashed); empty when the runtime looks usable."""
        ...

    def produce(self, source: LoadedSource, context: Context) -> Produced: ...


def _find(*modules: str) -> tuple[str, ...]:
    return tuple(
        f"runtime_missing:{name}" for name in modules if importlib.util.find_spec(name) is None
    )


class CannyProvider:
    modality = "canny"

    def availability(self) -> tuple[str, ...]:
        return canny.availability()

    def produce(self, source: LoadedSource, context: Context) -> Produced:
        reasons = self.availability()
        if reasons:
            raise ProviderUnavailable(
                "Canny needs OpenCV, which is not installed.", reasons=reasons
            )
        context.check()
        rgb = canny.canny_map(source.rgb)
        context.check()
        return Produced(rgb, canny.identity(), runtime=canny.runtime_versions())


def run_worker(
    job_dir: Path,
    modality: str,
    kind: str,
    request: dict[str, Any],
    rgb: np.ndarray,
    context: Context,
) -> dict[str, Any]:
    """Run the contained worker for one job and return its validated ``result.json`` document."""

    height, width = int(rgb.shape[0]), int(rgb.shape[1])
    (job_dir / SOURCE_FILE).write_bytes(np.ascontiguousarray(rgb).tobytes())
    (job_dir / REQUEST_FILE).write_text(
        json.dumps({**request, "kind": kind, "width": width, "height": height}), encoding="utf-8"
    )
    context.check()
    outcome = context.runner(
        [context.interpreter, "-I", str(WORKER_PATH), str(job_dir)],
        timeout_seconds=float(context.timeouts[modality]),
        max_stdout_bytes=WORKER_STDOUT_CAP,
        cancel=context.cancel,
        env=worker_environment(),
    )
    if outcome.cancelled:
        raise ReferenceMapError(CODE_CANCELLED, "Cancelled.")
    if outcome.timed_out:
        raise ReferenceMapError(CODE_TIMEOUT, "The model took too long and was stopped.")
    if outcome.launch_error:
        raise ReferenceMapError(CODE_INFERENCE, "The model process could not be started.")
    document = _read_result(job_dir)
    if outcome.returncode != 0 or not document.get("ok"):
        reasons = tuple(str(item) for item in document.get("reasons", ()) if isinstance(item, str))
        if document.get("code") == "provider_unavailable":
            raise ProviderUnavailable(
                "The model runtime is not available in this environment.", reasons=reasons[:8]
            )
        raise ReferenceMapError(
            CODE_INFERENCE, "The model failed to produce a map.", reasons=reasons[:8]
        )
    return document


def _read_result(job_dir: Path) -> dict[str, Any]:
    path = job_dir / RESULT_FILE
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_RESULT_BYTES + 1)
        if len(data) > MAX_RESULT_BYTES:
            raise ValueError("oversized")
        document = json.loads(data.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ReferenceMapError(CODE_INFERENCE, "The model produced no readable result.") from exc
    if not isinstance(document, dict):
        raise ReferenceMapError(CODE_INFERENCE, "The model produced an invalid result.")
    return document


def _runtime(document: Mapping[str, Any]) -> dict[str, str]:
    raw = document.get("runtime")
    if not isinstance(raw, dict):
        return {}
    return {str(k)[:32]: str(v)[:32] for k, v in list(raw.items())[:8]}


class _AuxiliaryProvider:
    modality = ""
    kind = ""
    modules: tuple[str, ...] = ()

    def availability(self) -> tuple[str, ...]:
        return _find(*self.modules)

    def _prepare(
        self, source: LoadedSource, context: Context
    ) -> tuple[Any, dict[str, Any], tempfile.TemporaryDirectory[str]]:
        reasons = self.availability()
        if reasons:
            raise ProviderUnavailable(
                f"{auxiliary.TITLE_BY_MODALITY[self.modality]} needs a runtime that is not installed "
                f"({', '.join(reasons)}).",
                reasons=reasons,
            )
        verified = auxiliary.verify_resource(
            context.registry, self.modality, cancelled=context.cancel
        )
        context.check()
        job = tempfile.TemporaryDirectory(prefix="stablenew-refmap-", dir=context.temp_root)
        try:
            staged = auxiliary.stage_resource(
                verified,
                context.registry.webui_root,
                Path(job.name) / "models",
                cancelled=context.cancel,
            )
        except BaseException:
            job.cleanup()
            raise
        return verified, staged, job


class DepthProvider(_AuxiliaryProvider):
    modality = "depth"
    kind = "depth"
    modules = ("torch", "transformers")

    def produce(self, source: LoadedSource, context: Context) -> Produced:
        verified, staged, job = self._prepare(source, context)
        try:
            directory = Path(job.name)
            document = run_worker(
                directory,
                "depth",
                "depth",
                {"staged_dir": str(directory / "models")},
                source.rgb,
                context,
            )
            context.check()
            shape = document.get("shape")
            if not (
                isinstance(shape, list)
                and len(shape) == 2
                and all(isinstance(n, int) and n > 0 for n in shape)
            ):
                raise ReferenceMapError(
                    CODE_INFERENCE, "The depth model returned an invalid shape."
                )
            data = (directory / DEPTH_FILE).read_bytes()
            if len(data) != shape[0] * shape[1] * 4:
                raise ReferenceMapError(CODE_INFERENCE, "The depth model returned truncated data.")
            prediction = np.frombuffer(data, dtype="<f4").reshape(shape[0], shape[1])
            rgb = depth.prediction_to_map(prediction, source.facts.width, source.facts.height)
        finally:
            job.cleanup()
        return Produced(
            rgb,
            depth.identity(),
            runtime=_runtime(document),
            auxiliary=verified.files,
            auxiliary_resource=verified.resource_id,
            warnings=verified.warnings,
        )


class PoseProvider(_AuxiliaryProvider):
    modality = "openpose"
    kind = "pose"
    modules = ("onnxruntime", "cv2")

    def produce(self, source: LoadedSource, context: Context) -> Produced:
        verified, staged, job = self._prepare(source, context)
        try:
            directory = Path(job.name)
            document = run_worker(
                directory,
                "openpose",
                "pose",
                {"staged": {role: str(path) for role, path in staged.items()}},
                source.rgb,
                context,
            )
            context.check()
            people = pose.people_from_payload(document)
        finally:
            job.cleanup()
        rgb, warnings = pose.render_pose(people, source.facts.width, source.facts.height)
        return Produced(
            rgb,
            pose.identity(),
            runtime=_runtime(document),
            auxiliary=verified.files,
            auxiliary_resource=verified.resource_id,
            warnings=tuple(dict.fromkeys((*verified.warnings, *warnings))),
        )


def default_providers() -> dict[str, Provider]:
    return {
        "canny": CannyProvider(),
        "depth": DepthProvider(),
        "openpose": PoseProvider(),
    }


__all__ = [
    "CannyProvider",
    "Context",
    "DepthProvider",
    "PoseProvider",
    "ProcessRunner",
    "Produced",
    "Provider",
    "bounded_runner",
    "default_providers",
    "run_worker",
    "worker_environment",
]
