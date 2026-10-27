"""Curated research seeds; subtype records never attach by filename hints."""

from typing import Any

from src.generation_profiles.evidence_catalog import Claim, EvidenceCatalog, EvidenceRecord

REVIEWED = "2026-10-27"
HF = "https://huggingface.co/"


def _record(
    key: str,
    family: str,
    settings: dict[str, Any],
    source: str,
    *,
    scope: str = "variant",
    classification: str = "implementation",
    caveat: str = "Publisher example; Forge translation is unqualified.",
    technical: dict[str, Any] | None = None,
) -> EvidenceRecord:
    claims = [
        Claim(
            field,
            value,
            classification,
            source,
            REVIEWED,
            "Reviewed primary source; applies only to the named model lineage.",
            "high",
            caveat,
        )
        for field, value in {**settings, **(technical or {})}.items()
    ]
    return EvidenceRecord(
        key, "checkpoint", family, scope, tuple(claims), variant=key if scope == "variant" else ""
    )


def baseline_catalog() -> EvidenceCatalog:
    records = [
        _record(
            "sd1_reference",
            "sd1",
            {"sampler_name": "PLMS", "steps": 50, "cfg_scale": 7.5, "width": 512, "height": 512},
            "https://github.com/CompVis/stable-diffusion",
            technical={"text_encoders": ["CLIP ViT-L/14"]},
        ),
        _record(
            "sd2_base_512",
            "sd2",
            {},
            "https://github.com/Stability-AI/stablediffusion",
            technical={
                "restrictions": "SD2 512 baseline awaits live publisher-card verification; no inferred recipe."
            },
        ),
        _record(
            "sd2_768",
            "sd2",
            {},
            "https://github.com/Stability-AI/stablediffusion",
            technical={
                "restrictions": "SD2 768 subtype is separate; gated publisher card was unavailable during review."
            },
        ),
        _record(
            "sdxl",
            "sdxl",
            {"width": 1024, "height": 1024},
            HF + "stabilityai/stable-diffusion-xl-base-1.0",
            scope="family",
            classification="publisher_family",
            caveat="",
            technical={"text_encoders": ["OpenCLIP-ViT/G", "CLIP-ViT/L"]},
        ),
        _record(
            "sdxl_implementation",
            "sdxl",
            {"steps": 50, "cfg_scale": 5.0},
            HF + "docs/diffusers/api/pipelines/stable_diffusion/stable_diffusion_xl",
            scope="family",
        ),
        _record(
            "sdxl_forge_hypothesis",
            "sdxl",
            {"sampler_name": "Euler", "scheduler": "Automatic"},
            HF
            + "stabilityai/stable-diffusion-xl-base-1.0/blob/main/scheduler/scheduler_config.json",
            scope="family",
            classification="community",
            caveat="Native EulerDiscreteScheduler does not establish a Forge sampler/scheduler mapping.",
            technical={"native_scheduler": "EulerDiscreteScheduler"},
        ),
        _record(
            "sdxl_turbo",
            "sdxl",
            {"width": 512, "height": 512, "steps": 4, "cfg_scale": 0.0},
            HF + "stabilityai/sdxl-turbo",
            classification="exact_publisher",
            caveat="SDXL-Turbo only; 1-4 steps. Forge mapping and local executable support are unqualified.",
        ),
        _record(
            "flux1_dev",
            "flux",
            {"steps": 50, "cfg_scale": 3.5, "width": 1024, "height": 1024},
            HF + "black-forest-labs/FLUX.1-dev",
            technical={
                "context_length": 512,
                "restrictions": "Metadata only; not ordinary FLUX execution qualification.",
            },
        ),
        _record(
            "flux1_schnell",
            "flux",
            {"steps": 4, "cfg_scale": 0.0},
            HF + "black-forest-labs/FLUX.1-schnell",
        ),
        _record(
            "sd3_medium",
            "sd3",
            {"steps": 28, "cfg_scale": 7.0},
            HF + "stabilityai/stable-diffusion-3-medium-diffusers",
            technical={"text_encoders": ["CLIP ViT-L", "OpenCLIP ViT-G", "T5-XXL"]},
        ),
        _record(
            "sd35_medium",
            "sd3",
            {"steps": 40, "cfg_scale": 4.5},
            HF + "stabilityai/stable-diffusion-3.5-medium",
        ),
    ]
    for steps in (1, 2, 4, 8):
        records.append(
            _record(
                f"sdxl_lightning_{steps}step",
                "sdxl",
                {"steps": steps, "cfg_scale": 0.0, "width": 1024, "height": 1024},
                HF + "ByteDance/SDXL-Lightning",
                classification="exact_publisher",
                technical={
                    "native_scheduler": "Euler with trailing timesteps; ComfyUI Euler + sgm_uniform",
                    "restrictions": "Exact N-step identity and backend mapping required; 1-step is experimental.",
                },
            )
        )
    # These are projections of immutable executable authorities, never competing defaults.
    from src.generation_profiles.research import _klein, _zimage

    for profile in (_klein(), _zimage()):
        records.append(
            _record(
                profile.model.key,
                profile.model.family,
                dict(profile.settings),
                "local:src/generation_profiles/research.py",
                classification="exact_stablenew",
                caveat="",
                technical={
                    "restrictions": "Exact immutable executable profile and its resource/qualification restrictions remain final."
                },
            )
        )
    return EvidenceCatalog(tuple(records))
