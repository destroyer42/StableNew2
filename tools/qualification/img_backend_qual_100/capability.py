"""The evidence-backed capability matrix (static facts with references; no I/O).

Every assertion names its evidence. Four statuses are used and never blurred:

* ``VERIFIED``   - physically exercised on this workstation through the StableNew path and recorded;
* ``SOURCE``     - the runtime's own source/API supports it; no physical run exists for it here;
* ``ABSENT``     - confirmed not available in the qualified configuration;
* ``UNVERIFIED`` - neither established nor excluded.

A Comfy still-image row can therefore never be ``VERIFIED`` until a still-image run exists: the only physical Comfy
evidence in the repository is for video workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

VERIFIED = "VERIFIED"
SOURCE = "SOURCE"
ABSENT = "ABSENT"
UNVERIFIED = "UNVERIFIED"
STATUSES = (VERIFIED, SOURCE, ABSENT, UNVERIFIED)

DIM_CAPABILITY = "capability"
DIM_QUALITY = "quality"
DIM_PERFORMANCE = "performance"
DIM_ARCHITECTURE = "architecture"
DIMENSIONS = (DIM_CAPABILITY, DIM_QUALITY, DIM_PERFORMANCE, DIM_ARCHITECTURE)

# Evidence kinds. doc/code/config are repository-relative and checkable anywhere; comfy_source/forge_source are paths
# inside the pinned runtime source trees (machine-local, checked only when that tree is supplied); record is a
# machine-local evidence directory and is never checked.
K_DOC, K_CODE, K_CONFIG = "doc", "code", "config"
K_COMFY, K_FORGE, K_RECORD = "comfy_source", "forge_source", "record"

_FORGE100 = "docs/Subsystems/Image/PR-IMG-FORGE-100_Forge_Compatibility_Qualification.md"
_IMG115 = "docs/Subsystems/Image/PR-IMG-115_FLUX2_Klein_4B_FP8_Target_Hardware_Qualification.md"
_IMG117 = "docs/Subsystems/Image/PR-IMG-117_FLUX2_Klein_LoRA_Qualification_and_Profile_v2.md"
_CNET210 = "docs/Subsystems/Image/PR-IMG-CNET-210_SDXL_OpenPose_ControlNet.md"
_COMFY_RT = "docs/Subsystems/Video/PR-COMFY-RUNTIME-100_Managed_Comfy_Runtime.md"
_IMG100 = "docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md"


@dataclass(frozen=True)
class Evidence:
    kind: str
    ref: str  # repo-relative path, runtime-source-relative path, or a record label
    symbol: str | None = (
        None  # a text fragment that must appear in the file (doc/code/source kinds)
    )
    note: str = ""


@dataclass(frozen=True)
class Assessment:
    status: str
    evidence: tuple[Evidence, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if self.status != UNVERIFIED and not self.evidence:
            raise ValueError("a non-UNVERIFIED assertion must cite evidence")


@dataclass(frozen=True)
class CapabilityRow:
    row_id: str
    dimension: str
    question: str
    forge: Assessment
    comfy: Assessment
    parity: str  # equivalent | approximate | unequal | unverified (see spec)
    consequence: str = ""

    def __post_init__(self) -> None:
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"unknown dimension {self.dimension!r}")


def _doc(path: str, symbol: str | None = None, note: str = "") -> Evidence:
    return Evidence(K_DOC, path, symbol, note)


def _comfy(path: str, symbol: str, note: str = "") -> Evidence:
    return Evidence(K_COMFY, path, symbol, note)


def _forge(path: str, symbol: str, note: str = "") -> Evidence:
    return Evidence(K_FORGE, path, symbol, note)


def capability_matrix() -> tuple[CapabilityRow, ...]:
    rows: list[CapabilityRow] = []

    def add(*args: object, **kwargs: object) -> None:
        rows.append(CapabilityRow(*args, **kwargs))  # type: ignore[arg-type]

    # ---- capability ---------------------------------------------------------------------------------------------
    add(
        "sdxl_txt2img",
        DIM_CAPABILITY,
        "SDXL text-to-image through the StableNew path",
        Assessment(VERIFIED, (_doc(_FORGE100, "CANONICAL_FORGE_BASELINE_PASS"),)),
        Assessment(
            SOURCE,
            (
                _comfy("nodes.py", "class CheckpointLoaderSimple"),
                _comfy("nodes.py", "class KSampler"),
            ),
            "no still-image run exists",
        ),
        "approximate",
        "Comfy parity must be shown by a physical S1 run before any like-for-like claim.",
    )
    add(
        "lora",
        DIM_CAPABILITY,
        "LoRA application on SDXL",
        Assessment(VERIFIED, (_doc(_FORGE100, "Pair B"),)),
        Assessment(SOURCE, (_comfy("nodes.py", "class LoraLoader"),)),
        "approximate",
    )
    add(
        "img2img",
        DIM_CAPABILITY,
        "Image-to-image with a denoise strength",
        Assessment(VERIFIED, (_doc(_FORGE100, "Pair C"),)),
        Assessment(SOURCE, (_comfy("nodes.py", "class VAEEncode"), _comfy("nodes.py", "denoise"))),
        "approximate",
    )
    add(
        "detail_restoration",
        DIM_CAPABILITY,
        "Detector-driven face/hand detail restoration (ADetailer-equivalent)",
        Assessment(VERIFIED, (_doc(_FORGE100, "ADetailer-Neo"),)),
        Assessment(
            ABSENT,
            (
                Evidence(
                    K_CONFIG,
                    "config/managed_comfy_runtime.json",
                    '"policy": "none"',
                    "the managed runtime forbids custom nodes; Comfy core ships no detector inpaint",
                ),
            ),
            "would need a custom-node policy change, a detector runtime and its own qualification",
        ),
        "unequal",
        "A Comfy SDXL backend would regress the accepted ADetailer path until that gap is closed.",
    )
    add(
        "upscale_model",
        DIM_CAPABILITY,
        "Model-based upscaling with a resize factor",
        Assessment(VERIFIED, (_doc(_FORGE100, "4xUltrasharp"),)),
        Assessment(
            SOURCE,
            (
                _comfy("comfy_extras/nodes_upscale_model.py", "class ImageUpscaleWithModel"),
                _comfy("nodes.py", "class ImageScaleBy"),
            ),
        ),
        "approximate",
        "A fixed 1.5x factor needs a 4x model followed by ImageScaleBy; not exercised.",
    )
    add(
        "controlnet_openpose_prerendered",
        DIM_CAPABILITY,
        "Pre-rendered OpenPose map conditioning on SDXL",
        Assessment(
            VERIFIED, (_doc(_CNET210, "Physical verification"),), "one pose, one checkpoint"
        ),
        Assessment(
            SOURCE,
            (
                _comfy("nodes.py", "class ControlNetLoader"),
                _comfy("nodes.py", "class ControlNetApplyAdvanced"),
            ),
        ),
        "approximate",
    )
    add(
        "klein4b_txt2img",
        DIM_CAPABILITY,
        "FLUX.2 Klein 4B FP8 text-to-image",
        Assessment(VERIFIED, (_doc(_IMG115, "FLUX2_KLEIN_4B_FP8_PASS_CONSTRAINED"),)),
        Assessment(
            SOURCE,
            (
                _comfy("comfy_extras/nodes_flux.py", "class EmptyFlux2LatentImage"),
                _comfy("nodes.py", '"flux2"', "CLIPLoader type"),
            ),
        ),
        "approximate",
    )
    add(
        "klein_single_reference_edit",
        DIM_CAPABILITY,
        "Single-reference image editing (Klein)",
        Assessment(VERIFIED, (_doc(_IMG115, "single-reference"),)),
        Assessment(SOURCE, (_comfy("comfy_extras/nodes_edit_model.py", "class ReferenceLatent"),)),
        "approximate",
    )
    add(
        "klein_multi_reference_edit",
        DIM_CAPABILITY,
        "Two-or-more-reference editing (Klein)",
        Assessment(
            ABSENT,
            (_doc(_IMG115, "FORGE_API_INTEGRATION_GAP"),),
            "the pinned Forge API rejects the built-in stitch script; model quality was never determined",
        ),
        Assessment(
            SOURCE,
            (
                _comfy("comfy_extras/nodes_edit_model.py", "class ReferenceLatent"),
                _comfy("comfy_extras/nodes_flux.py", "class FluxKontextMultiReferenceLatentMethod"),
            ),
            "chaining ReferenceLatent is a graph property; never run here",
        ),
        "unequal",
        "The one capability where Comfy plausibly adds value, and it is unverified.",
    )
    add(
        "klein_lora",
        DIM_CAPABILITY,
        "LoRA on Klein",
        Assessment(VERIFIED, (_doc(_IMG117, "qualified"),)),
        Assessment(SOURCE, (_comfy("nodes.py", "class LoraLoader"),)),
        "unverified",
    )
    add(
        "zimage_turbo",
        DIM_CAPABILITY,
        "Z-Image-Turbo FP8",
        Assessment(
            UNVERIFIED,
            (),
            "implemented behind the Forge backend; physical qualification ended INSTRUMENTATION_GAP",
        ),
        Assessment(SOURCE, (_comfy("comfy/supported_models.py", "class ZImage"),)),
        "unverified",
    )
    add(
        "qwen_image_family",
        DIM_CAPABILITY,
        "Qwen-Image family generation",
        Assessment(
            SOURCE,
            (_forge("backend/diffusion_engine/qwen.py", "class"),),
            "the engine exists in the pinned Forge; StableNew has no profile for it",
        ),
        Assessment(SOURCE, (_comfy("nodes.py", '"qwen_image"', "CLIPLoader type"),)),
        "unverified",
        "No installed Qwen image-generation model is established; text encoders do not imply one.",
    )

    # ---- architecture -------------------------------------------------------------------------------------------
    add(
        "submission_semantics",
        DIM_ARCHITECTURE,
        "Dispatch semantics and ambiguity window",
        Assessment(
            VERIFIED,
            (_doc(_IMG100, "ambiguous dispatched-POST non-replay"),),
            "the generation POST is synchronous; a lost response leaves the outcome ambiguous",
        ),
        Assessment(
            SOURCE,
            (
                _comfy("server.py", "validate_job_id"),
                _comfy("server.py", 'json_data.get("prompt_id")'),
            ),
            "/prompt is asynchronous and accepts a client-chosen UUID prompt_id; status is readable afterwards",
        ),
        "unequal",
        "A known prompt_id permits positive queue/history correlation. Absence proves nothing; the UUID is not an idempotency key and never authorizes POST replay.",
    )
    add(
        "cancellation",
        DIM_ARCHITECTURE,
        "Operator cancellation",
        Assessment(VERIFIED, (_doc(_FORGE100, "interrupt"),), "global interrupt"),
        Assessment(
            SOURCE,
            (_comfy("server.py", "json_data.get('prompt_id')"),),
            "/interrupt can target a prompt_id; /queue can delete pending items",
        ),
        "approximate",
    )
    add(
        "runtime_ownership",
        DIM_ARCHITECTURE,
        "Owned lifecycle and external-process rules",
        Assessment(VERIFIED, (_doc(_FORGE100, "WebUIProcessManager"),)),
        Assessment(
            VERIFIED, (_doc(_COMFY_RT, "ComfyProcessManager"),), "video only; no still-image use"
        ),
        "equivalent",
    )
    add(
        "workflow_versioning",
        DIM_ARCHITECTURE,
        "Versioned, hash-pinned execution definition",
        Assessment(
            SOURCE,
            (
                Evidence(
                    K_CODE,
                    "src/image_backends/forge_webui_backend.py",
                    "class ForgeWebUIImageBackend",
                    "payloads are built by the backend; no workflow artifact",
                ),
            ),
        ),
        Assessment(
            SOURCE,
            (
                Evidence(
                    K_CODE,
                    "src/video/workflow_catalog.py",
                    "workflow",
                    "a versioned, hash-pinned graph catalog already exists for video",
                ),
            ),
        ),
        "unequal",
        "Comfy needs a still-image graph catalog; the pattern exists, the content does not.",
    )
    add(
        "custom_node_policy",
        DIM_ARCHITECTURE,
        "Extension ecosystem available to the managed runtime",
        Assessment(
            VERIFIED,
            (_doc(_FORGE100, "ADetailer-Neo"),),
            "pinned extensions are part of the managed identity",
        ),
        Assessment(
            ABSENT,
            (Evidence(K_CONFIG, "config/managed_comfy_runtime.json", '"policy": "none"'),),
            "no custom nodes by contract",
        ),
        "unequal",
    )
    add(
        "host_runtime_coexistence",
        DIM_ARCHITECTURE,
        "Runtime slots on one 12 GB GPU / ~34 GB host",
        Assessment(VERIFIED, (_doc(_FORGE100, "WebUIProcessManager"),)),
        Assessment(VERIFIED, (_doc(_COMFY_RT, "Resource gate"),), "video exposures"),
        "unverified",
        "Two image-capable runtimes would add a second resident-memory consumer; never measured together.",
    )

    # ---- performance --------------------------------------------------------------------------------------------
    add(
        "latency_cold_warm",
        DIM_PERFORMANCE,
        "Cold and warm single-image latency",
        Assessment(VERIFIED, (_doc(_FORGE100, "16.3 s"), _doc(_IMG115, "18.9 s"))),
        Assessment(
            UNVERIFIED, (), "no still-image measurement; Wan video wall times are not comparable"
        ),
        "unverified",
    )
    add(
        "vram",
        DIM_PERFORMANCE,
        "Peak dedicated VRAM",
        Assessment(VERIFIED, (_doc(_FORGE100, "8,118 MiB"), _doc(_IMG115, "9,420 MiB"))),
        Assessment(UNVERIFIED, (), "no still-image measurement"),
        "unverified",
    )
    add(
        "host_ram",
        DIM_PERFORMANCE,
        "Host RAM pressure during load",
        Assessment(
            VERIFIED,
            (_doc(_IMG115, "0.01 GB"),),
            "Klein drove available RAM to ~0 on this host and passed",
        ),
        Assessment(UNVERIFIED, (), "no still-image measurement"),
        "unverified",
        "The binding unknown for a Klein physical run: it needs a conservative RAM precondition.",
    )
    add(
        "model_switch_cost",
        DIM_PERFORMANCE,
        "Checkpoint/model-family switch cost and release",
        Assessment(VERIFIED, (_doc(_FORGE100, "model_switches"),)),
        Assessment(UNVERIFIED, (), "per-job recycling exists for video only"),
        "unverified",
    )

    # ---- quality ------------------------------------------------------------------------------------------------
    add(
        "sdxl_keeper_quality",
        DIM_QUALITY,
        "SDXL keeper quality for the frozen workload",
        Assessment(
            UNVERIFIED,
            (_doc(_FORGE100, "cross-engine parity is unadjudicated"),),
            "historical artifacts exist, but no matched keeper-quality verdict",
        ),
        Assessment(UNVERIFIED, (), "no output exists"),
        "unverified",
        "No quality threshold is invented: the verdict is owner review of a blind contact sheet.",
    )
    add(
        "klein_keeper_quality",
        DIM_QUALITY,
        "Klein keeper quality for the frozen cases",
        Assessment(
            UNVERIFIED,
            (_doc(_IMG115, "Observations"),),
            "historical observations are not a matched keeper-quality verdict",
        ),
        Assessment(UNVERIFIED, (), "no output exists"),
        "unverified",
    )
    return tuple(rows)


def validate_evidence(
    rows: tuple[CapabilityRow, ...],
    *,
    repo_root: Path,
    comfy_source: Path | None = None,
    forge_source: Path | None = None,
) -> dict[str, list[str]]:
    """Check that every cited reference exists. ``problems`` are citation errors; ``unchecked`` are machine-local."""

    problems: list[str] = []
    unchecked: list[str] = []
    checked = 0
    roots = {
        K_DOC: repo_root,
        K_CODE: repo_root,
        K_CONFIG: repo_root,
        K_COMFY: comfy_source,
        K_FORGE: forge_source,
    }
    for row in rows:
        for side, assessment in (("forge", row.forge), ("comfy", row.comfy)):
            for item in assessment.evidence:
                label = f"{row.row_id}.{side}: {item.kind}:{item.ref}"
                if item.kind == K_RECORD:
                    unchecked.append(label)
                    continue
                root = roots.get(item.kind)
                if root is None:
                    unchecked.append(label)
                    continue
                target = Path(root) / item.ref
                if not target.is_file():
                    problems.append(f"{label}: file missing")
                    continue
                checked += 1
                if item.symbol:
                    try:
                        text = target.read_text(encoding="utf-8", errors="replace")
                    except OSError as exc:
                        problems.append(f"{label}: unreadable ({exc})")
                        continue
                    if item.symbol not in text:
                        problems.append(f"{label}: {item.symbol!r} not found")
    return {"problems": problems, "unchecked": unchecked, "checked": [str(checked)]}


def matrix_summary(rows: tuple[CapabilityRow, ...]) -> dict[str, object]:
    forge = dict.fromkeys(STATUSES, 0)
    comfy = dict.fromkeys(STATUSES, 0)
    for row in rows:
        forge[row.forge.status] += 1
        comfy[row.comfy.status] += 1
    return {"rows": len(rows), "forge": forge, "comfy": comfy}
