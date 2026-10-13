# PR-IMG-BACKEND-QUAL-100 — Forge vs. ComfyUI Still-Image Qualification

## Decision and limits

**Architecture feasibility: CONDITIONAL. Quality/performance comparison: INCONCLUSIVE.
Physical execution: HOLD. Production promotion: NO-GO until controlled evidence establishes incremental value.**

Retain Forge as the default production image backend. Comfy's pinned core has plausible value for explicit
reference-conditioning graphs, model families and targeted job observation/cancellation, but source support
and successful video exposures do not qualify a production still-image path. No new default, adapter, NJR
schema, compiler, queue, runner, process owner or lifecycle store is introduced here.

The October 12 GPU device-loss incident blocks physical comparison on this workstation. Source analysis and
deterministic tooling are complete independently of that fault. This report neither attributes the fault to
Forge nor claims that switching to Comfy would fix it.

## Execution Profile + Model/Reasoning Recommendation

Standard, qualification-focused package. Codex: GPT-6.1 Sol High; Claude Code: Sonnet 5.5 High.
Local/Desktop fits the installed runtime/asset evidence and retained work. Expected successful-work cost
favors continuing the existing specification over rediscovery; deeper scrutiny is reserved for comparison
fairness, ambiguous dispatch and resource evidence. Controller Surface Assessment: **none touched**.
Token-Efficient Validation Plan: test pure specification/graph/inventory/protocol seams with synthetic files,
check citations against retained local source, run affected Ruff and applicable mypy, inspect the aggregate
diff and run the canonical PR gate once near closeout. No GPU tests or runtime actions.

## Verified prerequisite and continuation

PR #97 is merged (2026-10-13 02:19:11 UTC). The verified remote main and local branch base are
`990d062ddc580aa4d8f8c4b986825a9ecaad7e60`. Continued Claude's existing
`qual/img-backend-qual-100-forge-vs-comfy` in `C:/Users/rob/projects/StableNew-main`.
Six untracked qualification modules were present; they were copied and hashed before continuation.
Unrelated `data/photo_optimize/` remains untracked and untouched. No publication or merge is authorized.

## Runtime evidence

| Runtime | Declared and installed source HEAD | Installed interpreter/package metadata | Authority and scope |
|---|---|---|---|
| Forge Neo | `d70373ebcf1a96d210b78cd6f77196459e783e2a` | Python 3.13.16; Torch 2.13.0+cu130 | `config/managed_forge_runtime.json`; WebUIProcessManager; configured 7871; production image path |
| ComfyUI v0.38.0 | `6b747c0428c343e1417219641db93a4fb7cb69ae` | Python 3.13.16; Torch 2.14.0+cu130 | `config/managed_comfy_runtime.json`; ComfyProcessManager; configured 8188; qualified video only |

Inventory reads source HEAD, pyvenv.cfg and dist-info directory names; it is not a full package verification
or proof of a clean installed source tree. Existing managed-runtime verifiers remain authoritative. Comfy's
custom-node policy is `none`; no unlisted custom-node entries were observed. No Comfy process or listener
was present during the incident inspection. Forge remained listening despite unusable CUDA.

## Controlled matrix and model identity

One common SDXL baseline plus optional SDXL LoRA/OpenPose probes; at most one modern candidate,
**FLUX.2 Klein 4B FP8** (portrait/product/single-reference settings from PR-IMG-115). Proposed graphs use
batch_size=1 and stable seeds, and separate cold/warm cases. These are definitions, not executed jobs.
Klein **9B BF16 remains excluded** by PR-IMG-MODELS-151's NO_GO_RESOURCE_RISK. No Qwen image-generation
model is established by the existence of Qwen text encoders.

Read-only SHA-256 observations on October 12/13, with size/mtime checked before and after each read:

