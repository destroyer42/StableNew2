"""Controlled textual-inversion experiments: one designated embedding position varies, every other input is frozen.

Toolkit-neutral Learning contract ``learning_embedding/1``. The canonical PromptPack intent, target adaptation and
rendering (``resolution_layer``) stay authoritative; this module only decides *which structured embedding
contribution* each candidate holds, refuses anything it cannot prove is a one-position change, and later classifies
the observed prompt and any backend report. Asset identity comes from an injected resolver over the existing
``AssetRegistry`` (``embedding_inventory``); nothing here scans, hashes, writes, deserializes a model file or imports
a toolkit.

Three claims are kept apart everywhere (never merged into one flag):

* **requested** - the frozen design (intent only);
* **request verified** - the executed prompts equal the frozen expectation (the invocation reached the boundary);
* **consumption reported** - the backend's own report names exactly the expected embeddings (identity by name only:
  Forge Neo reports names, not hashes, and never states the attention weight it applied).
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.image_backends.image_backend_types import (
    FORGE_IMAGE_BACKEND_ID,
    normalize_image_backend_options,
)
from src.image_backends.model_policy import (
    DIALECT_WEIGHTED_TAGS,
    EVIDENCE_REGISTRY,
    ModelPolicy,
    Support,
)
from src.learning.prompt_slot_experiment import (
    digest,
    expected_execution_prompts,
    slots_in,
)
from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import (
    adapt_pack_intent,
    pack_prompt_intent_to_dict,
    render_pack_intent,
    resolve_pack_intent,
    substitute_matrix_tokens,
)
from src.utils.embedding_prompt_utils import (
    extract_embedding_entries,
    is_invocable_embedding_name,
    render_embedding_invocation,
)
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

STUDY_TYPE = "embedding_experiment"
CONTRACT = "learning_embedding/1"
VARIABLE = "Embedding"
PRESENCE = "presence"
WEIGHT = "weight"
IDENTITY = "identity"
OPERATIONS = (PRESENCE, WEIGHT, IDENTITY)
OPERATION_LABELS = {PRESENCE: "Presence", WEIGHT: "Weight", IDENTITY: "Identity"}
POSITIVE = "positive"
NEGATIVE = "negative"
CHANNELS = (POSITIVE, NEGATIVE)
CHANNEL_LABELS = {POSITIVE: "Positive prompt", NEGATIVE: "Negative prompt"}
#: Prompt-attention ceiling for a tested embedding; zero is absence, never a zero-weight invocation.
MAX_WEIGHT = 1.5

STATUS_COMPATIBLE = "compatible"
STATUS_UNVERIFIED = "unverified"
STATUS_INCOMPATIBLE = "incompatible"
STATUS_MISSING = "missing"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_STALE = "stale"

CONSUMPTION_REQUEST_ONLY = "request_verified_consumption_unverified"
CONSUMPTION_REPORTED = "consumption_reported_by_name"
CONSUMPTION_CONTRADICTED = "consumption_contradicted"
CONSUMPTION_LABELS = {
    CONSUMPTION_REQUEST_ONLY: "Embedding request verified; actual consumption unverified",
    CONSUMPTION_REPORTED: "Backend reported using exactly the expected embeddings (by name; weight not reported)",
    CONSUMPTION_CONTRADICTED: "Backend report contradicts the expected embeddings",
}

EVIDENCE_LIMITS = (
    "Verified: the frozen canonical embedding intent, the observed final prompt readback and registry asset "
    "identity. Weight is ordinary prompt attention on the embedding token, not an embedding multiplier. The "
    "pinned backend reports used embedding names but neither their hashes nor the applied weight, so consumption "
    "is at most reported by name, and without that report only the request is verified."
)

_ASSET_PHRASES = {
    STATUS_MISSING: "was not found in the local asset registry",
    STATUS_AMBIGUOUS: "is ambiguous: its name matches more than one local file",
    STATUS_INCOMPATIBLE: "cannot be used with the target model and backend",
    STATUS_STALE: "changed on disk since the last verified inventory",
    STATUS_UNVERIFIED: "has unverified compatibility (no safe structural evidence for the target model)",
}


def _key(name: str) -> str:
    return str(name).strip().casefold()


def _sanitized(name: str) -> str:
    """The name as Forge records it in its ``TI`` report (``:`` and ``,`` removed)."""
    return str(name).replace(":", "").replace(",", "").strip().casefold()


@dataclass(frozen=True)
class EmbeddingAsset:
    """Path-free identity and compatibility evidence for one named textual inversion."""

    name: str
    status: str
    sha256: str = ""
    family: str = ""
    structure: str = ""
    file_format: str = ""
    vectors: int | None = None
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.status == STATUS_COMPATIBLE

    @property
    def identified(self) -> bool:
        return bool(re.fullmatch(r"[0-9a-f]{64}", self.sha256 or ""))

    def facts(self) -> dict[str, bool]:
        """The separate claims a registry entry can and cannot support (consumption is never one of them here)."""
        return {
            "installed": self.status not in (STATUS_MISSING, STATUS_AMBIGUOUS),
            "identified": self.identified,
            "structurally_readable": bool(self.structure),
            "compatible_with_target": self.status == STATUS_COMPATIBLE,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "sha256": self.sha256,
            "family": self.family,
            "structure": self.structure,
            "file_format": self.file_format,
            "vectors": self.vectors,
        }


AssetResolver = Callable[[str], EmbeddingAsset]


def canonical_weight(value: Any) -> float:
    try:
        weight = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Embedding weight must be a number.") from exc
    if not math.isfinite(weight) or weight < 0 or weight > MAX_WEIGHT:
        raise ValueError(f"Embedding weight must be between 0 and {MAX_WEIGHT:g}.")
    return round(weight, 2)


@dataclass(frozen=True)
class Candidate:
    """One assignment to the tested position; ``name`` None (or weight 0) means the position is empty."""

    name: str | None
    weight: float = 0.0

    def __post_init__(self) -> None:
        weight = canonical_weight(self.weight)
        name = str(self.name).strip() if self.name is not None else ""
        if not name or weight == 0:
            name, weight = "", 0.0
        object.__setattr__(self, "name", name or None)
        object.__setattr__(self, "weight", weight)

    @property
    def text(self) -> str:
        return "No embedding" if self.name is None else f"{self.name} @ {self.weight:g}"


@dataclass(frozen=True)
class EmbeddingDesign:
    operation: str
    channel: str
    prompt: str
    candidates: tuple[Candidate, ...]
    original: str | None = None
    images_per_candidate: int = 1
    #: Explicit, fixed resolution of any Matrix slots in the source; never an experimental axis.
    fixed_slots: Mapping[str, str] = field(default_factory=dict)


def candidates_from_spec(spec: Sequence[Mapping[str, Any]]) -> tuple[Candidate, ...]:
    return tuple(Candidate(item.get("name"), item.get("weight") or 0.0) for item in spec)


def design_from_spec(spec: Mapping[str, Any], prompt: str, images: int) -> EmbeddingDesign:
    return EmbeddingDesign(
        str(spec.get("operation") or ""),
        str(spec.get("channel") or ""),
        prompt,
        candidates_from_spec(spec.get("candidates") or ()),
        str(spec["original"]).strip() if spec.get("original") else None,
        images,
        dict(spec.get("fixed_slots") or {}),
    )


def validate_bounds(design: EmbeddingDesign) -> None:
    if design.channel not in CHANNELS:
        raise ValueError("Choose the positive or the negative prompt as the tested channel.")
    if not 2 <= len(design.candidates) <= 8:
        raise ValueError("Choose two to eight distinct candidates; none were truncated.")
    images = design.images_per_candidate
    if isinstance(images, bool) or not isinstance(images, int) or not 1 <= images <= 3:
        raise ValueError("Choose one to three images per candidate (at most 24 images).")
    seen: dict[tuple[str, float], Candidate] = {}
    for candidate in design.candidates:
        identity = (_key(candidate.name or ""), candidate.weight)
        if identity in seen:
            raise ValueError(
                "Candidates must be distinct at two-decimal weight precision; zero weight is the same as "
                f"No embedding ('{candidate.text}' repeats an earlier candidate)."
            )
        seen[identity] = candidate


def validate_operation(design: EmbeddingDesign) -> None:
    present = [c for c in design.candidates if c.name]
    absent = [c for c in design.candidates if c.name is None]
    names = {_key(c.name) for c in present if c.name}
    original = _key(design.original) if design.original else ""
    if design.operation == PRESENCE:
        if len(design.candidates) != 2 or len(absent) != 1 or len(present) != 1:
            raise ValueError(
                "Presence compares exactly two states: No embedding and the embedding present; use Weight "
                "for several weights."
            )
    elif design.operation == WEIGHT:
        if len(names) != 1:
            raise ValueError(
                "Weight tests one embedding at different weights; choose exactly one embedding."
            )
        if len(present) < 1:
            raise ValueError("Weight requires at least one present weight.")
    elif design.operation == IDENTITY:
        if len(names) < 2:
            raise ValueError(
                "Identity compares at least two different embeddings at one common weight."
            )
        if len(absent) > 1:
            raise ValueError("Identity allows at most one No embedding control.")
        if len({c.weight for c in present}) > 1:
            raise ValueError(
                "Identity candidates must use the same weight to isolate the embedding; use Weight for "
                "different weights."
            )
    else:
        raise ValueError("Choose Presence, Weight or Identity.")
    if original and original not in names:
        raise ValueError("The designated original embedding must be one of the tested embeddings.")
    bad = next(
        (c.name for c in present if c.name and not is_invocable_embedding_name(c.name)), None
    )
    if bad:
        raise ValueError(
            f"Embedding '{bad}' contains prompt syntax characters and cannot be invoked by name."
        )


def validation_error(spec: Mapping[str, Any], prompt: str, images: int) -> str:
    """The first design-shape refusal ("" when the shape is valid); baseline-dependent checks happen at Preview."""
    try:
        design = design_from_spec(spec, prompt, images)
        validate_bounds(design)
        validate_operation(design)
    except (TypeError, ValueError) as exc:
        return str(exc)
    return ""


def require_target(
    policy: ModelPolicy, baseline: Mapping[str, Any], channel: str, stage: str = "txt2img"
) -> None:
    if (
        stage != "txt2img"
        or "txt2img" not in policy.stages
        or policy.family != "sdxl"
        or policy.evidence != EVIDENCE_REGISTRY
    ):
        raise ValueError("Embedding experiments currently require registry-verified SDXL txt2img.")
    backend = normalize_image_backend_options(baseline.get("backend_options"))["image"][
        "backend_id"
    ]
    if backend != FORGE_IMAGE_BACKEND_ID:
        raise ValueError(
            "Embedding experiments are verified for the Forge backend only; select Forge in the Learning "
            "baseline and rebuild Preview."
        )
    if policy.feature("embeddings", "txt2img").support is not Support.SUPPORTED:
        raise ValueError("The target model policy does not support embeddings.")
    if policy.prompt_dialect != DIALECT_WEIGHTED_TAGS:
        raise ValueError(
            "The target prompt dialect does not support attention-weighted embeddings."
        )
    if (
        channel == NEGATIVE
        and policy.feature("negative_prompt", "txt2img").support is not Support.SUPPORTED
    ):
        raise ValueError(
            "The target does not support a negative prompt; a negative embedding is never moved to the positive prompt."
        )
    if any(
        bool((section.get("prompt_optimizer") or {}).get("enabled"))
        for section in (baseline, baseline.get("txt2img") or {})
    ):
        raise ValueError(
            "Disable the prompt optimizer in the independent Learning baseline before Preview; it may "
            "rewrite or erase the tested embedding."
        )
    style = baseline.get("style_lora")
    if (
        isinstance(style, Mapping)
        and style.get("enabled", True)
        and any(style.get(k) for k in ("style_id", "id", "name", "lora_name"))
    ):
        raise ValueError(
            "Style Consistency is enabled in the Learning baseline; its ownership is not part of this "
            "controlled embedding experiment. Disable it before Preview."
        )


@dataclass(frozen=True)
class _Source:
    quality: str
    subject: str
    negative_phrases: tuple[str, ...]
    positive: tuple[tuple[str, float], ...]
    negative: tuple[tuple[str, float], ...]


def _no_inline_embedding(text: str, where: str) -> None:
    if extract_embedding_entries(text):
        raise ValueError(
            f"The {where} contains an inline embedding reference, which cannot be isolated as a controlled "
            "contribution. Use a structured PromptPack embedding or remove it before Preview."
        )


def _fix_slots(text: str, fixed: Mapping[str, str]) -> str:
    values = {normalize_matrix_slot_name(k): str(v) for k, v in fixed.items()}
    for value in values.values():
        if not value.strip() or re.search(r"<[^>]*>|\[\[|\]\]", value):
            raise ValueError(
                "Fixed slot values must be plain text without LoRA, embedding or Matrix directives."
            )
    return substitute_matrix_tokens(text, values)


def fixed_embeddings_of(row: PackRow | None) -> dict[str, list[tuple[str, float]]]:
    """The structured embeddings a native PromptPack row already holds, for display and conflict checks."""
    if row is None:
        return {POSITIVE: [], NEGATIVE: []}
    return {
        POSITIVE: [(str(n), float(w)) for n, w in row.embeddings],
        NEGATIVE: [(str(n), float(w)) for n, w in row.negative_embeddings],
    }


def _resolve_source(design: EmbeddingDesign, row: PackRow | None, negative: str) -> _Source:
    if row is not None:
        if row.conditioning or row.controlnet_units:
            raise ValueError(
                "Conditioned PromptPack rows are not supported by embedding experiments."
            )
        quality = _fix_slots(row.quality_line, design.fixed_slots)
        subject = _fix_slots(row.subject_template, design.fixed_slots)
        phrases = tuple(str(p) for p in row.negative_phrases)
    else:
        quality, subject, phrases = "", _fix_slots(design.prompt, design.fixed_slots), ()
    if slots_in(quality) or slots_in(subject):
        raise ValueError(
            "The prompt still contains unresolved Matrix slots; give each slot an explicit fixed value."
        )
    for where, text in (
        ("positive prompt", quality),
        ("positive prompt", subject),
        ("negative prompt", negative),
    ):
        _no_inline_embedding(text, where)
    for phrase in phrases:
        _no_inline_embedding(phrase, "negative prompt")
    fixed = fixed_embeddings_of(row)
    for channel in CHANNELS:
        counts = Counter(_key(name) for name, _ in fixed[channel])
        repeated = sorted(name for name, count in counts.items() if count > 1)
        if repeated:
            raise ValueError(
                f"Embedding '{repeated[0]}' is declared more than once in the {channel} channel; resolve the "
                "duplicate before Preview (it would be silently deduplicated otherwise)."
            )
        unsafe = next((n for n, _ in fixed[channel] if not is_invocable_embedding_name(n)), None)
        if unsafe:
            raise ValueError(
                f"Fixed embedding '{unsafe}' cannot be invoked by name; correct it before Preview."
            )
    return _Source(quality, subject, phrases, tuple(fixed[POSITIVE]), tuple(fixed[NEGATIVE]))


def _evidence(asset: EmbeddingAsset) -> dict[str, Any]:
    return asset.to_dict()


def _admit_assets(names: Sequence[str], resolver: AssetResolver) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for name in names:
        asset = resolver(name)
        if asset.status in _ASSET_PHRASES and not asset.usable:
            detail = f": {asset.reason}" if asset.reason else ""
            raise ValueError(f"Embedding '{name}' {_ASSET_PHRASES[asset.status]}{detail}")
        if not asset.usable:
            raise ValueError(
                f"Embedding '{name}' has unknown availability; refresh the installed embeddings."
            )
        if not asset.identified:
            raise ValueError(
                f"Embedding '{name}' has no verified asset identity (SHA-256); refresh the installed embeddings first."
            )
        evidence[name] = _evidence(asset)
    return evidence


def multiset(entries: Sequence[Sequence[Any]]) -> list[list[Any]]:
    return sorted([[_key(str(n)), float(w)] for n, w in entries])


def observed_embeddings(text: str, names: Iterable[str]) -> list[tuple[str, float]]:
    """Occurrences of the *known* embedding invocations in rendered prompt text, in order: ``[(name, weight)]``.

    Only names the experiment already knows are searched (no guessing of ordinary prose), as a bare token or the
    canonical ``(Name:w)`` attention group. Boundaries treat ``-`` and word characters as part of a name so a name
    that prefixes another (``Style`` / ``Style-A``) is not double-counted.
    """
    canonical = {_key(n): n for n in names if str(n).strip()}
    if not canonical:
        return []
    alternation = "|".join(re.escape(k) for k in sorted(canonical, key=len, reverse=True))
    pattern = re.compile(
        rf"\(\s*(?P<wn>{alternation})\s*:\s*(?P<w>[0-9]*\.?[0-9]+)\s*\)"
        rf"|(?<![\w-])(?P<bn>{alternation})(?![\w-])",
        re.IGNORECASE,
    )
    found: list[tuple[str, float]] = []
    for match in pattern.finditer(str(text or "")):
        if match.group("wn"):
            found.append((canonical[_key(match.group("wn"))], float(match.group("w"))))
        else:
            found.append((canonical[_key(match.group("bn"))], 1.0))
    return found


def same_entries(observed: Sequence[Sequence[Any]], expected: Sequence[Sequence[Any]]) -> bool:
    left = sorted((_key(n), round(float(w), 2)) for n, w in observed)
    right = sorted((_key(n), round(float(w), 2)) for n, w in expected)
    return left == right


def _norm(text: str) -> str:
    """Whitespace and separator-insensitive form: removing a token leaves no double space or empty comma slot."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\s*,){2,}", ",", text)
    return re.sub(r"\s+,", ",", text).strip(" ,")


