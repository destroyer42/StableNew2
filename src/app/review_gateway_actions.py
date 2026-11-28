"""Phone actions from the review gateway (RG-140 slices 1 and 2): prepare a summary, then admit what it showed.

Slice 1: fix face, fix hands, fix both, more like this. Slice 2: run through another model, change the aspect ratio,
a small prompt tweak and Make Video; "more like this" also re-runs a whole multi-stage recipe with new seeds. A picker
action (another model, aspect ratio) first answers with the PC's options (``receipt.choices``) and is prepared again
with one of them. The clip actions (re-run, continue) stay reserved for V1's shared functions (N8).

An ``action_request`` outbox record is untrusted input. ``RecordApplier`` has already checked its closed lists, the
device and its ``queue`` scope, and resolved the target by library id through this PC's publish ledger with the file
re-hashed (S3, invariant 3). This module then:

* **prepare** compiles exactly what the action would queue with the existing compilers (the Review re-work compile
  for the ADetailer fixes, the History variation compiler for "more like this"), admits nothing, and answers with an
  ``action_summary``: PC-written text, the job count, where the jobs go in the queue and every N1 warning, all
  scrubbed of paths (S7, S12);
* **queue** (RG-160), for a request made while this PC was away, compiles and admits in one step: the tap that made
  it accepted the warnings, which the receipt lists. What would pass by itself leaves it unanswered; only a certain
  failure refuses it, and the record id is its receipt id, so it can never be admitted twice;
* **confirm** compiles again and admits only when the fresh summary has the revision the phone showed. Admission is
  one call to ``admit_phone_records`` (``JobService.submit_njrs``; invariant 6) with deterministic job ids, the
  shown warnings frozen as accepted on the phone, fixes at the queue's existing HIGH priority (D8 first step) and
  "more like this" at NORMAL.

There is no quota on phone work (owner decision 2026-11-26, RG-140 Q3): phone and desktop are the same owner. What
stays is protection against duplicates, not against volume: one admission per prepare and deterministic job ids (S8),
and the input bound of 1 to 8 seeds for "more like this". Compiler failures become closed ``detail`` codes, never
their text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any, Protocol

from src.app.review_gateway_protocol import (
    ACTION_UNAVAILABLE,
    ADMISSION_REFUSED,
    CHOICE_ACTIONS,
    CLIP_ACTIONS,
    DETAILS,
    IN_PROGRESS,
    INVALID_RECORD,
    MAX_SEEDS,
    PHONE_ACTIONS,
    PREPARE_REQUIRED,
    SUMMARY_CHANGED,
    ActionChoices,
    ActionInput,
    ActionSummary,
    OutboxRecord,
    SummaryWarning,
    parse_timestamp,
    utc_now,
    utc_text,
)
from src.app.review_gateway_store import SyncLedger
from src.app.site_media_files import SiteOutputError
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.policy_warnings import PolicyWarning, pending_warnings

log = logging.getLogger(__name__)

DEFAULT_SEEDS = 4
PREPARE_TTL = timedelta(minutes=30)
#: A backend list found missing is not asked for again before this, however many requests wait for it.
READY_RECHECK = timedelta(seconds=3)
#: A deferred request meeting one of these is left unanswered and tried again: it passes by itself.
_PASSING = frozenset({"app_busy", "app_shutting_down"})
_SEED_LIMIT = 2**31

_TITLES = {
    "fix_face": "Fix face",
    "fix_hands": "Fix hands",
    "fix_both": "Fix face and hands",
    "more_like_this": "More like this",
    "another_model": "Run through another model",
    "aspect_ratio": "Change the aspect ratio",
    "prompt_tweak": "Tweak the prompt",
    "make_video": "Make a video",
    "continue_clip": "Continue the clip",
}
_PASSES = {"fix_face": (True, False), "fix_hands": (False, True), "fix_both": (True, True)}
#: PHONE-FAST: actions that make one replacement of the image, so the phone compares the two and keeps one. The
#: gateway holds the same list.
REWORK_ACTIONS = frozenset(_PASSES) | {"another_model", "aspect_ratio"}
#: Compiler and admission refusals that keep their own name on the phone; anything else is ``compile_failed``.
_DETAIL_ALIASES = {
    "followup_provenance_unverified": "provenance_unverified",
    "media_changed": "source_changed",
    "preview_changed": "source_changed",
    "preview_unavailable": "app_busy",
}


@dataclass(frozen=True)
class CompiledAction:
    """What an action would queue, compiled by the existing compilers, plus what the phone is shown about it."""

    records: tuple[NormalizedJobRecord, ...]
    lines: tuple[str, ...]
    warnings: tuple[PolicyWarning, ...]
    identity: tuple[str, ...]
    reprocess: bool
    kind: str
    require_current: Callable[[], None] = lambda: None
    #: Slice 2: for a ``CHOICE_ACTIONS`` action, the options with the one compiled selected, so the phone can change it.
    choices: ActionChoices | None = None
    #: RG-160: made while the PC was away, so admitted without a summary first.
    deferred: bool = False
    #: V1-6: a Storyboard take, built only when admitted (``records`` is then empty): it is given the admission
    #: of its records and returns the admitted job ids.
    build: Callable[[Callable[[list[Any]], Sequence[str]]], list[str]] | None = None


class ActionRefused(Exception):
    """An action this PC cannot prepare or admit now; ``detail`` is one of the schema's closed codes."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail if detail in DETAILS else "compile_failed"