| File | Bytes | SHA-256 |
|---|---:|---|
| cyberrealisticXL_v90-16fp.safetensors | 6,938,040,682 | `4f2dc6418c8d93737e2d0a5f022707977c783851e79ccd23aed1fda8397ac10e` |
| add-detail-xl.safetensors | 228,452,344 | `0d9bd1b873a7863e128b4672e3e245838858f71469a3cec58123c16c06f83bd7` |
| colossusProjectXLSFW_12cExperimental3.safetensors | 6,941,319,204 | `afec7180209fa55b01a027ceaca0b8f40b2cf6e5b000b586230199cbbaa66e52` |
| thibaud_xl_openpose.safetensors | 2,502,139,104 | `9e070426568a3c60c128ffb98c66cdc7a0ea21d0d8abb86f73564aaf2e0c6f42` |
| flux-2-klein-4b-fp8.safetensors | 4,070,624,520 | `97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6` |
| qwen_3_4b.safetensors | 8,044,982,048 | `6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a` |
| flux2-vae.safetensors | 336,211,292 | `868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3` |

SDXL/LoRA/OpenPose files are visible through ComfyRuntime's existing extra-model paths. The exact Klein
transformer and encoder are installed under managed Forge's data/models, but those folders are **not** in
Comfy's configured diffusion_models/text_encoders search paths. The VAE is visible. No configuration was
changed. A future qualified run must explicitly bind existing exact files through its approved isolated
layout; it cannot substitute the differently named Qwen encoder in the A1111 library or download assets.

## Capability ledger and source locations

`tools/qualification/img_backend_qual_100/capability.py::capability_matrix` contains 24 individually cited
rows and separates historical physical evidence, source evidence, absence in the qualified configuration
and unverified behavior. Fifty cited references/symbols were checked against repository and installed runtime
source with no missing citation; existence checks support references, not automatic proof of every inference.
`cli.py::build_packet` emits those rows, workload/graph digests, source-class checks and model visibility.

| Dimension | Evidence-backed finding | Remaining uncertainty |
|---|---|---|
| SDXL, LoRA, img2img, upscaling | Forge accepted FORGE-100 paths; Comfy core `nodes.py` and `comfy_extras/nodes_upscale_model.py` expose the needed primitives | Complete Comfy image graphs and output behavior are unqualified |
| OpenPose | Forge's CNET-210 physical check used one pose/checkpoint; Comfy core ControlNetLoader/ControlNetApplyAdvanced exist | Conditioning semantics, output quality and exact weight loading need a controlled run |
| Reference editing | Comfy `comfy_extras/nodes_edit_model.py::ReferenceLatent` appends reference latents; Forge Klein single-reference passed, multi-reference API was rejected in IMG-115 | Multiple-reference model behavior/resource cost is source-only, not a proven product advantage |
| Detail restoration | Qualified Forge ADetailer-Neo exists; no qualified detector-driven Comfy equivalent under custom-node policy `none` | Mask/inpaint primitives alone do not establish face/hand detector parity; widening node policy requires approval |
| New model families | Pinned source includes Qwen-Image/Z-Image architecture support | No Qwen image bundle/readiness or fair cross-runtime Z-Image comparison established here |
| Dispatch/replay | Comfy `server.py` accepts caller-chosen UUID prompt_id; queue/history can positively correlate a request | UUID is not an idempotency key; missing queue/history proves nothing, especially after runtime loss. Never replay an ambiguous POST automatically |
| Cancellation | Comfy `server.py` permits targeted prompt interruption and deletion of pending items | Still-image adapter cancellation must stay subordinate to JobService/repository lifecycle and existing ownership rules |
| Runtime/artifacts | Existing `src/video/comfy_api_client.py`, ComfyProcessManager, workflow catalogs, resource-transition and output-observation seams are reusable | An image-specific adapter/catalog/readiness policy is still needed; Comfy's queue/history remain backend private |
| Quality/performance | Retained Forge artifacts, timings and resource observations exist | No Comfy still-image outputs, keeper votes, cold/warm measurements, model-switch costs or matched current-driver comparison exist |

## Fairness critiques

Same weights/geometry/steps/seed mean controlled intent, not identical computation. Sampler implementations,
schedulers (including Automatic resolution), precision/quantization and RNG behavior need explicit evidence.
The proposal marks sampler/CLIP-skip mappings approximate and seed equality unverified. Forge Automatic VAE
does not prove checkpoint-baked VAE identity. Reference-latent mechanisms differ. Torch versions differ.
Historical Forge resource measurements were collected in other sessions/platform states and cannot establish
a contemporary speed/VRAM advantage. Blind owner review of matched outputs is needed for keeper quality;
no invented numerical quality threshold or default change is justified by the source ledger.

