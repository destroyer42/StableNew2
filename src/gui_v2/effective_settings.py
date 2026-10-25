"""Read-only "Effective Settings" projection of compiled preview jobs (PR-GUI-UX-520).

Toolkit-neutral and pure. It reads only the frozen, already-compiled ``NormalizedJobRecord`` objects of the current
Preview, so what it shows is exactly what the queue will receive: there is no second merge of defaults, pack settings
and stage cards here. It never reads the draft, the pack files or the settings folder.

Provenance is stated honestly. A compiled job records the resolved values and the adjustments the compiler reported
(``prompt_adaptation`` operations), not which layer supplied each value, so this view says how the layers combine and
what the working state was loaded from, and does not claim per-field ownership.

Hidden-content mode: LoRA names are asset identities and are replaced by a count; prompt text is never shown.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.gui.view_contracts import config_source_contract as contract
from src.gui_v2.adaptation_notice import compact_adaptation_notice

NO_PREVIEW_TEXT = (
    "No compiled preview yet. Add a PromptPack to the job (or change a setting) and the settings the queued jobs "
    "will use appear here."
)
PER_FIELD_NOTE = (
    "A compiled job records the resolved values, not which layer supplied each one, so this is a summary of the "
    "job itself and not proof of where a value came from."
)
NO_ADJUSTMENTS_TEXT = "The compiler reported no adjustments for the selected model."
_VARIES_SHOWN = 3


@dataclass(frozen=True)
class EffectiveContext:
    """What the GUI knows that a frozen job does not: the override choice and where the working state came from."""

    override_pack_config: bool | None = None
    settings_source: contract.SettingsSource = contract.SettingsSource()
    visible: bool = True  # False in hidden-content mode: asset names are replaced by counts
    #: Selected model and generation profile as the working settings hold them (PR-IMG-PROFILE-630); never a job fact.
    profile_lines: tuple[str, ...] = ()
    #: Why this Preview may no longer match the working settings (the draft was built before a stage/override/profile change).
    draft_notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectiveRow:
    label: str
    value: str


@dataclass(frozen=True)
class EffectiveSettingsView:
    job_count: int
    rows: tuple[EffectiveRow, ...] = ()
    adjustments: tuple[str, ...] = ()
    adjustment_summary: str = ""
    provenance: tuple[str, ...] = ()
    empty_text: str = ""
    profile: tuple[str, ...] = ()
    notices: tuple[str, ...] = ()

    def value_of(self, label: str) -> str | None:
        return next((row.value for row in self.rows if row.label == label), None)

    def as_text(self) -> str:
        head: list[str] = []
        if self.notices:
            head.extend(["Preview may be out of date", *(f"  {item}" for item in self.notices), ""])
        if self.job_count == 0:
            return "\n".join([*head, self.empty_text or NO_PREVIEW_TEXT])
        noun = "job" if self.job_count == 1 else "jobs"
        lines = [*head, f"Effective settings of {self.job_count} compiled {noun}"]
        width = max(len(row.label) for row in self.rows) if self.rows else 0
        lines.extend(f"{row.label.ljust(width)}  {row.value}" for row in self.rows)
        lines.append("")
        lines.append("Compile adjustments")
        lines.extend(f"  {item}" for item in self.adjustments or (NO_ADJUSTMENTS_TEXT,))
        if self.profile:
            lines.append("")
            lines.append("Working model and profile (not part of the compiled jobs)")
            lines.extend(f"  {item}" for item in self.profile)
        lines.append("")
        lines.append("Where the values come from")
        lines.extend(f"  {item}" for item in self.provenance)
        return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ projection


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _first(config: Mapping[str, Any], *keys: str) -> Any:
    txt2img = _mapping(config.get("txt2img"))
    for key in keys:
        for container in (config, txt2img):
            value = container.get(key)
            if value not in (None, ""):
                return value
    return None


def _source_text(job: Any) -> str:
    source = getattr(job, "source", None)
    kind = getattr(getattr(source, "kind", None), "value", getattr(source, "kind", ""))
    name = _text(getattr(source, "display_name", None) or getattr(source, "id", None), "")
    if str(kind) == "prompt_pack":
        row = getattr(source, "row_index", None)
        revision = getattr(source, "revision", None)
        extras = []
        if row is not None:
            extras.append(f"row {int(row) + 1}")
        if revision:
            extras.append(f"revision {revision}")
        return f"PromptPack '{name}'" + (f" ({', '.join(extras)})" if extras else "")
    return f"{str(kind).replace('_', ' ').capitalize() or 'Job'}" + (f" '{name}'" if name else "")


def _seed_text(job: Any, config: Mapping[str, Any]) -> str:
    requested = config.get("seed")
    resolved = getattr(getattr(job, "provenance", None), "seed", None)
    if requested in (None, -1, "-1", ""):
        return "random per image" + (
            f" (this job: {resolved})" if resolved not in (None, -1) else ""
        )
    return f"fixed {requested}"


def _lora_text(job: Any, visible: bool) -> str:
    tags = tuple(getattr(getattr(job, "provenance", None), "lora_tags", ()) or ())
    if not tags:
        return "none"
    if not visible:
        return f"{len(tags)} LoRA(s) (names hidden)"
    return ", ".join(f"{tag.name} @ {tag.weight:g}" for tag in tags)


def _job_rows(job: Any, context: EffectiveContext) -> dict[str, str]:
    config = _mapping(getattr(job, "config", {}))
    pipeline = _mapping(config.get("pipeline"))
    workload = getattr(job, "workload", None)
    stages = [
        str(getattr(stage, "stage_type", ""))
        for stage in getattr(job, "stages", ())
        if getattr(stage, "enabled", False)
    ]
    disabled = [
        str(getattr(stage, "stage_type", "") or "")
        for stage in getattr(job, "stages", ())
        if not getattr(stage, "enabled", False)
    ]
    disabled = [name for name in disabled if name]
    width, height = _first(config, "width"), _first(config, "height")
    sampler, scheduler = _first(config, "sampler_name", "sampler"), _first(config, "scheduler")
    per_prompt = int(getattr(workload, "images_per_prompt", 1) or 1)
    loops = int(getattr(workload, "loop_count", 1) or 1)
    output_plan = getattr(job, "output_plan", None)
    route = getattr(output_plan, "route", None)
    return {
        "Source": _source_text(job),
        "Model": _text(_first(config, "model", "model_name")),
        "Stages": " + ".join(stages) if stages else "-",
        "Stages off": ", ".join(disabled) if disabled else "none",
        "Size": f"{width} x {height}" if width and height else "-",
        "Sampler": f"{_text(sampler)} / {_text(scheduler)}",
        "Steps": _text(_first(config, "steps")),
        "CFG": _text(_first(config, "cfg_scale")),
        "Images": f"{per_prompt} per prompt x {loops} batch run(s)",
        "Seed": _seed_text(job, config),
        "LoRAs": _lora_text(job, context.visible),
        "Output folder": _text(
            getattr(output_plan, "base_output_dir", None) or pipeline.get("output_dir")
        ),
        "Output format": _text(pipeline.get("image_format"), "default"),
        "Output route": _text(route, "auto"),
    }


def _merge_rows(per_job: Sequence[dict[str, str]]) -> tuple[EffectiveRow, ...]:
    rows: list[EffectiveRow] = []
    for label in per_job[0]:
        values = list(dict.fromkeys(item.get(label, "-") for item in per_job))
        if len(values) == 1:
            rows.append(EffectiveRow(label, values[0]))
            continue
        shown = "; ".join(values[:_VARIES_SHOWN])
        extra = len(values) - _VARIES_SHOWN
        rows.append(
            EffectiveRow(
                label, f"varies across jobs: {shown}" + (f"; +{extra} more" if extra > 0 else "")
            )
        )
    return tuple(rows)


def _adjustments(jobs: Sequence[Any], context: EffectiveContext) -> tuple[tuple[str, ...], str]:
    lines: list[str] = []
    manifests: list[Mapping[str, Any]] = []
    for job in jobs:
        metadata = _mapping(getattr(getattr(job, "provenance", None), "metadata", {}))
        manifest = _mapping(metadata.get("prompt_adaptation"))
        manifests.append(manifest)
        for operation in manifest.get("operations") or ():
            operation = _mapping(operation)
            if operation.get("code") != "profile_value_normalized":
                continue
            details = _mapping(operation.get("details"))
            setting = _text(details.get("setting"), "")
            if not setting:
                continue
            if details.get("cleared"):
                line = f"{setting}: cleared for this model"
            else:
                line = f"{setting}: {_text(details.get('from'))} -> {_text(details.get('to'))} (model profile value)"
            if line not in lines:
                lines.append(line)
    summary = next(
        (note for note in (compact_adaptation_notice(item) for item in manifests) if note), ""
    )
    return tuple(lines), summary


def _provenance(jobs: Sequence[Any], context: EffectiveContext) -> tuple[str, ...]:
    from_pack = any(
        str(getattr(getattr(getattr(job, "source", None), "kind", None), "value", ""))
        == "prompt_pack"
        for job in jobs
    )
    lines = [
        "Resolved in this order: code defaults, then the PromptPack's saved settings, then the job's stage-card snapshot."
        if from_pack
        else "Resolved in this order: code defaults, then the job's stage-card snapshot."
    ]
    if context.override_pack_config is not None:
        lines.append(contract.override_description(context.override_pack_config))
    lines.append(context.settings_source.describe() + ". Edits after loading are not tracked.")
    lines.append(
        "Model adjustments change the compiled job only; the saved PromptPack files are not rewritten."
    )
    lines.append(PER_FIELD_NOTE)
    return tuple(lines)


def project_effective_settings(
    jobs: Sequence[Any] | None, context: EffectiveContext | None = None
) -> EffectiveSettingsView:
    """Project the current Preview's compiled jobs. ``None`` or an empty list gives the explained empty state."""

    context = context or EffectiveContext()
    records = [job for job in (jobs or ()) if hasattr(job, "stages") and hasattr(job, "source")]
    if not records:
        return EffectiveSettingsView(
            job_count=0, empty_text=NO_PREVIEW_TEXT, notices=tuple(context.draft_notices)
        )
    adjustments, summary = _adjustments(records, context)
    return EffectiveSettingsView(
        job_count=len(records),
        rows=_merge_rows([_job_rows(job, context) for job in records]),
        adjustments=adjustments,
        adjustment_summary=summary,
        provenance=_provenance(records, context),
        profile=tuple(context.profile_lines),
        notices=tuple(context.draft_notices),
    )


__all__ = [
    "EffectiveContext",
    "EffectiveRow",
    "EffectiveSettingsView",
    "NO_PREVIEW_TEXT",
    "PER_FIELD_NOTE",
    "project_effective_settings",
]
