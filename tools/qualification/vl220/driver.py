"""The supervised visual evaluation driver (PR-AI-VL-220, owner-approved image invocation contract of 2026-11-14).

One bounded, contained, CPU-only ``llama-mtmd-cli.exe`` child per case, launched only through
:func:`src.utils.managed_process.run_bounded`: this module has no ``subprocess``, thread or socket code of its own, and the
tests prove it (an import scan, and a run with sockets and process creation patched to fail around the fake child).

Everything is fail-closed and happens before every launch, in this order, each refusal a stable code that runs nothing:

1. the contract's ``INVOCATION_APPROVED`` flag (and, in the CLI, the owner's plan digest);
2. the evaluation root is not the AI Assist root and not a Git working tree, and a single-flight lock (an exclusive lock file,
   so a second driver in this or another process is refused rather than queued) is taken;
3. generation is idle (an injected reading; an unreadable one is a refusal, never "idle");
4. the ``b11960-cpu-vision`` build entry is pinned, is hash-identical to the required ``b11960-cpu`` build, carries
   ``llama-mtmd-cli.exe``, is unqualified and is listed by no model; the unpacked runtime re-hashes to its pins; and the
   operator's attestation covers ``(b11960-cpu-vision, llama-mtmd-cli.exe)``;
5. host memory headroom for the model, the projector and a margin;
6. every image is a pinned PNG or JPEG of at most 8 MiB and 4096 x 4096 (header read only), copied to a private work directory;
7. :func:`tools.qualification.vl220.candidates.check_admission`: pinned bytes, matching GGUF headers, the required build and the
   owner's license acknowledgement.

Only then is the closed vocabulary of :mod:`tools.qualification.vl220.visual_argv` built and the child launched with a scrubbed
environment. Output is stdout only and bounded; it is decoded, checked with a strict ``json.loads`` (no duplicate keys, no
``NaN``) and then :func:`tools.qualification.vl220.contract.validate_response`.

Evidence is timing, peak memory, the path-free argv hash, the exit code and a reason code. No image, prompt or answer text is
written anywhere: the prompt and images exist only in a per-case work directory that is removed when the case ends, and the
raw answers stay in memory long enough to be scored. The driver writes nothing under the AI Assist root, records no
attestation, creates no firewall rule and never writes the license acknowledgement.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.ai_assist.activation import runtime_import_problem
from src.ai_assist.argv import build_environment
from src.ai_assist.attestation import attestation_covers
from src.ai_assist.host import (
    GenerationActivity,
    HostMemory,
    checked_activity,
    checked_memory,
    read_host_memory,
)
from src.ai_assist.manifests import (
    ModelRegistry,
    RuntimeBuild,
    RuntimeManifest,
    load_model_registry,
    load_runtime_manifest,
)
from src.ai_assist.observe import ChildObserver
from src.ai_assist.paths import attestation_path, runtime_dir
from src.ai_assist.runtime import CommandFactory, Runner, default_command, strip_end_of_text
from src.utils.managed_process import run_bounded
from tools.qualification.vl220 import contract, diagnostics, plan, scoring, staging
from tools.qualification.vl220.candidates import (
    GEMMA_CANDIDATE_ID,
    REASON_CANCELLED,
    REPO_ROOT,
    RUNTIME_MANIFEST_PATH,
    CancelCheck,
    VisualCandidate,
    check_admission,
    has_link,
)
from tools.qualification.vl220.contract import (
    Asset,
    Case,
    CaseSet,
    LabelSet,
    Measurement,
)
from tools.qualification.vl220.prompts import render_control_prompt, render_visual_prompt
from tools.qualification.vl220.visual_argv import (
    MAX_IMAGE_BYTES,
    VISION_BUILD_ID,
    VISION_TOOL,
    VisualArgvRefused,
    VisualLimits,
    VisualSampling,
    argv_shape_digest,
    build_visual_argv,
    inspect_image,
)

logger = logging.getLogger(__name__)

MODEL_REGISTRY_PATH = REPO_ROOT / "config" / "ai_model_registry.json"
EVIDENCE_SCHEMA = "stablenew.vl220.evidence/1"

_GIB = 1024**3
#: The same margins the production service uses before a launch and while a child runs.
MEMORY_MARGIN_GIB = 4.0
GUARD_AVAILABLE_GIB = 0.25
GUARD_COMMIT_HEADROOM_GIB = 1.0
GUARD_CONSECUTIVE = 2
WATCH_INTERVAL_SECONDS = 1.0

LOCK_NAME = "vl220.lock"
WORK_NAME = "_work"

# --- refusal codes (nothing was launched) -------------------------------------------------------------------------------
REFUSED_NOT_APPROVED = "invocation_not_approved"
REFUSED_PLAN_DIGEST = "plan_digest_mismatch"
REFUSED_ROOT = "evaluation_root_refused"
REFUSED_BUSY = "another_evaluation_active"
REFUSED_ACTIVITY = "activity_unreadable"
REFUSED_GENERATION = "generation_running"
REFUSED_QUARANTINE = "gpu_quarantine"
REFUSED_VISION_BUILD = "vision_build_refused"
REFUSED_RUNTIME = "runtime_not_verified"
REFUSED_ATTESTATION = "egress_not_attested"
REFUSED_MEMORY_UNREADABLE = "memory_unreadable"
REFUSED_MEMORY = "available_ram_below_requirement"
REFUSED_COMMIT = "commit_headroom_below_requirement"
REFUSED_IMAGE = "image_refused"
REFUSED_CANDIDATE = "candidate_not_admitted"
REFUSED_ARGV = "argv_refused"
REFUSED_SCRATCH = "scratch_unavailable"
REFUSED_CANCELLED = "cancelled"
REFUSED_DIAGNOSTICS = "diagnostics_not_enabled"

# --- per-case status ----------------------------------------------------------------------------------------------------
STATUS_VALID = "valid"
STATUS_MODEL_REFUSED = "model_refused"
STATUS_INVALID = "invalid"
STATUS_NOT_RUN = "not_run"
STATUS_TIMEOUT = "timeout"
STATUS_CANCELLED = "cancelled"
STATUS_TOO_LARGE = "output_too_large"
STATUS_CHILD_FAILED = "child_exit_nonzero"
STATUS_LAUNCH_FAILED = "launch_failed"
#: The unscored free-text control of the diagnostic: the child answered (or printed nothing).
STATUS_CONTROL_ANSWERED = "control_answered"
STATUS_CONTROL_EMPTY = "control_empty"

ActivityReader = Callable[[], GenerationActivity]
MemoryReader = Callable[[], HostMemory | None]


@dataclass(frozen=True, slots=True)
class Refusal:
    """Admission said no and nothing ran. ``code`` is stable; ``reasons`` carries sub-codes (admission reasons)."""

    code: str
    reasons: tuple[str, ...] = ()

    def __str__(self) -> str:
        return self.code if not self.reasons else f"{self.code}: {', '.join(self.reasons)}"


@dataclass(frozen=True, slots=True)
class CaseEvidence:
    """Everything kept about one case: timing, memory, the path-free argv hash, the exit code and a reason code."""

    case_id: str
    status: str
    reason: str = ""
    wall_seconds: float = 0.0
    peak_working_set_bytes: int = 0
    peak_private_bytes: int = 0
    exit_code: int | None = None
    argv_shape_sha256: str = ""
    context_tokens: int = 0
    cpu_only: bool = True

    def record(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def launched(self) -> bool:
        return bool(self.argv_shape_sha256) and self.status not in (
            STATUS_NOT_RUN,
            STATUS_LAUNCH_FAILED,
        )


@dataclass(frozen=True, slots=True)
class CaseRun:
    evidence: CaseEvidence
    #: The child's raw answer, in memory only so it can be scored; never written by this module.
    text: str = field(default="", repr=False, compare=False)
    refusal: Refusal | None = None


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    evidence: tuple[CaseEvidence, ...]
    refusal: Refusal | None = None
    #: Aggregate numbers only (``scoring.score_run``); ``None`` when the run was refused or cancelled.
    report: Mapping[str, Any] | None = None
    complete: bool = False


# ----------------------------------------------------------------------------------------------------- pure admission


def vision_build_reasons(
    manifest: RuntimeManifest, registry: ModelRegistry, candidate: VisualCandidate
) -> list[str]:
    """Why ``b11960-cpu-vision`` may not carry the candidate. Empty only when the entry is pinned, is a hash-identical twin of the
    required build, names ``llama-mtmd-cli.exe``, is unqualified and no model can reach it."""

    build = manifest.find(VISION_BUILD_ID)
    twin = manifest.find(candidate.runtime.required_build_id)
    if manifest.problems or registry.problems:
        return ["manifest_or_registry_invalid"]
    if build is None or twin is None:
        return ["vision_build_not_pinned"]
    reasons: list[str] = []
    if (
        build.asset_sha256 != twin.asset_sha256
        or build.asset_bytes != twin.asset_bytes
        or build.asset_name != twin.asset_name
        or build.upstream_tag != twin.upstream_tag
        or dict(build.files) != dict(twin.files)
    ):
        reasons.append("vision_build_differs_from_required_build")
    if (
        build.executable != VISION_TOOL
        or build.executable != candidate.runtime.tool
        or VISION_TOOL not in build.files
    ):
        reasons.append("vision_build_wrong_executable")
    if build.qualified is not False:
        reasons.append("vision_build_qualified")
    if any(VISION_BUILD_ID in entry.compatible_builds for entry in registry.entries):
        reasons.append("vision_build_listed_by_a_model")
    return reasons


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite constant {name}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def load_strict_json(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_no_duplicate_keys)


def strict_json(text: str) -> bool:
    """Whether ``text`` is exactly one JSON document with no duplicate keys and no ``NaN``/``Infinity``."""

    try:
        load_strict_json(text)
    except (ValueError, RecursionError):
        return False
    return True


def check_output(case: Case, stdout: bytes) -> tuple[str, contract.ResponseCheck, str]:
    """``(status, check, text)`` for a successful child's stdout: strip one trailing end-of-text marker, decode, strict
    ``json.loads``, then the contract validator."""

    try:
        text = strip_end_of_text(stdout).decode("utf-8").strip()
    except UnicodeDecodeError:
        return STATUS_INVALID, contract.ResponseCheck("invalid", "not_utf8", {}), ""
    if not strict_json(text):
        return STATUS_INVALID, contract.ResponseCheck("invalid", "not_json", {}), text
    check = contract.validate_response(case, text)
    if check.status == "valid":
        return STATUS_VALID, check, text
    if check.status == "refused":
        return STATUS_MODEL_REFUSED, check, text
    return STATUS_INVALID, check, text


class _Watch:
    """The ``cancel`` callable handed to ``run_bounded``: the caller's token, the memory/process observer, and generation and
    host-memory guards. The first reason that fires is kept and the child's tree is killed by the launcher."""

    def __init__(
        self,
        *,
        token: Callable[[], bool],
        observer: ChildObserver,
        activity: ActivityReader,
        memory: MemoryReader,
        clock: Callable[[], float],
        interval: float,
        working_set_limit_bytes: int | None = None,
    ) -> None:
        self._token, self._observer = token, observer
        self._activity, self._memory = activity, memory
        self._clock, self._interval = clock, interval
        self._last = clock()
        self._working_set_limit_bytes = working_set_limit_bytes
        self._strikes = 0
        self.reason = ""

    def __call__(self) -> bool:
        if self.reason:
            return True
        try:
            if self._token():
                self.reason = "request_cancelled"
                return True
        except Exception:  # noqa: BLE001 - an unreadable token is a stop, never a pass
            self.reason = "cancel_token_error"
            return True
        reason = self._observer.poll()
        if reason is not None:
            self.reason = reason
            return True
        if (
            self._working_set_limit_bytes is not None
            and self._observer.evidence.peak_tree_working_set_gib * _GIB
            > self._working_set_limit_bytes
        ):
            self.reason = "working_set_limit"
            return True
        now = self._clock()
        if now - self._last < self._interval:
            return False
        self._last = now
        try:
            activity = checked_activity(self._activity())
        except Exception:  # noqa: BLE001
            activity = None
        if activity is None:
            self.reason = REFUSED_ACTIVITY
        elif activity.running_jobs > 0:
            self.reason = REFUSED_GENERATION
        elif activity.gpu_quarantined:
            self.reason = REFUSED_QUARANTINE
        if self.reason:
            return True
        try:
            memory = checked_memory(self._memory())
        except Exception:  # noqa: BLE001
            memory = None
        clear = (
            memory is not None
            and memory.available_gib >= GUARD_AVAILABLE_GIB
            and memory.commit_headroom_gib >= GUARD_COMMIT_HEADROOM_GIB
        )
        self._strikes = 0 if clear else self._strikes + 1
        if self._strikes >= GUARD_CONSECUTIVE:
            self.reason = "memory_guard"
            return True
        return False