def freeze_candidates(
    design: EmbeddingDesign,
    policy: ModelPolicy,
    baseline: Mapping[str, Any],
    *,
    resolver: AssetResolver,
    negative: str = "",
    row: PackRow | None = None,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    require_target(policy, baseline, design.channel)
    validate_bounds(design)
    validate_operation(design)
    if slots_in(negative):
        raise ValueError("The fixed negative prompt may not contain unresolved Matrix slots.")
    resolved = _resolve_source(design, row, negative)
    channel = design.channel
    other = NEGATIVE if channel == POSITIVE else POSITIVE
    fixed_by_channel = {POSITIVE: list(resolved.positive), NEGATIVE: list(resolved.negative)}
    tested_names = {_key(c.name) for c in design.candidates if c.name}
    original = _key(design.original) if design.original else ""
    channel_fixed = fixed_by_channel[channel]
    position = len(channel_fixed)
    original_weight: float | None = None
    if original:
        index = next((i for i, (n, _) in enumerate(channel_fixed) if _key(n) == original), None)
        if index is None:
            raise ValueError("The designated original embedding is not in the baseline channel.")
        position, original_weight = index, channel_fixed[index][1]
        del channel_fixed[index]
    for name in sorted(tested_names):
        if any(_key(n) == name for n, _ in channel_fixed):
            raise ValueError(
                f"Embedding '{name}' is already a fixed embedding in the {channel} channel; designate it as "
                "the original to test it."
            )
        if any(_key(n) == name for n, _ in fixed_by_channel[other]):
            raise ValueError(
                f"Embedding '{name}' is also present in the {other} channel; one experiment cannot vary both "
                "polarities."
            )
    if design.operation == IDENTITY and original_weight is not None:
        for candidate in design.candidates:
            if (
                candidate.name
                and _key(candidate.name) == original
                and abs(candidate.weight - round(original_weight, 2)) > 1e-9
            ):
                raise ValueError(
                    f"The original embedding control must keep its baseline weight ({original_weight:g})."
                )
    fixed_all = fixed_by_channel[POSITIVE] + fixed_by_channel[NEGATIVE]
    shown_names = list(
        dict.fromkeys([n for n, _ in fixed_all] + [c.name for c in design.candidates if c.name])
    )
    assets = _admit_assets(shown_names, resolver)
    universe = list(shown_names)
    if design.original and design.original not in universe:
        universe.append(design.original)

    def build(tested: tuple[str, float] | None) -> dict[str, list[tuple[str, float]]]:
        channel_entries = list(channel_fixed)
        if tested is not None:
            channel_entries.insert(min(position, len(channel_entries)), tested)
        lists = {
            POSITIVE: list(fixed_by_channel[POSITIVE]),
            NEGATIVE: list(fixed_by_channel[NEGATIVE]),
        }
        lists[channel] = channel_entries
        return lists

    def render(lists: Mapping[str, list[tuple[str, float]]]) -> Any:
        pack_row = PackRow(
            tuple(lists[POSITIVE]),
            resolved.quality,
            resolved.subject,
            tuple(row.lora_tags) if row else (),
            tuple(lists[NEGATIVE]),
            resolved.negative_phrases,
        )
        intent = resolve_pack_intent(
            pack_row=pack_row, pack_negative=negative, apply_global_negative=False
        )
        adapted = adapt_pack_intent(intent, policy, optimizer_enabled=False)
        if not adapted.plan.adaptable or not adapted.plan.complete or adapted.plan.changed:
            raise ValueError("Target adaptation cannot prove an unchanged one-position comparison.")
        if tuple(adapted.intent.positive_embeddings) != tuple(lists[POSITIVE]) or tuple(
            adapted.intent.negative_embeddings
        ) != tuple(lists[NEGATIVE]):
            raise ValueError(
                "Target adaptation changed the embedding set; the comparison cannot be controlled."
            )
        return intent, adapted, render_pack_intent(adapted.intent)

    # The reference render without any tested contribution proves what "everything else" looks like.
    reference_lists = build(None)
    _, _, reference = render(reference_lists)
    reference_positive, reference_negative = expected_execution_prompts(
        reference.positive, reference.negative, baseline
    )
    frozen: list[dict[str, Any]] = []
    for index, candidate in enumerate(design.candidates):
        tested = (candidate.name, candidate.weight) if candidate.name else None
        lists = build(tested)
        intent, adapted, rendered = render(lists)
        positive, negative_text = expected_execution_prompts(
            rendered.positive, rendered.negative, baseline
        )
        invocation = render_embedding_invocation(*tested) if tested else ""
        observed_p = observed_embeddings(positive, universe)
        observed_n = observed_embeddings(negative_text, universe)
        if not (
            same_entries(observed_p, lists[POSITIVE]) and same_entries(observed_n, lists[NEGATIVE])
        ):
            raise ValueError(
                "A rendered prompt does not contain exactly the intended embeddings (an embedding name also "
                "appears in ordinary prompt text, or a global prompt repeats it). Resolve the duplicate before Preview."
            )
        tested_text, other_text = (
            (positive, negative_text) if channel == POSITIVE else (negative_text, positive)
        )
        ref_tested, ref_other = (
            (reference_positive, reference_negative)
            if channel == POSITIVE
            else (reference_negative, reference_positive)
        )
        if other_text != ref_other:
            raise ValueError(
                "The opposite prompt channel must remain fixed; the candidate changed it."
            )
        stripped = tested_text.replace(invocation, "", 1) if invocation else tested_text
        if _norm(stripped) != _norm(ref_tested):
            raise ValueError(
                "Prompt text outside the tested embedding differs from the fixed prompt; the comparison cannot "
                "be controlled."
            )
        frozen.append(
            {
                "label": chr(65 + index),
                "name": candidate.name,
                "weight": candidate.weight,
                "label_text": candidate.text,
                "asset": assets.get(candidate.name) if candidate.name else None,
                "invocation": invocation,
                "expected_positive_embeddings": [[n, w] for n, w in lists[POSITIVE]],
                "expected_negative_embeddings": [[n, w] for n, w in lists[NEGATIVE]],
                "embedding_digest": digest([multiset(lists[POSITIVE]), multiset(lists[NEGATIVE])]),
                "positive": rendered.positive,
                "negative": rendered.negative,
                "expected_positive": positive,
                "expected_negative": negative_text,
                "source_intent": pack_prompt_intent_to_dict(intent),
                "adaptation": adapted.plan.to_diagnostics(),
                "effective_digest": digest([positive, negative_text]),
            }
        )
    channel_key = "expected_positive" if channel == POSITIVE else "expected_negative"
    if len({item[channel_key] for item in frozen}) != len(frozen):
        raise ValueError(
            "Distinct candidates collapse to the same executable prompt; at least two would be identical at "
            "execution."
        )
    fixed_items = [
        {"channel": POSITIVE, "name": n, "weight": w, "asset": assets[n]}
        for n, w in fixed_by_channel[POSITIVE]
    ] + [
        {"channel": NEGATIVE, "name": n, "weight": w, "asset": assets[n]}
        for n, w in fixed_by_channel[NEGATIVE]
    ]
    payload = {
        "contract": CONTRACT,
        "operation": design.operation,
        "channel": channel,
        "original": design.original,
        "original_weight": original_weight,
        "position": position,
        "fixed": fixed_items,
        "fixed_digest": digest(
            [multiset(fixed_by_channel[POSITIVE]), multiset(fixed_by_channel[NEGATIVE])]
        ),
        "universe": universe,
        "source": dict(source or {"kind": "custom"}),
        "source_digest": digest(
            [
                resolved.quality,
                resolved.subject,
                list(resolved.negative_phrases),
                negative,
                [list(t) for t in resolved.positive],
                [list(t) for t in resolved.negative],
            ]
        ),
        "candidates": frozen,
        "images_per_candidate": design.images_per_candidate,
        "assets": assets,
        "evidence_limits": EVIDENCE_LIMITS,
    }
    return {**payload, "digest": digest(payload)}


def frozen_section(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    section = snapshot[STUDY_TYPE]
    if section.get("contract") != CONTRACT or digest(
        {k: v for k, v in section.items() if k != "digest"}
    ) != section.get("digest"):
        raise ValueError("Frozen embedding experiment contract is missing or corrupt.")
    return dict(section)


def frozen_candidate(snapshot: Mapping[str, Any], label: str) -> dict[str, Any]:
    section = frozen_section(snapshot)
    candidate = next((item for item in section["candidates"] if item["label"] == label), None)
    if candidate is None or label not in snapshot["variant_values"]:
        raise ValueError("Variant does not belong to this frozen embedding experiment.")
    return copy.deepcopy(candidate)


def verify_assets(snapshot: Mapping[str, Any], resolver: AssetResolver) -> None:
    """Run-time preflight: every frozen asset must still be the same installed bytes (identity, not re-qualification)."""
    for name, frozen in frozen_section(snapshot)["assets"].items():
        current = resolver(name)
        if (
            current.status in (STATUS_MISSING, STATUS_AMBIGUOUS, STATUS_STALE, STATUS_INCOMPATIBLE)
            or not current.identified
            or current.sha256 != frozen["sha256"]
        ):
            raise ValueError(
                f"Embedding asset identity changed or is unavailable for '{name}'. "
                "No variants were admitted; rebuild Preview."
            )


def declarations(candidate: Mapping[str, Any]) -> dict[str, list[tuple[str, float]]]:
    return {
        POSITIVE: [(n, float(w)) for n, w in candidate["expected_positive_embeddings"]],
        NEGATIVE: [(n, float(w)) for n, w in candidate["expected_negative_embeddings"]],
    }


def readback_reason(
    snapshot: Mapping[str, Any],
    variant: Any,
    readback: Mapping[str, Any],
    backend_report: Mapping[str, Any] | None = None,
) -> str:
    """ "" when the observed prompts prove the whole expected embedding set; else a stable reason code."""
    if snapshot.get("study_type") != STUDY_TYPE:
        return ""
    try:
        section = frozen_section(snapshot)
        candidate = frozen_candidate(snapshot, variant.param_value)
        index = snapshot["variant_values"].index(variant.param_value)
        if (
            not variant.job_id
            or variant.variant_id != f"{snapshot['experiment_id']}:{index}"
            or variant.experiment_id != snapshot["experiment_id"]
        ):
            return "embedding_identity_unverified"
        config = variant.executed_config or {}
        if digest(config) != snapshot["compiled_embedding_plan"][index]["config_digest"]:
            return "embedding_compiled_context_conflict"
        if (
            config.get("prompt") != candidate["positive"]
            or config.get("negative_prompt") != candidate["negative"]
        ):
            return "embedding_compiled_prompt_conflict"
        if "final_prompt" not in readback or "final_negative_prompt" not in readback:
            return "embedding_readback_unavailable"
        final_positive = str(readback["final_prompt"])
        final_negative = str(readback["final_negative_prompt"])
        if extract_embedding_entries(final_positive) or extract_embedding_entries(final_negative):
            return "embedding_unexpected_reference"
        universe = list(section["universe"])
        expected = declarations(candidate)
        reason = _compare_channels(
            observed_embeddings(final_positive, universe),
            expected[POSITIVE],
            observed_embeddings(final_negative, universe),
            expected[NEGATIVE],
            section,
        )
        if reason:
            return reason
        if (
            final_positive != candidate["expected_positive"]
            or final_negative != candidate["expected_negative"]
        ):
            return "embedding_readback_mismatch"
        return consumption_status(candidate, backend_report)[1]
    except (KeyError, TypeError, ValueError, AttributeError):
        return "embedding_frozen_evidence_invalid"


def _compare_channels(
    positive: Sequence[tuple[str, float]],
    expected_positive: Sequence[tuple[str, float]],
    negative: Sequence[tuple[str, float]],
    expected_negative: Sequence[tuple[str, float]],
    section: Mapping[str, Any],
) -> str:
    tested = {_key(c["name"]) for c in section["candidates"] if c["name"]}
    if section.get("original"):
        tested.add(_key(section["original"]))
    observed = {POSITIVE: list(positive), NEGATIVE: list(negative)}
    wanted = {POSITIVE: list(expected_positive), NEGATIVE: list(expected_negative)}
    wanted_keys = {ch: Counter(_key(n) for n, _ in wanted[ch]) for ch in CHANNELS}
    seen_keys = {ch: Counter(_key(n) for n, _ in observed[ch]) for ch in CHANNELS}
    for ch in CHANNELS:
        opposite = NEGATIVE if ch == POSITIVE else POSITIVE
        for name in seen_keys[ch]:
            if name in tested and name not in wanted_keys[ch]:
                if name in wanted_keys[opposite]:
                    return "embedding_polarity_mismatch"
                return "embedding_excluded_present"
    for ch in CHANNELS:
        for _name, count in seen_keys[ch].items():
            if count > 1:
                return "embedding_duplicate"
    for ch in CHANNELS:
        for name in wanted_keys[ch]:
            if name not in seen_keys[ch]:
                return "embedding_missing" if name in tested else "embedding_fixed_changed"
        for name in seen_keys[ch]:
            if name not in wanted_keys[ch]:
                return "embedding_unexpected"
    for ch in CHANNELS:
        for name, weight in observed[ch]:
            expected_weight = next(w for n, w in wanted[ch] if _key(n) == _key(name))
            if abs(round(weight, 2) - round(expected_weight, 2)) > 1e-9:
                return (
                    "embedding_weight_mismatch"
                    if _key(name) in tested
                    else "embedding_fixed_changed"
                )
    return ""


def consumption_status(
    candidate: Mapping[str, Any], report: Mapping[str, Any] | None
) -> tuple[str, str]:
    """``(status, contradiction_reason)`` from the backend's own report against the candidate's expected set.

    Absence of a report, or an empty report while embeddings were expected, proves nothing (conditioning can be
    served from the backend's cache without re-encoding), so it stays "request verified". Only a report that names
    embeddings and disagrees with the expectation is a contradiction.
    """
    expected = {
        _sanitized(name)
        for entries in (
            candidate["expected_positive_embeddings"],
            candidate["expected_negative_embeddings"],
        )
        for name, _ in entries
    }
    if not isinstance(report, Mapping) or not report.get("reported"):
        return CONSUMPTION_REQUEST_ONLY, ""
    names = {_sanitized(n) for n in report.get("names") or ()}
    if names - expected:
        return CONSUMPTION_CONTRADICTED, "embedding_backend_unexpected"
    if names and expected - names:
        return CONSUMPTION_CONTRADICTED, "embedding_backend_not_consumed"
    if names == expected:
        return CONSUMPTION_REPORTED, ""
    return CONSUMPTION_REQUEST_ONLY, ""


def execution_evidence(
    snapshot: Mapping[str, Any], variant: Any, backend_report: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Typed execution-metadata additions for an embedding variant ({} for any other study)."""
    if snapshot.get("study_type") != STUDY_TYPE:
        return {}
    try:
        candidate = frozen_candidate(snapshot, variant.param_value)
    except (KeyError, TypeError, ValueError, AttributeError):
        return {"embedding_consumption_status": CONSUMPTION_REQUEST_ONLY}
    status, _ = consumption_status(candidate, backend_report)
    return {
        "embedding_consumption_status": status,
        "backend_textual_inversion": dict(backend_report)
        if isinstance(backend_report, Mapping)
        else {},
    }


def rating_metadata(snapshot: Mapping[str, Any], variant: Any) -> dict[str, Any]:
    if snapshot.get("study_type") != STUDY_TYPE:
        return {}
    section = frozen_section(snapshot)
    candidate = frozen_candidate(snapshot, variant.param_value)
    execution = variant.execution_metadata or {}
    return {
        "study_type": STUDY_TYPE,
        STUDY_TYPE: {
            "contract": CONTRACT,
            "operation": section["operation"],
            "channel": section["channel"],
            "candidate_label": candidate["label"],
            "candidate_name": candidate["name"],
            "requested_weight": candidate["weight"],
            "asset": candidate["asset"],
            "fixed_digest": section["fixed_digest"],
            "expected_embedding_digest": candidate["embedding_digest"],
            "effective_digest": candidate["effective_digest"],
            "controlled_evidence_valid": execution.get("controlled_evidence_valid") is True,
            "runtime_embedding_readback_status": str(
                execution.get("variable_validation_reason") or ""
            ),
            "consumption_status": str(
                execution.get("embedding_consumption_status") or CONSUMPTION_REQUEST_ONLY
            ),
            "evidence_limits": EVIDENCE_LIMITS,
        },
        "runtime_prompt_readback": dict(execution.get("runtime_prompt_readback") or {}),
    }


def conclusion(
    plan: Sequence[Any], ratings: Mapping[str, Any], drafts: Mapping[str, Any]
) -> dict[str, Any]:
    """Experiment-local only. The causal wording needs reported consumption; otherwise it is exploratory."""
    from src.learning.prompt_slot_experiment import conclusion as local_conclusion

    result = local_conclusion(plan, ratings, drafts)
    controlled = [
        v for v in plan if (v.execution_metadata or {}).get("controlled_evidence_valid") is True
    ]
    contradicted = any(
        (v.execution_metadata or {}).get("embedding_consumption_status") == CONSUMPTION_CONTRADICTED
        for v in plan
    )
    consumption_verified = (
        bool(controlled)
        and len(controlled) == len(plan)
        and all(
            (v.execution_metadata or {}).get("embedding_consumption_status") == CONSUMPTION_REPORTED
            for v in plan
        )
        and not contradicted
    )
    winner = result.get("best_value")
    if consumption_verified:
        qualifier = (
            "The backend reported using exactly the expected embeddings (by name); the applied weight is not "
            "reported by the backend."
        )
    else:
        qualifier = (
            "Exploratory preference: embedding request verified; actual consumption unverified. It is not "
            "promoted as proven embedding-specific evidence."
        )
    result.update(
        study_type=STUDY_TYPE,
        comparison_claim="experiment_local_embedding_preference",
        causal_one_variable=consumption_verified,
        consumption_verified=consumption_verified,
        evidence_level="consumption_reported" if consumption_verified else "request_verified",
        message=(
            f"Highest rated in this experiment: Candidate {winner}."
            if winner
            else "No unique highest-rated candidate with sufficient controlled saved evidence."
        )
        + " This describes the tested model, prompt, fixed embeddings and settings; no universal best "
        "embedding or weight and no statistical significance is claimed. " + qualifier,
    )
    return result


def _snapshot_of(experiment: Any) -> dict[str, Any] | None:
    try:
        snapshot = json.loads(getattr(experiment, "execution_snapshot_json", "") or "{}")
    except (TypeError, ValueError):
        return None
    return snapshot if snapshot.get("study_type") == STUDY_TYPE else None


def visibility_prompt(experiment: Any) -> str:
    """Private input to the existing visibility classifier, never a presentation caption."""
    from src.learning.prompt_slot_experiment import visibility_prompt as slot_prompt

    try:
        snapshot = _snapshot_of(experiment)
        if snapshot is None:
            return slot_prompt(experiment)
        return "\n".join(
            str(candidate[key])
            for candidate in snapshot[STUDY_TYPE]["candidates"]
            for key in ("expected_positive", "expected_negative")
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return "nsfw unverified embedding content"


def fixed_text(section: Mapping[str, Any], *, visible: bool) -> str:
    items = section["fixed"]
    if not items:
        return "none"
    if not visible:
        return f"{len(items)} fixed (names hidden by content visibility)"
    return ", ".join(f"{i['name']} @ {i['weight']:g} ({i['channel']})" for i in items)


def candidate_caption(experiment: Any, label: str, *, visible: bool) -> str:
    try:
        snapshot = _snapshot_of(experiment)
        if snapshot is None:
            raise ValueError("not an embedding experiment")
        candidate = frozen_candidate(snapshot, label)
        section = frozen_section(snapshot)
    except (AttributeError, KeyError, TypeError, ValueError):
        return "Candidate embedding evidence is unavailable or unverified."
    if not visible:
        return f"Candidate {candidate['label']}\nEmbedding details hidden by content visibility."
    return (
        f"Candidate {candidate['label']}: {candidate['label_text']}\n"
        f"Channel: {CHANNEL_LABELS[section['channel']]}\n"
        f"Fixed embeddings: {fixed_text(section, visible=True)}"
    )


def candidate_label_text(experiment: Any, label: str, *, visible: bool) -> str:
    """ "PortraitStyle @ 0.6" / "No embedding", or a generic phrase when embedding names are hidden."""
    try:
        snapshot = _snapshot_of(experiment)
        if snapshot is None:
            return ""
        item = frozen_candidate(snapshot, label)
    except (AttributeError, KeyError, TypeError, ValueError):
        return "unverified"
    if item["name"] is None:
        return "No embedding"
    return item["label_text"] if visible else f"Embedding hidden @ {item['weight']:g}"


def preview_details(section: Mapping[str, Any]) -> str:
    blocks = [
        f"Experiment: {OPERATION_LABELS[section['operation']]} ({CHANNEL_LABELS[section['channel']]})"
        + (f"; tested original: {section['original']}" if section.get("original") else ""),
        f"Fixed embeddings (unchanged in every candidate): {fixed_text(section, visible=True)}",
    ]
    for item in section["candidates"]:
        asset = item["asset"]
        blocks.append(
            f"Candidate {item['label']}: {item['label_text']}\n"
            + (
                f"Invocation: {item['invocation']}\n"
                f"Asset {asset['sha256'][:12]}… {asset['status']} ({asset['structure'] or 'structure unknown'}, "
                f"{asset['file_format'] or 'format unknown'})\n"
                if asset
                else "No tested embedding contribution\n"
            )
            + f"Expected execution: {item['expected_positive']}\n"
            f"Expected negative: {item['expected_negative']}"
        )
    blocks.append(section["evidence_limits"])
    return "\n\n".join(blocks)


__all__ = [
    "IDENTITY",
    "PRESENCE",
    "STUDY_TYPE",
    "VARIABLE",
    "WEIGHT",
    "Candidate",
    "EmbeddingAsset",
    "EmbeddingDesign",
    "freeze_candidates",
]
