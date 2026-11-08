"""Likely causes for a checkpoint that does not work (MEC-904), from facts StableNew already holds.

Inputs are the file's header structure (from the census), past-run failure messages and settings (observational),
an unreviewed Civitai identification, and the family StableNew resolved. Output is a short list of plain-language
hypotheses with the check that would confirm each. Nothing here changes a policy, a family or a recipe; the operator
confirms a hypothesis with a Compatibility Probe.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.learning.model_run_history import ModelRunSummary

_ERROR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"out of memory|cuda.*memory|allocat", re.I),
        "Past runs ran out of GPU memory. Try a smaller size or Forge's low-VRAM options; the model itself may be fine.",
    ),
    (
        re.compile(
            r"dependenc|text.?encoder|clip.*(missing|not found)|vae.*(missing|not found)|not selected",
            re.I,
        ),
        "Past failures mention missing components (text encoder / VAE). Diffusion-only files need those selected "
        "separately in Forge.",
    ),
    (
        re.compile(r"size mismatch|shape|unexpected key|missing key", re.I),
        "Past failures mention tensor shape/key mismatches: Forge loaded it as the wrong architecture, or it is not a "
        "full checkpoint.",
    ),
    (
        re.compile(r"lora.*(not verified|incompatible|family)", re.I),
        "Past failures came from LoRAs that do not match this checkpoint's family; probe it without LoRAs first.",
    ),
    (
        re.compile(r"timeout|timed out|connection|refused", re.I),
        "Past failures were connection/timeouts to the WebUI, not necessarily the model.",
    ),
)

_LINEAGE_FAMILY = (
    ("pony", "sdxl"),
    ("illustrious", "sdxl"),
    ("sdxl", "sdxl"),
    ("flux", "flux"),
    ("sd 1", "sd1"),
    ("sd 2", "sd2"),
    ("sd 3", "sd3"),
)


def _family_of_label(label: str) -> str:
    lowered = label.casefold()
    for token, family in _LINEAGE_FAMILY:
        if token in lowered:
            return family
    return ""


def _top(history: ModelRunSummary | None, name: str) -> str:
    if history is None:
        return ""
    values = dict(history.settings).get(name) or ()
    return str(values[0][0]) if values else ""


def triage(
    *,
    header: Mapping[str, Any] | None,
    family: str,
    history: ModelRunSummary | None,
    civitai_base_model: str = "",
) -> list[str]:
    header = header or {}
    architecture = str(header.get("checkpoint_architecture") or "")
    variant = str(header.get("checkpoint_variant") or "")
    quantized = header.get("quantization_formats") or ()
    fmt = str(header.get("format") or "")
    error = str(header.get("error") or "")
    causes: list[str] = []
    if "malformed" in error or "truncated" in error:
        causes.append(
            "The file header is malformed or truncated: the download is probably incomplete. Re-download it and "
            "verify again."
        )
    if architecture == "sdxl_inpaint":
        causes.append(
            "This is an inpainting checkpoint (9-channel input). It works for inpaint/img2img with a mask; plain "
            "txt2img gives noise or broken images."
        )
    elif architecture == "sdxl_refiner":
        causes.append(
            "This is the SDXL refiner: a second pass (img2img at low denoise) after an SDXL base, not a standalone "
            "txt2img model."
        )
    elif quantized or fmt == "gguf":
        causes.append(
            "Quantized weights ("
            + ", ".join(str(item) for item in quantized or (fmt,))
            + "): Forge needs the matching loader plus separate text encoder and VAE files."
        )
    elif architecture == "unrecognized" and not error:
        causes.append(
            "The tensor layout is not a full SD1/SD2/SDXL checkpoint. It may be diffusion-only weights (Flux, SD3) "
            "needing separate text encoders and VAE, or a LoRA/VAE filed as a checkpoint."
        )
    if variant == "turbo":
        used = _top(history, "steps")
        causes.append(
            "Turbo distilled model: it expects about 1–4 steps, CFG about 1 and 512×512"
            + (
                f"; your completed runs mostly used {used} steps, which over-cooks it."
                if used
                else "."
            )
        )
    lineage = _family_of_label(civitai_base_model)
    if lineage and family and family not in ("unknown",) and lineage != family:
        causes.append(
            f"Civitai lists it as {civitai_base_model}, but StableNew resolved family '{family}'. Settings for the "
            "wrong lineage commonly produce artifacts."
        )
    elif civitai_base_model and family == "unknown":
        causes.append(
            f"Civitai lists it as {civitai_base_model}; StableNew could not classify it. Probe with that lineage's "
            "recipe, then classify it if the images look right."
        )
    if history is not None:
        seen: set[str] = set()
        for message, _count in history.errors:
            for pattern, cause in _ERROR_PATTERNS:
                if pattern.search(message) and cause not in seen:
                    seen.add(cause)
                    causes.append(cause)
        if history.failed and not history.completed and not seen:
            causes.append(
                f"All {history.failed} past attempts failed; their messages are listed under PAST RUNS."
            )
    if not causes:
        causes.append(
            "No structural or history problem is visible. Artifacts usually come from settings for the wrong "
            "lineage: compare recipes with a probe."
        )
    causes.append("Confirm with a Compatibility Probe (suggested recipes are preselected).")
    return causes
