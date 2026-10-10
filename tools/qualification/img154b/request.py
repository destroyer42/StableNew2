"""D1 (154B): pinned-Forge request semantics, an immutable payload constructor and effective-option verification.

Nothing here performs I/O except the injected ``read_source`` reader used to RE-VERIFY the evidence anchors against a managed
Forge source tree (a read of source text; never an import or execution of that source).

Why this module exists. The PR-154A manifest froze the sampling INTENT (CFG 1.0, shift 9.0, Euler, Beta, 9 steps) from the
pinned Forge UI preset and the model card. A JSON key that looks right is not proof that the pinned API honours it. Reading the
pinned source (``d70373eb``) establishes three facts that change the payload:

* ``guidance_scale`` does not exist in the API. ``cfg_scale`` is the classifier-free-guidance weight in the
  ``uncond + (cond - uncond) * cfg`` convention, so the model card's "guidance 0.0 / no CFG" is ``cfg_scale == 1.0`` there
  (the unconditional pass is skipped and negative prompts are ignored). Sending ``0.0`` would select the UNCONDITIONAL
  prediction and ignore the prompt: the opposite of the intent. The frozen CFG 1.0 is therefore correct and unchanged.
* The API has no ``shift`` key. The pinned Forge reuses ``distilled_cfg_scale`` (default 3.5) as the shift carrier
  (``set_shift(shift=self.distilled_cfg_scale)``, honoured only by engines with ``use_shift``, which Z-Image sets). The
  pydantic request model ignores unknown keys, so a ``"shift": 9.0`` key would be silently dropped and the run would use 3.5
  (neither the model config's 3.0 nor the preset's 9.0). The payload must carry ``"distilled_cfg_scale": 9.0``.
* The Beta scheduler's two parameters, the sigma bounds and the early-conditioning skips are SERVER OPTIONS, not request keys.
  Beta reads the live predictor sigmas, which ``set_shift`` rewrites before sampling, so the frozen shift reaches the schedule.

The sampling VALUES are unchanged by this reconciliation; only their API encoding is. Every claim is tied to textual anchors
that are re-checked against the managed Forge source at preflight, so a source drift flips to a refusal instead of a stale claim.
"""

from __future__ import annotations

import json
import math
import os
import re
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tools.qualification.img154.core import Finding, digest
from tools.qualification.img154.manifest import (
    FORBIDDEN_REQUEST_KEYS,
    SEMANTICS_STATUS_RECONCILED,
    QualificationManifest,
    build_manifest,
)

SEMANTICS_REVISION = "img154b-request-semantics-r1"
SEMANTICS_STATUS = SEMANTICS_STATUS_RECONCILED

TXT2IMG_ENDPOINT = "/sdapi/v1/txt2img"
OPTIONS_ENDPOINT = "/sdapi/v1/options"
PROGRESS_ENDPOINT = "/sdapi/v1/progress"

#: The API request keys of the one frozen txt2img request, in canonical order.
PAYLOAD_KEYS = (
    "prompt",
    "negative_prompt",
    "seed",
    "steps",
    "sampler_name",
    "scheduler",
    "cfg_scale",
    "distilled_cfg_scale",
    "width",
    "height",
    "batch_size",
    "n_iter",
    "send_images",
    "save_images",
)

#: Frozen-intent field -> the pinned API key that actually carries it. ``shift`` has NO key of its own.
INTENT_TO_PAYLOAD_KEY: Mapping[str, str] = types.MappingProxyType(
    {
        "prompt": "prompt",
        "negative_prompt": "negative_prompt",
        "seed": "seed",
        "steps": "steps",
        "sampler_name": "sampler_name",
        "scheduler": "scheduler",
        "cfg_scale": "cfg_scale",
        "shift": "distilled_cfg_scale",
        "width": "width",
        "height": "height",
        "batch_size": "batch_size",
        "n_iter": "n_iter",
    }
)

#: Not part of any request: the harness's own routing field, and server options that shape the sampling path.
NOT_A_REQUEST_KEY = ("workflow",)
SERVER_OPTION_ONLY = (
    "beta_dist_alpha",
    "beta_dist_beta",
    "sigma_min",
    "sigma_max",
    "rho",
    "s_churn",
    "s_tmin",
    "s_tmax",
    "s_noise",
    "skip_early_cond",
    "s_min_uncond",
    "s_min_uncond_all",
    "always_discard_next_to_last_sigma",
    "sgm_noise_multiplier",
    "eta_noise_seed_delta",
    "randn_source",
    "use_dynamic_shifting",
    "face_restoration",
    "tiling",
    "forge_unet_storage_dtype",
)
#: Model-card or diffusers vocabulary that the pinned API does not expose.
NOT_EXPOSED = ("guidance_scale", "shift", "num_inference_steps")

