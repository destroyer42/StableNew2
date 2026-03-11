from __future__ import annotations

from datetime import datetime
from typing import Any


def _compact_prompt(prompt_text: str, *, limit: int = 36) -> str:
    text = " ".join(str(prompt_text or "").split())
    if not text:
        return "workspace"
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def _slug_fragment(value: str, *, limit: int = 18) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip())
    text = "_".join(part for part in text.split("_") if part)
    if not text:
        return "none"
    return text[:limit]


def build_experiment_identity(
    *,
    stage: str,
    variable_label: str,
    prompt_text: str,
    model: str = "",
    vae: str = "",
    timestamp: datetime | None = None,
) -> dict[str, str]:
    ts = timestamp or datetime.now()
    stage_label = str(stage or "txt2img").strip().lower() or "txt2img"
    variable = str(variable_label or "variable").strip() or "variable"
    prompt_preview = _compact_prompt(prompt_text)
    model_label = str(model or "default model").strip() or "default model"
    vae_label = str(vae or "automatic").strip() or "automatic"
    stamp = ts.strftime("%d%b%Y@%H%M").upper()
    file_stamp = ts.strftime("%Y%m%d_%H%M%S")
    name = (
        f"{file_stamp}_{_slug_fragment(stage_label)}_"
        f"{_slug_fragment(variable)}_{_slug_fragment(model_label)}_{_slug_fragment(vae_label)}"
    )
    description = (
        f"A {stage_label} comparison of {variable} using the prompt "
        f"'{prompt_preview}', with model '{model_label}' and VAE '{vae_label}', conducted {stamp}."
    )
    summary = f"{stage_label} | {variable} | {model_label} | {vae_label} | {stamp}"
    return {
        "name": name,
        "description": description,
        "summary": summary,
    }
