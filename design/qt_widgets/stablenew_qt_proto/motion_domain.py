"""Pure, in-memory mock domain for the Motion & Video workspace (QT-DS-04).

Everything here is a deterministic fixture simulation. Nothing creates video, queues a job, builds an
NJR, writes a Storyboard file or reads media. Readiness summaries, simulated runs, mock movie receipts
and saved drafts are distinct objects with distinct identities; none of them is a production record.

Authority it mirrors (read-only, see ``docs/Subsystems/Video/VIDEO_PIPELINE.md`` sections 1.1, 4.2, 7 and
``STORYBOARDS.md``): approved/experimental/retired workflow governance, 4n+1 native frame policy, 2-12 shot
Storyboards with provided versus carried anchors, per-job experimental consent that no saved draft restores,
stale-save conflicts, explicit acceptance of changed media, and Movie Clips assembly as a separate operation.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from .edit_domain import SOURCES as STILL_SOURCES
from .edit_domain import Availability, Replacement

MOCK_NOTICE = "Simulated · no video generated · no job queued"
MIN_SHOTS, MAX_SHOTS = 2, 12
MAX_VARIANTS = 3
UNDO_LIMIT = 50
SEED_MAX = 2**31 - 1
KIND_QUICK, KIND_STORY, KIND_MOVIE = "quick", "story", "movie"
KINDS = (KIND_QUICK, KIND_STORY, KIND_MOVIE)


class MotionRefused(ValueError):
    """A mock Motion action needs a different or more current input. Never a production refusal."""


class StaleSave(MotionRefused):
    """The saved mock revision moved on since this draft was opened."""


class Status(StrEnum):
    """Prototype display labels. They are not production job states."""

    NOT_REVIEWED = "Not reviewed"
    STALE = "Stale"
    BLOCKED = "Blocked"
    READY = "Ready for mock simulation"
    SIMULATED = "Simulated result available"


class Governance(StrEnum):
    APPROVED = "Approved"
    EXPERIMENTAL = "Experimental"
    RETIRED = "Retired"


class Route(StrEnum):
    SVD = "Native SVD XT"
    COMFY = "Comfy workflow"


# ----------------------------------------------------------------------------------------- media
def media_digest(key: str, revision: int = 0) -> str:
    """Deterministic fixture identity. It is *not* a file hash and has no production meaning."""
    return hashlib.sha256(f"{key}#{revision}".encode()).hexdigest()[:12]


@dataclass(frozen=True)
class MotionSource:
    """An immutable, explicitly identified source image or motion-reference fixture."""

    key: str
    title: str
    motif: int
    size: tuple[int, int]
    availability: Availability
    digest: str
    kind: str = "image"  # image | motion-reference

    @property
    def available(self) -> bool:
        return self.availability == Availability.AVAILABLE


ANCHORS = (
    ("anchor:ridge-dusk", "Ridge at dusk (authored anchor)", 3, (640, 400)),
    ("anchor:ridge-high", "High ridge (authored anchor)", 1, (640, 400)),
    ("anchor:coast-wide", "Wide coast (authored anchor)", 2, (800, 400)),
)
REFERENCES = (
    ("motion:orbit-slow", "Slow orbit (motion reference)", Availability.AVAILABLE),
    ("motion:handheld", "Handheld walk (motion reference)", Availability.AVAILABLE),
    ("motion:lost", "Lost reference clip", Availability.MISSING),
)
AUDIO = (
    ("audio:ambience", "Imported ambience loop", 12.0, Availability.AVAILABLE),
    ("audio:score", "Imported short score", 3.0, Availability.AVAILABLE),
    ("audio:lost", "Lost audio file", 12.0, Availability.MISSING),
)


class MediaCatalog:
    """Session catalog of fixture media. ``replace_media`` models bytes changing on disk."""

    def __init__(self) -> None:
        self._sources: dict[str, MotionSource] = {}
        self._revisions: dict[str, int] = {}
        for still in STILL_SOURCES:
            self._add(still.key, still.title, still.motif, still.size, still.availability)
        for key, title, motif, size in ANCHORS:
            self._add(key, title, motif, size, Availability.AVAILABLE)
        for key, title, availability in REFERENCES:
            self._add(key, title, 0, (640, 400), availability, "motion-reference")

    def _add(self, key, title, motif, size, availability, kind="image") -> None:
        self._sources[key] = MotionSource(
            key, title, motif, size, availability, media_digest(key), kind
        )

    def get(self, key: str) -> MotionSource:
        try:
            return self._sources[key]
        except KeyError:
            raise MotionRefused(
                f"Unknown media identity: {key}. Select an explicit fixture."
            ) from None

    def images(self) -> tuple[MotionSource, ...]:
        return tuple(s for s in self._sources.values() if s.kind == "image")

    def references(self) -> tuple[MotionSource, ...]:
        return tuple(s for s in self._sources.values() if s.kind == "motion-reference")

    def replace_media(self, key: str) -> MotionSource:
        """Simulate the file behind ``key`` changing. The old record is untouched; a new one replaces it."""
        old = self.get(key)
        self._revisions[key] = self._revisions.get(key, 0) + 1
        new = replace(old, digest=media_digest(key, self._revisions[key]))
        self._sources[key] = new
        return new

    def fingerprint(self, keys: Iterable[str]) -> tuple[tuple[str, str, str], ...]:
        out = []
        for key in dict.fromkeys(k for k in keys if k):
            src = self.get(key)
            out.append((key, src.digest, src.availability.value))
        return tuple(out)


def usable_image(catalog: MediaCatalog, key: str | None, role: str = "Source") -> list[str]:
    """Problems that block using ``key`` as an image. No substitute is ever chosen."""
    if not key:
        return [f"Select a {role.lower()} image fixture."]
    try:
        src = catalog.get(key)
    except MotionRefused as exc:
        return [str(exc)]
    if src.kind != "image":
        return [f"{role} {key} is not an image."]
    if not src.available:
        return [f"{role}: {src.availability}. No substitute selected for {key}."]
    return []


# ----------------------------------------------------------------------------------- workflows
@dataclass(frozen=True)
class FramePolicy:
    minimum: int
    maximum: int
    rule: str  # "4n+1" or "any"
    fps: int
    default: int

    def is_legal(self, frames: int) -> bool:
        if type(frames) is not int or not self.minimum <= frames <= self.maximum:
            return False
        return self.rule != "4n+1" or (frames - 1) % 4 == 0

    def describe(self) -> str:
        rule = "4n+1, " if self.rule == "4n+1" else ""
        return f"{rule}{self.minimum}–{self.maximum} native frames at {self.fps} fps"


@dataclass(frozen=True)
class WorkflowCapabilityFixture:
    """Fixture mirroring the video catalog at contract preparation. Identity is (id, version) only."""

    workflow_id: str
    version: str
    display_name: str
    route: Route
    governance: Governance
    policy: FramePolicy
    controls: frozenset[str]
    required: frozenset[str] = frozenset()
    storyboard: bool = False
    frames_out: bool = False
    admission_hold: str = ""
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.workflow_id, self.version)

    @property
    def label(self) -> str:
        return f"{self.display_name} {self.version}"

    @property
    def offered(self) -> bool:
        return self.governance != Governance.RETIRED


_WAN = FramePolicy(17, 81, "4n+1", 24, 33)
_SVD = FramePolicy(8, 25, "any", 6, 25)
WORKFLOWS: tuple[WorkflowCapabilityFixture, ...] = (
    WorkflowCapabilityFixture(
        "svd_native",
        "svd-xt",
        "Native SVD XT",
        Route.SVD,
        Governance.APPROVED,
        _SVD,
        frozenset({"seed", "motion_bucket"}),
        note="Separate accepted route. No motion prompt; not a Storyboard-editor workflow.",
    ),  # fmt: skip
    WorkflowCapabilityFixture(
        "wan22_ti2v_5b_i2v_v1",
        "1.3.0",
        "Wan2.2 TI2V-5B",
        Route.COMFY,
        Governance.APPROVED,
        _WAN,
        frozenset({"prompt", "seed"}),
        frozenset({"prompt"}),
        storyboard=True,
        frames_out=True,
        note="Approved. Frames-out version offered by the picker.",
    ),  # fmt: skip
    WorkflowCapabilityFixture(
        "wan22_ti2v_5b_i2v_v1",
        "1.2.0",
        "Wan2.2 TI2V-5B",
        Route.COMFY,
        Governance.APPROVED,
        _WAN,
        frozenset({"prompt", "seed"}),
        frozenset({"prompt"}),
        storyboard=True,
        note="Approved. Encoded-clip version kept so stored work replays on its exact graph.",
    ),  # fmt: skip
    WorkflowCapabilityFixture(
        "wan22_ti2v_5b_i2v_v1",
        "1.1.0",
        "Wan2.2 TI2V-5B",
        Route.COMFY,
        Governance.EXPERIMENTAL,
        _WAN,
        frozenset({"prompt", "seed"}),
        frozenset({"prompt"}),
        storyboard=True,
        note="Experimental: earlier qualification. Needs this job's own consent.",
    ),  # fmt: skip
    WorkflowCapabilityFixture(
        "wan_animate2_drive_i2v_v1",
        "1.2.0",
        "Wan-Animate-2 (driving video)",
        Route.COMFY,
        Governance.EXPERIMENTAL,
        FramePolicy(17, 49, "4n+1", 24, 33),
        frozenset({"prompt", "seed", "motion_reference"}),
        frozenset({"prompt", "motion_reference"}),
        note="Experimental. Driving video required; incompatible with Storyboard sequences.",
    ),  # fmt: skip
    WorkflowCapabilityFixture(
        "wan22_fun_control_5b_canny_i2v_v1",
        "1.0.0",
        "Wan2.2 Fun Control 5B",
        Route.COMFY,
        Governance.EXPERIMENTAL,
        FramePolicy(17, 49, "4n+1", 24, 33),
        frozenset({"prompt", "seed", "motion_reference"}),
        frozenset({"prompt", "motion_reference"}),
        admission_hold="Hardware not qualified: Preview is available but admission is blocked.",
        note="Experimental and hardware not qualified.",
    ),  # fmt: skip
    WorkflowCapabilityFixture(
        "ltx_multiframe_anchor_v1",
        "1.0.0",
        "LTX multi-frame anchor",
        Route.COMFY,
        Governance.RETIRED,
        _WAN,
        frozenset({"prompt", "seed"}),
        frozenset({"prompt"}),
        note="Retired. Readable in history; an execution request is refused.",
    ),  # fmt: skip
)
RECOMMENDED = ("wan22_ti2v_5b_i2v_v1", "1.3.0")
SVD_KEY = ("svd_native", "svd-xt")


def workflow_for(key: tuple[str, str]) -> WorkflowCapabilityFixture:
    """Look up by exact (id, version). Display names are never used to infer identity."""
    for workflow in WORKFLOWS:
        if workflow.key == tuple(key):
            return workflow
    raise MotionRefused(f"Unknown workflow identity: {key[0]} {key[1]}.")


def offered_workflows() -> tuple[WorkflowCapabilityFixture, ...]:
    return tuple(w for w in WORKFLOWS if w.offered)


# ------------------------------------------------------------------------------------------ seeds
@dataclass(frozen=True)
class SeedIntent:
    """Authoring intent only. A summary never freezes a seed; admission resolves it."""

    kind: str = "inherit"  # inherit | random | explicit
    value: int | None = None

    def problem(self) -> str:
        if self.kind not in ("inherit", "random", "explicit"):
            return f"Unknown seed intent '{self.kind}'."
        if self.kind == "explicit" and (
            type(self.value) is not int or not 0 <= self.value <= SEED_MAX
        ):
            return f"Explicit seed must be a whole number from 0 to {SEED_MAX}."
        return ""

    def describe(self) -> str:
        if self.kind == "explicit":
            return f"explicit {self.value}"
        return {"inherit": "inherit", "random": "random (drawn at admission)"}.get(self.kind, "?")


INHERIT, RANDOM = SeedIntent("inherit"), SeedIntent("random")


# ---------------------------------------------------------------------------------------- drafts
@dataclass(frozen=True)
class MotionDraft:
    """Quick Clip authoring intent."""

    draft_id: str
    source_key: str | None
    source_digest: str | None
    workflow: tuple[str, str] = RECOMMENDED
    prompt: str = ""
    frames: int = 33
    seed: SeedIntent = RANDOM
    reference_key: str | None = None
    motion_bucket: int | None = None
    variants: int = 1
    drill_fail_variant: int | None = None


@dataclass(frozen=True)
class StoryboardShot:
    """``prompt`` None inherits the storyboard prompt; ``""`` is explicitly empty and blocks."""

    shot_id: str
    label: str
    prompt: str | None = None
    frames: int | None = None
    seed: SeedIntent = INHERIT
    anchor_key: str | None = None  # None: carry the previous exact last frame (shot 1: the source)
    anchor_digest: str | None = None


@dataclass(frozen=True)
class StoryboardDraft:
    storyboard_id: str
    title: str
    base_revision: int  # 0 = never saved
    source_key: str | None
    source_digest: str | None
    workflow: tuple[str, str]
    default_prompt: str
    default_frames: int | None
    seed: SeedIntent
    shots: tuple[StoryboardShot, ...]
    drill_fail_shot: str | None = None


@dataclass(frozen=True)
class AssemblyItem:
    item_id: str
    clip_id: str
    trim_start: int = 0
    trim_end: int = 0


@dataclass(frozen=True)
class MovieAssemblyDraft:
    assembly_id: str
    title: str = "Mock movie"
    items: tuple[AssemblyItem, ...] = ()
    transition: str = "cut"
    audio_key: str | None = None
    profile: str = "recommended"
    drill_failure: bool = False


TRANSITIONS = {"cut": ("Hard cut", 0.0), "crossfade": ("Crossfade (illustrated)", 0.5)}


@dataclass(frozen=True)
class ExportProfile:
    key: str
    label: str
    fps: int
    max_seconds: float
    audio: bool
    match_first_size: bool


PROFILES = {
    p.key: p
    for p in (
        ExportProfile("recommended", "Recommended · 24 fps (illustrative)", 24, 60.0, True, False),
        ExportProfile("draft", "Draft · 12 fps small (illustrative)", 12, 30.0, True, False),
        ExportProfile("archive", "Archive · match first clip, no audio (illustrative)", 24, 20.0, False, True),
    )
}  # fmt: skip


# ------------------------------------------------------------------------------------- previews
@dataclass(frozen=True)
class ShotReadiness:
    shot_id: str
    position: int
    label: str
    frames: int | None
    seconds: float | None
    anchor_basis: str  # source | provided | carried
    prompt_origin: str  # explicit | inherited
    frames_origin: str
    seed_text: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class MotionPreview:
    """Readiness summary. ``executable`` is always False: it is not a job, plan or NJR."""

    kind: str
    revision: int
    media_fingerprint: tuple
    snapshot: object
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    facts: tuple[tuple[str, str], ...]
    total_frames: int = 0
    seconds: float = 0.0
    shots: tuple[ShotReadiness, ...] = ()
    executable: bool = False


def _seconds(frames: int, fps: int) -> float:
    return round(frames / fps, 3)


def _seed_problem(intent: SeedIntent, prefix: str = "") -> list[str]:
    problem = intent.problem()
    return [f"{prefix}{problem}"] if problem else []


def _workflow_problems(wf: WorkflowCapabilityFixture) -> list[str]:
    problems = []
    if wf.governance == Governance.RETIRED:
        problems.append(
            f"{wf.label} is retired: it stays readable in history but is never offered as ready."
        )
    if wf.admission_hold:
        problems.append(f"{wf.label}: {wf.admission_hold}")
    return problems


def evaluate_quick(draft: MotionDraft, catalog: MediaCatalog, revision: int) -> MotionPreview:
    errors, warnings = [], []
    try:
        wf = workflow_for(draft.workflow)
    except MotionRefused as exc:
        return MotionPreview(KIND_QUICK, revision, (), draft, (str(exc),), (), ())
    errors += usable_image(catalog, draft.source_key)
    source = catalog.get(draft.source_key) if not errors else None
    if source is not None and draft.source_digest != source.digest:
        errors.append(
            f"Source media changed since selection (recorded {draft.source_digest}, current "
            f"{source.digest}). Review it, then Accept Current Media."
        )
    errors += _workflow_problems(wf)
    prompt = draft.prompt.strip()
    if "prompt" in wf.controls:
        if "prompt" in wf.required and not prompt:
            errors.append("Enter a motion prompt.")
    elif prompt:
        errors.append(
            f"{wf.label} declares no motion prompt control. Controls are refused, never dropped: "
            "clear the prompt or choose a prompt-directed workflow."
        )
    if not wf.policy.is_legal(draft.frames):
        errors.append(
            f"{draft.frames} frames is not legal for {wf.label} ({wf.policy.describe()})."
        )
    errors += _seed_problem(draft.seed)
    if (
        draft.seed.kind == "explicit"
        and not draft.seed.problem()
        and draft.seed.value + draft.variants - 1 > SEED_MAX
    ):
        errors.append(
            f"Explicit seed {draft.seed.value} with {draft.variants} variants would pass {SEED_MAX}. "
            "Choose a lower seed or fewer variants."
        )
    if draft.seed.kind == "inherit":
        warnings.append("Seed intent 'inherit' resolves to a random draw at admission.")
    if draft.reference_key:
        if "motion_reference" not in wf.controls:
            errors.append(
                f"{wf.label} does not support a motion reference. Remove it or change workflow."
            )
        else:
            try:
                ref = catalog.get(draft.reference_key)
                if ref.kind != "motion-reference":
                    errors.append(f"{draft.reference_key} is not a motion reference.")
                elif not ref.available:
                    errors.append(f"Motion reference: {ref.availability}. No substitute selected.")
            except MotionRefused as exc:
                errors.append(str(exc))
    elif "motion_reference" in wf.required:
        errors.append(f"{wf.label} requires a motion reference (driving video).")
    if draft.motion_bucket is not None:
        if "motion_bucket" not in wf.controls:
            errors.append(
                f"{wf.label} does not declare Motion bucket. The value is refused, not dropped."
            )
        elif not 1 <= draft.motion_bucket <= 255:
            errors.append("Motion bucket must be between 1 and 255.")
    if not 1 <= draft.variants <= MAX_VARIANTS:
        errors.append(f"Variants must be between 1 and {MAX_VARIANTS}.")
    if wf.governance == Governance.EXPERIMENTAL:
        warnings.append("Experimental workflow: this submission needs its own explicit consent.")
    keys = [k for k in (draft.source_key, draft.reference_key) if k]
    fp = catalog.fingerprint(k for k in keys if _known(catalog, k))
    legal = wf.policy.is_legal(draft.frames)
    seconds = _seconds(draft.frames, wf.policy.fps) if legal else 0.0
    facts = (
        ("Source", f"{draft.source_key or 'none'} · {source.availability.value if source else 'unknown'}"),
        ("Source identity", f"recorded {draft.source_digest or '-'} · current {source.digest if source else '-'}"),
        ("Workflow", f"{wf.workflow_id} {wf.version} · {wf.route.value}"),
        ("Governance", wf.governance.value),
        ("Declared controls", ", ".join(sorted(wf.controls))),
        ("Frames", f"{draft.frames} native · {seconds:.2f} s at {wf.policy.fps} fps" if legal else f"{draft.frames} (illegal)"),
        ("Seed intent", draft.seed.describe()),
        ("Motion reference", draft.reference_key or "none"),
        ("Variants", str(draft.variants)),
        ("Not an executable job", "This summary freezes no seed and builds no NJR."),
    )  # fmt: skip
    return MotionPreview(
        KIND_QUICK, revision, fp, draft, tuple(errors), tuple(warnings), facts,
        draft.frames if legal else 0, seconds,
    )  # fmt: skip


def _known(catalog: MediaCatalog, key: str) -> bool:
    try:
        catalog.get(key)
        return True
    except MotionRefused:
        return False


def effective_frames(draft: StoryboardDraft, shot: StoryboardShot, wf) -> int:
    if shot.frames is not None:
        return shot.frames
    return draft.default_frames if draft.default_frames is not None else wf.policy.default


def effective_prompt(draft: StoryboardDraft, shot: StoryboardShot) -> str | None:
    return draft.default_prompt if shot.prompt is None else shot.prompt


def anchor_basis(position: int, shot: StoryboardShot) -> str:
    if position == 0:
        return "source"
    return "provided" if shot.anchor_key else "carried"


def evaluate_storyboard(
    draft: StoryboardDraft, catalog: MediaCatalog, revision: int
) -> MotionPreview:
    errors, warnings = [], []
    try:
        wf = workflow_for(draft.workflow)
    except MotionRefused as exc:
        return MotionPreview(KIND_STORY, revision, (), draft, (str(exc),), (), ())
    count = len(draft.shots)
    if not MIN_SHOTS <= count <= MAX_SHOTS:
        errors.append(f"A Storyboard needs {MIN_SHOTS}–{MAX_SHOTS} shots (this draft has {count}).")
    ids = [s.shot_id for s in draft.shots]
    if len(set(ids)) != len(ids):
        errors.append("Shot identities must be unique.")
    errors += _workflow_problems(wf)
    if not wf.storyboard:
        errors.append(
            f"{wf.label} does not support the Storyboard editor "
            "(native SVD sequences and driving-video workflows keep their own routes)."
        )
    image_problems = usable_image(catalog, draft.source_key)
    errors += image_problems
    source = None if image_problems else catalog.get(draft.source_key)
    if source is not None and draft.source_digest != source.digest:
        errors.append(
            "Source media changed since it was recorded. Review it, then Accept Current Media."
        )
    errors += _seed_problem(draft.seed, "Storyboard seed: ")
    keys: list[str] = [draft.source_key] if draft.source_key else []
    keys += [s.anchor_key for s in draft.shots if s.anchor_key]
    shots, total, seconds, carried = [], 0, 0.0, 0
    for position, shot in enumerate(draft.shots):
        shot_errors: list[str] = []
        basis = anchor_basis(position, shot)
        prompt = effective_prompt(draft, shot)
        if prompt is None or (shot.prompt is None and not prompt.strip()):
            shot_errors.append("has no prompt and inherits an empty Storyboard prompt")
        elif not prompt.strip():
            shot_errors.append("prompt is explicitly empty")
        frames = effective_frames(draft, shot, wf)
        legal = wf.policy.is_legal(frames)
        if not legal:
            shot_errors.append(f"{frames} frames is not legal ({wf.policy.describe()})")
        shot_errors += _seed_problem(shot.seed)
        if position == 0 and shot.anchor_key:
            shot_errors.append(
                "has an authored anchor but shot 1 starts from the main source: clear it or move it back"
            )
        if shot.anchor_key and position > 0:
            problems = usable_image(catalog, shot.anchor_key, "Anchor")
            shot_errors += problems
            if not problems:
                anchor, main = catalog.get(shot.anchor_key), source
                if main is not None and anchor.size != main.size:
                    shot_errors.append(
                        f"anchor size {anchor.size[0]}×{anchor.size[1]} differs from the sequence frame size "
                        f"{main.size[0]}×{main.size[1]}"
                    )
                if shot.anchor_digest != anchor.digest:
                    shot_errors.append(
                        f"anchor media changed (recorded {shot.anchor_digest}, current {anchor.digest}): "
                        "Accept Current Media"
                    )
        if basis == "carried":
            carried += 1
        if legal:
            total += frames
            seconds += _seconds(frames, wf.policy.fps)
        seed_text = shot.seed.describe()
        if shot.seed.kind == "inherit":
            seed_text = (
                f"inherits Storyboard seed ({draft.seed.describe()})"
                if position == 0
                else "inherit (random at admission)"
            )
        shots.append(
            ShotReadiness(
                shot.shot_id, position + 1, shot.label, frames if legal else None,
                _seconds(frames, wf.policy.fps) if legal else None, basis,
                "inherited" if shot.prompt is None else "explicit",
                "inherited" if shot.frames is None else "explicit", seed_text, tuple(shot_errors),
            )
        )  # fmt: skip
        errors += [f"Shot {position + 1} ({shot.label}): {e}." for e in shot_errors]
    if wf.governance == Governance.EXPERIMENTAL:
        warnings.append("Experimental workflow: this submission needs its own explicit consent.")
    warnings.append("Seeds are intent only: blank later seeds and 'random' resolve at admission.")
    fp = catalog.fingerprint(k for k in keys if _known(catalog, k))
    overlap = carried
    facts = (
        ("Source (shot 1)", f"{draft.source_key or 'none'} · {source.availability.value if source else 'unknown'}"),
        ("Workflow", f"{wf.workflow_id} {wf.version} · {wf.governance.value}"),
        ("Shots", f"{count} in authored order"),
        ("Native frames", f"{total} total · ≈{seconds:.2f} s before overlap trims ({overlap} carried boundary frame(s))"),
        ("Anchors", f"{sum(1 for s in shots if s.anchor_basis == 'provided')} provided · {carried} carried"),
        ("Not an executable plan", "This summary freezes no seed and builds no NJR."),
    )  # fmt: skip
    return MotionPreview(
        KIND_STORY, revision, fp, draft, tuple(errors), tuple(warnings), facts, total,
        round(seconds, 3), tuple(shots),
    )  # fmt: skip


# ------------------------------------------------------------------------------------- results
@dataclass(frozen=True)
class MockClip:
    clip_id: str
    run_id: str
    kind: str  # variant | segment
    label: str
    variant: int | None
    shot_id: str | None
    position: int | None
    source_key: str
    source_digest: str
    anchor_basis: str
    workflow: tuple[str, str]
    prompt: str
    frames: int
    fps: int
    seed: int | None
    seed_origin: str
    motion: str
    status: str  # completed | failed
    failure: str = ""
    consent_recorded: bool = False
    output_available: bool = True
    reference_key: str | None = None
    origin: str = "session"

    @property
    def seconds(self) -> float:
        return _seconds(self.frames, self.fps)

    @property
    def completed(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True)
class ResolvedShot:
    shot_id: str
    position: int
    label: str
    prompt: str
    frames: int
    seed: int
    seed_origin: str
    anchor_basis: str
    anchor_key: str | None
    anchor_digest: str | None


@dataclass(frozen=True)
class MockRun:
    """A simulated quick-clip submission or sequence. Not a job record."""

    run_id: str
    kind: str  # quick | sequence
    title: str
    snapshot: object  # frozen MotionDraft / StoryboardDraft as simulated
    plan_fingerprint: str
    resolved: tuple[ResolvedShot, ...]
    clips: tuple[MockClip, ...]
    state: str  # Completed | Partially completed | Failed
    completed_prefix: int
    origin: str = "session"
    expressible: bool = True


@dataclass(frozen=True)
class MockMovieResult:
    movie_id: str
    assembly_id: str
    title: str
    snapshot: MovieAssemblyDraft
    clip_ids: tuple[str, ...]
    seconds: float
    frames: int
    fps: int
    profile: str
    audio_key: str | None
    status: str  # completed | failed
    failure: str = ""


@dataclass(frozen=True)
class Rating:
    stars: int
    note: str = ""


def plan_fingerprint(draft: object) -> str:
    """Identity of the *plan* (not title or save revision). Used for strict-resume eligibility."""
    if isinstance(draft, StoryboardDraft):
        draft = replace(draft, base_revision=0, title="")
    return hashlib.sha256(repr(draft).encode()).hexdigest()[:16]


def motion_for(prompt: str, seed: int | None) -> str:
    """Pick the illustration camera move from the prompt; deterministic."""
    text = prompt.lower()
    for word, motion in (
        ("left", "pan-left"), ("right", "pan-right"), ("zoom out", "zoom-out"), ("zoom", "zoom-in"),
        ("tilt", "tilt-up"), ("up", "tilt-up"),
    ):  # fmt: skip
        if re.search(rf"\b{re.escape(word)}\b", text):
            return motion
    options = ("pan-right", "zoom-in", "pan-left", "tilt-up", "zoom-out")
    return options[(seed or 0) % len(options)]


def resume_eligibility(run: MockRun, current_plan: object | None) -> tuple[bool, str]:
    """Fixture-only explanation of strict resume. There is no Resume action in this prototype."""
    if run.kind != "sequence":
        return False, "Only a sequence has a checkpoint prefix."
    if run.state != "Failed":
        return False, "Nothing to resume: the simulated sequence did not fail."
    if current_plan is None or plan_fingerprint(current_plan) != run.plan_fingerprint:
        return False, (
            "Not eligible: the plan changed since this run. A changed plan is a new full candidate, "
            "never a same-plan checkpoint resume."
        )
    return True, (
        f"Would be eligible only because the plan is unchanged ({run.completed_prefix} segment(s) done). "
        "Explanation only: this prototype has no Resume."
    )


def describe_run(run: MockRun) -> list[str]:
    lines = [f"{run.run_id} · {run.title} · {run.state} · {MOCK_NOTICE}"]
    for clip in run.clips:
        flag = "" if clip.completed else f" · FAILED: {clip.failure}"
        lines.append(
            f"{clip.clip_id} · {clip.label} · {clip.frames} f ({clip.seconds:.2f} s) · seed {clip.seed} "
            f"({clip.seed_origin}) · {clip.anchor_basis} anchor{flag}"
        )
    return lines


def diff_runs(a: MockRun, b: MockRun) -> list[str]:
    """Effective-setting differences between two simulated runs (never merges them)."""
    out = []
    if a.kind != b.kind:
        return ["Different run kinds cannot be compared setting by setting."]
    if a.kind == "quick":
        da, db = a.snapshot, b.snapshot
        for field in (
            "source_key",
            "workflow",
            "prompt",
            "frames",
            "reference_key",
            "motion_bucket",
        ):
            if getattr(da, field) != getattr(db, field):
                out.append(f"{field} · {getattr(da, field)} → {getattr(db, field)}")
        return out or ["No effective settings differ."]
    ra, rb = {r.shot_id: r for r in a.resolved}, {r.shot_id: r for r in b.resolved}
    if [r.shot_id for r in a.resolved] != [r.shot_id for r in b.resolved]:
        out.append(
            "Shot order/membership · "
            + " ".join(r.label for r in a.resolved) + " → " + " ".join(r.label for r in b.resolved)
        )  # fmt: skip
    for shot_id in ra.keys() & rb.keys():
        for field in ("prompt", "frames", "anchor_basis", "anchor_key"):
            if getattr(ra[shot_id], field) != getattr(rb[shot_id], field):
                out.append(
                    f"{ra[shot_id].label} {field} · {getattr(ra[shot_id], field)} → {getattr(rb[shot_id], field)}"
                )
    if a.snapshot.workflow != b.snapshot.workflow:  # type: ignore[attr-defined]
        out.append(f"workflow · {a.snapshot.workflow} → {b.snapshot.workflow}")  # type: ignore[attr-defined]
    return out or ["No effective settings differ."]


# ---------------------------------------------------------------------------------- authoring
class Authoring[T]:
    """One mutable owner of a draft with undo/redo. Drafts themselves are immutable values."""

    def __init__(self) -> None:
        self.draft: T | None = None
        self.revision = 0
        self._initial: T | None = None
        self._undo: list[T] = []
        self._redo: list[T] = []

    @property
    def dirty(self) -> bool:
        return self.draft is not None and self.draft != self._initial

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def reset(self, draft: T) -> None:
        self.draft = self._initial = draft
        self._undo.clear()
        self._redo.clear()
        self.revision += 1

    def set(self, draft: T) -> bool:
        if self.draft is None or draft == self.draft:
            return False
        self._undo.append(self.draft)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self.draft = draft
        self.revision += 1
        return True

    def rebase(self, draft: T, adapt: Callable[[T], T] | None = None) -> None:
        """Adopt a saved form of the same content without a material change (no revision bump).

        ``adapt`` carries save metadata (the new base revision) onto the undo/redo history."""
        self.draft = self._initial = draft
        if adapt is not None:
            self._undo = [adapt(d) for d in self._undo]
            self._redo = [adapt(d) for d in self._redo]

    def undo(self) -> None:
        if self.draft is not None and self._undo:
            self._redo.append(self.draft)
            self.draft = self._undo.pop()
            self.revision += 1

    def redo(self) -> None:
        if self.draft is not None and self._redo:
            self._undo.append(self.draft)
            self.draft = self._redo.pop()
            self.revision += 1


class StoryboardStore:
    """In-memory mock of a saved-draft library. It never touches the filesystem."""

    def __init__(self) -> None:
        self._revisions: dict[str, list[StoryboardDraft]] = {}

    def latest_revision(self, storyboard_id: str) -> int:
        return len(self._revisions.get(storyboard_id, ()))

    def list(self) -> list[tuple[str, str, int]]:
        return [(sid, revs[-1].title, len(revs)) for sid, revs in self._revisions.items()]

    def save(self, draft: StoryboardDraft) -> StoryboardDraft:
        latest = self.latest_revision(draft.storyboard_id)
        if draft.base_revision != latest:
            raise StaleSave(
                f"Stale save: you edited revision {draft.base_revision} but revision {latest} is saved. "
                "Reopen the saved draft or use Save As."
            )
        saved = replace(draft, base_revision=latest + 1)
        self._revisions.setdefault(draft.storyboard_id, []).append(saved)
        return saved

    def open(self, storyboard_id: str, revision: int | None = None) -> StoryboardDraft:
        revs = self._revisions.get(storyboard_id)
        if not revs:
            raise MotionRefused(f"No saved Storyboard {storyboard_id}.")
        number = revision or len(revs)
        if not 1 <= number <= len(revs):
            raise MotionRefused(f"Storyboard {storyboard_id} has no revision {number}.")
        return revs[number - 1]

    def external_save(self, storyboard_id: str) -> StoryboardDraft:
        """Fixture: another session saves first (makes the next local save stale)."""
        latest = self.open(storyboard_id)
        saved = replace(
            latest, base_revision=latest.base_revision + 1, title=latest.title + " (other session)"
        )
        self._revisions[storyboard_id].append(saved)
        return saved


# ------------------------------------------------------------------------------------- session
class MotionSession:
    """Single owner of mutable prototype state. Results, previews and drafts are immutable values."""

    def __init__(self, *, with_history: bool = True) -> None:
        self.catalog = MediaCatalog()
        self._counters: dict[str, int] = {}
        self.quick: Authoring[MotionDraft] = Authoring()
        self.story: Authoring[StoryboardDraft] = Authoring()
        self.assembly: Authoring[MovieAssemblyDraft] = Authoring()
        self.previews: dict[str, MotionPreview | None] = dict.fromkeys(KINDS)
        self.assembly_preview: MotionPreview | None = None
        self._consent: dict[str, tuple[int, str]] = {}
        self._admitted: dict[str, tuple[int, str, tuple]] = {}
        self.runs: list[MockRun] = []
        self.clips: dict[str, MockClip] = {}
        self.movies: list[MockMovieResult] = []
        self.ratings: dict[str, Rating] = {}
        self.store = StoryboardStore()
        self.origin: dict[str, str] = {}
        if with_history:
            self._seed_history()

    # ----------------------------------------------------------------------------- identity
    def mint(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}-{self._counters[prefix]}"

    def _auth(self, kind: str) -> Authoring:
        return {KIND_QUICK: self.quick, KIND_STORY: self.story, KIND_MOVIE: self.assembly}[kind]

    # ------------------------------------------------------------------------ fixture history
    def _seed_history(self) -> None:
        """Previously simulated sequences (clearly labelled fixture history, never real output)."""

        def shot(sid, label, prompt, frames, anchor=None):
            return StoryboardShot(
                sid, label, prompt, frames, INHERIT, anchor,
                self.catalog.get(anchor).digest if anchor else None,
            )  # fmt: skip

        ridge = self.catalog.get("create:ridge-study")
        draft = StoryboardDraft(
            "hist-board-1", "Fixture · Ridge walk", 1, ridge.key, ridge.digest, RECOMMENDED,
            "", 33, SeedIntent("explicit", 4100),
            (shot("hist-shot-1", "Open on ridge", "Slow push toward the ridge", 33),
             shot("hist-shot-2", "Dusk turn", "Tilt up as dusk arrives", 25, "anchor:ridge-dusk"),
             shot("hist-shot-3", "Wind in grass", "Pan right across the grass", 17)),
        )  # fmt: skip
        self._record_history_run("hist-run-1", draft, fail_at=None)
        mixed = replace(
            draft,
            storyboard_id="hist-board-2",
            title="Fixture · Mixed workflows",
            shots=draft.shots[:2],
        )
        self._record_history_run("hist-run-2", mixed, fail_at=None, mixed=True)
        lost = replace(self.clips["hist-run-1-clip-1"], clip_id="hist-clip-lost", label="Archived clip (file missing)",
                       output_available=False)  # fmt: skip
        self.clips[lost.clip_id] = lost
        failed = replace(self.clips["hist-run-1-clip-2"], clip_id="hist-clip-failed", label="Failed fixture variant",
                         status="failed", failure="Fixture history: backend refused.")  # fmt: skip
        self.clips[failed.clip_id] = failed
        retired = replace(self.clips["hist-run-1-clip-3"], clip_id="hist-clip-retired",
                          label="Clip from a retired workflow", workflow=("ltx_multiframe_anchor_v1", "1.0.0"))  # fmt: skip
        self.clips[retired.clip_id] = retired

    def _record_history_run(self, run_id, draft: StoryboardDraft, *, fail_at, mixed=False) -> None:
        resolved = self._resolve_shots(draft, run_id)
        clips = []
        for r in resolved:
            wf = draft.workflow if not (mixed and r.position == 2) else ("svd_native", "svd-xt")
            clip = MockClip(
                f"{run_id}-clip-{r.position}", run_id, "segment", r.label, None, r.shot_id, r.position,
                draft.source_key or "", draft.source_digest or "", r.anchor_basis, wf, r.prompt, r.frames,
                workflow_for(wf).policy.fps, r.seed, r.seed_origin, motion_for(r.prompt, r.seed),
                "completed", "", False, True, None, "fixture history",
            )  # fmt: skip
            clips.append(clip)
            self.clips[clip.clip_id] = clip
        self.runs.append(
            MockRun(
                run_id,
                "sequence",
                draft.title,
                draft,
                plan_fingerprint(draft),
                resolved,
                tuple(clips),
                "Completed",
                len(clips),
                "fixture history",
                expressible=not mixed,
            )  # fmt: skip
        )

    # -------------------------------------------------------------------------------- consent
    def consent_required(self, kind: str) -> bool:
        draft = self._auth(kind).draft
        if kind == KIND_MOVIE or draft is None:
            return False
        try:
            return workflow_for(draft.workflow).governance == Governance.EXPERIMENTAL
        except MotionRefused:
            return False

    def consent_valid(self, kind: str) -> bool:
        auth = self._auth(kind)
        return (
            auth.draft is not None
            and kind in self._consent
            and self._consent[kind] == (auth.revision, self._consent_fingerprint(kind, auth.draft))
        )

    def _consent_fingerprint(self, kind: str, draft: object) -> str:
        media = self.media_fingerprint(kind)
        return hashlib.sha256(f"{kind}|{draft!r}|{media!r}".encode()).hexdigest()

    def _admitted_now(self, kind: str) -> tuple | None:
        """The admission record, only while the draft revision and media bytes are unchanged."""
        admitted = self._admitted.get(kind)
        if (
            admitted
            and admitted[0] == self._auth(kind).revision
            and admitted[2] == self.media_fingerprint(kind)
        ):
            return admitted
        return None

    def grant_consent(self, kind: str) -> None:
        """Consent is bound to this exact draft revision: any later change (even back to equal values) voids it."""
        if not self.consent_required(kind):
            raise MotionRefused("This workflow does not need experimental consent.")
        auth = self._auth(kind)
        self._consent[kind] = (auth.revision, self._consent_fingerprint(kind, auth.draft))

    def revoke_consent(self, kind: str) -> None:
        self._consent.pop(kind, None)

    # ----------------------------------------------------------------------------- quick clip
    def _new_quick(self, key: str, workflow: tuple[str, str] | None = None) -> MotionDraft:
        src = self.catalog.get(key)
        return MotionDraft(self.mint("draft"), key, src.digest, workflow or RECOMMENDED)

    def select_source(
        self, key: str, choice: Replacement | None = None, *, origin: str = "picker"
    ) -> bool:
        """Select the Quick Clip source. False means the unsaved draft needs a Cancel/Replace decision."""
        problems = usable_image(self.catalog, key)
        if problems:
            raise MotionRefused(problems[0])
        draft = self.quick.draft
        if draft is not None and draft.source_key == key:
            return True
        needs_decision = draft is not None and (self.quick.dirty or origin != "picker")
        if needs_decision and choice != Replacement.REPLACE:
            return False
        workflow = draft.workflow if draft else None
        self.quick.reset(self._new_quick(key, workflow))
        self.previews[KIND_QUICK] = None
        self._consent.pop(KIND_QUICK, None)  # a new source is a new proposed submission
        self.origin[KIND_QUICK] = origin
        return True

    def receive_source(self, key: str, origin: str, choice: Replacement | None = None) -> bool:
        """H4 (Create/Edit -> Motion): identity and availability only. Never preview, consent or submission."""
        return self.select_source(key, choice, origin=origin)

    def update_quick(self, **changes) -> bool:
        if self.quick.draft is None:
            raise MotionRefused("Select an available source image first.")
        return self.quick.set(replace(self.quick.draft, **changes))

    def accept_source_media(self, kind: str = KIND_QUICK) -> None:
        """Explicitly record the current bytes of the source (never automatic)."""
        draft = self._auth(kind).draft
        if draft is None or not draft.source_key:
            raise MotionRefused("No source to accept.")
        digest = self.catalog.get(draft.source_key).digest
        self._auth(kind).set(replace(draft, source_digest=digest))

    # -------------------------------------------------------------------------------- review
    def media_fingerprint(self, kind: str) -> tuple:
        draft = self._auth(kind).draft
        if draft is None:
            return ()
        if kind == KIND_QUICK:
            keys = [draft.source_key, draft.reference_key]
        elif kind == KIND_STORY:
            keys = [draft.source_key, *(s.anchor_key for s in draft.shots)]
        else:
            return ()
        return self.catalog.fingerprint(k for k in keys if k and _known(self.catalog, k))

    def review(self, kind: str) -> MotionPreview:
        auth = self._auth(kind)
        if auth.draft is None:
            raise MotionRefused("Nothing to review yet.")
        if kind == KIND_QUICK:
            preview = evaluate_quick(auth.draft, self.catalog, auth.revision)
        elif kind == KIND_STORY:
            preview = evaluate_storyboard(auth.draft, self.catalog, auth.revision)
        else:
            preview = self._evaluate_assembly(auth.draft, auth.revision)
        self.previews[kind] = preview
        return preview

    def status(self, kind: str) -> Status:
        auth, preview = self._auth(kind), self.previews[kind]
        if auth.draft is None or preview is None:
            return Status.NOT_REVIEWED
        if preview.revision != auth.revision or preview.media_fingerprint != self.media_fingerprint(
            kind
        ):
            return Status.STALE
        if preview.errors or (self.consent_required(kind) and not self.consent_valid(kind)):
            return Status.BLOCKED
        if self._admitted_now(kind):
            return Status.SIMULATED
        return Status.READY

    def issues(self, kind: str) -> tuple[str, ...]:
        """Blocking reasons for the current draft (from the last review plus the live consent check)."""
        preview = self.previews[kind]
        if preview is None:
            return ()
        reasons = list(preview.errors)
        if self.consent_required(kind) and not self.consent_valid(kind):
            reasons.append(
                "Experimental workflow: grant consent for this specific mock submission to continue."
            )
        return tuple(reasons)

    def _require_ready(self, kind: str) -> None:
        status = self.status(kind)
        if status in (Status.READY, Status.SIMULATED):
            return
        why = {
            Status.NOT_REVIEWED: "Review Readiness first.",
            Status.STALE: "The reviewed summary is stale: the draft or media changed. Review Readiness again.",
            Status.BLOCKED: "Blocked: " + " ".join(self.issues(kind)[:3]),
        }[status]
        raise MotionRefused(f"No simulated admission: {why}")

    # ------------------------------------------------------------------------------ simulate
    def _derive_seed(self, plan: str, label: str) -> int:
        return int(hashlib.sha256(f"{plan}:{label}".encode()).hexdigest()[:8], 16)

    def simulate_quick(self) -> MockRun:
        self._require_ready(KIND_QUICK)
        draft = self.quick.draft
        admitted = self._admitted_now(KIND_QUICK)
        if admitted:
            return next(r for r in self.runs if r.run_id == admitted[1])
        wf = workflow_for(draft.workflow)
        run_id, plan = self.mint("mock-run"), plan_fingerprint(draft)
        consent = self.consent_required(KIND_QUICK) and self.consent_valid(KIND_QUICK)
        clips = []
        for variant in range(1, draft.variants + 1):
            if draft.seed.kind == "explicit":
                seed, origin = draft.seed.value + variant - 1, "explicit"
            else:
                seed, origin = self._derive_seed(plan, f"v{variant}"), "drawn at admission"
            failed = draft.drill_fail_variant == variant
            clip = MockClip(
                self.mint("mock-clip"), run_id, "variant", f"Variant {variant}", variant, None, None,
                draft.source_key, draft.source_digest, "source", draft.workflow, draft.prompt.strip(),
                draft.frames, wf.policy.fps, seed, origin, motion_for(draft.prompt, seed),
                "failed" if failed else "completed",
                "Fixture drill: simulated failure (no backend ran)." if failed else "",
                consent, not failed, draft.reference_key,
            )  # fmt: skip
            clips.append(clip)
            self.clips[clip.clip_id] = clip
        done = sum(c.completed for c in clips)
        state = (
            "Completed"
            if done == len(clips)
            else ("Failed" if done == 0 else "Partially completed")
        )
        run = MockRun(
            run_id,
            "quick",
            f"Quick Clip · {draft.source_key}",
            draft,
            plan,
            (),
            tuple(clips),
            state,
            done,
        )
        self.runs.append(run)
        self._admitted[KIND_QUICK] = (
            self.quick.revision,
            run_id,
            self.media_fingerprint(KIND_QUICK),
        )
        return run

    def simulate_storyboard(self) -> MockRun:
        self._require_ready(KIND_STORY)
        draft = self.story.draft
        admitted = self._admitted_now(KIND_STORY)
        if admitted:
            return next(r for r in self.runs if r.run_id == admitted[1])
        wf = workflow_for(draft.workflow)
        run_id, plan = self.mint("mock-run"), plan_fingerprint(draft)
        resolved = self._resolve_shots(draft, plan)
        consent = self.consent_required(KIND_STORY) and self.consent_valid(KIND_STORY)
        clips, prefix = [], 0
        for r in resolved:
            failed = draft.drill_fail_shot == r.shot_id
            if failed:
                clips.append(self._segment(run_id, draft, wf, r, consent, failed=True))
                self.clips[clips[-1].clip_id] = clips[-1]
                break
            clip = self._segment(run_id, draft, wf, r, consent, failed=False)
            clips.append(clip)
            self.clips[clip.clip_id] = clip
            prefix += 1
        state = "Completed" if prefix == len(resolved) else "Failed"
        run = MockRun(
            run_id, "sequence", draft.title, draft, plan, resolved, tuple(clips), state, prefix
        )
        self.runs.append(run)
        self._admitted[KIND_STORY] = (
            self.story.revision,
            run_id,
            self.media_fingerprint(KIND_STORY),
        )
        return run

    def _segment(
        self, run_id, draft, wf, r: ResolvedShot, consent: bool, *, failed: bool
    ) -> MockClip:
        source = draft.source_key if r.position == 1 else (r.anchor_key or draft.source_key)
        digest = self.catalog.get(source).digest
        return MockClip(
            self.mint("mock-clip"), run_id, "segment", r.label, None, r.shot_id, r.position, source,
            digest, r.anchor_basis, draft.workflow, r.prompt, r.frames, wf.policy.fps, r.seed,
            r.seed_origin, motion_for(r.prompt, r.seed), "failed" if failed else "completed",
            "Fixture drill: simulated failure at this shot (no backend ran)." if failed else "",
            consent, not failed,
        )  # fmt: skip

    def _resolve_shots(self, draft: StoryboardDraft, plan) -> tuple[ResolvedShot, ...]:
        wf = workflow_for(draft.workflow)
        out = []
        for position, shot in enumerate(draft.shots):
            intent = shot.seed
            if intent.kind == "inherit" and position == 0:
                intent = draft.seed
            if intent.kind == "explicit":
                seed, origin = intent.value, "explicit"
            else:
                seed, origin = self._derive_seed(str(plan), shot.shot_id), "drawn at admission"
            out.append(
                ResolvedShot(
                    shot.shot_id,
                    position + 1,
                    shot.label,
                    (effective_prompt(draft, shot) or "").strip(),
                    effective_frames(draft, shot, wf),
                    seed,
                    origin,
                    anchor_basis(position, shot),
                    shot.anchor_key,
                    shot.anchor_digest,
                )  # fmt: skip
            )
        return tuple(out)

    # ---------------------------------------------------------------------------- storyboard
    def _new_storyboard(
        self, source_key: str | None, workflow: tuple[str, str], title: str, prompt: str = ""
    ) -> StoryboardDraft:
        digest = self.catalog.get(source_key).digest if source_key else None
        sid = self.mint("board")
        shots = tuple(self._blank_shot(i + 1) for i in range(MIN_SHOTS))
        return StoryboardDraft(
            sid, title, 0, source_key, digest, workflow, prompt, None, RANDOM, shots
        )

    def _blank_shot(self, number: int) -> StoryboardShot:
        return StoryboardShot(self.mint("shot"), f"Shot {number}")

    def new_storyboard(
        self,
        source_key: str | None = None,
        choice: Replacement | None = None,
        *,
        workflow: tuple[str, str] = RECOMMENDED,
        title: str = "Untitled Storyboard",
        prompt: str = "",
    ) -> bool:
        if self.story.dirty and choice != Replacement.REPLACE:
            return False
        if source_key:
            problems = usable_image(self.catalog, source_key)
            if problems:
                raise MotionRefused(problems[0])
        self.story.reset(self._new_storyboard(source_key, workflow, title, prompt))
        self.previews[KIND_STORY] = None
        self._consent.pop(KIND_STORY, None)
        return True

    def ensure_storyboard(self) -> StoryboardDraft:
        if self.story.draft is None:
            self.new_storyboard()
        return self.story.draft

    def update_story(self, **changes) -> bool:
        draft = self.ensure_storyboard()
        return self.story.set(replace(draft, **changes))

    def _story_shots(self) -> tuple[StoryboardShot, ...]:
        return self.ensure_storyboard().shots

    def _index(self, shot_id: str) -> int:
        for i, shot in enumerate(self._story_shots()):
            if shot.shot_id == shot_id:
                return i
        raise MotionRefused(f"Unknown shot identity: {shot_id}.")

    def add_shot(self, *, after: str | None = None) -> StoryboardShot:
        shots = list(self._story_shots())
        if len(shots) >= MAX_SHOTS:
            raise MotionRefused(f"A Storyboard holds at most {MAX_SHOTS} shots.")
        new = self._blank_shot(len(shots) + 1)
        index = self._index(after) + 1 if after else len(shots)
        shots.insert(index, new)
        self.update_story(shots=tuple(shots))
        return new

    def duplicate_shot(self, shot_id: str) -> StoryboardShot:
        shots = list(self._story_shots())
        if len(shots) >= MAX_SHOTS:
            raise MotionRefused(f"A Storyboard holds at most {MAX_SHOTS} shots.")
        index = self._index(shot_id)
        copy = replace(shots[index], shot_id=self.mint("shot"), label=f"{shots[index].label} copy")
        shots.insert(index + 1, copy)
        self.update_story(shots=tuple(shots))
        return copy

    def remove_shot(self, shot_id: str) -> None:
        shots = list(self._story_shots())
        if len(shots) <= 1:
            raise MotionRefused("A Storyboard keeps at least one shot while editing.")
        del shots[self._index(shot_id)]
        self.update_story(shots=tuple(shots))

    def move_shot(self, shot_id: str, delta: int) -> bool:
        shots = list(self._story_shots())
        index = self._index(shot_id)
        target = index + delta
        if not 0 <= target < len(shots):
            return False
        shots.insert(target, shots.pop(index))
        return self.update_story(shots=tuple(shots))

    def update_shot(self, shot_id: str, **changes) -> bool:
        shots = list(self._story_shots())
        index = self._index(shot_id)
        if "anchor_key" in changes and "anchor_digest" not in changes:
            key = changes["anchor_key"]
            changes["anchor_digest"] = self.catalog.get(key).digest if key else None
        shots[index] = replace(shots[index], **changes)
        return self.update_story(shots=tuple(shots))

    def accept_anchor_media(self, shot_id: str) -> None:
        """Explicit acceptance of the current anchor bytes (the production 'Accept Current Media')."""
        shot = self._story_shots()[self._index(shot_id)]
        if not shot.anchor_key:
            raise MotionRefused("This shot has no authored anchor.")
        self.update_shot(shot_id, anchor_digest=self.catalog.get(shot.anchor_key).digest)

    def save_storyboard(self) -> StoryboardDraft:
        """In-memory mock save. Consent is never saved with a draft and the save clears it."""
        saved = self.store.save(self.ensure_storyboard())
        self.story.rebase(saved, lambda d: replace(d, base_revision=saved.base_revision))
        self._consent.pop(KIND_STORY, None)
        return saved

    def save_storyboard_as(self, title: str) -> StoryboardDraft:
        """Save As / Duplicate: a new Storyboard identity with independent shot identities."""
        draft = self.ensure_storyboard()
        shots = tuple(replace(s, shot_id=self.mint("shot")) for s in draft.shots)
        copy = replace(draft, storyboard_id=self.mint("board"), title=title, base_revision=0, shots=shots,
                       drill_fail_shot=None)  # fmt: skip
        saved = self.store.save(copy)
        self.story.reset(saved)
        self.previews[KIND_STORY] = None
        self._consent.pop(KIND_STORY, None)
        return saved

    def open_storyboard(self, storyboard_id: str, choice: Replacement | None = None) -> bool:
        if self.story.dirty and choice != Replacement.REPLACE:
            return False
        self.story.reset(self.store.open(storyboard_id))
        self.previews[KIND_STORY] = None
        self._consent.pop(KIND_STORY, None)  # a reopened draft never restores consent
        return True

    # ------------------------------------------------------------------------------ handoffs
    def storyboard_from_clip(self, clip_id: str, choice: Replacement | None = None) -> bool:
        """Motion -> Storyboard. A new draft identity from the clip's source; no historical job is reopened."""
        clip = self.clip(clip_id)
        wf = workflow_for(clip.workflow)
        if not wf.storyboard:
            raise MotionRefused(
                f"{wf.label} does not support the Storyboard editor, so this clip cannot start one."
            )
        problems = usable_image(self.catalog, clip.source_key)
        if problems:
            raise MotionRefused(problems[0])
        return self.new_storyboard(
            clip.source_key,
            choice,
            workflow=clip.workflow,
            title=f"From {clip.clip_id}",
            prompt=clip.prompt,
        )

    def storyboard_from_run(self, run_id: str, choice: Replacement | None = None) -> bool:
        """H8: reopen a previous simulated sequence as a NEW draft where its fields are expressible."""
        run = self.run(run_id)
        if run.kind != "sequence":
            raise MotionRefused("Only a simulated sequence can reopen as a Storyboard draft.")
        if not run.expressible:
            raise MotionRefused(
                "This sequence mixes workflows, which the Storyboard editor cannot express. "
                "It stays inspectable; nothing was reopened."
            )
        if self.story.dirty and choice != Replacement.REPLACE:
            return False
        snap: StoryboardDraft = run.snapshot  # type: ignore[assignment]
        shots = tuple(replace(s, shot_id=self.mint("shot")) for s in snap.shots)
        draft = replace(snap, storyboard_id=self.mint("board"), title=f"From {run.run_id}", base_revision=0,
                        shots=shots, drill_fail_shot=None)  # fmt: skip
        self.story.reset(draft)
        self.previews[KIND_STORY] = None
        self._consent.pop(KIND_STORY, None)
        return True

    # --------------------------------------------------------------------------- lookup/rating
    def clip(self, clip_id: str) -> MockClip:
        try:
            return self.clips[clip_id]
        except KeyError:
            raise MotionRefused(f"Unknown clip identity: {clip_id}.") from None

    def run(self, run_id: str) -> MockRun:
        for run in self.runs:
            if run.run_id == run_id:
                return run
        raise MotionRefused(f"Unknown simulated run: {run_id}.")

    def rate(self, clip_id: str, stars: int, note: str = "") -> Rating:
        """Operator impression of the illustration. Never enters Learning or changes the clip."""
        clip = self.clip(clip_id)
        if not clip.completed:
            raise MotionRefused("A failed variant has no illustration to rate.")
        if type(stars) is not int or not 1 <= stars <= 5:
            raise MotionRefused("Quality rating must be 1 to 5 stars.")
        self.ratings[clip_id] = Rating(stars, note)
        return self.ratings[clip_id]

    @staticmethod
    def clip_eligibility(clip: MockClip) -> tuple[bool, str]:
        if not clip.completed:
            return False, "Not eligible: this variant failed and has no simulated output."
        if not clip.output_available:
            return False, "Not eligible: the simulated output file is missing."
        try:
            if not workflow_for(clip.workflow).offered:
                return False, "Not eligible: produced by a retired workflow."
        except MotionRefused:
            return False, "Not eligible: unknown workflow identity."
        return True, "Eligible"

    # -------------------------------------------------------------------------------- movie
    def ensure_assembly(self) -> MovieAssemblyDraft:
        if self.assembly.draft is None:
            self.assembly.reset(MovieAssemblyDraft(self.mint("assembly")))
        return self.assembly.draft

    def update_assembly(self, **changes) -> bool:
        return self.assembly.set(replace(self.ensure_assembly(), **changes))

    def add_clips(
        self, clip_ids: Sequence[str], *, allow_duplicate: bool = False
    ) -> list[AssemblyItem]:
        """H5 and Select/Add: carries clip identities in the given order. Never starts assembly."""
        draft = self.ensure_assembly()
        items, added = list(draft.items), []
        for clip_id in clip_ids:
            clip = self.clip(clip_id)
            ok, reason = self.clip_eligibility(clip)
            if not ok:
                raise MotionRefused(f"{clip_id}: {reason}")
            if not allow_duplicate and any(i.clip_id == clip_id for i in items):
                raise MotionRefused(f"Duplicate source: {clip_id} is already in the assembly.")
            item = AssemblyItem(self.mint("item"), clip_id)
            items.append(item)
            added.append(item)
        self.update_assembly(items=tuple(items))
        return added

    def remove_item(self, item_id: str) -> None:
        draft = self.ensure_assembly()
        items = tuple(i for i in draft.items if i.item_id != item_id)
        if len(items) == len(draft.items):
            raise MotionRefused(f"Unknown assembly item: {item_id}.")
        self.update_assembly(items=items)

    def move_item(self, item_id: str, delta: int) -> bool:
        items = list(self.ensure_assembly().items)
        index = next((i for i, it in enumerate(items) if it.item_id == item_id), None)
        if index is None:
            raise MotionRefused(f"Unknown assembly item: {item_id}.")
        target = index + delta
        if not 0 <= target < len(items):
            return False
        items.insert(target, items.pop(index))
        return self.update_assembly(items=tuple(items))

    def set_trim(self, item_id: str, trim_start: int, trim_end: int) -> bool:
        items = list(self.ensure_assembly().items)
        for i, item in enumerate(items):
            if item.item_id == item_id:
                items[i] = replace(item, trim_start=trim_start, trim_end=trim_end)
                return self.update_assembly(items=tuple(items))
        raise MotionRefused(f"Unknown assembly item: {item_id}.")

    def _evaluate_assembly(self, draft: MovieAssemblyDraft, revision: int) -> MotionPreview:
        errors, warnings = [], []
        profile = PROFILES.get(draft.profile)
        if profile is None:
            errors.append(f"Unknown export profile: {draft.profile}.")
            profile = PROFILES["recommended"]
        if draft.transition not in TRANSITIONS:
            errors.append(f"Unknown transition: {draft.transition}.")
        transition_s = TRANSITIONS.get(draft.transition, ("", 0.0))[1]
        if not draft.items:
            errors.append("Add at least one clip to the assembly.")
        seen: dict[str, int] = {}
        durations, sizes, ordered = [], [], []
        for position, item in enumerate(draft.items, start=1):
            clip = self.clips.get(item.clip_id)
            if clip is None:
                errors.append(f"Item {position}: unknown clip {item.clip_id}.")
                continue
            ordered.append(clip.clip_id)
            ok, reason = self.clip_eligibility(clip)
            if not ok:
                errors.append(
                    f"Item {position} ({clip.clip_id}): {reason.removeprefix('Not eligible: ')}"
                )
            if item.clip_id in seen:
                errors.append(
                    f"Duplicate source: {item.clip_id} appears at positions {seen[item.clip_id]} and {position}. "
                    "Remove one."
                )
            seen.setdefault(item.clip_id, position)
            if item.trim_start < 0 or item.trim_end < 0:
                errors.append(f"Item {position}: trim cannot be negative.")
            elif item.trim_start + item.trim_end >= clip.frames:
                errors.append(f"Item {position}: trims remove all {clip.frames} frames.")
            else:
                durations.append(_seconds(clip.frames - item.trim_start - item.trim_end, clip.fps))
            sizes.append(self.catalog.get(clip.source_key).size)
        if profile.match_first_size and len(set(sizes)) > 1:
            errors.append(
                f"{profile.label} needs every clip at the first clip's size; sizes differ."
            )
        if transition_s and durations and transition_s > min(durations) / 2:
            errors.append(
                f"Crossfade {transition_s:.2f} s is longer than half of the shortest clip "
                f"({min(durations):.2f} s)."
            )
        total = round(sum(durations) - transition_s * max(0, len(durations) - 1), 3)
        if durations and total > profile.max_seconds:
            errors.append(
                f"≈{total:.1f} s exceeds {profile.label} limit of {profile.max_seconds:.0f} s."
            )
        audio_note = "none"
        if draft.audio_key:
            audio = next((a for a in AUDIO if a[0] == draft.audio_key), None)
            if audio is None:
                errors.append(f"Unknown imported audio: {draft.audio_key}.")
            elif audio[3] != Availability.AVAILABLE:
                errors.append(f"Audio {audio[1]}: {audio[3]}. No substitute selected.")
            elif not profile.audio:
                errors.append(
                    f"{profile.label} excludes imported audio. Choose none or another profile."
                )
            else:
                audio_note = f"{audio[1]} ({audio[2]:.0f} s imported fixture)"
                if audio[2] < total:
                    warnings.append(
                        "Audio is shorter than the movie: illustrated as padded with silence."
                    )
                elif audio[2] > total:
                    warnings.append(
                        "Audio is longer than the movie: illustrated as cut with a fade-out."
                    )
        facts = (
            ("Clips in order", " → ".join(ordered) or "none"),
            ("Estimated duration", f"≈{total:.2f} s · ≈{round(total * profile.fps)} frames at {profile.fps} fps"),
            ("Transition", TRANSITIONS.get(draft.transition, ("?", 0))[0]),
            ("Audio", audio_note),
            ("Export profile", profile.label),
            ("Simulated assembly only", "No FFmpeg, no encoded file, no queued assembly job."),
        )  # fmt: skip
        return MotionPreview(
            KIND_MOVIE, revision, (), draft, tuple(errors), tuple(warnings), facts,
            round(total * profile.fps), total,
        )  # fmt: skip

    def simulate_assembly(self) -> MockMovieResult:
        self._require_ready(KIND_MOVIE)
        admitted = self._admitted_now(KIND_MOVIE)
        if admitted:
            return next(m for m in self.movies if m.movie_id == admitted[1])
        draft, preview = self.assembly.draft, self.previews[KIND_MOVIE]
        profile = PROFILES[draft.profile]
        failed = draft.drill_failure
        result = MockMovieResult(
            self.mint("mock-movie"), draft.assembly_id, draft.title, draft,
            tuple(i.clip_id for i in draft.items), preview.seconds, preview.total_frames, profile.fps,
            draft.profile, draft.audio_key, "failed" if failed else "completed",
            "Fixture drill: simulated assembly failure. The clip list is retained." if failed else "",
        )  # fmt: skip
        self.movies.append(result)
        self._admitted[KIND_MOVIE] = (self.assembly.revision, result.movie_id, ())
        return result

    def latest_run(self, kind: str) -> MockRun | None:
        admitted = self._admitted.get(kind)
        if admitted is None:
            return None
        return next((r for r in self.runs if r.run_id == admitted[1]), None)

    def eligible_clips(self) -> list[MockClip]:
        return [c for c in self.clips.values() if self.clip_eligibility(c)[0]]