#: Pinned server defaults of every option that changes the sampling path (read from ``shared_options.py``); a value other than
#: the default means the run no longer exercises the frozen intent and is refused.
EXPECTED_SAMPLING_OPTIONS: Mapping[str, Any] = types.MappingProxyType(
    {
        "beta_dist_alpha": 0.6,
        "beta_dist_beta": 0.6,
        "sigma_min": 0.0,
        "sigma_max": 0.0,
        "rho": 0.0,
        "s_churn": 0.0,
        "s_tmin": 0.0,
        "s_tmax": 0.0,
        "s_noise": 1.0,
        "skip_early_cond": 0.0,
        "s_min_uncond": 0.0,
        "s_min_uncond_all": False,
        "always_discard_next_to_last_sigma": False,
        "sgm_noise_multiplier": False,
        "eta_noise_seed_delta": 0,
        "randn_source": "CPU",
        "use_dynamic_shifting": False,
        "face_restoration": False,
        "tiling": False,
        "forge_unet_storage_dtype": "Automatic",
    }
)


class RequestRefused(ValueError):
    """The intent or a presented payload is not the frozen, reconciled request."""


# ----------------------------------------------------------------------------------------------------- source anchors


@dataclass(frozen=True)
class SourceAnchor:
    """Textual evidence in one file of the pinned Forge source tree.

    ``present`` substrings must all occur, ``ordered`` substrings must occur in that order, ``absent`` substrings must not
    occur. ``proves`` states, in one sentence, what the anchor establishes.
    """

    anchor_id: str
    file: str
    proves: str
    present: tuple[str, ...] = ()
    ordered: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()