_MEDIA_SUFFIX = {"image/png": ".png", "image/jpeg": ".jpg"}

#: Free-text controls stop early: a description is a few sentences.
CONTROL_MAX_NEW_TOKENS = 256


@dataclass(frozen=True, slots=True)
class _Job:
    """One request to the runtime: a scored case (a schema, a case to validate against) or an unscored control (neither)."""

    request_id: str
    asset_ids: tuple[str, ...]
    prompt_text: str
    schema: dict[str, Any] | None
    case: Case | None


class VisualDriver:
    """Runs pinned visual cases one at a time. Construct it, then call :meth:`run_case` or :meth:`run_cases`."""

    def __init__(
        self,
        candidate: VisualCandidate,
        *,
        evaluation_root: Path,
        ai_root: Path,
        assets_dir: Path,
        acknowledgement: Mapping[str, Any] | None,
        activity: ActivityReader | None,
        runtime_manifest: RuntimeManifest | None = None,
        registry: ModelRegistry | None = None,
        memory_probe: MemoryReader = read_host_memory,
        clock: Callable[[], float] = time.monotonic,
        environ: Mapping[str, str] | None = None,
        command_factory: CommandFactory = default_command,
        runner: Runner = run_bounded,
        limits: VisualLimits | None = None,
        sampling: VisualSampling | None = None,
        cancel: CancelCheck | None = None,
        watch_interval: float = WATCH_INTERVAL_SECONDS,
        capture: diagnostics.DiagnosticCapture | None = None,
    ) -> None:
        self._candidate = candidate
        self._root = Path(evaluation_root)
        self._ai_root = Path(ai_root)
        self._assets = Path(assets_dir)
        self._ack = acknowledgement
        self._activity = activity
        self._manifest = runtime_manifest
        self._registry = registry
        self._memory = memory_probe
        self._clock = clock
        self._environ = os.environ if environ is None else environ
        self._command_factory = command_factory
        self._runner = runner
        self._limits = limits if limits is not None else VisualLimits()
        self._sampling = sampling if sampling is not None else VisualSampling()
        self._use_jinja = candidate.candidate_id == GEMMA_CANDIDATE_ID
        self._resource_limits = plan.evaluation_limits(candidate)
        self._cancel: CancelCheck = cancel if cancel is not None else (lambda: False)
        self._interval = watch_interval
        #: Only a capture built for a built-in synthetic set can exist (``DiagnosticCapture`` refuses anything else), so
        #: with ``None`` no answer text and no runtime output is kept beyond scoring, exactly as before.
        self._capture = capture

    # -- locations ------------------------------------------------------------------------------------------------------

    @property
    def staged_dir(self) -> Path:
        """Where ``import`` put the pair: ``<root>/<candidate id>/<model sha prefix>``."""

        return staging.installed_pair(self._root, self._candidate)

    # -- admission ------------------------------------------------------------------------------------------------------

    def _acquire(self) -> Path | None:
        path = self._root / LOCK_NAME
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except OSError:  # exists (another evaluation, or a stale lock the operator must remove) or cannot be made
            return None
        return path

    def _activity_refusal(self) -> Refusal | None:
        if self._activity is None:
            return Refusal(REFUSED_ACTIVITY)
        try:
            activity = checked_activity(self._activity())
        except Exception:  # noqa: BLE001 - no answer is never "idle"
            activity = None
        if activity is None:
            return Refusal(REFUSED_ACTIVITY)
        if activity.running_jobs > 0:
            return Refusal(REFUSED_GENERATION)
        if activity.gpu_quarantined:
            return Refusal(REFUSED_QUARANTINE)
        return None

    def _runtime_refusal(
        self,
    ) -> tuple[Refusal | None, RuntimeBuild | None, RuntimeManifest | None]:
        try:
            manifest = (
                self._manifest
                if self._manifest is not None
                else load_runtime_manifest(RUNTIME_MANIFEST_PATH)
            )
            registry = (
                self._registry
                if self._registry is not None
                else load_model_registry(MODEL_REGISTRY_PATH)
            )
            reasons = vision_build_reasons(manifest, registry, self._candidate)
            if reasons:
                return Refusal(REFUSED_VISION_BUILD, tuple(reasons)), None, manifest
            build = manifest.find(VISION_BUILD_ID)
            assert build is not None
            installed = runtime_dir(self._ai_root.absolute(), build.build_id)
            if has_link(installed):
                return Refusal(REFUSED_RUNTIME, ("unsafe_runtime_path",)), None, manifest
            if installed.is_dir() and any(
                child.name not in {*build.files, "LICENSE-LLVM-OpenMP"}
                or has_link(child)
                or not child.is_file()
                for child in installed.iterdir()
            ):
                return Refusal(REFUSED_RUNTIME, ("unexpected_runtime_file",)), None, manifest
            problem = runtime_import_problem(self._ai_root, build, deep=True)
            if problem:
                return Refusal(REFUSED_RUNTIME, (problem,)), None, manifest
            if has_link(attestation_path(self._ai_root.absolute())) or not attestation_covers(
                self._ai_root, build.build_id, build.executable
            ):
                return Refusal(REFUSED_ATTESTATION), None, manifest
            return None, build, manifest
        except Exception:  # noqa: BLE001 - admission is fail-closed
            return Refusal(REFUSED_VISION_BUILD, ("admission_error",)), None, None

    def readiness(self) -> dict[str, Any]:
        """Report static launch prerequisites, without acquiring a slot or launching a child."""
        reasons: list[str] = []
        root_reason = staging.root_refusal(self._root)
        if root_reason:
            reasons.append(root_reason)
        else:
            refusal, _, manifest = self._runtime_refusal()
            if refusal is not None:
                reasons.extend((refusal.code, *refusal.reasons))
            admission = check_admission(
                self._candidate,
                self.staged_dir,
                build_id=self._candidate.runtime.required_build_id,
                runtime_manifest=manifest,
                acknowledgement=self._ack,
            )
            reasons.extend(admission.reasons)
        if not contract.INVOCATION_APPROVED:
            reasons.append(REFUSED_NOT_APPROVED)
        return {
            "candidate_id": self._candidate.candidate_id,
            "build_id": VISION_BUILD_ID,
            "launch_prerequisites_met": not reasons,
            "qualified": False,
            "reasons": reasons,
        }

    def _memory_refusal(self) -> Refusal | None:
        needed = self._candidate.download_bytes / _GIB + MEMORY_MARGIN_GIB
        try:
            memory = checked_memory(self._memory())
        except Exception:  # noqa: BLE001
            memory = None
        if memory is None:
            return Refusal(REFUSED_MEMORY_UNREADABLE)
        if not memory.available_gib >= needed:
            return Refusal(REFUSED_MEMORY)
        if not memory.commit_headroom_gib >= needed:
            return Refusal(REFUSED_COMMIT)
        return None

    def _stage_images(
        self, asset_ids: tuple[str, ...], assets: Mapping[str, Asset], scratch: Path
    ) -> list[Path] | Refusal:
        """Copy each pinned image into the private work directory after proving its pin, then read its header."""

        staged: list[Path] = []
        for position, asset_id in enumerate(asset_ids):
            asset = assets.get(asset_id)
            if asset is None:
                return Refusal(REFUSED_IMAGE, ("unknown_asset",))
            source = self._assets / f"{asset.asset_id}{_MEDIA_SUFFIX[asset.media_type]}"
            try:
                if has_link(source.absolute()):
                    return Refusal(REFUSED_IMAGE, ("unsafe_image_path",))
                if not source.is_file():
                    return Refusal(REFUSED_IMAGE, ("image_missing",))
                if not 0 < source.stat().st_size <= MAX_IMAGE_BYTES:
                    return Refusal(REFUSED_IMAGE, ("image_size_out_of_range",))
                with source.open("rb") as handle:
                    data = handle.read(MAX_IMAGE_BYTES + 1)
            except OSError:
                return Refusal(REFUSED_IMAGE, ("image_unreadable",))
            if len(data) > MAX_IMAGE_BYTES:
                return Refusal(REFUSED_IMAGE, ("image_size_out_of_range",))
            if len(data) != asset.bytes or hashlib.sha256(data).hexdigest() != asset.sha256:
                return Refusal(REFUSED_IMAGE, ("image_does_not_match_its_pin",))
            target = scratch / f"image_{position}{_MEDIA_SUFFIX[asset.media_type]}"
            target.write_bytes(data)
            try:
                media, _, _ = inspect_image(target)
            except VisualArgvRefused as exc:
                return Refusal(REFUSED_IMAGE, (exc.code,))
            if media != asset.media_type:
                return Refusal(REFUSED_IMAGE, ("image_media_type_mismatch",))
            staged.append(target)
        return staged

    # -- one case -------------------------------------------------------------------------------------------------------

    def run_case(self, case_set: CaseSet, case: Case) -> CaseRun:
        """Admit and (only if every gate passes) run one case. Never raises; a refusal runs nothing."""

        job = _Job(
            case.case_id,
            case.asset_ids,
            render_visual_prompt(case),
            contract.build_response_schema(case.kind, case),
            case,
        )
        return self._run_job(case_set, job)

    def run_control(self, case_set: CaseSet, request: diagnostics.ControlRequest) -> CaseRun:
        """The diagnostic's unscored free-text control: no schema, answer text kept only in the capture. Needs a capture
        (so only a built-in synthetic set can reach it) and every admission gate a case needs."""

        if self._capture is None:
            return _refused(request.request_id, Refusal(REFUSED_DIAGNOSTICS))
        job = _Job(request.request_id, (request.asset_id,), render_control_prompt(), None, None)
        return self._run_job(case_set, job)

    def _run_job(self, case_set: CaseSet, job: _Job) -> CaseRun:
        try:
            return self._run_case(case_set, job)
        except Exception:  # noqa: BLE001 - fail closed: an unexpected problem is a refusal that launched nothing
            logger.warning("Visual case could not be run", exc_info=True)
            return _refused(job.request_id, Refusal(REFUSED_SCRATCH, ("unexpected_error",)))

    def _run_case(self, case_set: CaseSet, job: _Job) -> CaseRun:
        name = job.request_id
        if contract.INVOCATION_APPROVED is not True:
            return _refused(name, Refusal(REFUSED_NOT_APPROVED))
        if self._cancel():
            return _refused(name, Refusal(REFUSED_CANCELLED))
        refused_root = staging.root_refusal(self._root)
        if refused_root or not self._root.is_dir():
            return _refused(
                name, Refusal(REFUSED_ROOT, (refused_root or "evaluation_root_missing",))
            )
        if has_link((self._root / WORK_NAME).absolute()):
            return _refused(name, Refusal(REFUSED_SCRATCH, ("unsafe_work_path",)))
        lock = self._acquire()
        if lock is None:
            return _refused(name, Refusal(REFUSED_BUSY))
        scratch = self._root / WORK_NAME / uuid.uuid4().hex
        try:
            try:
                scratch.mkdir(parents=True, exist_ok=False)
            except OSError:
                return _refused(name, Refusal(REFUSED_SCRATCH))
            try:
                return self._admitted_run(case_set, job, scratch)
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
        finally:
            lock.unlink(missing_ok=True)

    def _admitted_run(self, case_set: CaseSet, job: _Job, scratch: Path) -> CaseRun:
        name = job.request_id
        refusal = self._activity_refusal()
        if refusal is not None:
            return _refused(name, refusal)
        refusal, build, manifest = self._runtime_refusal()
        if refusal is not None or build is None or manifest is None:
            return _refused(name, refusal or Refusal(REFUSED_VISION_BUILD))
        refusal = self._memory_refusal()
        if refusal is not None:
            return _refused(name, refusal)
        staged = self._stage_images(
            job.asset_ids, {asset.asset_id: asset for asset in case_set.assets}, scratch
        )
        if isinstance(staged, Refusal):
            return _refused(name, staged)
        admission = check_admission(
            self._candidate,
            self.staged_dir,
            build_id=self._candidate.runtime.required_build_id,
            runtime_manifest=manifest,
            acknowledgement=self._ack,
            cancel=self._cancel,
        )
        if not admission.ok:
            code = (
                REFUSED_CANCELLED if admission.reasons == (REASON_CANCELLED,) else REFUSED_CANDIDATE
            )
            return _refused(name, Refusal(code, admission.reasons))
        prompt_file, schema_file = scratch / "prompt.txt", scratch / "schema.json"
        prompt_file.write_text(job.prompt_text, encoding="utf-8", newline="\n")
        if job.schema is not None:
            schema_file.write_text(json.dumps(job.schema), encoding="utf-8", newline="\n")
        limits = (
            self._limits
            if job.case is not None
            else dataclasses.replace(
                self._limits,
                max_new_tokens=min(self._limits.max_new_tokens, CONTROL_MAX_NEW_TOKENS),
            )
        )
        try:
            argv = build_visual_argv(
                model_path=self.staged_dir / self._candidate.model.filename,
                projector_path=self.staged_dir / self._candidate.projector.filename,
                prompt_file=prompt_file,
                schema_file=schema_file if job.schema is not None else None,
                image_paths=staged,
                evaluation_root=self._root,
                work_dir=scratch,
                limits=limits,
                sampling=self._sampling,
                free_text=job.schema is None,
                use_jinja=self._use_jinja,
            )
        except VisualArgvRefused as exc:
            return _refused(name, Refusal(REFUSED_ARGV, (exc.code,)))
        return self._launch(job, build, argv, scratch, limits)

    def _launch(
        self, job: _Job, build: RuntimeBuild, argv: list[str], scratch: Path, limits: VisualLimits
    ) -> CaseRun:
        shape = argv_shape_digest(argv)
        resource = self._resource_limits
        observer = ChildObserver(
            cap_gib=resource.max_peak_working_set_bytes / _GIB, clock=self._clock
        )
        watch = _Watch(
            token=self._cancel,
            observer=observer,
            activity=self._activity,
            memory=self._memory,
            clock=self._clock,
            interval=self._interval,
            working_set_limit_bytes=resource.max_peak_working_set_bytes
            if self._use_jinja
            else None,
        )
        assert self._activity is not None  # admission refused without a reading
        runtime_root = runtime_dir(self._ai_root, build.build_id)
        executable = runtime_root / build.executable
        started = self._clock()
        container_options = (
            {
                "require_containment": True,
                "memory_limit_mb": resource.max_peak_working_set_bytes / 1024**2,
            }
            if self._use_jinja
            else {}
        )
        outcome = self._runner(
            self._command_factory(executable, argv),
            timeout_seconds=limits.timeout_seconds,
            max_stdout_bytes=limits.max_stdout_bytes,
            cancel=watch,
            cwd=scratch,
            env=build_environment(runtime_root, self._environ, scratch),
            observe=observer.bind,
            **container_options,
        )
        wall = max(0.0, self._clock() - started)
        evidence = {
            "case_id": job.request_id,
            "wall_seconds": round(wall, 3),
            "peak_working_set_bytes": int(observer.evidence.peak_tree_working_set_gib * _GIB),
            "peak_private_bytes": int(observer.evidence.peak_tree_private_gib * _GIB),
            "exit_code": outcome.returncode,
            "argv_shape_sha256": shape,
            "context_tokens": limits.context_tokens,
            "cpu_only": True,
        }
        run = self._judge(job, outcome, evidence, watch, observer)
        if self._capture is not None:
            self._capture.record(
                request_id=job.request_id,
                request_kind=diagnostics.REQUEST_CASE
                if job.case is not None
                else diagnostics.REQUEST_CONTROL,
                kind=job.case.kind if job.case is not None else "free_text",
                status=run.evidence.status,
                reason=run.evidence.reason,
                exit_code=outcome.returncode,
                stdout=outcome.stdout or b"",
                stderr=outcome.stderr or b"",
            )
        return run

    def _judge(
        self,
        job: _Job,
        outcome: Any,
        evidence: dict[str, Any],
        watch: _Watch,
        observer: ChildObserver,
    ) -> CaseRun:
        if outcome.launch_error:
            reason = (
                "containment_unavailable"
                if outcome.launch_error.startswith("containment unavailable")
                else "launch_failed"
            )
            return CaseRun(CaseEvidence(status=STATUS_LAUNCH_FAILED, reason=reason, **evidence))
        if self._use_jinja and (not outcome.contained or outcome.memory_limit_enforced is not True):
            return CaseRun(
                CaseEvidence(
                    status=STATUS_LAUNCH_FAILED,
                    reason="containment_unverified",
                    **evidence,
                )
            )
        if outcome.cancelled:
            return CaseRun(
                CaseEvidence(
                    status=STATUS_CANCELLED, reason=watch.reason or "request_cancelled", **evidence
                )
            )
        if outcome.timed_out:
            return CaseRun(
                CaseEvidence(status=STATUS_TIMEOUT, reason="wall_clock_limit", **evidence)
            )
        if outcome.output_truncated:
            return CaseRun(
                CaseEvidence(status=STATUS_TOO_LARGE, reason="output_too_large", **evidence)
            )
        if outcome.returncode != 0:
            return CaseRun(
                CaseEvidence(status=STATUS_CHILD_FAILED, reason="child_exit_nonzero", **evidence)
            )
        if self._use_jinja and not observer.evidence.child_observed:
            return CaseRun(
                CaseEvidence(
                    status=STATUS_LAUNCH_FAILED,
                    reason="child_not_observed",
                    **evidence,
                )
            )
        if job.case is None:
            text = outcome.stdout.decode("utf-8", errors="replace").strip()
            status = STATUS_CONTROL_ANSWERED if text else STATUS_CONTROL_EMPTY
            # A control is never scored and its text is not kept here: only an attached capture records it.
            return CaseRun(CaseEvidence(status=status, **evidence))
        status, check, text = check_output(job.case, outcome.stdout)
        return CaseRun(CaseEvidence(status=status, reason=check.reason, **evidence), text)

    # -- a whole case set -----------------------------------------------------------------------------------------------

    def run_cases(self, case_set: CaseSet, labels: LabelSet) -> EvaluationRun:
        """Run every case in order. The first admission refusal stops the run (the same gate would refuse every case);
        a case that ran and failed is kept and scored as a wrong answer, never skipped. A cancel stops cleanly."""

        rows: list[CaseEvidence] = []
        responses: dict[str, str] = {}
        measurements: dict[str, Measurement] = {}
        for case in case_set.cases:
            run = self.run_case(case_set, case)
            rows.append(run.evidence)
            if run.refusal is not None:
                return EvaluationRun(tuple(rows), refusal=run.refusal)
            if run.evidence.status == STATUS_CANCELLED:
                return EvaluationRun(
                    tuple(rows), refusal=Refusal(REFUSED_CANCELLED, (run.evidence.reason,))
                )
            responses[case.case_id] = run.text
            if run.evidence.launched:
                measurements[case.case_id] = Measurement(
                    wall_seconds=run.evidence.wall_seconds,
                    peak_working_set_bytes=run.evidence.peak_working_set_bytes,
                    context_tokens=run.evidence.context_tokens,
                    cpu_only=run.evidence.cpu_only,
                )
        report = scoring.score_run(case_set, labels, responses, measurements, self._resource_limits)
        if self._use_jinja:
            report["baselines"] = {
                mode: scoring.score_run(
                    case_set, labels, scoring.baseline_responses(case_set, mode)
                )
                for mode in ("all_yes", "all_no", "seeded_random")
            }
        return EvaluationRun(tuple(rows), report=report, complete=True)

    def run_controls(
        self, case_set: CaseSet, requests: tuple[diagnostics.ControlRequest, ...]
    ) -> EvaluationRun:
        """Run the unscored free-text controls in order (diagnostic mode only). Nothing is scored; the first refusal stops."""

        rows: list[CaseEvidence] = []
        for request in requests:
            run = self.run_control(case_set, request)
            rows.append(run.evidence)
            if run.refusal is not None:
                return EvaluationRun(tuple(rows), refusal=run.refusal)
            if run.evidence.status == STATUS_CANCELLED:
                return EvaluationRun(
                    tuple(rows), refusal=Refusal(REFUSED_CANCELLED, (run.evidence.reason,))
                )
        return EvaluationRun(tuple(rows), complete=True)