class ActionCompiler(Protocol):
    def compile(
        self,
        action: str,
        path: Path,
        digest: str,
        seeds: tuple[int, ...],
        options: ActionInput | None = None,
    ) -> CompiledAction: ...

    def choices(self, action: str, path: Path, digest: str) -> ActionChoices: ...

    def ready(self, action: str) -> bool: ...


#: ``(owner, receipt id, compiled action, warnings shown, runs next) -> admitted job ids``.
Admit = Callable[[str, str, CompiledAction, tuple[PolicyWarning, ...], bool], list[str]]
#: ``(owner, receipt id) -> the job ids already admitted under it``.
Admitted = Callable[[str, str], Sequence[str]]


def admission_claim(compiled: CompiledAction) -> dict[str, str]:
    """What each admitted job records about how it was asked for."""

    return {"channel": "review_gateway", **({"deferred": "true"} if compiled.deferred else {})}


def shown_warnings(compiled: CompiledAction) -> tuple[PolicyWarning, ...]:
    """Every N1 warning the summary shows: the compiler's and those attached to the jobs (one per code and subject)."""

    shown = {item.key: item for item in compiled.warnings}
    for job in compiled.records:
        for item in pending_warnings(job):
            shown.setdefault(item.key, item)
    return tuple(shown.values())


@dataclass(frozen=True)
class ActionOutcome:
    outcome: str
    reason: str = ""
    receipt: Mapping[str, Any] = field(default_factory=dict)


def _refused(reason: str, **receipt: Any) -> ActionOutcome:
    return ActionOutcome("refused", reason, receipt)


def detail_of(error: BaseException) -> str:
    code = str(error)
    code = _DETAIL_ALIASES.get(code, code)
    return code if code in DETAILS else "compile_failed"


def _warning(item: PolicyWarning) -> SummaryWarning:
    return SummaryWarning(
        item.code,
        PureWindowsPath(item.subject).name or item.subject,
        item.title,
        item.why,
        item.fix,
    )


def model_name(record: NormalizedJobRecord) -> str:
    return PureWindowsPath(str(record.base_model or "")).name or "the recorded checkpoint"


