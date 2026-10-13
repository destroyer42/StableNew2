"""The frozen comparison specification: workloads, parameter mapping and equivalence classes (pure, no I/O except the
tracked intent contract).

Forge-side values come from retained FORGE-100, IMG-115 and CNET-210 evidence. That evidence is a historical
reference, not a contemporaneous performance baseline. A parameter that cannot be matched is recorded as such.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_ID = "PR-IMG-BACKEND-QUAL-100"
SPEC_REVISION = "1"
FORGE_BACKEND = "forge_webui"
COMFY_BACKEND = "comfyui"
REPO_ROOT = Path(__file__).resolve().parents[3]
SDXL_INTENT_PATH = REPO_ROOT / "tests" / "data" / "contracts" / "img_forge_100_frozen_intent.json"

# Parity classes. A workload parameter is exactly one of these; the report never upgrades one to another.
EQUIVALENT = "equivalent"  # same numeric value and the same named algorithm on both sides
APPROXIMATE = "approximate"  # same intent, documented implementation difference
UNEQUAL = (
    "unequal"  # cannot be matched; stated so that no result is read as a like-for-like comparison
)
UNVERIFIED = "unverified"  # no evidence either way
PARITY_CLASSES = (EQUIVALENT, APPROXIMATE, UNEQUAL, UNVERIFIED)

# Workload identities (stable; used by the protocol, the matrix and the adjudication).
S1 = "S1_SDXL_BASELINE"
S3 = "S3_SDXL_LORA"
S2 = "S2_SDXL_OPENPOSE"
K1 = "K1_KLEIN_PORTRAIT"
K2 = "K2_KLEIN_PRODUCT"
K3 = "K3_KLEIN_SINGLE_REFERENCE_EDIT"

#: S2 reuses the PR-IMG-CNET-210 physical check exactly (its Forge evidence is retained machine-local).
S2_SETTINGS: dict[str, Any] = {
    "checkpoint": "colossusProjectXLSFW_12cExperimental3",
    "prompt": "a woman waving with her right hand in a sunlit park, full body shot, photorealistic, natural light",
    "negative_prompt": "lowres, bad anatomy, blurry, deformed hands, extra limbs",
    "seed": 424242,
    "steps": 20,
    "cfg_scale": 6.0,
    "sampler_name": "Euler a",
    "scheduler": "Automatic",
    "width": 1024,
    "height": 1024,
    "clip_skip": 2,
    "controlnet_model": "thibaud_xl_openpose",
    "controlnet_preprocessor": "None",
    "controlnet_weight": 1.0,
    "controlnet_guidance_start": 0.0,
    "controlnet_guidance_end": 1.0,
    "pose_image_name": "cnet210_check_pose.png",
    "pose_image_sha256": "abeefcae5692ed063b22d79c7c9fbe726ac03f4cd4d974ae324f9c32491b6752",
    "pose_image_size": 9453,
    "asset_identities": {
        "colossusProjectXLSFW_12cExperimental3.safetensors": {
            "size": 6941319204,
            "sha256": "afec7180209fa55b01a027ceaca0b8f40b2cf6e5b000b586230199cbbaa66e52",
        },
        "thibaud_xl_openpose.safetensors": {
            "size": 2502139104,
            "sha256": "9e070426568a3c60c128ffb98c66cdc7a0ea21d0d8abb86f73564aaf2e0c6f42",
        },
    },
}

#: K3 edits the exact IMG-115 case-A artifact (the same input on both backends, never a Comfy-generated image).
K3_REFERENCE: dict[str, Any] = {
    "label": "IMG-115 case A output (outputs/case-A.png)",
    "sha256": "8a722fdc49d8f5bcc34b7e6c7ad0a2f2f741d7cd46773d2d2b1c1d282432e2ff",
    "size": 1345091,
}

#: Forge sampler / scheduler display names to the ComfyUI identifiers the qualification graphs use.
SAMPLER_MAP = {"Euler a": "euler_ancestral", "Euler": "euler", "DPM++ 2M": "dpmpp_2m"}
SCHEDULER_MAP = {"Karras": "karras", "Beta": "beta", "Automatic": "normal", "Simple": "simple"}


def digest(value: Any) -> str:
    """Canonical SHA-256 of a JSON-able value (stable key order, no whitespace)."""

    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class Parameter:
    name: str
    forge: Any
    comfy: Any
    parity: str
    note: str = ""

    def __post_init__(self) -> None:
        if self.parity not in PARITY_CLASSES:
            raise ValueError(f"unknown parity class {self.parity!r}")


@dataclass(frozen=True)
class Workload:
    workload_id: str
    family: str  # sdxl | flux2_klein
    kind: str  # txt2img | edit
    settings: dict[str, Any]
    parameters: tuple[Parameter, ...] = field(default_factory=tuple)
    forge_evidence: tuple[str, ...] = ()  # existing accepted Forge evidence this workload reuses

    def identity(self) -> dict[str, Any]:
        return {
            "workload_id": self.workload_id,
            "family": self.family,
            "kind": self.kind,
            "settings": self.settings,
            "parameters": [
                {
                    "name": p.name,
                    "forge": p.forge,
                    "comfy": p.comfy,
                    "parity": p.parity,
                    "note": p.note,
                }
                for p in self.parameters
            ],
            "forge_evidence": list(self.forge_evidence),
        }

    @property
    def digest(self) -> str:
        return digest(self.identity())

    def unequal_or_unverified(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.parameters if p.parity in (UNEQUAL, UNVERIFIED))


def load_sdxl_baseline(path: Path = SDXL_INTENT_PATH) -> dict[str, Any]:
    """The tracked FORGE-100 Pair-A settings (single authority; nothing is re-typed here)."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    settings = dict(data["settings"])
    keep = (
        "checkpoint",
        "prompt",
        "negative_prompt",
        "seed",
        "steps",
        "cfg_scale",
        "sampler_name",
        "scheduler",
        "width",
        "height",
        "clip_skip",
        "lora_name",
        "lora_strength",
        "vae",
    )
    return {key: settings[key] for key in keep}


