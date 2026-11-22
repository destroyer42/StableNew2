"""PR-IMG-COMFY-381: the production Forge/A1111 -> ComfyUI vocabulary maps for SDXL txt2img (pure; no I/O).

Three small, explicit translations. Nothing is guessed: a name or syntax with no faithful ComfyUI equivalent is refused
with the offending text in the message, never approximated silently.

* **sampler / scheduler**: Forge display names -> ComfyUI ids. The qualification record (PR-IMG-BACKEND-QUAL-100) calls
  these *approximate* (the same named algorithm family; each runtime owns its implementation), and ``Automatic`` is an
  explicit closest value rather than an identity; ``approximations`` records exactly which values were approximated.
* **prompt**: ``<lora:name:weight>`` tags are removed from the text and returned as LoRA requests (the backend turns
  them into ``LoraLoader`` nodes); ``<embedding:name>`` and the names of the job's textual inversions become ComfyUI's
  ``embedding:name``; ``(word:1.2)`` emphasis is identical in both runtimes and passes through. A1111-only syntax
  (``[from:to:n]``, ``[a|b]``, ``[word]``, ``BREAK``, ``AND``) and other ``<...>`` tags are refused.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


class ComfySdxlMappingError(ValueError):
    """A value or syntax has no faithful ComfyUI equivalent (the message names it)."""


#: Forge sampler display name -> ComfyUI ``KSampler.sampler_name``.
SAMPLER_MAP: Mapping[str, str] = {
    "Euler a": "euler_ancestral",
    "Euler": "euler",
    "Heun": "heun",
    "DPM2": "dpm_2",
    "DPM2 a": "dpm_2_ancestral",
    "LMS": "lms",
    "DPM++ 2S a": "dpmpp_2s_ancestral",
    "DPM++ 2M": "dpmpp_2m",
    "DPM++ SDE": "dpmpp_sde",
    "DPM++ 2M SDE": "dpmpp_2m_sde",
    "DPM++ 3M SDE": "dpmpp_3m_sde",
    "DDIM": "ddim",
    "UniPC": "uni_pc",
    "LCM": "lcm",
}
#: Forge scheduler display name -> ComfyUI ``KSampler.scheduler``.
SCHEDULER_MAP: Mapping[str, str] = {
    "Normal": "normal",
    "Karras": "karras",
    "Exponential": "exponential",
    "Simple": "simple",
    "Beta": "beta",
    "Uniform": "ddim_uniform",
    "SGM Uniform": "sgm_uniform",
    "KL Optimal": "kl_optimal",
}
#: ``Automatic`` resolves per model inside Forge; the explicit closest ComfyUI scheduler is ``normal`` (as in QUAL-100).
AUTOMATIC_SCHEDULER = "normal"
_AUTOMATIC = {"", "automatic", "none"}
#: A1111-style combined names ("DPM++ 2M Karras") carry their scheduler in the sampler name.
_SCHEDULER_SUFFIXES = ("Karras", "Exponential")


@dataclass(frozen=True, slots=True)
class SamplingMap:
    sampler: str
    scheduler: str
    #: Values that were mapped to the closest ComfyUI equivalent rather than an identity (recorded in the manifest).
    approximations: tuple[str, ...]


def map_sampling(sampler: str | None, scheduler: str | None) -> SamplingMap:
    """Map Forge sampler/scheduler display names; an unmapped name is refused (the name is in the message)."""

    sampler_text = str(sampler or "").strip()
    scheduler_text = str(scheduler or "").strip()
    if not sampler_text:
        raise ComfySdxlMappingError("a sampler is required for SDXL on ComfyUI")
    suffix_scheduler = ""
    for suffix in _SCHEDULER_SUFFIXES:
        if sampler_text.endswith(f" {suffix}"):
            sampler_text = sampler_text[: -len(suffix) - 1].strip()
            suffix_scheduler = suffix
            break
    comfy_sampler = SAMPLER_MAP.get(sampler_text)
    if comfy_sampler is None:
        raise ComfySdxlMappingError(
            f"sampler {sampler!r} has no ComfyUI equivalent in StableNew's map "
            f"(supported: {', '.join(sorted(SAMPLER_MAP))}); choose one of those or switch the Image backend to Forge"
        )
    approximations = [f"sampler {sampler_text!r} -> {comfy_sampler!r}"]
    if suffix_scheduler and scheduler_text.lower() not in _AUTOMATIC | {suffix_scheduler.lower()}:
        raise ComfySdxlMappingError(
            f"sampler {sampler!r} already names the {suffix_scheduler} scheduler, which conflicts with {scheduler_text!r}"
        )
    effective = suffix_scheduler or scheduler_text
    if effective.lower() in _AUTOMATIC:
        comfy_scheduler = AUTOMATIC_SCHEDULER
        approximations.append(f"scheduler 'Automatic' -> {comfy_scheduler!r}")
    else:
        comfy_scheduler = SCHEDULER_MAP.get(effective) or ""
        if not comfy_scheduler:
            raise ComfySdxlMappingError(
                f"scheduler {scheduler!r} has no ComfyUI equivalent in StableNew's map "
                f"(supported: {', '.join(sorted(SCHEDULER_MAP))}, Automatic); choose one of those or switch the "
                "Image backend to Forge"
            )
        approximations.append(f"scheduler {effective!r} -> {comfy_scheduler!r}")
    return SamplingMap(comfy_sampler, comfy_scheduler, tuple(approximations))


# -- prompt ------------------------------------------------------------------------------------------------------------

_LORA_TAG = re.compile(
    r"<\s*(?:lora|lyco)\s*:\s*([^<>:]+?)\s*(?::\s*([-+]?\d*\.?\d+)\s*)?>", re.IGNORECASE
)
_EMBEDDING_TAG = re.compile(r"<\s*embedding\s*:\s*([^<>]+?)\s*>", re.IGNORECASE)
_OTHER_TAG = re.compile(r"<[^<>\n]*>")
_BRACKET_SYNTAX = re.compile(r"(?<!\\)\[[^\[\]]*\]")
_BREAK = re.compile(r"\bBREAK\b")
_AND = re.compile(r"(?<![A-Za-z])AND(?![A-Za-z])")
_SPACE_BEFORE_COMMA = re.compile(r"\s+,")
_REPEATED_COMMA = re.compile(r"(?:,\s*){2,}")


@dataclass(frozen=True, slots=True)
class LoraRequest:
    name: str
    weight: float


@dataclass(frozen=True, slots=True)
class PromptTranslation:
    text: str
    loras: tuple[LoraRequest, ...]
    embeddings: tuple[str, ...]


def _tidy(text: str) -> str:
    text = _SPACE_BEFORE_COMMA.sub(",", text)
    text = _REPEATED_COMMA.sub(", ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip().strip(",").strip()


def refuse_unsupported_syntax(text: str, *, what: str = "prompt") -> None:
    """Refuse A1111-only prompt syntax ComfyUI would read literally (it would change the picture silently)."""

    problems: list[str] = []
    if _BRACKET_SYNTAX.search(text):
        problems.append("square-bracket syntax ([from:to:n], [a|b], [word])")
    if _BREAK.search(text):
        problems.append("BREAK")
    if _AND.search(text):
        problems.append("AND")
    if problems:
        raise ComfySdxlMappingError(
            f"the {what} uses A1111-only syntax ComfyUI does not read the same way: {', '.join(problems)}. "
            "Remove it, or switch the Image backend to Forge"
        )


def translate_prompt(
    text: str, *, embedding_names: Iterable[str] = (), what: str = "prompt"
) -> PromptTranslation:
    """The ComfyUI form of one prompt: LoRA tags extracted, embeddings renamed, unsupported syntax refused."""

    source = str(text or "")
    loras: list[LoraRequest] = []

    def take_lora(match: re.Match[str]) -> str:
        weight = float(match.group(2)) if match.group(2) is not None else 1.0
        loras.append(LoraRequest(match.group(1).strip(), weight))
        return " "

    without_loras = _LORA_TAG.sub(take_lora, source)
    embeddings: list[str] = []

    def take_embedding(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        embeddings.append(name)
        return f"embedding:{name}"

    translated = _EMBEDDING_TAG.sub(take_embedding, without_loras)
    leftover = _OTHER_TAG.search(translated)
    if leftover is not None:
        raise ComfySdxlMappingError(
            f"the {what} uses the tag {leftover.group(0)!r}, which has no ComfyUI equivalent here "
            "(supported tags: <lora:name:weight>, <embedding:name>). Remove it, or switch the Image backend to Forge"
        )
    refuse_unsupported_syntax(translated, what=what)
    for name in dict.fromkeys(str(item).strip() for item in embedding_names if str(item).strip()):
        # A textual inversion Forge applies by bare name needs the explicit ``embedding:`` prefix in ComfyUI.
        pattern = re.compile(rf"(?<![\w:]){re.escape(name)}(?![\w])")
        if pattern.search(translated):
            translated = pattern.sub(f"embedding:{name}", translated)
            embeddings.append(name)
    return PromptTranslation(_tidy(translated), tuple(loras), tuple(dict.fromkeys(embeddings)))


__all__ = [
    "AUTOMATIC_SCHEDULER",
    "SAMPLER_MAP",
    "SCHEDULER_MAP",
    "ComfySdxlMappingError",
    "LoraRequest",
    "PromptTranslation",
    "SamplingMap",
    "map_sampling",
    "refuse_unsupported_syntax",
    "translate_prompt",
]
