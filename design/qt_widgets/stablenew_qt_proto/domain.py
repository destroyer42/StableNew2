"""Pure-Python, in-memory fixtures for a non-executing Create workflow.

This module knows nothing about StableNew production queues, NJRs, backends,
filesystems, GUI toolkits, networks, subprocesses, or persistent application state.
The names and model profiles below are DEMONSTRATION fixtures, not qualified
settings or compatibility claims for installed Stable Diffusion models.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import re
from typing import Any

PROFILE_DEFAULT = "Model default (fixture)"
PROFILE_LEARNING = "Learning-informed (fixture)"
PROFILES = (PROFILE_DEFAULT, PROFILE_LEARNING)

SAMPLERS = ("DPM++ 2M", "Euler", "Euler a", "DDIM")
SCHEDULERS = ("Karras", "Simple", "Normal")

# Numeric limits shared by validation and the Qt editors (single source).
SETTING_RANGES: dict[str, tuple[float, float]] = {
    "steps": (1, 150),
    "cfg": (0.0, 30.0),
    "width": (256, 4096),
    "height": (256, 4096),
    "seed": (-1, 2_147_483_647),
    "batch": (1, 16),
}
SETTING_LABELS = {
    "sampler": "Sampler",
    "scheduler": "Scheduler",
    "steps": "Steps",
    "cfg": "CFG",
    "width": "Width",
    "height": "Height",
    "seed": "Seed",
    "batch": "Batch count",
}

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SLOT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Settings:
    sampler: str
    scheduler: str
    steps: int
    cfg: float
    width: int
    height: int
    seed: int = -1  # -1 means "random" in this demonstration
    batch: int = 1


@dataclass(frozen=True)
class ModelFixture:
    key: str
    label: str
    settings: Settings
    allows_negative: bool
    characterized_sizes: tuple[tuple[int, int], ...]


MODELS: tuple[ModelFixture, ...] = (
    ModelFixture(
        key="fixture-sdxl",
        label="SDXL example (unqualified fixture)",
        settings=Settings("DPM++ 2M", "Karras", 28, 7.0, 1024, 1024),
        allows_negative=True,
        characterized_sizes=((1024, 1024), (832, 1216)),
    ),
    ModelFixture(
        key="fixture-flux",
        label="Flux example (unqualified fixture)",
        settings=Settings("Euler", "Simple", 8, 1.0, 1024, 1024),
        allows_negative=False,
        characterized_sizes=((1024, 1024), (768, 1360)),
    ),
)
MODEL_BY_KEY = {model.key: model for model in MODELS}
SETTING_FIELDS = tuple(Settings.__dataclass_fields__.keys())

# Settings an operator edits in ordinary use vs. optional overrides disclosed under Advanced.
BASIC_SETTINGS = ("steps", "cfg", "seed", "batch")
ADVANCED_SETTINGS = ("sampler", "scheduler", "width", "height")

SOURCE_FREE = "free"


@dataclass(frozen=True)
class PackFixture:
    """A fictional PromptPack used to demonstrate source selection. Not a real pack or schema."""

    key: str
    label: str
    pack_name: str
    prompt: str
    negative: str
    slots: tuple[tuple[str, str], ...]


PACKS: tuple[PackFixture, ...] = (
    PackFixture(
        "pack-portraits", "Explorer portraits (fixture pack)", "Explorer portraits",
        "A cinematic portrait of an imaginary {subject}, detailed eyes, {lighting}",
        "low detail, distorted anatomy",
        (("subject", "explorer"), ("lighting", "soft daylight")),
    ),
    PackFixture(
        "pack-landscapes", "Landscape studies (fixture pack)", "Landscape studies",
        "A wide landscape of {terrain} at {time_of_day}, {mood} atmosphere",
        "",
        (("terrain", "mountains"), ("time_of_day", "dawn"), ("mood", "calm")),
    ),
)
PACK_BY_KEY = {pack.key: pack for pack in PACKS}

# Illustrative "Learning-informed" deltas. Not evidence of any real profile.
PROFILE_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("fixture-sdxl", PROFILE_LEARNING): {"steps": 32, "cfg": 6.5},
    ("fixture-flux", PROFILE_LEARNING): {"steps": 10},
}


def recommended_settings(model_key: str, profile: str) -> Settings:
    """Fixture recommendation for a model/profile pair (no real metadata)."""
    model = MODEL_BY_KEY[model_key]
    return replace(model.settings, **PROFILE_OVERRIDES.get((model_key, profile), {}))


def format_setting(name: str, value: Any) -> str:
    if name == "seed":
        return "Random" if value == -1 else str(value)
    if name == "cfg":
        return f"{value:g}"
    return str(value)


def expand_prompt(text: str, slots: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    """Resolve ``{slot}`` placeholders; return (resolved text, unresolved names)."""
    unresolved: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in slots:
            return slots[key]
        if key not in unresolved:
            unresolved.append(key)
        return match.group(0)

    return _PLACEHOLDER.sub(_sub, text), tuple(unresolved)


def referenced_slots(*texts: str) -> set[str]:
    found: set[str] = set()
    for text in texts:
        found.update(_PLACEHOLDER.findall(text))
    return found


@dataclass(frozen=True)
class Preview:
    """A frozen *display-only* summary, not an NJR or admission authorization."""

    fingerprint: str
    revision: int
    text: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return not self.errors


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> tuple[str, ...]:
    """Dotted names of draft fields that differ between two ``stable_data`` snapshots."""
    old, new = _flatten(before), _flatten(after)
    return tuple(sorted(key for key in {*old, *new} if old.get(key) != new.get(key)))


@dataclass(frozen=True)
class ResultTile:
    """One placeholder entry in the mock result gallery (never a real image)."""

    index: int
    label: str
    size: str
    seed: str


@dataclass(frozen=True)
class DemoReceipt:
    """In-memory UI demonstration receipt. Never a real queue/job identity."""

    revision: int
    preview_fingerprint: str
    message: str = "DEMO ONLY: No job submitted and no image generated."
    tiles: tuple[ResultTile, ...] = ()


@dataclass
class CreateDraft:
    source_key: str = SOURCE_FREE
    pack_name: str = "Untitled exploration"
    prompt: str = "A cinematic portrait of an imaginary {subject}, detailed eyes, {lighting}"
    negative: str = "low detail, distorted anatomy"
    slots: dict[str, str] = field(default_factory=lambda: {"subject": "explorer", "lighting": "soft daylight"})
    global_prompt: str = ""
    adetailer_prompt: str = ""
    adetailer_enabled: bool = False
    loras: str = ""
    embeddings: str = ""
    model_key: str = "fixture-sdxl"
    profile_source: str = PROFILE_DEFAULT
    settings: Settings = field(default_factory=lambda: MODELS[0].settings)
    locked_fields: set[str] = field(default_factory=set)
    manual_fields: set[str] = field(default_factory=set)

    def clone(self) -> "CreateDraft":
        return replace(
            self,
            slots=dict(self.slots),
            locked_fields=set(self.locked_fields),
            manual_fields=set(self.manual_fields),
        )

    def stable_data(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "pack_name": self.pack_name,
            "prompt": self.prompt,
            "negative": self.negative,
            "slots": dict(sorted(self.slots.items())),
            "global_prompt": self.global_prompt,
            "adetailer_prompt": self.adetailer_prompt,
            "adetailer_enabled": self.adetailer_enabled,
            "loras": self.loras,
            "embeddings": self.embeddings,
            "model_key": self.model_key,
            "profile_source": self.profile_source,
            "settings": asdict(self.settings),
            "locked_fields": sorted(self.locked_fields),
            "manual_fields": sorted(self.manual_fields),
        }

    def fingerprint(self) -> str:
        serialized = json.dumps(self.stable_data(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


_TEXT_FIELDS = {"pack_name", "prompt", "negative", "global_prompt", "adetailer_prompt", "loras", "embeddings"}
_UNDO_LIMIT = 100
_LOG_LIMIT = 200


class CreateSession:
    """Mutable *local-only* intent for UI exploration.

    Does not persist, compile, enqueue, run, discover backends, or access real media.
    Provides in-memory undo/redo and a change log; neither is written anywhere.
    """

    def __init__(self) -> None:
        self.draft = CreateDraft()
        self.revision = 0
        self.preview: Preview | None = None
        self.demo_receipt: DemoReceipt | None = None
        self.change_notes: tuple[str, ...] = ()
        self._log: list[tuple[int, str]] = []
        self._undo: list[CreateDraft] = []
        self._redo: list[CreateDraft] = []
        self._committed = self.draft.clone()
        self._last_key: str | None = None

    # ------------------------------------------------------------------ state
    def _changed(self, notes: tuple[str, ...] = (), key: str | None = None) -> None:
        """Record a mutation. Consecutive changes with the same ``key`` coalesce
        into one undo step (so typing a word is a single undo)."""
        self.revision += 1
        self.change_notes = notes
        self.demo_receipt = None
        for note in notes:
            self._log.append((self.revision, note))
        del self._log[:-_LOG_LIMIT]
        if key is None or key != self._last_key:
            self._undo.append(self._committed)
            del self._undo[:-_UNDO_LIMIT]
        self._committed = self.draft.clone()
        self._last_key = key
        self._redo.clear()

    @property
    def change_log(self) -> tuple[tuple[int, str], ...]:
        return tuple(self._log)

    @property
    def recommended(self) -> Settings:
        return recommended_settings(self.draft.model_key, self.draft.profile_source)

    def differs_from_recommended(self, name: str) -> bool:
        return getattr(self.draft.settings, name) != getattr(self.recommended, name)

    def setting_origin(self, name: str) -> str:
        """Why a setting has its value: ``locked``, ``manual`` override, or ``recommended``."""
        if name in self.draft.locked_fields:
            return "locked"
        if name in self.draft.manual_fields:
            return "manual"
        return "recommended"

    @property
    def pack_modified(self) -> bool:
        """True when a fixture pack is the source but the working draft no longer matches it."""
        pack = PACK_BY_KEY.get(self.draft.source_key)
        if pack is None:
            return False
        d = self.draft
        return (d.prompt, d.negative, d.slots) != (pack.prompt, pack.negative, dict(pack.slots))

    @property
    def source_label(self) -> str:
        pack = PACK_BY_KEY.get(self.draft.source_key)
        if pack is None:
            return "Free prompt · unsaved working draft"
        return f"{pack.label} · " + ("modified, unsaved working edits" if self.pack_modified else "unmodified")

    def stale_reasons(self) -> tuple[str, ...]:
        """Which draft fields changed since the preview was built (empty if current or no preview)."""
        if self.preview is None or self.is_preview_current:
            return ()
        changed = changed_fields(self.preview.data, self.draft.stable_data())
        if any(name.startswith("settings.") for name in changed):
            changed = tuple(name for name in changed if name != "manual_fields")  # derived from the setting edit
        return tuple("locks" if n == "locked_fields" else "overrides" if n == "manual_fields" else n for n in changed)

    @property
    def is_preview_current(self) -> bool:
        return self.preview is not None and self.preview.fingerprint == self.draft.fingerprint()

    @property
    def can_simulate_admission(self) -> bool:
        return self.is_preview_current and self.preview is not None and self.preview.ready

    # ------------------------------------------------------------- undo/redo
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _restore(self, draft: CreateDraft, note: str) -> None:
        self.draft = draft.clone()
        self._committed = draft.clone()
        self._last_key = None
        self.revision += 1
        self.demo_receipt = None
        self.change_notes = (note,)
        self._log.append((self.revision, note))
        del self._log[:-_LOG_LIMIT]

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._committed)
        self._restore(self._undo.pop(), "Undo: restored the previous draft state.")
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._committed)
        self._restore(self._redo.pop(), "Redo: re-applied the undone draft state.")
        return True

    # ------------------------------------------------------------- mutations
    def set_text(self, field_name: str, value: str) -> None:
        if field_name not in _TEXT_FIELDS:
            raise ValueError(f"Unknown text field: {field_name}")
        if getattr(self.draft, field_name) != value:
            setattr(self.draft, field_name, value)
            self._changed(key=f"text:{field_name}")

    def set_slot(self, name: str, value: str) -> None:
        name = name.strip()
        if not name or len(name) > 64:
            raise ValueError("Slot name must be between 1 and 64 characters")
        if self.draft.slots.get(name) != value:
            self.draft.slots[name] = value
            self._changed()

    def replace_slots(self, slots: dict[str, str]) -> None:
        cleaned = {key.strip(): value for key, value in slots.items() if key.strip()}
        if any(len(key) > 64 for key in cleaned):
            raise ValueError("Slot names must be at most 64 characters")
        if cleaned != self.draft.slots:
            self.draft.slots = cleaned
            self._changed(("PromptPack slot table changed in mock draft.",), key="slots")

    def remove_slot(self, name: str) -> None:
        if name in self.draft.slots:
            del self.draft.slots[name]
            self._changed((f"Removed slot '{name}'.",))

    def select_source(self, key: str) -> None:
        """Choose the prompt source: a fixture PromptPack (loads its template) or a free prompt."""
        if key != SOURCE_FREE and key not in PACK_BY_KEY:
            raise ValueError(f"Unknown prompt source: {key}")
        if key == self.draft.source_key:
            return
        if key == SOURCE_FREE:
            self.draft.source_key = key
            self._changed(("Prompt source set to a free prompt; the working text was kept.",))
            return
        pack = PACK_BY_KEY[key]
        self.draft.source_key = key
        self.draft.pack_name, self.draft.prompt, self.draft.negative = pack.pack_name, pack.prompt, pack.negative
        self.draft.slots = dict(pack.slots)
        self._changed((f"Loaded fixture {pack.label}: prompt, negative prompt and slots replaced (undo available).",))

    def set_adetailer_enabled(self, enabled: bool) -> None:
        if self.draft.adetailer_enabled != enabled:
            self.draft.adetailer_enabled = enabled
            self._changed()

    def toggle_lock(self, name: str, locked: bool) -> None:
        if name not in SETTING_FIELDS:
            raise ValueError(f"Unknown setting: {name}")
        next_locks = self.draft.locked_fields | {name} if locked else self.draft.locked_fields - {name}
        if next_locks != self.draft.locked_fields:
            self.draft.locked_fields = next_locks
            self._changed((f"{SETTING_LABELS[name]} {'locked' if locked else 'unlocked'} in this draft only.",))

    def _apply_settings(self, **values: Any) -> None:
        """Set one or more settings as a manual edit (single revision)."""
        for name in values:
            if name not in SETTING_FIELDS:
                raise ValueError(f"Unknown setting: {name}")
        self.draft.settings = replace(self.draft.settings, **values)
        rec = self.recommended
        for name in values:
            if getattr(self.draft.settings, name) == getattr(rec, name):
                self.draft.manual_fields.discard(name)  # back to the recommendation
            else:
                self.draft.manual_fields.add(name)

    def set_setting(self, name: str, value: Any) -> None:
        if name not in SETTING_FIELDS:
            raise ValueError(f"Unknown setting: {name}")
        if getattr(self.draft.settings, name) != value:
            self._apply_settings(**{name: value})
            self._changed((f"{SETTING_LABELS[name]} set to {format_setting(name, value)}.",), key=f"set:{name}")

    def apply_size(self, width: int, height: int) -> None:
        s = self.draft.settings
        if (s.width, s.height) != (width, height):
            self._apply_settings(width=width, height=height)
            self._changed((f"Size set to {width} × {height}.",))

    def reset_setting(self, name: str) -> None:
        """Explicitly return one setting to the fixture recommendation."""
        if name not in SETTING_FIELDS:
            raise ValueError(f"Unknown setting: {name}")
        rec = getattr(self.recommended, name)
        if getattr(self.draft.settings, name) != rec:
            self.draft.settings = replace(self.draft.settings, **{name: rec})
            self.draft.manual_fields.discard(name)
            self._changed((f"{SETTING_LABELS[name]} reset to recommended {format_setting(name, rec)}.",))

    def reset_unlocked_settings(self) -> None:
        rec = self.recommended
        values = {
            n: getattr(rec, n)
            for n in SETTING_FIELDS
            if n not in self.draft.locked_fields and getattr(self.draft.settings, n) != getattr(rec, n)
        }
        if values:
            self.draft.settings = replace(self.draft.settings, **values)
            self.draft.manual_fields -= set(values)
            names = ", ".join(SETTING_LABELS[n] for n in values)
            self._changed((f"Reset unlocked settings to recommended: {names}.",))

    def _rebase(self, model_key: str, profile: str, headline: str) -> list[str]:
        """Move to a new model/profile recommendation, protecting locks and manual edits."""
        incoming = recommended_settings(model_key, profile)
        protected = self.draft.locked_fields | self.draft.manual_fields
        updated: dict[str, Any] = {}
        notes = [headline]
        for name in SETTING_FIELDS:
            current = getattr(self.draft.settings, name)
            recommended = getattr(incoming, name)
            label = SETTING_LABELS[name]
            if name in protected:
                updated[name] = current
                if current != recommended:
                    reason = "locked" if name in self.draft.locked_fields else "manually overridden"
                    notes.append(
                        f"Preserved {reason} {label.lower()}: {format_setting(name, current)} "
                        f"(fixture proposes {format_setting(name, recommended)})."
                    )
                else:
                    self.draft.manual_fields.discard(name)
            else:
                updated[name] = recommended
                if current != recommended:
                    notes.append(
                        f"Suggested {label.lower()} changed: "
                        f"{format_setting(name, current)} → {format_setting(name, recommended)}."
                    )
        self.draft.settings = Settings(**updated)
        self.draft.model_key = model_key
        self.draft.profile_source = profile
        return notes

    def switch_model(self, key: str) -> None:
        if key not in MODEL_BY_KEY:
            raise ValueError(f"Unknown fixture: {key}")
        if self.draft.model_key == key:
            return
        incoming = MODEL_BY_KEY[key]
        notes = self._rebase(key, self.draft.profile_source, f"Changed model fixture to {incoming.label}.")
        if self.draft.negative.strip() and not incoming.allows_negative:
            notes.append("Negative prompt is unsupported by this DEMO fixture; edit it before a ready preview.")
        self._changed(tuple(notes))

    def set_profile_source(self, source: str) -> None:
        if source not in PROFILES:
            raise ValueError("Unknown profile source")
        if source == self.draft.profile_source:
            return
        notes = self._rebase(
            self.draft.model_key,
            source,
            "Profile source changed in this demonstration; no real learned profile was loaded.",
        )
        self._changed(tuple(notes))

    # ------------------------------------------------------------ validation
    def validation(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        d = self.draft
        model = MODEL_BY_KEY[d.model_key]
        s = d.settings
        errors: list[str] = []
        warnings: list[str] = []
        resolved, unresolved = expand_prompt(d.prompt, d.slots)
        if not resolved.strip():
            errors.append("Prompt is empty. Supply a prompt before previewing.")
        if s.sampler not in SAMPLERS:
            errors.append(f"Sampler '{s.sampler}' is not in this fixture's sampler list.")
        if s.scheduler not in SCHEDULERS:
            errors.append(f"Scheduler '{s.scheduler}' is not in this fixture's scheduler list.")
        for name, (low, high) in SETTING_RANGES.items():
            value = getattr(s, name)
            if not low <= value <= high:
                errors.append(f"{SETTING_LABELS[name]} must be between {low:g} and {high:g}.")
        if d.negative.strip() and not model.allows_negative:
            errors.append("This fictional model fixture does not accept a negative prompt; no automatic deletion was performed.")
        if (s.width, s.height) not in model.characterized_sizes:
            warnings.append("This size is outside the fixture's illustrative characterization; treat it as unverified, not proven incompatible.")
        if d.profile_source.startswith("Learning"):
            warnings.append("Learning-informed selection is a UI fixture, not evidence of an existing qualified profile.")
        if self.pack_modified:
            warnings.append("Working edits differ from the fixture pack; nothing is saved to any pack store.")
        if d.locked_fields:
            warnings.append("Draft-only locks: " + ", ".join(sorted(d.locked_fields)))
        all_unresolved = list(unresolved)
        for text in (d.negative, d.global_prompt, d.adetailer_prompt):
            for name in expand_prompt(text, d.slots)[1]:
                if name not in all_unresolved:
                    all_unresolved.append(name)
        if all_unresolved:
            warnings.append("Unresolved placeholders will appear literally: " + ", ".join("{" + n + "}" for n in all_unresolved))
        unused = sorted(set(d.slots) - referenced_slots(d.prompt, d.negative, d.global_prompt, d.adetailer_prompt))
        if unused:
            warnings.append("Slots defined but not referenced by any prompt: " + ", ".join(unused))
        bad_names = sorted(name for name in d.slots if not _SLOT_NAME.match(name))
        if bad_names:
            warnings.append("Slot names that cannot be used as {placeholders}: " + ", ".join(repr(n) for n in bad_names))
        return tuple(errors), tuple(warnings)

    def build_preview(self) -> Preview:
        errors, warnings = self.validation()
        d = self.draft
        model = MODEL_BY_KEY[d.model_key]
        resolved = expand_prompt(d.prompt, d.slots)[0]
        diffs = [
            f"  {SETTING_LABELS[n]}: {format_setting(n, getattr(d.settings, n))} "
            f"(recommended {format_setting(n, getattr(self.recommended, n))})"
            for n in SETTING_FIELDS
            if self.differs_from_recommended(n)
        ]
        lines = [
            "MOCK PREVIEW — NOT AN NJR OR EXECUTION APPROVAL",
            "",
            f"Source: {self.source_label}",
            f"Pack: {d.pack_name or '(unsaved draft)'}",
            f"Model: {model.label}",
            f"Profile: {d.profile_source}",
            f"Prompt template: {d.prompt}",
            f"Prompt resolved: {resolved}",
            f"Negative: {d.negative or '(none)'}",
            "PromptPack slots: " + (", ".join(f"{k}={v}" for k, v in d.slots.items()) or "(none)"),
            f"Sampler / scheduler: {d.settings.sampler} / {d.settings.scheduler}",
            f"Steps / CFG: {d.settings.steps} / {d.settings.cfg:g}",
            f"Size: {d.settings.width} × {d.settings.height}",
            f"Seed / batch: {format_setting('seed', d.settings.seed)} / {d.settings.batch}",
            f"Global prompt: {d.global_prompt or '(none)'}",
            f"ADetailer: {'ON — ' + (d.adetailer_prompt or '(no prompt)') if d.adetailer_enabled else 'off'}",
            f"LoRA notes: {d.loras or '(none)'}",
            f"Embedding notes: {d.embeddings or '(none)'}",
            "",
            "Differs from recommended settings:" + ("" if diffs else " (none)"),
            *diffs,
            "",
            "No model validation, pack compilation, randomization or generation is performed.",
        ]
        self.preview = Preview(d.fingerprint(), self.revision, "\n".join(lines), errors, warnings, d.stable_data())
        self.demo_receipt = None
        return self.preview

    def simulate_admission(self) -> DemoReceipt:
        if not self.can_simulate_admission:
            raise RuntimeError("Preview is missing, stale, or contains an invalid DEMO condition")
        assert self.preview is not None
        s = self.draft.settings
        tiles = tuple(
            ResultTile(
                index=i + 1,
                label=f"MOCK IMAGE {i + 1} OF {s.batch}",
                size=f"{s.width} × {s.height}",
                seed="random at run time" if s.seed == -1 else str(s.seed + i),
            )
            for i in range(s.batch)
        )
        self.demo_receipt = DemoReceipt(self.revision, self.preview.fingerprint, tiles=tiles)
        return self.demo_receipt

    def reset(self) -> None:
        """Return to the default demo draft. Undoable; nothing is persisted."""
        self.draft = CreateDraft()
        self.preview = None
        self._changed(("Demo draft reset. Nothing was saved or queued (undo is available).",))