## Proposed physical protocol — not executed

`protocol.py` defines three separately authorized proposed stages: SDXL cold/warm plus LoRA (3 requests),
OpenPose (1), Klein 4B portrait/product/reference edit (3). No retries or ambiguous-POST replay. Suggested
qualification port 8196 is a proposal, not a second process owner; future execution must use the existing
manager and exclusivity/resource-transition rules. This package deliberately contains **no runtime driver**.

Proposed stage/case/startup deadlines, RAM/VRAM/temperature limits and graph/model identities are sealed into
digests. They are conservative review proposals, not proven-safe thresholds. Require explicit recent-fault
clearance, fresh readable GPU telemetry, clean source/runtime identity, exact file hashes, a free approved port,
adequate host RAM and no conflicting GPU workload. Missing clearance or telemetry refuses readiness. Stop on
device loss, CUDA fault, memory/temperature threshold, resource-observation failure, timeout, unexpected
ownership, identity or ambiguous dispatch. Capture actual graph/request hashes, prompt_id, queue/history
responses, output hashes/dimensions, timing, telemetry and immediate/settled owned-runtime cleanup evidence.
No automatic backend substitution, driver reset, reboot or ambiguous replay is permitted.

Historical Forge artifacts can anchor capabilities. A performance comparison needs a separately authorized
contemporary Forge baseline with matching input/settings and recorded backend differences. Qualification
authorization-record validation checks digests/expiry/source/owner fields only; a file cannot authorize execution
or authenticate human approval. The explicit owner decision remains required in the future executing chat.

## Workstation fault and prioritization

Survivor telemetry identifies an active Forge SDXL txt2img job and brackets GPU loss at
2026-10-12 **22:28:01.544–22:28:02.612 ET**. Last valid sample: 76 C, 9,169/12,282 MiB VRAM,
247.47 W and 8,561.8 MB host RAM available. Fourteen jobs then failed with AcceleratorError while HTTP
remained responsive. NVIDIA currently reports GPU lost and recommends reboot. The current read-only SQLite
inspection found no queued/running rows. No queue, runtime, driver or settings mutation was performed.

Those samples do not demonstrate OOM or obvious core overheating; they cannot exclude transients or identify
hardware/driver causation. WER codes 141/1A8/1B8 reference current watchdog artifacts. Old reports were also
re-emitted in the same burst and are not new-crash counts. Private WER/dump access was denied: attribution needs
an administrator-supported handoff. The retained capture and analysis are in
`C:/Users/rob/qual/GPU-20261012-2228/incident.md`, with logs, event XML, survivor records, job timestamps,
model hashes, offline packet and Claude handoff copies. No memory files were updated.

**Next priority:** a separately approved GPU-device-loss containment investigation. PR-172 correctly prevents
ambiguous replay and contains dead endpoints; this incident shows the different case of a live HTTP endpoint
with unusable CUDA. Do not silently extend queue/recovery authority within this qualification package.

## Smallest justified follow-on

Do not start PR-IMG-COMFY-100 production implementation yet. First clear the workstation fault, confirm installed
Klein model visibility without substitution, and explicitly approve a bounded matched qualification. If it proves
useful reference-edit capability or a material resource/quality advantage, the smallest production slice is one
typed Comfy image adapter for one qualified model/mode, one frozen graph version and one image per NJR. Reuse
the existing compiler, image registry, JobService/SQLite/run_njr, Comfy process manager and artifact/history path.
Unsupported stages fail before dispatch. No Forge/Comfy per-stage composition or default switch belongs in it.

Expected scope comes from the adapter, model/readiness policy, graph catalog, dispatch/observation/cancellation
and artifact seams plus cross-boundary regression tests. It is a Standard-to-Architectural decision depending on
whether shared transport/lifecycle extraction is required; no unsupported human-day estimate is given.

## Validation

Focused offline contracts: 29 passed before final documentation. Affected Ruff passes. Seven-module supplemental
mypy has no code diagnostics when the two missing third-party stub boundaries are excluded; strict supplemental
mypy reports missing PyYAML/psutil stubs. No install/environment change was made. The required canonical mypy
smoke and final PR gate results are reported at closeout. Physical readiness remains HOLD regardless of test results.