PINNED_ANCHORS: tuple[SourceAnchor, ...] = (
    SourceAnchor(
        "API_MODEL_IGNORES_UNKNOWN_KEYS",
        "modules/api/models.py",
        "The txt2img request model is built with the default pydantic extra policy, so an unknown key such as 'shift' is "
        "silently dropped.",
        present=("ConfigDict(populate_by_name=True, frozen=False)",),
        absent=("extra=", 'extra="forbid"', "extra='forbid'"),
    ),
    SourceAnchor(
        "API_MODEL_FIELDS_COME_FROM_PROCESSING_CLASS",
        "modules/api/models.py",
        "The request fields are the dataclass fields of StableDiffusionProcessingTxt2Img plus a short additional list.",
        present=(
            "StableDiffusionProcessingTxt2Img,",
            '{"key": "send_images", "type": bool, "default": True}',
            '{"key": "save_images", "type": bool, "default": False}',
        ),
    ),
    SourceAnchor(
        "SHIFT_CARRIED_BY_DISTILLED_CFG_SCALE",
        "modules/processing.py",
        "Shift is supplied through distilled_cfg_scale (default 3.5), which is also what the infotext reports as 'Shift'.",
        present=(
            "distilled_cfg_scale: float = 3.5",
            "self.sd_model.set_shift(shift=self.distilled_cfg_scale)",
            'generation_params["Shift"] = p.distilled_cfg_scale',
        ),
    ),
    SourceAnchor(
        "SHIFT_IS_SET_BEFORE_SIGMAS_ARE_COMPUTED",
        "modules/processing.py",
        "set_shift runs after the sampler is created and before sampler.sample (which computes the sigmas).",
        ordered=(
            "self.sampler = sd_samplers.create_sampler(self.sampler_name, self.sd_model)",
            "self.sd_model.set_shift(shift=self.distilled_cfg_scale)",
            "samples = self.sampler.sample(self, x, conditioning, unconditional_conditioning",
        ),
    ),
    SourceAnchor(
        "SHIFT_APPLIED_ONLY_WHEN_ENGINE_USES_SHIFT",
        "backend/diffusion_engine/base.py",
        "set_shift is a no-op unless the engine declares use_shift; otherwise it rewrites the predictor parameters.",
        ordered=(
            "def set_shift(self, shift: float):",
            "if not self.use_shift:",
            "predictor.set_parameters(shift=shift)",
        ),
    ),
    SourceAnchor(
        "ZIMAGE_ENGINE_USES_SHIFT",
        "backend/diffusion_engine/zimage.py",
        "The Z-Image engine sets use_shift and does not enable distilled guidance, so distilled_cfg_scale is only a shift.",
        present=("self.use_shift = True",),
        absent=("use_distilled_cfg_scale = True",),
    ),
    SourceAnchor(
        "PREDICTOR_REBUILDS_SIGMAS_FROM_SHIFT",
        "backend/modules/k_prediction.py",
        "The flow predictor recomputes its sigma table from the supplied shift.",
        present=(
            "def set_parameters(self, *, shift=None, multiplier=None, timesteps=1000):",
            "self.shift = shift or self.shift",
            'self.register_buffer("sigmas", ts)',
        ),
    ),
    SourceAnchor(
        "BETA_SCHEDULER_READS_PREDICTOR_SIGMAS",
        "modules/sd_schedulers.py",
        "The Beta scheduler picks its sigmas from inner_model.sigmas using the server options alpha and beta.",
        present=(
            'Scheduler("beta", "Beta", beta_scheduler, need_inner_model=True)',
            "alpha = shared.opts.beta_dist_alpha",
            "beta = shared.opts.beta_dist_beta",
            "total_timesteps = len(inner_model.sigmas) - 1",
            "sigs += [float(inner_model.sigmas[int(t)])]",
            "schedulers_map = {**{x.name: x for x in schedulers}, **{x.label: x for x in schedulers}}",
        ),
    ),
    SourceAnchor(
        "SCHEDULE_LINKER_IS_LIVE",
        "modules_forge/packages/k_diffusion/external.py",
        "inner_model.sigmas is a live property of the predictor, not a copy taken when the sampler was created.",
        ordered=("def sigmas(self):", "return self.predictor.sigmas"),
    ),
    SourceAnchor(
        "SCHEDULER_KEY_REACHES_THE_SAMPLER",
        "modules/api/api.py",
        "The txt2img API forwards the request scheduler; an unset scheduler is the only case that is replaced.",
        present=(
            "sd_samplers.get_sampler_and_scheduler(txt2imgreq.sampler_name or txt2imgreq.sampler_index, txt2imgreq.scheduler)",
            'if not populate.scheduler and scheduler != "Automatic":',
        ),
    ),
    SourceAnchor(
        "SCHEDULER_NAME_IS_TAKEN_FROM_P",
        "modules/sd_samplers_kdiffusion.py",
        "The sampler resolves p.scheduler through schedulers_map.",
        present=(
            'scheduler_name = (p.hr_scheduler if p.is_hr_pass else p.scheduler) or "Automatic"',
            "scheduler = sd_schedulers.schedulers_map.get(scheduler_name)",
        ),
    ),
    SourceAnchor(
        "CFG_ONE_IS_NO_GUIDANCE",
        "modules/processing.py",
        "cfg_scale == 1 drops the negative/unconditional conditioning entirely.",
        ordered=("if self.cfg_scale == 1:", "self.uc = None"),
    ),
    SourceAnchor(
        "CFG_ONE_SKIPS_THE_UNCONDITIONAL_PASS",
        "backend/sampling/sampling_function.py",
        "A cond_scale close to 1.0 skips the unconditional forward pass; the combine rule is uncond + (cond - uncond) * cfg, "
        "so cfg 0.0 would return the unconditional prediction.",
        present=(
            "if math.isclose(cond_scale, 1.0)",
            "uncond_ = None",
            "cfg_result = uncond_pred + (cond_pred - uncond_pred) * cond_scale",
        ),
    ),
    SourceAnchor(
        "CFG_SCALE_IS_THE_SAMPLER_COND_SCALE",
        "modules/sd_samplers_kdiffusion.py",
        "The request cfg_scale is the sampler's cond_scale.",
        present=('"cond_scale": p.cfg_scale',),
    ),
    SourceAnchor(
        "OPTIONS_POST_SELECTS_CHECKPOINT_AND_MODULES",
        "modules/sysinfo.py",
        "POST /sdapi/v1/options routes sd_model_checkpoint and forge_additional_modules through the dedicated functions.",
        present=(
            "main_entry.checkpoint_change(v, preset=None, save=False, refresh=False)",
            "main_entry.modules_change(v, preset=None, save=False, refresh=False)",
            "main_entry.refresh_model_loading_parameters()",
        ),
    ),
    SourceAnchor(
        "UNKNOWN_MODULE_NAMES_ARE_DROPPED_SILENTLY",
        "modules_forge/main_entry.py",
        "A module name that is not in the discovered module list is skipped without an error, so selection must be "
        "confirmed from the options read-back.",
        present=("if module_name in module_list:", "modules.append(module_list[module_name])"),
    ),
    SourceAnchor(
        "WEIGHTS_LOAD_INSIDE_THE_GENERATION_CALL",
        "modules/sd_models.py",
        "Selection only records loading parameters; forge_model_reload (called from processing) loads the weights.",
        present=(
            "def forge_model_reload():",
            "sd_model = forge_loader(state_dict, additional_state_dicts=additional_state_dicts)",
        ),
    ),
    SourceAnchor(
        "GENERATION_CALLS_THE_RELOAD",
        "modules/processing.py",
        "Generation begins with forge_model_reload, so the first generation request is the load request.",
        present=("p.sd_model, just_reloaded = forge_model_reload()",),
    ),
    SourceAnchor(
        "PROGRESS_STATE_EXPOSES_SAMPLING_STEP",
        "modules/shared_state.py",
        "The progress API reports the sampler's current step and total, set by the sampling loop callback.",
        present=('"sampling_step": self.sampling_step', '"sampling_steps": self.sampling_steps'),
    ),
    SourceAnchor(
        "SAMPLING_LOOP_UPDATES_THE_STEP",
        "modules/sd_samplers_common.py",
        "state.sampling_step/steps are written by the sampling loop (steps at launch, step on every callback).",
        present=(
            "state.sampling_step = step",
            "state.sampling_steps = steps",
            "state.sampling_step = 0",
        ),
    ),
    SourceAnchor(
        "INFOTEXT_REPORTS_EFFECTIVE_PARAMETERS",
        "modules/processing.py",
        "The returned infotext states the effective steps, sampler, schedule type, CFG, shift, module names and seed.",
        present=(
            '"Steps": p.steps,',
            '"Sampler": p.sampler_name,',
            '"Schedule type": p.scheduler,',
            '"CFG scale": p.cfg_scale,',
            'generation_params[f"Module {i+1}"]',
        ),
    ),
    SourceAnchor(
        "FORGE_STORAGE_DTYPE_DEFAULT_AUTOMATIC",
        "modules_forge/shared_options.py",
        "The Forge-owned precision and module options default to Automatic and an empty module list.",
        present=(
            '"forge_additional_modules": OptionInfo([]),',
            '"forge_unet_storage_dtype": OptionInfo("Automatic"),',
        ),
    ),
    SourceAnchor(
        "SERVER_OPTION_DEFAULTS",
        "modules/shared_options.py",
        "The sampling-path options keep these defaults unless something changes them.",
        present=(
            '"beta_dist_alpha": OptionInfo(0.6,',
            '"beta_dist_beta": OptionInfo(0.6,',
            '"sigma_min": OptionInfo(0.0,',
            '"sigma_max": OptionInfo(0.0,',
            '"rho": OptionInfo(0.0,',
            '"s_churn": OptionInfo(0.0,',
            '"s_tmin": OptionInfo(0.0,',
            '"s_tmax": OptionInfo(0.0,',
            '"s_noise": OptionInfo(1.0,',
            '"skip_early_cond": OptionInfo(0.0,',
            '"s_min_uncond": OptionInfo(0.0,',
            '"s_min_uncond_all": OptionInfo(False,',
            '"always_discard_next_to_last_sigma": OptionInfo(False,',
            '"sgm_noise_multiplier": OptionInfo(False,',
            '"eta_noise_seed_delta": OptionInfo(0,',
            '"randn_source": OptionInfo("CPU",',
            '"use_dynamic_shifting": OptionInfo(False,',
            '"face_restoration": OptionInfo(False,',
            '"tiling": OptionInfo(False,',
        ),
    ),
)