def _refused(request_id: str, refusal: Refusal) -> CaseRun:
    return CaseRun(
        CaseEvidence(case_id=request_id, status=STATUS_NOT_RUN, reason=refusal.code),
        refusal=refusal,
    )


def readiness(
    candidate: VisualCandidate,
    evaluation_root: Path,
    ai_root: Path,
    acknowledgement: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return VisualDriver(
        candidate,
        evaluation_root=evaluation_root,
        ai_root=ai_root,
        assets_dir=evaluation_root,
        acknowledgement=acknowledgement,
        activity=None,
    ).readiness()


def execution_identity(candidate: VisualCandidate, limits: VisualLimits) -> dict[str, Any]:
    manifest = load_runtime_manifest(RUNTIME_MANIFEST_PATH)
    registry = load_model_registry(MODEL_REGISTRY_PATH)
    if vision_build_reasons(manifest, registry, candidate):
        raise ValueError("vision_build_refused")
    build = manifest.find(VISION_BUILD_ID)
    assert build is not None
    identity = {
        "plan_sha256": plan.build_plan(candidate)["plan_sha256"],
        "profile": "vl230.mtmd.b11960/2",
        "build_id": build.build_id,
        "executable": build.executable,
        "executable_sha256": build.files[build.executable],
        "archive_sha256": build.asset_sha256,
        "loadable_files_sha256": contract.digest(dict(build.files)),
        "resources": asdict(plan.evaluation_limits(candidate)),
        "invocation_limits": asdict(limits),
        "jinja": candidate.candidate_id == GEMMA_CANDIDATE_ID,
    }
    return {**identity, "execution_sha256": contract.digest(identity)}


def evidence_document(
    run: EvaluationRun,
    *,
    plan_sha256: str,
    case_set_sha256: str,
    candidate: VisualCandidate,
    controls: EvaluationRun | None = None,
) -> dict[str, Any]:
    """The only thing a run writes: timing, memory, the path-free argv hash, exit codes and reason codes, plus the aggregate
    score numbers. It contains no image, prompt or answer text."""

    return {
        "schema": EVIDENCE_SCHEMA,
        "contract_id": contract.CONTRACT_ID,
        "plan_sha256": plan_sha256,
        "case_set_sha256": case_set_sha256,
        "candidate_id": candidate.candidate_id,
        "build_id": VISION_BUILD_ID,
        "executable": VISION_TOOL,
        "complete": run.complete,
        "refusal": None
        if run.refusal is None
        else {"code": run.refusal.code, "reasons": list(run.refusal.reasons)},
        "cases": [row.record() for row in run.evidence],
        "controls": [] if controls is None else [row.record() for row in controls.evidence],
        "report": None if run.report is None else dict(run.report),
    }


__all__ = [
    "EVIDENCE_SCHEMA",
    "LOCK_NAME",
    "MODEL_REGISTRY_PATH",
    "REFUSED_NOT_APPROVED",
    "REFUSED_PLAN_DIGEST",
    "CaseEvidence",
    "CaseRun",
    "EvaluationRun",
    "Refusal",
    "VisualDriver",
    "check_output",
    "evidence_document",
    "strict_json",
    "vision_build_reasons",
]