# --------------------------------------------------------------------------------- playback
@dataclass(frozen=True)
class PlaybackSegment:
    label: str
    clip_id: str
    source_key: str
    motion: str
    frames: int  # frames shown (after any trim)
    fps: int
    offset: int  # first source-clip frame shown
    clip_frames: int


@dataclass(frozen=True)
class PlaybackPlan:
    """What the fixture viewer animates. Frames are illustrations of a source, never generated video."""

    title: str
    segments: tuple[PlaybackSegment, ...]

    @property
    def total_frames(self) -> int:
        return sum(s.frames for s in self.segments)

    @property
    def seconds(self) -> float:
        return round(sum(s.frames / s.fps for s in self.segments), 3)

    def locate(self, index: int) -> tuple[int, int, float]:
        """(segment index, local frame, progress 0..1 through the whole source clip)."""
        if not self.segments:
            raise MotionRefused("Nothing to play.")
        index = max(0, min(index, self.total_frames - 1))
        for position, seg in enumerate(self.segments):
            if index < seg.frames:
                return position, index, (seg.offset + index) / max(1, seg.clip_frames - 1)
            index -= seg.frames
        raise AssertionError("unreachable")  # pragma: no cover


def _segment_for(clip: MockClip, *, trim_start: int = 0, trim_end: int = 0) -> PlaybackSegment:
    return PlaybackSegment(
        clip.label, clip.clip_id, clip.source_key, clip.motion,
        max(1, clip.frames - trim_start - trim_end), clip.fps, trim_start, clip.frames,
    )  # fmt: skip


