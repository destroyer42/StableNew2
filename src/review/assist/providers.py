"""Adapter protocols and the contained-child implementations for Smart Review (PR-IMG-REVIEW-320).

``SegmentAdapter`` and ``CaptionAdapter`` are the only things the session knows about; tests drive it with fakes. The real
adapters reuse the repository's existing seams and add nothing new:

* model byte identity and readiness come from PR-ASSET-130's ``AssetRegistry``/curated catalog (``auxiliary.verify_resource``),
  never from a second installed-model registry;
* the verified files are copied into a private staging directory while being hashed again (``auxiliary.stage_resource``), so the
  bytes the model reads are the bytes that were verified;
* inference runs once in a child process under ``run_bounded`` (own OS container, wall-clock timeout, output cap, cooperative
  cancellation that kills the whole tree), on CPU only, offline, with no remote code and no pickle. Nothing here starts a
  thread, a server, a job or a network request, and nothing loads a model at import time.

A model that cannot run raises ``AssistUnavailable`` with precise reason codes; nothing falls back to another model.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import re
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from src.conditioning.reference_map import auxiliary
from src.conditioning.reference_map.contracts import ProviderUnavailable, ReferenceMapError
from src.conditioning.reference_map.providers import (
    Context,
    ProcessRunner,
    bounded_runner,
    run_worker,
    unenforced_warnings,
)
from src.review.assist.contracts import (
    CAPABILITY_CAPTION,
    CAPABILITY_SEGMENT,
    CODE_CANCELLED,
    CODE_INFERENCE,
    CODE_OUTPUT,
    CODE_TIMEOUT,
    MAX_LABEL_CHARS,
    MAX_LOGIT_SIDE,
    MAX_OBJECTS,
    MAX_RESULT_TEXT_BYTES,
    TITLES,
    AssistError,
    AssistUnavailable,
    Availability,
    BoxPrompt,
    CancelCheck,
    CaptionOutput,
    ModelIdentity,
    PointPrompt,
    RawObject,
    SegmentOutput,
    reason_text,
)
from src.review.assist.identity import LoadedSource
from src.review.assist.loading import transformers_reason

WORKER_PATH = Path(__file__).with_name("worker.py")
LOGITS_FILE = "logits.f32"
ADAPTER_LABEL = "local child process, CPU"
DEFAULT_TIMEOUT_SECONDS: dict[str, float] = {CAPABILITY_SEGMENT: 300.0, CAPABILITY_CAPTION: 600.0}
_MODULES: dict[str, tuple[str, ...]] = {
    CAPABILITY_SEGMENT: ("torch", "transformers", "torchvision", "safetensors", "PIL"),
    CAPABILITY_CAPTION: ("torch", "transformers", "safetensors", "PIL"),
}
_RESOURCE: dict[str, str] = {
    CAPABILITY_SEGMENT: auxiliary.RESOURCE_BY_MODALITY["sam2"],
    CAPABILITY_CAPTION: auxiliary.RESOURCE_BY_MODALITY["florence2"],
}

RegistryFactory = Callable[[], Any]


class SegmentAdapter(Protocol):
    def segment(
        self,
        source: LoadedSource,
        points: Sequence[PointPrompt],
        boxes: Sequence[BoxPrompt],
        cancel: CancelCheck,
    ) -> SegmentOutput: ...


class CaptionAdapter(Protocol):
    def caption(self, source: LoadedSource, cancel: CancelCheck) -> CaptionOutput: ...


class AvailabilityProbe(Protocol):
    def check(self, capability: str, cancel: CancelCheck) -> Availability:
        """Blocking (it may hash model files); never imports a model library or touches the network."""
        ...


_REASON = re.compile(r"[A-Za-z_]{1,48}(?::[\w.\-/]{1,64})?")


def safe_reasons(reasons: Sequence[object]) -> tuple[str, ...]:
    """Reason codes are short stable tokens; anything else a child process wrote is dropped, not shown."""

    return tuple(item for item in reasons[:8] if isinstance(item, str) and _REASON.fullmatch(item))


def _translate(exc: ReferenceMapError) -> AssistError:
    if isinstance(exc, ProviderUnavailable):
        return AssistUnavailable(exc.message, reasons=safe_reasons(exc.reasons))
    if exc.code == "cancelled":
        return AssistError(CODE_CANCELLED, "Cancelled.")
    if exc.code == "timeout":
        return AssistError(CODE_TIMEOUT, "The model took too long and was stopped.")
    return AssistError(CODE_INFERENCE, exc.message, reasons=safe_reasons(exc.reasons))


def runtime_reasons(capability: str) -> tuple[str, ...]:
    """Cheap reasons the runtime cannot work (nothing imported, nothing hashed); empty when it looks usable."""

    reasons = [
        f"runtime_missing:{name}"
        for name in _MODULES[capability]
        if importlib.util.find_spec(name) is None
    ]
    if "runtime_missing:transformers" not in reasons:
        try:
            reason = transformers_reason(importlib.metadata.version("transformers"))
        except importlib.metadata.PackageNotFoundError:
            reason = "runtime_missing:transformers"
        if reason:
            reasons.append(reason)
    return tuple(reasons)


class ModelAvailability:
    """The real probe: runtime first (free), then the registry's byte verification of the catalog resource."""

    def __init__(self, registry_factory: RegistryFactory) -> None:
        self._registry_factory = registry_factory

    def check(self, capability: str, cancel: CancelCheck) -> Availability:
        reasons = runtime_reasons(capability)
        if not reasons:
            try:
                auxiliary.verify_resource(
                    self._registry_factory(),
                    "sam2" if capability == CAPABILITY_SEGMENT else "florence2",
                    cancelled=cancel,
                )
            except ProviderUnavailable as exc:
                reasons = exc.reasons
            except ReferenceMapError as exc:
                reasons = (exc.code,)
            except Exception:  # noqa: BLE001 - the probe must report, never raise; only a stable code is kept
                reasons = ("probe_failed",)
        return availability_from(capability, reasons)