#: Payload key -> (file, regex proving the pinned model defines it). A plausible-looking key that the pinned model does not
#: define is refused; a defined key is not by itself proof of its effect (see the anchors above).
PAYLOAD_KEY_SOURCES: Mapping[str, tuple[str, str]] = types.MappingProxyType(
    {
        "prompt": ("modules/processing.py", r'(?m)^    prompt: str = ""'),
        "negative_prompt": ("modules/processing.py", r'(?m)^    negative_prompt: str = ""'),
        "seed": ("modules/processing.py", r"(?m)^    seed: int = -1"),
        "steps": ("modules/processing.py", r"(?m)^    steps: int = \d+"),
        "sampler_name": ("modules/processing.py", r"(?m)^    sampler_name: str = None"),
        "scheduler": ("modules/processing.py", r"(?m)^    scheduler: str = None"),
        "cfg_scale": ("modules/processing.py", r"(?m)^    cfg_scale: float = "),
        "distilled_cfg_scale": (
            "modules/processing.py",
            r"(?m)^    distilled_cfg_scale: float = 3\.5",
        ),
        "width": ("modules/processing.py", r"(?m)^    width: int = "),
        "height": ("modules/processing.py", r"(?m)^    height: int = "),
        "batch_size": ("modules/processing.py", r"(?m)^    batch_size: int = 1"),
        "n_iter": ("modules/processing.py", r"(?m)^    n_iter: int = 1"),
        "send_images": ("modules/api/models.py", r'\{"key": "send_images", "type": bool'),
        "save_images": ("modules/api/models.py", r'\{"key": "save_images", "type": bool'),
    }
)