def plan_for_clip(clip: MockClip) -> PlaybackPlan:
    if not clip.completed or not clip.output_available:
        raise MotionRefused(f"{clip.clip_id} has no simulated output to play.")
    return PlaybackPlan(f"{clip.clip_id} · {clip.label}", (_segment_for(clip),))


def plan_for_run(run: MockRun) -> PlaybackPlan:
    clips = [c for c in run.clips if c.completed]
    if not clips:
        raise MotionRefused(f"{run.run_id} produced no playable simulated clip.")
    return PlaybackPlan(f"{run.run_id} · {run.title}", tuple(_segment_for(c) for c in clips))


def plan_for_movie(session: MotionSession, movie: MockMovieResult) -> PlaybackPlan:
    segments = []
    for item in movie.snapshot.items:
        clip = session.clip(item.clip_id)
        segments.append(_segment_for(clip, trim_start=item.trim_start, trim_end=item.trim_end))
    return PlaybackPlan(f"{movie.movie_id} · {movie.title}", tuple(segments))


def camera_window(motion: str, progress: float) -> tuple[float, float, float]:
    """Illustrated camera move: the visible window (x, y, scale) as fractions of the source image."""
    t = min(1.0, max(0.0, progress))
    if motion == "zoom-in":
        scale = 1.0 - 0.28 * t
        return (1 - scale) / 2, (1 - scale) / 2, scale
    if motion == "zoom-out":
        scale = 0.72 + 0.28 * t
        return (1 - scale) / 2, (1 - scale) / 2, scale
    scale = 0.8
    if motion == "pan-left":
        return (1 - scale) * (1 - t), (1 - scale) / 2, scale
    if motion == "tilt-up":
        return (1 - scale) / 2, (1 - scale) * (1 - t), scale
    return (1 - scale) * t, (1 - scale) / 2, scale  # pan-right and any unknown move
