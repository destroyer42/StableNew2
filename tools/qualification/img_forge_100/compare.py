"""Compare reported facts without inventing a visual similarity acceptance threshold."""

from __future__ import annotations

from typing import Any

AGREEMENT_FIELDS = ("seed", "checkpoint", "vae", "lora", "stages", "prompt", "negative_prompt",
                    "sampler_name", "scheduler", "steps", "cfg_scale", "width", "height",
                    "img2img_denoise", "adetailer", "upscale")


def compare_settings(requested: dict[str, Any], reported: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in requested if key in AGREEMENT_FIELDS and key not in reported]
    differences = {key: {"requested": requested[key], "reported": reported[key]}
                   for key in AGREEMENT_FIELDS if key in requested and key in reported
                   and requested[key] != reported[key]}
    return {"agreement": not missing and not differences, "missing_evidence": missing,
            "differences": differences}


def compare_pair(a1111: dict[str, Any], forge: dict[str, Any]) -> dict[str, Any]:
    checks = {}
    for label, evidence, backend in (("a1111", a1111, "a1111_webui"), ("forge", forge, "forge_webui")):
        checks[label] = {
            "settings": compare_settings(evidence["requested"], evidence.get("reported", {})),
            "backend_identity": evidence.get("backend_id") == backend,
            "artifact_manifest_history": all(evidence.get(key) for key in ("artifacts", "manifest", "history")),
            "resources": evidence.get("resources"), "timing": evidence.get("timing"),
        }
    return {"checks": checks, "visual_verdict": "OWNER_REVIEW_PENDING", "perceptual_threshold": None}