def _sdxl_parameters(
    settings: dict[str, Any], *, lora: bool = False, openpose: bool = False
) -> tuple[Parameter, ...]:
    sampler = settings["sampler_name"]
    scheduler = settings["scheduler"]
    rows = [
        Parameter(
            "checkpoint",
            settings["checkpoint"],
            settings["checkpoint"],
            EQUIVALENT,
            "same file; identity is size + SHA-256, never the name",
        ),
        Parameter(
            "size",
            f"{settings['width']}x{settings['height']}",
            f"{settings['width']}x{settings['height']}",
            EQUIVALENT,
        ),
        Parameter("steps", settings["steps"], settings["steps"], EQUIVALENT),
        Parameter("cfg_scale", settings["cfg_scale"], settings["cfg_scale"], EQUIVALENT),
        Parameter(
            "sampler",
            sampler,
            SAMPLER_MAP.get(sampler),
            APPROXIMATE,
            "same named algorithm family; each runtime owns its own implementation",
        ),
        Parameter(
            "scheduler",
            scheduler,
            SCHEDULER_MAP.get(scheduler),
            APPROXIMATE,
            "Forge 'Automatic' resolves per model; the Comfy value is the explicit closest scheduler",
        ),
        Parameter(
            "clip_skip",
            settings["clip_skip"],
            -int(settings["clip_skip"]),
            APPROXIMATE,
            "display-value mapping only; SDXL encoder-layer semantics need validation",
        ),
        Parameter(
            "seed",
            settings["seed"],
            settings["seed"],
            UNVERIFIED,
            "both default to a CPU torch generator, but equal latents have not been demonstrated",
        ),
        Parameter(
            "prompt_parsing",
            "A1111 emphasis/BREAK/chunking",
            "Comfy CLIPTextEncode",
            APPROXIMATE,
            "the frozen prompts use no weights or BREAK; long-prompt chunking is not exercised",
        ),
        Parameter(
            "vae",
            settings.get("vae", "Automatic"),
            "checkpoint-baked",
            UNVERIFIED,
            "Forge Automatic does not prove the served VAE equals the checkpoint-baked VAE",
        ),
    ]
    if lora:
        rows.append(
            Parameter(
                "lora",
                f"{settings['lora_name']}@{settings['lora_strength']}",
                f"LoraLoader {settings['lora_strength']}/{settings['lora_strength']}",
                APPROXIMATE,
                "Forge applies the network from a prompt token; Comfy patches model and clip explicitly",
            )
        )
    if openpose:
        rows.append(
            Parameter(
                "controlnet",
                settings["controlnet_model"],
                settings["controlnet_model"],
                APPROXIMATE,
                "pre-rendered pose, preprocessor None on both; unit semantics are runtime-owned",
            )
        )
    return tuple(rows)