class GatewayActions:
    def __init__(
        self,
        ledger: SyncLedger,
        compiler: ActionCompiler,
        admit: Admit,
        *,
        owner_of: Callable[[str], str],
        clock: Callable[[], datetime] = utc_now,
        seeds: Callable[[], int] = lambda: secrets.randbelow(_SEED_LIMIT),
        admitted: Admitted = lambda _owner, _receipt: (),
    ) -> None:
        self._ledger = ledger
        self._compiler = compiler
        self._admit = admit
        self._owner_of = owner_of
        self._clock = clock
        self._seeds = seeds
        self.admitted = admitted
        self._not_ready: dict[str, datetime] = {}

    def admitted_before(self, record: OutboxRecord) -> ActionOutcome | None:
        """The receipt of a deferred request already admitted (a restart before it was answered), else ``None``."""

        request = record.action_request
        assert request is not None
        receipt_id = record.record_id.replace("-", "")
        job_ids = list(self.admitted(self._owner_of(record.device_id), receipt_id))
        if not job_ids:
            return None
        if request.action in REWORK_ACTIONS:
            target = record.target
            file_sha = self._ledger.file_digest(target.library_id, target.sha256)
            self._ledger.remember_rework(job_ids, target.library_id, file_sha)
        return ActionOutcome("applied", receipt={"job_ids": job_ids})

    def ready(self, action: str) -> bool:
        """Whether this PC can compile ``action`` now. ``False`` only for what passes by itself."""

        now = self._clock()
        found = self._not_ready.get(action)
        if found is not None and now - found < READY_RECHECK:
            return False
        try:
            ready = bool(self._compiler.ready(action))
        except Exception as error:  # noqa: BLE001 - a busy or closing app is asked again later
            log.debug("A waiting phone action is not ready (%s)", type(error).__name__)
            ready = False
        if ready:
            self._not_ready.pop(action, None)
        else:
            self._not_ready[action] = now
        return ready

    def handle(self, record: OutboxRecord, path: Path) -> ActionOutcome:
        request = record.action_request
        assert request is not None
        if request.action not in PHONE_ACTIONS:
            return _refused(INVALID_RECORD)  # reserved for a later slice (N8's clip actions)
        now = self._clock()
        if request.step == "prepare":
            return self._prepare(record, path, now)
        if request.step == "queue":
            return self._queue(record, path, now)
        return self._confirm(record, path, now)

    # -- steps -----------------------------------------------------------------------------------------------------

    def _seed_count(self, action: str, requested: int | None) -> int:
        if action == "more_like_this":
            return requested or DEFAULT_SEEDS
        return 1 if action in ("make_video", "continue_clip") else 0  # one clip, a fresh seed each step

    def _guarded(self, compile_step: Callable[[], Any]) -> Any:
        """Run a compiler call; every failure becomes a closed ``ActionRefused`` code, never its text."""

        try:
            return compile_step()
        except ActionRefused:
            raise
        except (SiteOutputError, ValueError, OSError) as error:
            raise ActionRefused(detail_of(error)) from error
        except Exception as error:  # noqa: BLE001 - one bad record must never stall the outbox behind it
            log.error("A phone action could not be compiled (%s)", type(error).__name__)
            raise ActionRefused("compile_failed") from error

    def _compile(
        self,
        action: str,
        path: Path,
        digest: str,
        count: int,
        options: ActionInput,
        now: datetime,
    ) -> tuple[CompiledAction, ActionSummary]:
        seeds = tuple(self._seeds() for _ in range(count))
        compiled: CompiledAction = self._guarded(
            lambda: self._compiler.compile(action, path, digest, seeds, options)
        )
        # The compilers make one job per fix and one per seed; anything else is a compiler fault, not a request.
        if compiled.build is None and len(compiled.records) != max(count, 1):
            raise ActionRefused("compile_failed")
        return compiled, self._summary(action, compiled, now)

    def _prepare(self, record: OutboxRecord, path: Path, now: datetime) -> ActionOutcome:
        request = record.action_request
        assert request is not None
        count = self._seed_count(request.action, request.count)
        if count > MAX_SEEDS:  # already refused by the codec; an input bound, not a quota
            return _refused(INVALID_RECORD)
        options = ActionInput(request.choice, request.text.strip())
        if request.action == "prompt_tweak" and not options.text:
            return _refused(ACTION_UNAVAILABLE, detail="prompt_required")
        if request.action in CHOICE_ACTIONS and not options.choice:
            # Slice 2: first the PC's options; the phone prepares again with one of them. Nothing to confirm yet.
            try:
                listed: ActionChoices = self._guarded(
                    lambda: self._compiler.choices(request.action, path, record.target.sha256)
                )
                return ActionOutcome("applied", receipt={"choices": listed.payload()})
            except ActionRefused as refusal:
                return _refused(ACTION_UNAVAILABLE, detail=refusal.detail)
        try:
            compiled, summary = self._compile(
                request.action, path, record.target.sha256, count, options, now
            )
        except ActionRefused as refusal:
            return _refused(ACTION_UNAVAILABLE, detail=refusal.detail)
        self._remember(record, request.action, count, options, summary, now)
        receipt: dict[str, Any] = {"action_summary": summary.payload()}
        if compiled.choices is not None:
            receipt["choices"] = replace(compiled.choices, selected=options.choice).payload()
        return ActionOutcome("applied", receipt=receipt)

    def _queue(self, record: OutboxRecord, path: Path, now: datetime) -> ActionOutcome:
        """RG-160: compile against what is true now and admit at once."""

        request = record.action_request
        assert request is not None
        count = self._seed_count(request.action, request.count)
        if count > MAX_SEEDS:
            return _refused(INVALID_RECORD)
        options = ActionInput(request.choice, request.text.strip())
        if request.action == "prompt_tweak" and not options.text:
            return _refused(ACTION_UNAVAILABLE, detail="prompt_required")
        try:
            compiled, summary = self._compile(
                request.action, path, record.target.sha256, count, options, now
            )
        except ActionRefused as refusal:
            if refusal.detail in _PASSING:
                return ActionOutcome(IN_PROGRESS)
            return _refused(ACTION_UNAVAILABLE, detail=refusal.detail)
        outcome = self._admit_compiled(
            record, record.record_id.replace("-", ""), replace(compiled, deferred=True), summary
        )
        if outcome.reason == ADMISSION_REFUSED and outcome.receipt.get("detail") in _PASSING:
            return ActionOutcome(IN_PROGRESS)
        return outcome

    def _confirm(self, record: OutboxRecord, path: Path, now: datetime) -> ActionOutcome:
        request = record.action_request
        assert request is not None
        prepared = self._ledger.prepared(request.prepared_record)
        if (
            prepared is None
            or prepared["device_id"] != record.device_id
            or (prepared["library_id"], prepared["sha256"])
            != (record.target.library_id, record.target.sha256)
            or prepared["action"] != request.action
            or parse_timestamp(prepared["at"]) + PREPARE_TTL < now
        ):
            return _refused(PREPARE_REQUIRED)
        if prepared["admitted_by"] is not None:
            # S8: one admission per prepare. A second confirm answers with the first receipt.
            return ActionOutcome("duplicate", receipt=json.loads(prepared["receipt"] or "{}"))
        if prepared["revision"] != request.summary_revision:
            return _refused(SUMMARY_CHANGED)
        count = self._seed_count(request.action, int(prepared["seeds"] or 0) or None)
        options = self._ledger.prepare_options(prepared)
        try:
            compiled, summary = self._compile(
                request.action, path, record.target.sha256, count, options, now
            )
        except ActionRefused as refusal:
            return _refused(ACTION_UNAVAILABLE, detail=refusal.detail)
        if summary.revision != prepared["revision"]:
            # The phone shows this one instead; confirming this record admits it (it acts as a prepare).
            self._remember(record, request.action, count, options, summary, now)
            return _refused(SUMMARY_CHANGED, action_summary=summary.payload())
        outcome = self._admit_compiled(
            record, str(prepared["record_id"]).replace("-", ""), compiled, summary
        )
        if outcome.outcome == "applied":
            self._ledger.mark_prepare_admitted(
                str(prepared["record_id"]), record.record_id, outcome.receipt
            )
        return outcome

    def _admit_compiled(
        self,
        record: OutboxRecord,
        receipt_id: str,
        compiled: CompiledAction,
        summary: ActionSummary,
    ) -> ActionOutcome:
        """Admit what was compiled. Every admission path goes through here, so each rework is remembered."""

        request = record.action_request
        assert request is not None
        try:
            compiled.require_current()
            job_ids = self._admit(
                self._owner_of(record.device_id),
                receipt_id,
                compiled,
                shown_warnings(compiled),
                request.action in _PASSES,
            )
        except ActionRefused as refusal:
            return _refused(ADMISSION_REFUSED, detail=refusal.detail)
        except (SiteOutputError, ValueError, OSError) as error:
            log.info("A phone action was not admitted (%s)", detail_of(error))
            return _refused(ADMISSION_REFUSED, detail=detail_of(error))
        except Exception as error:  # noqa: BLE001 - answered, never retried into a second admission
            log.error("A phone action was not admitted (%s)", type(error).__name__)
            return _refused(ADMISSION_REFUSED, detail="compile_failed")
        if request.action in REWORK_ACTIONS:
            self._ledger.remember_rework(job_ids, record.target.library_id, record.target.sha256)
        receipt = {"job_ids": job_ids, "action_summary": summary.payload()}
        return ActionOutcome("applied", receipt=receipt)

    # -- summary ---------------------------------------------------------------------------------------------------

    def _remember(
        self,
        record: OutboxRecord,
        action: str,
        count: int,
        options: ActionInput,
        summary: ActionSummary,
        now: datetime,
    ) -> None:
        self._ledger.remember_prepare(
            record.record_id,
            record.device_id,
            record.target.library_id,
            record.target.sha256,
            action,
            count if action == "more_like_this" else None,
            summary.revision,
            utc_text(now),
            options={"choice": options.choice, "text": options.text}
            if options != ActionInput()
            else None,
        )

    def _summary(self, action: str, compiled: CompiledAction, now: datetime) -> ActionSummary:
        warnings = tuple(_warning(item) for item in shown_warnings(compiled))
        position = "next" if action in _PASSES else "last"
        lines = (
            *compiled.lines,
            "Runs next, after the current job."
            if position == "next"
            else "Joins the end of the queue.",
        )
        body = {
            "action": action,
            "title": _TITLES[action],
            "lines": list(lines),
            "job_count": 1 if compiled.build is not None else len(compiled.records),
            "queue_position": position,
            "warnings": [item.payload() for item in warnings],
            "identity": list(compiled.identity),
        }
        revision = hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
        return ActionSummary(
            action=action,
            revision=revision,
            title=_TITLES[action],
            lines=tuple(lines),
            job_count=body["job_count"],
            queue_position=position,
            warnings=warnings,
            expires_at=now + PREPARE_TTL,
        )