SourceReader = Callable[[str], "str | None"]


def verify_pinned_semantics(read_source: SourceReader) -> list[Finding]:
    """Re-check every anchor and every payload key against ``read_source(relative_posix_path)``.

    An unreadable file is inconclusive, a missing/forbidden/out-of-order anchor is a refusal. An empty list means the source at
    hand still states every fact this package relies on; it says nothing about how the model behaves when run.
    """

    findings: list[Finding] = []
    texts: dict[str, str | None] = {}

    def text_of(relative: str) -> str | None:
        if relative not in texts:
            try:
                raw = read_source(relative)
            except (OSError, UnicodeError, ValueError):
                raw = None
            texts[relative] = raw.replace("\r\n", "\n") if isinstance(raw, str) else None
        return texts[relative]

    for anchor in PINNED_ANCHORS:
        text = text_of(anchor.file)
        if text is None:
            findings.append(
                Finding(
                    "SEMANTICS_SOURCE_UNREADABLE",
                    "inconclusive",
                    f"{anchor.anchor_id}: {anchor.file}",
                )
            )
            continue
        missing = [fragment for fragment in anchor.present if fragment not in text]
        if missing:
            findings.append(
                Finding(
                    "SEMANTICS_ANCHOR_MISSING",
                    "refuse",
                    f"{anchor.anchor_id}: {len(missing)} expected fragment(s) absent from {anchor.file}",
                )
            )
        cursor = 0
        for fragment in anchor.ordered:
            index = text.find(fragment, cursor)
            if index < 0:
                findings.append(
                    Finding(
                        "SEMANTICS_ANCHOR_ORDER",
                        "refuse",
                        f"{anchor.anchor_id}: ordered fragment absent or out of order in {anchor.file}",
                    )
                )
                break
            cursor = index + len(fragment)
        present_forbidden = [fragment for fragment in anchor.absent if fragment in text]
        if present_forbidden:
            findings.append(
                Finding(
                    "SEMANTICS_ANCHOR_FORBIDDEN_PRESENT",
                    "refuse",
                    f"{anchor.anchor_id}: forbidden fragment present in {anchor.file}",
                )
            )
    for key, (relative, pattern) in PAYLOAD_KEY_SOURCES.items():
        text = text_of(relative)
        if text is None:
            findings.append(
                Finding(
                    "SEMANTICS_SOURCE_UNREADABLE",
                    "inconclusive",
                    f"payload key {key!r}: {relative}",
                )
            )
        elif re.search(pattern, text) is None:
            findings.append(
                Finding(
                    "PAYLOAD_KEY_NOT_DEFINED_BY_PINNED_MODEL",
                    "refuse",
                    f"payload key {key!r} is not defined in the pinned request model",
                )
            )
    return findings


def forge_source_reader(source_root: str | os.PathLike[str]) -> SourceReader:
    """A read-only reader over a managed Forge ``source`` directory (decoded as UTF-8; never imported or executed)."""

    root = os.path.realpath(os.fspath(source_root))

    def read(relative: str) -> str | None:
        target = os.path.realpath(os.path.join(root, *relative.split("/")))
        try:
            if os.path.commonpath([root, target]) != root:
                return None
        except ValueError:  # different drives
            return None
        try:
            with open(target, encoding="utf-8") as stream:
                return stream.read()
        except OSError:
            return None

    return read


# --------------------------------------------------------------------------------------------------- payload constructor


def _finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


@dataclass(frozen=True)
class FrozenPayload:
    """The one immutable request. ``body`` is a read-only mapping; ``wire_bytes`` is exactly what is sent."""

    endpoint: str
    body: Mapping[str, Any]
    wire_bytes: bytes
    payload_digest: str
    intent_digest: str
    semantics_revision: str = SEMANTICS_REVISION

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "body": dict(self.body),
            "payload_digest": self.payload_digest,
            "intent_digest": self.intent_digest,
            "semantics_revision": self.semantics_revision,
            "key_map": dict(INTENT_TO_PAYLOAD_KEY),
        }