def availability_from(capability: str, reasons: Sequence[str]) -> Availability:
    reasons = safe_reasons(reasons)
    if not reasons:
        return Availability(capability, True, (), f"{TITLES[capability]} is ready.")
    shown = "; ".join(reason_text(code) for code in list(reasons)[:4])
    return Availability(
        capability,
        False,
        tuple(reasons),
        f"{TITLES[capability]} is unavailable: {shown} Manual mask editing is unaffected. "
        "StableNew never downloads models; see Model Resources for the exact files.",
    )


class _ChildAdapter:
    capability = ""
    modality = ""

    def __init__(
        self,
        registry_factory: RegistryFactory,
        *,
        runner: ProcessRunner = bounded_runner,
        timeouts: Mapping[str, float] | None = None,
        interpreter: str = sys.executable,
        temp_root: str | None = None,
    ) -> None:
        self._registry_factory = registry_factory
        self._runner = runner
        self._timeouts = dict(timeouts) if timeouts is not None else dict(DEFAULT_TIMEOUT_SECONDS)
        self._interpreter = interpreter
        self._temp_root = temp_root

    def _run(
        self, source: LoadedSource, extra: dict[str, Any], cancel: CancelCheck
    ) -> tuple[
        dict[str, Any], Path | None, auxiliary.VerifiedResource, tempfile.TemporaryDirectory[str]
    ]:
        """Verify, stage and run. The caller must clean up the returned directory."""

        reasons = runtime_reasons(self.capability)
        if reasons:
            raise AssistUnavailable(
                f"{TITLES[self.capability]} needs a runtime that is not ready.", reasons=reasons
            )
        registry = self._registry_factory()
        job: tempfile.TemporaryDirectory[str] | None = None
        try:
            verified = auxiliary.verify_resource(registry, self.modality, cancelled=cancel)
            job = tempfile.TemporaryDirectory(prefix="stablenew-assist-", dir=self._temp_root)
            directory = Path(job.name)
            staged = auxiliary.stage_resource(
                verified, registry.webui_root, directory / "models", cancelled=cancel
            )
            context = Context(
                registry=registry,
                cancel=cancel,
                runner=self._runner,
                timeouts=self._timeouts,
                interpreter=self._interpreter,
                temp_root=self._temp_root,
            )
            document = run_worker(
                directory,
                self.capability,
                self.modality,
                {
                    "staged_dir": str(directory / "models"),
                    "staged": {k: str(v) for k, v in staged.items()},
                    **extra,
                },
                source.rgb,
                context,
                worker_path=WORKER_PATH,
            )
        except ReferenceMapError as exc:
            if job is not None:
                job.cleanup()
            raise _translate(exc) from exc
        except BaseException:
            if job is not None:
                job.cleanup()
            raise
        return document, directory, verified, job

    def _identity(
        self, verified: auxiliary.VerifiedResource, document: Mapping[str, Any]
    ) -> ModelIdentity:
        raw = document.get("runtime")
        runtime = (
            {str(k)[:32]: str(v)[:32] for k, v in list(raw.items())[:8]}
            if isinstance(raw, dict)
            else {}
        )
        return ModelIdentity(
            capability=self.capability,
            resource_id=verified.resource_id,
            adapter=ADAPTER_LABEL,
            files=verified.files,
            runtime=runtime,
            warnings=(*verified.warnings, *unenforced_warnings(document)),
        )