# -- the running application ------------------------------------------------------------------------------------------

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_VIDEO_SUFFIXES = frozenset({".mp4", ".webm"})
_HASH_LIMIT = 256 * 1024 * 1024


#: ``aspect_ratio`` choices: id, label, width and height of the ratio. Outpainting only adds space around the image.
ASPECT_RATIOS = (
    ("1x1", "Square 1:1", 1, 1),
    ("4x5", "Portrait 4:5", 4, 5),
    ("2x3", "Portrait 2:3", 2, 3),
    ("9x16", "Tall 9:16", 9, 16),
    ("5x4", "Landscape 5:4", 5, 4),
    ("3x2", "Landscape 3:2", 3, 2),
    ("16x9", "Wide 16:9", 16, 9),
)


def model_choice_id(name: str) -> str:
    """A checkpoint's choice id: stable for the name, and never the name or a path itself."""

    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def _same_model(left: str, right: str) -> bool:
    def key(value: str) -> str:
        return PureWindowsPath(value.split(" [", 1)[0].strip()).name.casefold()

    return bool(left) and key(left) == key(right)


GatewayVideo = Callable[[Path, Path, str, str, int], tuple[Any, Any]]


def _default_video(root: Path, path: Path, digest: str, prompt: str, seed: int) -> tuple[Any, Any]:
    from src.app.site_phone_video import gateway_make_video

    return gateway_make_video(root, path, digest, prompt, seed)