def build_workloads(*, sdxl_intent_path: Path = SDXL_INTENT_PATH) -> dict[str, Workload]:
    from tools.qualification.img115.spec import ASSETS as KLEIN_ASSETS
    from tools.qualification.img115.spec import CASES as KLEIN_CASES

    base = load_sdxl_baseline(sdxl_intent_path)
    # Retained managed-Forge expectations; revalidate every file before any future physical comparison.
    base["asset_identities"] = {
        "cyberrealisticXL_v90-16fp.safetensors": {
            "size": 6938040682,
            "sha256": "4f2dc6418c8d93737e2d0a5f022707977c783851e79ccd23aed1fda8397ac10e",
        },
        "add-detail-xl.safetensors": {
            "size": 228452344,
            "sha256": "0d9bd1b873a7863e128b4672e3e245838858f71469a3cec58123c16c06f83bd7",
        },
    }
    lora = dict(base)
    workloads: dict[str, Workload] = {
        S1: Workload(
            S1,
            "sdxl",
            "txt2img",
            {k: v for k, v in base.items() if k not in ("lora_name", "lora_strength")},
            _sdxl_parameters(base),
            ("docs/Subsystems/Image/PR-IMG-FORGE-100_Forge_Compatibility_Qualification.md",),
        ),
        S3: Workload(
            S3,
            "sdxl",
            "txt2img",
            lora,
            _sdxl_parameters(lora, lora=True),
            ("docs/Subsystems/Image/PR-IMG-FORGE-100_Forge_Compatibility_Qualification.md",),
        ),
        S2: Workload(
            S2,
            "sdxl",
            "txt2img",
            dict(S2_SETTINGS),
            _sdxl_parameters(S2_SETTINGS, openpose=True),
            ("docs/Subsystems/Image/PR-IMG-CNET-210_SDXL_OpenPose_ControlNet.md",),
        ),
    }
    assets = {
        role: {
            "filename": a.filename,
            "size": a.size,
            "sha256": a.sha256,
            "models_subdir": a.models_subdir,
        }
        for role, a in KLEIN_ASSETS.items()
    }
    for workload_id, case_id in ((K1, "A"), (K2, "B"), (K3, "C")):
        case = dict(KLEIN_CASES[case_id])
        settings = {**case, "assets": assets}
        if case["kind"] == "edit":
            settings["reference"] = dict(K3_REFERENCE)
        params: tuple[Parameter, ...] = (
            Parameter(
                "assets",
                "transformer+text_encoder+vae",
                "diffusion_models+text_encoders+vae",
                EQUIVALENT,
                "exact frozen files (size + SHA-256)",
            ),
            Parameter(
                "size",
                f"{case['width']}x{case['height']}",
                f"{case['width']}x{case['height']}",
                EQUIVALENT,
            ),
            Parameter("steps", case["steps"], case["steps"], EQUIVALENT),
            Parameter(
                "guidance",
                case["cfg_scale"],
                case["cfg_scale"],
                EQUIVALENT,
                "distilled model, CFG 1.0",
            ),
            Parameter(
                "sampler",
                case["sampler_name"],
                "euler",
                APPROXIMATE,
                "runtime implementations differ",
            ),
            Parameter(
                "scheduler",
                case["scheduler"],
                "beta",
                APPROXIMATE,
                "Comfy also ships Flux2Scheduler for this family; it is not the frozen Forge scheduler",
            ),
            Parameter("seed", case["seed"], case["seed"], UNVERIFIED),
        )
        if case["kind"] == "edit":
            params += (
                Parameter(
                    "reference_mechanism",
                    "img2img init image as reference latent",
                    "ReferenceLatent on conditioning",
                    APPROXIMATE,
                    "different mechanisms for the same single-reference intent",
                ),
            )
        workloads[workload_id] = Workload(
            workload_id,
            "flux2_klein",
            "edit" if case["kind"] == "edit" else "txt2img",
            settings,
            params,
            (
                "docs/Subsystems/Image/PR-IMG-115_FLUX2_Klein_4B_FP8_Target_Hardware_Qualification.md",
            ),
        )
    return workloads


def spec_digest(workloads: dict[str, Workload]) -> str:
    return digest(
        {
            "package": PACKAGE_ID,
            "revision": SPEC_REVISION,
            "workloads": {key: workloads[key].digest for key in sorted(workloads)},
        }
    )