class ChildSegmentAdapter(_ChildAdapter):
    capability = CAPABILITY_SEGMENT
    modality = "sam2"

    def segment(
        self,
        source: LoadedSource,
        points: Sequence[PointPrompt],
        boxes: Sequence[BoxPrompt],
        cancel: CancelCheck,
    ) -> SegmentOutput:
        extra: dict[str, Any] = {
            "points": [[p.x, p.y] for p in points],
            "labels": [p.label for p in points],
            "box": [boxes[0].x1, boxes[0].y1, boxes[0].x2, boxes[0].y2] if boxes else None,
        }
        document, directory, verified, job = self._run(source, extra, cancel)
        try:
            shape = document.get("shape")
            if not (
                isinstance(shape, list)
                and len(shape) == 2
                and all(isinstance(n, int) and 0 < n <= MAX_LOGIT_SIDE for n in shape)
            ):
                raise AssistError(CODE_OUTPUT, "The mask model returned an invalid shape.")
            assert directory is not None
            path = directory / LOGITS_FILE
            expected = shape[0] * shape[1] * 4
            with path.open("rb") as stream:
                data = stream.read(expected + 1)
            if len(data) != expected:
                raise AssistError(CODE_OUTPUT, "The mask model returned truncated data.")
            logits = np.frombuffer(data, dtype="<f4").reshape(shape[0], shape[1]).copy()
            score = document.get("score")
            return SegmentOutput(
                logits,
                float(score) if isinstance(score, (int, float)) and np.isfinite(score) else None,
                self._identity(verified, document),
            )
        finally:
            job.cleanup()


class ChildCaptionAdapter(_ChildAdapter):
    capability = CAPABILITY_CAPTION
    modality = "florence2"

    def caption(self, source: LoadedSource, cancel: CancelCheck) -> CaptionOutput:
        document, _, verified, job = self._run(source, {}, cancel)
        try:
            text = document.get("caption")
            if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESULT_TEXT_BYTES:
                raise AssistError(CODE_OUTPUT, "The caption model returned an unusable result.")
            objects: list[RawObject] = []
            raw_objects = document.get("objects")
            for item in (raw_objects if isinstance(raw_objects, list) else [])[:MAX_OBJECTS]:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("label"), str)
                    and isinstance(item.get("box"), list)
                    and len(item["box"]) == 4
                    and all(isinstance(v, (int, float)) for v in item["box"])
                ):
                    x1, y1, x2, y2 = (float(v) for v in item["box"])
                    objects.append(
                        RawObject(item["label"][: MAX_LABEL_CHARS * 4], (x1, y1, x2, y2))
                    )
            return CaptionOutput(text, tuple(objects), self._identity(verified, document))
        finally:
            job.cleanup()


__all__ = [
    "ADAPTER_LABEL",
    "AvailabilityProbe",
    "CaptionAdapter",
    "ChildCaptionAdapter",
    "ChildSegmentAdapter",
    "ModelAvailability",
    "SegmentAdapter",
    "availability_from",
    "runtime_reasons",
]