class AppActionCompiler:
    """Phone action compiles on the running application, through the existing Preview, follow-up and video services.

    Slice 1: the ADetailer fixes and "more like this". Slice 2: another model and a prompt tweak (the Review img2img
    re-work), an aspect ratio (Review's canvas extension) and Make Video (the desktop's Make Video hand-off), and
    "more like this" of a whole multi-stage recipe (a reseeded Replay).
    """

    def __init__(
        self,
        host: Any,
        repository: Any,
        output_root: Path,
        *,
        video: GatewayVideo = _default_video,
        storyboards: Callable[[], Any] | None = None,
    ) -> None:
        self._storyboards = storyboards
        self._host = host
        self._repository = repository
        self._root = output_root
        self._video = video

    def ready(self, action: str) -> bool:
        """Whether the backend list ``action`` is compiled from is loaded (RG-160); the other actions need none."""

        if action in _PASSES:
            return bool(self._host.gateway_detectors())
        if action == "another_model":
            return bool(self._host.gateway_models())
        return True

    def compile(
        self,
        action: str,
        path: Path,
        digest: str,
        seeds: tuple[int, ...],
        options: ActionInput | None = None,
    ) -> CompiledAction:
        options = options or ActionInput()
        if action in CLIP_ACTIONS:
            return self._continue_clip(path, digest, seeds, options.text)
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            raise ActionRefused("not_an_image")
        if action in _PASSES:
            return self._fix(action, path, digest)
        if action == "more_like_this":
            return self._more(path, digest, seeds)
        if action == "another_model":
            return self._another_model(path, digest, options.choice)
        if action == "aspect_ratio":
            return self._aspect_ratio(path, digest, options.choice)
        if action == "prompt_tweak":
            return self._prompt_tweak(path, digest, options.text)
        if action == "make_video":
            return self._make_video(path, digest, seeds, options.text)
        raise ActionRefused("compile_failed")

    def choices(self, action: str, path: Path, digest: str) -> ActionChoices:
        """What the phone may pick for ``another_model`` (this PC's checkpoints) or ``aspect_ratio``."""

        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            raise ActionRefused("not_an_image")
        if action == "another_model":
            return self._models(path)[0]
        if action == "aspect_ratio":
            from PIL import Image, ImageOps

            from src.pipeline.outpaint_canvas import has_aspect

            with Image.open(path) as image:
                size = ImageOps.exif_transpose(image).size
            return ActionChoices(
                action,
                tuple(
                    (key, label, has_aspect(size, (width, height)))
                    for key, label, width, height in ASPECT_RATIOS
                ),
            )
        raise ActionRefused("compile_failed")

    def _fix(self, action: str, path: Path, digest: str) -> CompiledAction:
        face, hands = _PASSES[action]
        draft = self._host.compile_gateway_fix(path, digest, face=face, hands=hands)
        [job] = draft.records
        block = job.config.get("adetailer")
        settings = block if isinstance(block, Mapping) else {}
        detectors = [
            PureWindowsPath(str(settings.get(key) or "")).name
            for key, enabled in (("adetailer_model", face), ("adetailer_hands_model", hands))
            if enabled
        ]
        passes = {
            "fix_face": "ADetailer face pass",
            "fix_hands": "ADetailer hand pass",
            "fix_both": "ADetailer face pass, then the hand pass",
        }[action]
        lines = (
            f"{passes} on this exact image ({', '.join(name for name in detectors if name) or 'default detector'}).",
            "The original stays as it is; the result is a new image in Reprocess.",
            f"Checkpoint {model_name(job)}.",
        )
        identity = (
            action,
            str(job.base_model or ""),
            ",".join(job.stage_chain_labels),
            *detectors,
            digest,
        )
        return CompiledAction(
            tuple(draft.records),
            lines,
            (),
            identity,
            reprocess=True,
            kind="rework",
            require_current=draft.require_current,
        )

    def _more(self, path: Path, digest: str, seeds: tuple[int, ...]) -> CompiledAction:
        """New seeds for this image's recipe.

        A single-stage txt2img recipe goes through the History variation compiler, as in slice 1. Anything else whose
        whole recipe can be re-run (a multi-stage chain, an N5 batch member) is a Replay with a new seed per job
        (``reseed_refusals``): every frozen value is kept, the stages after txt2img included.
        """

        from src.app.site_media_files import open_scoped
        from src.app.site_phone_followup import verified_history_source, verified_recipe_source
        from src.image_backends.model_policy_warnings import shown_model_warnings
        from src.pipeline.history_variation_compiler import (
            HistoryVariationDraft,
            HistoryVariationRefused,
            compile_history_variation,
        )
        from src.pipeline.replay_njr_compiler import (
            ReplayIntent,
            compile_replay_intent,
            reseed_refusals,
        )

        if not seeds:
            raise ActionRefused("compile_failed")

        def source() -> tuple[NormalizedJobRecord, str, bool]:
            with open_scoped(self._root, path) as stream:
                raw = stream.read(_HASH_LIMIT + 1)
            if len(raw) > _HASH_LIMIT or hashlib.sha256(raw).hexdigest() != digest:
                raise ActionRefused("source_changed")
            try:
                return (*verified_history_source(self._repository, path, raw), True)
            except SiteOutputError:
                return (*verified_recipe_source(self._repository, path, raw), False)

        record, snapshot, variable = source()
        artifact = f"sha256:{digest}"
        try:
            if variable:
                draft = HistoryVariationDraft.from_source(record, parent_artifact_id=artifact)
                jobs = tuple(
                    compile_history_variation(draft.with_edits(seed=seed)) for seed in seeds
                )
            elif reseed_refusals(record):
                raise ActionRefused("recipe_not_variable")
            else:
                jobs = tuple(
                    compile_replay_intent(
                        ReplayIntent(record, parent_artifact_id=artifact, seed=seed)
                    )
                    for seed in seeds
                )
        except (HistoryVariationRefused, ValueError, RuntimeError) as error:
            raise ActionRefused("recipe_not_variable") from error

        def require_current() -> None:
            if source()[1] != snapshot:
                raise ActionRefused("source_changed")

        count = len(jobs)
        plural = "s" if count != 1 else ""
        chain = " → ".join(record.stage_chain_labels)
        how = (
            ("Same prompt, checkpoint and settings as this image.",)
            if variable
            else (
                f"Re-runs this image's whole recipe ({chain}) with only the seed changed.",
                "Same prompt, checkpoint and settings in every stage.",
            )
        )
        return CompiledAction(
            jobs,
            (
                f"{count} new image{plural}, each with a new seed.",
                *how,
                f"Checkpoint {model_name(record)}.",
            ),
            tuple(shown_model_warnings(record)),
            (
                "more_like_this",
                record.job_id,
                snapshot,
                str(count),
                "variation" if variable else "recipe",
            ),
            reprocess=False,
            kind="followup",
            require_current=require_current,
        )

    # -- slice 2 -------------------------------------------------------------------------------------------------------

    def _rework(
        self,
        action: str,
        draft: Any,
        lines: tuple[str, ...],
        identity: tuple[str, ...],
        choices: ActionChoices | None = None,
    ) -> CompiledAction:
        from src.image_backends.model_policy_warnings import shown_model_warnings

        [job] = draft.records  # one job per re-work
        return CompiledAction(
            tuple(draft.records),
            (
                *lines,
                "The original stays as it is; the result is a new image in Reprocess.",
                f"Checkpoint {model_name(job)}.",
            ),
            tuple(shown_model_warnings(job)),
            (action, str(job.base_model or ""), ",".join(job.stage_chain_labels), *identity),
            reprocess=True,
            kind="rework",
            require_current=draft.require_current,
            choices=choices,
        )

    @staticmethod
    def _denoise(job: NormalizedJobRecord) -> str:
        block = job.config.get("img2img")
        value = block.get("denoising_strength") if isinstance(block, Mapping) else None
        return f" at denoise {value:g}" if isinstance(value, int | float) else ""

    def _models(self, path: Path) -> tuple[ActionChoices, dict[str, str], str]:
        """This PC's checkpoints as choices, by choice id, and the image's own checkpoint."""

        models = self._host.gateway_models()
        if not models:
            raise ActionRefused("model_unavailable")
        current = str(self._host.image_baseline(path).get("model") or "")
        ordered = sorted(models, key=str.casefold)
        listed = ActionChoices(
            "another_model",
            tuple(
                (
                    model_choice_id(name),
                    PureWindowsPath(name).name or name,
                    _same_model(current, name),
                )
                for name in ordered
            ),
        )
        return listed, {model_choice_id(name): name for name in ordered}, current

    def _another_model(self, path: Path, digest: str, choice: str) -> CompiledAction:
        listed, by_id, current = self._models(path)
        name = by_id.get(choice)
        if name is None:
            raise ActionRefused("choice_unavailable")
        if _same_model(current, name):
            raise ActionRefused("no_change")
        draft = self._host.compile_gateway_img2img(path, digest, model=name)
        [job] = draft.records
        return self._rework(
            "another_model",
            draft,
            (f"img2img of this exact image through {model_name(job)}{self._denoise(job)}.",),
            (choice, digest),
            listed,
        )

    def _aspect_ratio(self, path: Path, digest: str, choice: str) -> CompiledAction:
        listed = self.choices("aspect_ratio", path, digest)
        ratio = next((entry for entry in ASPECT_RATIOS if entry[0] == choice), None)
        if ratio is None:
            raise ActionRefused("choice_unavailable")
        key, label, width, height = ratio
        draft = self._host.compile_gateway_outpaint(path, digest, ratio=(width, height))
        [job] = draft.records
        block = job.config.get("img2img")
        stage = block if isinstance(block, Mapping) else {}
        size = (
            f" ({stage['width']} × {stage['height']})"
            if isinstance(stage.get("width"), int) and isinstance(stage.get("height"), int)
            else ""
        )
        return self._rework(
            "aspect_ratio",
            draft,
            (
                f"Extends the canvas to {label}{size}: every original pixel is kept and only the new space is "
                "generated.",
                "The new space follows the image's own prompt.",
            ),
            (key, size, digest),
            listed,
        )

    def _prompt_tweak(self, path: Path, digest: str, text: str) -> CompiledAction:
        words = " ".join(text.split())
        if not words:
            raise ActionRefused("prompt_required")
        draft = self._host.compile_gateway_img2img(path, digest, prompt_add=words)
        [job] = draft.records
        return self._rework(
            "prompt_tweak",
            draft,
            (
                f"Adds to the prompt: “{words}”.",
                f"img2img of this exact image{self._denoise(job)}, same checkpoint.",
            ),
            (words, digest),
        )

    def _continue_clip(
        self, path: Path, digest: str, seeds: tuple[int, ...], text: str
    ) -> CompiledAction:
        """V1-6: continue a published video through the shared facade (``site_phone_continue``)."""

        if path.suffix.lower() not in _VIDEO_SUFFIXES:
            raise ActionRefused("operation_unsupported")
        if len(seeds) != 1:
            raise ActionRefused("compile_failed")
        if self._storyboards is None:
            raise ActionRefused("video_unavailable")
        from src.app.site_phone_continue import compile_continuation

        found = compile_continuation(
            self._storyboards(),
            self._root,
            path,
            digest,
            " ".join(text.split()),
            seeds[0],
            video=self._video,
        )
        lines = (*found.lines, "The clip comes back to the inbox when it is published.")
        if found.build is not None:
            return CompiledAction(
                (),
                lines,
                found.warnings,
                found.identity,
                reprocess=False,
                kind="video",
                build=found.build,
            )
        return CompiledAction(
            tuple(found.video.records),
            lines,
            found.warnings,
            found.identity,
            reprocess=False,
            kind="video",
            require_current=found.video.require_current,
        )

    def _make_video(
        self, path: Path, digest: str, seeds: tuple[int, ...], text: str
    ) -> CompiledAction:
        if len(seeds) != 1:
            raise ActionRefused("compile_failed")
        words = " ".join(text.split())
        prompt = words or " ".join(str(self._host.image_baseline(path).get("prompt") or "").split())
        if not prompt:
            raise ActionRefused("prompt_required")
        from src.video.workflow_frame_count import frame_count_policy

        spec, draft = self._video(self._root, path, digest, prompt, seeds[0])

        frames = frame_count_policy(spec) or {}
        count, fps = frames.get("default"), frames.get("fps")
        length = (
            f", about {count / fps:.1f} s at {fps:g} fps"
            if isinstance(count, int) and isinstance(fps, int | float) and fps
            else ""
        )
        return CompiledAction(
            tuple(draft.records),
            (
                f"{spec.display_name}: a {count}-frame clip from this image{length}.",
                f"Motion prompt: “{words}”." if words else "Motion prompt: the image's own prompt.",
                "Negative prompt: the workflow's default.",
                "The clip comes back to the inbox when it is published.",
            ),
            (),
            ("make_video", *spec.registry_key, str(count), prompt, digest),
            reprocess=False,
            kind="video",
            require_current=draft.require_current,
        )