def _canonical_wire(body: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(body), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def build_txt2img_payload(
    manifest: QualificationManifest | None = None, *, require_frozen: bool = True
) -> FrozenPayload:
    """Pure: the pinned-API encoding of the manifest intent. No request is sent and no host state is read.

    ``require_frozen`` (the default, and the only mode a live path may use) refuses any intent that is not the frozen one:
    the CFG 1.0 equivalence and the shift carrier are established for these values only.
    """

    plan = manifest or build_manifest()
    intent = plan.intent
    try:
        request_digest = plan.request_digest()
    except (TypeError, ValueError) as exc:
        raise RequestRefused(f"the intent is not canonical JSON ({type(exc).__name__})") from exc
    if require_frozen and request_digest != build_manifest().request_digest():
        raise RequestRefused(
            "the intent differs from the frozen intent; a different case needs a new owner decision"
        )
    if intent.workflow != "txt2img":
        raise RequestRefused("only txt2img is supported")
    if intent.batch_size != 1 or intent.n_iter != 1:
        raise RequestRefused("exactly one image is allowed")
    if intent.negative_prompt != "":
        raise RequestRefused(
            "a negative prompt is ignored at CFG 1.0 and is not part of the frozen request"
        )
    if intent.automatic_retry or intent.automatic_replay:
        raise RequestRefused("retry and replay are not permitted")
    if not (_finite_number(intent.cfg_scale) and float(intent.cfg_scale) == 1.0):
        raise RequestRefused(
            "only cfg_scale 1.0 (no classifier-free guidance) is established for Z-Image-Turbo"
        )
    if not (_finite_number(intent.shift) and float(intent.shift) > 0.0):
        raise RequestRefused(
            "shift must be a positive finite number (a zero shift is ignored by the pinned predictor)"
        )
    for name in ("seed", "steps", "width", "height"):
        value = getattr(intent, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RequestRefused(f"{name} must be a non-negative integer")
    body: dict[str, Any] = {
        "prompt": intent.prompt,
        "negative_prompt": intent.negative_prompt,
        "seed": intent.seed,
        "steps": intent.steps,
        "sampler_name": intent.sampler,
        "scheduler": intent.scheduler,
        "cfg_scale": float(intent.cfg_scale),
        "distilled_cfg_scale": float(intent.shift),
        "width": intent.width,
        "height": intent.height,
        "batch_size": intent.batch_size,
        "n_iter": intent.n_iter,
        "send_images": True,
        "save_images": False,
    }
    problems = payload_problems(body)
    if problems:
        raise RequestRefused("; ".join(problems))
    frozen_body = types.MappingProxyType({key: body[key] for key in PAYLOAD_KEYS})
    return FrozenPayload(
        TXT2IMG_ENDPOINT,
        frozen_body,
        _canonical_wire(frozen_body),
        digest(dict(frozen_body)),
        request_digest,
    )


def payload_problems(body: Mapping[str, Any]) -> list[str]:
    """Why a presented body is not the allowed shape (unknown, forbidden or missing keys, and not-exposed vocabulary)."""

    problems: list[str] = []
    keys = set(body)
    for key in sorted(keys & set(FORBIDDEN_REQUEST_KEYS)):
        problems.append(f"forbidden request key {key!r}")
    for key in sorted(keys & set(NOT_EXPOSED) - set(FORBIDDEN_REQUEST_KEYS)):
        problems.append(
            f"{key!r} is not an API key in the pinned Forge (it would be ignored or rejected)"
        )
    for key in sorted(keys - set(PAYLOAD_KEYS) - set(FORBIDDEN_REQUEST_KEYS) - set(NOT_EXPOSED)):
        problems.append(f"unexpected request key {key!r}")
    for key in sorted(set(PAYLOAD_KEYS) - keys):
        problems.append(f"missing request key {key!r}")
    return problems


def verify_payload(
    presented: Mapping[str, Any] | None, manifest: QualificationManifest | None = None
) -> list[Finding]:
    """The presented body must be exactly the constructor's output for the manifest (bit-for-bit after canonical JSON)."""

    if presented is None:
        return [Finding("PAYLOAD_NOT_PRESENTED", "inconclusive", "no request body was presented")]
    findings = [
        Finding("PAYLOAD_SHAPE", "refuse", problem) for problem in payload_problems(presented)
    ]
    try:
        expected = build_txt2img_payload(manifest)
        if _canonical_wire(presented) != expected.wire_bytes:
            findings.append(
                Finding("PAYLOAD_DRIFT", "refuse", "presented body differs from the frozen payload")
            )
    except (RequestRefused, TypeError, ValueError) as exc:
        findings.append(Finding("PAYLOAD_NOT_CANONICAL", "refuse", f"{type(exc).__name__}"))
    return findings


# ---------------------------------------------------------------------------------------------- options (selection) side


def selection_payload(served_paths: Mapping[str, str]) -> dict[str, Any]:
    """The ``/sdapi/v1/options`` body that selects the exact served files (checkpoint by name, modules by served path)."""

    from tools.qualification.img154.manifest import FROZEN_ASSETS

    for role in ("transformer", "text_encoder", "vae"):
        if role not in served_paths or not str(served_paths[role]).strip():
            raise RequestRefused(f"served path for {role!r} is required")
    return {
        "sd_model_checkpoint": FROZEN_ASSETS["transformer"].filename,
        "forge_additional_modules": [str(served_paths["text_encoder"]), str(served_paths["vae"])],
    }


def _same_number(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return (
            math.isfinite(left) and math.isfinite(right) and abs(float(left) - float(right)) <= 1e-9
        )
    return left == right


def verify_sampling_options(options: Mapping[str, Any] | None) -> list[Finding]:
    """Every sampling-path option is at its pinned default and the Beta scheduler is selectable."""

    if options is None:
        return [Finding("OPTIONS_NOT_READ", "inconclusive", "the server options were not read")]
    findings: list[Finding] = []
    for name, expected in EXPECTED_SAMPLING_OPTIONS.items():
        if name not in options:
            findings.append(
                Finding("OPTION_MISSING", "inconclusive", f"option {name!r} was not reported")
            )
        elif not _same_number(options[name], expected):
            findings.append(
                Finding(
                    "OPTION_NOT_DEFAULT", "refuse", f"option {name!r} is not its pinned default"
                )
            )
    hidden = options.get("hide_schedulers")
    if not isinstance(hidden, list):
        findings.append(
            Finding("OPTION_MISSING", "inconclusive", "option 'hide_schedulers' was not reported")
        )
    elif any(str(item).strip().lower() == "beta" for item in hidden):
        findings.append(
            Finding("SCHEDULER_HIDDEN", "refuse", "the Beta scheduler is hidden on this server")
        )
    return findings


def _norm(path: str, resolve: Callable[[str], str]) -> str:
    return resolve(path).replace("\\", "/").rstrip("/").lower()


def verify_selection(
    options: Mapping[str, Any] | None,
    served_paths: Mapping[str, str],
    *,
    resolve: Callable[[str], str] = os.path.realpath,
) -> list[Finding]:
    """The options read-back names exactly the served transformer and the two served modules (and nothing else)."""

    from tools.qualification.img154.manifest import FROZEN_ASSETS

    if options is None:
        return [Finding("OPTIONS_NOT_READ", "inconclusive", "the server options were not read")]
    findings: list[Finding] = []
    checkpoint = options.get("sd_model_checkpoint")
    if not isinstance(checkpoint, str) or not checkpoint.strip():
        findings.append(
            Finding("SELECTION_CHECKPOINT_UNKNOWN", "inconclusive", "no checkpoint is reported")
        )
    elif FROZEN_ASSETS["transformer"].filename not in checkpoint:
        findings.append(
            Finding(
                "SELECTION_CHECKPOINT_MISMATCH",
                "refuse",
                "the active checkpoint is not the frozen transformer",
            )
        )
    modules = options.get("forge_additional_modules")
    if not isinstance(modules, list) or not all(isinstance(item, str) for item in modules):
        findings.append(
            Finding("SELECTION_MODULES_UNKNOWN", "inconclusive", "no module list is reported")
        )
        return findings
    expected = {_norm(str(served_paths[role]), resolve) for role in ("text_encoder", "vae")}
    actual = [_norm(item, resolve) for item in modules]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        findings.append(
            Finding(
                "SELECTION_MODULES_MISMATCH",
                "refuse",
                f"expected exactly the two served modules; {len(actual)} reported "
                "(an unknown module name is dropped silently by the pinned selection code)",
            )
        )
    return findings


# ----------------------------------------------------------------------------------------------------- infotext parsing

_INFOTEXT_PAIR = re.compile(
    r'(?P<key>[A-Za-z][A-Za-z0-9 _/.-]*?):\s*(?P<value>"(?:[^"\\]|\\.)*"|[^,]*)(?:,|$)'
)


def parse_infotext(text: str) -> dict[str, str]:
    """``key: value`` pairs of the last (parameters) line of a Forge infotext; quoted values are unquoted."""

    last = [line for line in str(text).splitlines() if line.strip()][-1:] or [""]
    pairs: dict[str, str] = {}
    for match in _INFOTEXT_PAIR.finditer(last[0]):
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        pairs.setdefault(match.group("key").strip(), value)
    return pairs


def modules_in_infotext(pairs: Mapping[str, str]) -> list[str]:
    return [
        value
        for key, value in sorted(
            ((k, v) for k, v in pairs.items() if re.fullmatch(r"Module \d+", k)),
            key=lambda item: int(item[0].split()[1]),
        )
    ]


def expected_infotext(manifest: QualificationManifest | None = None) -> dict[str, str]:
    """What the pinned Forge's own infotext must report for the frozen request (effective, not requested, values)."""

    plan = manifest or build_manifest()
    intent = plan.intent
    return {
        "Steps": str(intent.steps),
        "Sampler": intent.sampler,
        "Schedule type": intent.scheduler,
        "CFG scale": repr(float(intent.cfg_scale)),
        "Shift": repr(float(intent.shift)),
        "Seed": str(intent.seed),
        "Size": f"{intent.width}x{intent.height}",
    }


def verify_infotext(
    infotext: str | None, manifest: QualificationManifest | None = None
) -> tuple[list[Finding], dict[str, Any]]:
    """Effective-parameter and identity check of the returned infotext. ``facts`` records what was seen."""

    from tools.qualification.img154.manifest import FROZEN_ASSETS

    plan = manifest or build_manifest()
    findings: list[Finding] = []
    facts: dict[str, Any] = {"parsed": False}
    if not isinstance(infotext, str) or not infotext.strip():
        return [Finding("INFOTEXT_ABSENT", "inconclusive", "no infotext was returned")], facts
    pairs = parse_infotext(infotext)
    facts.update(parsed=True, keys=sorted(pairs))
    for key, wanted in expected_infotext(plan).items():
        seen = pairs.get(key)
        if seen is None:
            findings.append(
                Finding("INFOTEXT_FIELD_ABSENT", "inconclusive", f"{key!r} not reported")
            )
            continue
        if key in ("CFG scale", "Shift"):
            try:
                same = float(seen) == float(wanted)
            except ValueError:
                same = False
        else:
            same = seen == wanted
        if not same:
            findings.append(
                Finding("INFOTEXT_FIELD_MISMATCH", "refuse", f"{key!r} is not the frozen value")
            )
    spec_hash = FROZEN_ASSETS["transformer"].sha256
    model_hash = pairs.get("Model hash")
    facts["model_hash_reported"] = model_hash is not None
    if model_hash is None:
        findings.append(
            Finding("INFOTEXT_MODEL_HASH_ABSENT", "inconclusive", "no model hash was reported")
        )
    elif not spec_hash.startswith(model_hash.lower()) or len(model_hash) < 8:
        findings.append(
            Finding(
                "INFOTEXT_MODEL_HASH_MISMATCH",
                "refuse",
                "the model hash is not the frozen transformer's",
            )
        )
    wanted_modules = sorted(
        os.path.splitext(FROZEN_ASSETS[role].filename)[0] for role in ("text_encoder", "vae")
    )
    seen_modules = sorted(modules_in_infotext(pairs))
    facts["modules_reported"] = len(seen_modules)
    if not seen_modules:
        findings.append(
            Finding("INFOTEXT_MODULES_ABSENT", "inconclusive", "no module names were reported")
        )
    elif seen_modules != wanted_modules:
        findings.append(
            Finding(
                "INFOTEXT_MODULES_MISMATCH",
                "refuse",
                "the reported modules are not the frozen pair",
            )
        )
    return findings, facts


def semantics_report(
    findings: Sequence[Finding], manifest: QualificationManifest | None = None
) -> dict[str, Any]:
    """A bounded, redacted description of the reconciliation for packets and evidence (no source text, no local path)."""

    plan = manifest or build_manifest()
    payload = build_txt2img_payload(plan, require_frozen=False)
    return {
        "revision": SEMANTICS_REVISION,
        "status": SEMANTICS_STATUS if not findings else "NOT_VERIFIED",
        "frozen_intent_values_changed": False,
        "cfg": "cfg_scale 1.0 is the pinned Forge's no-guidance setting; the card's guidance 0.0 would send the "
        "unconditional prediction if copied literally",
        "shift": "carried by the distilled_cfg_scale API key; a 'shift' key would be ignored (default 3.5 would apply)",
        "beta_scheduler": "scheduler key; alpha/beta are server options (defaults 0.6/0.6) verified by options read-back",
        "payload_digest": payload.payload_digest,
        "intent_digest": payload.intent_digest,
        "payload_keys": list(PAYLOAD_KEYS),
        "server_option_only": list(SERVER_OPTION_ONLY),
        "not_exposed": list(NOT_EXPOSED),
        "anchors": [
            {"id": anchor.anchor_id, "file": anchor.file, "proves": anchor.proves}
            for anchor in PINNED_ANCHORS
        ],
        "findings": [
            {"code": f.code, "severity": f.severity, "detail": f.detail} for f in findings
        ],
        "model_load": "occurs inside the generation request (forge_model_reload); options selection records parameters only",
    }
