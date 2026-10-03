# PR-IMG-FORGE-100 — Forge Neo Compatibility / A1111 Successor Qualification

Status: **QUALIFICATION_INFRASTRUCTURE_BLOCKED — attempt2 is preserved; prompt-intent repair
passes deterministic validation. Physical cohort3 requires renewed owner authorization.**
Forge is an explicit, **non-default** backend identity (`forge_webui`). `a1111_webui` remains the
default. Nothing here promotes Forge (that is `PR-IMG-FORGE-110`, a separate owner decision) and no
image parity verdict has been reached. The first attempt failed admission (sections16-17); the resumed
cohort passed that repaired surface but was refused for prompt mismatch before network generation
dispatch (section18). Neither attempt is evidence of Forge image failure.
The bounded canonical intent-preservation repair and no-generation evidence are recorded in section19.

Base: `origin/main` `715e352f28640cb0eb3225a5b1752fc5e192c778` (PR #35 / PR-TEST-TRUTH-210 merged).
Initial implementation/evidence: Claude Code cloud session. Local/Desktop installation and GET-only
runtime qualification now pass with the known Gradio/Pillow conflict; see section 15. No image parity verdict.

## 1. Qualification target and lineage

- Target: Forge Neo — `https://github.com/Haoming02/sd-webui-forge-classic`, branch `neo`.
- Discovery-reviewed commit: `97b26fb404314a11dad7cdde2706da57ea53f4f2` (2026-10-02).
  The owner authorized a bounded review of its direct child; the qualification pin is now
  **`d70373ebcf1a96d210b78cd6f77196459e783e2a`** (2026-10-03). See the local review below.
  Re-check the pinned source before installation; do not silently advance it again.
- Why Neo: it is the actively maintained continuation of the newer Forge line, keeps the A1111-compatible
  `/sdapi/v1` surface, targets CPython 3.13 (upstream tested 3.13.12), supports `--api`, and supports
  `--forge-ref-a1111-home` for read-only model-directory reuse. Original `lllyasviel` Forge is lineage and
  reference evidence only.
- License: AGPL-3.0. StableNew bundles nothing from Forge; the qualification runtime is a separate,
  operator-owned installation.
- Current upstream evidence did not change this conclusion; no STOP condition was met.

## 2. API compatibility matrix (source-level; physical confirmation pending)

Reviewed in `modules/api/api.py` and `modules_forge/main_entry.py` at the frozen commit. "Same" means the
route exists with the contract StableNew's existing client already uses.

| StableNew use | Forge Neo route | Result |
|---|---|---|
| txt2img | `POST /sdapi/v1/txt2img` | same |
| img2img (also the ADetailer REST endpoint) | `POST /sdapi/v1/img2img` | same |
| upscale (extras path) | `POST /sdapi/v1/extra-single-image` | same |
| progress | `GET /sdapi/v1/progress` | same |
| cancellation | `POST /sdapi/v1/interrupt` | same |
| options read/write | `GET`/`POST /sdapi/v1/options` | same; `sd_model_checkpoint` is routed through `checkpoint_change` and an unknown model raises |
| runtime flags | `GET /sdapi/v1/cmd-flags` | upstream HTTP 500 response-model defect; optional corroboration only |
| model/sampler/scheduler/upscaler lists | `GET /sdapi/v1/sd-models`, `samplers`, `schedulers`, `upscalers` | same |
| scripts | `GET /sdapi/v1/scripts`, `/script-info` | same |
| best-effort VRAM cleanup | `POST /sdapi/v1/unload-checkpoint`, `/refresh-checkpoints` | same |
| **VAE listing** | `GET /sdapi/v1/sd-modules` (VAE **and** text encoders, `{model_name, filename}`) | **different** — there is no `/sd-vae` |
| **VAE selection** | option `forge_additional_modules` (module name in, file paths out) | **different** — `sd_vae` is a non-interactive "Automatic" placeholder; unknown module names are **silently dropped**, which would clear the VAE |
| per-request VAE | `override_settings.sd_vae` handled specially in `modules/processing.py` (`_vae_override`) | needs physical confirmation |
| top-level `sd_model` / `sd_vae` payload keys | ignored (pydantic extras), same as A1111 | same |

StableNew never uses `server-kill`/`server-restart`/`server-stop`.

## 3. Architecture and runtime identity decisions (implemented)

Canonical path unchanged: `Intent -> Compiler -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr
-> ImageBackend -> Artifact/History`. No second queue, runner, history, compiler, cancellation or process
authority. No `ForgeProcessManager`. No GUI backend selector. No per-stage backend selection or fallback.

| Decision | Implementation |
|---|---|
| Durable identity | `FORGE_IMAGE_BACKEND_ID = "forge_webui"`; `DEFAULT_IMAGE_BACKEND_ID` stays `a1111_webui`; historical NJRs without an image backend still resolve to `a1111_webui` and can never silently run as Forge |
| One runtime slot, two identities | `WebUIProcessConfig.runtime_identity` / `WebUIProcessManager.runtime_identity` declare which identity the single existing manager launches (setting `webui_runtime_identity`, default `a1111_webui`). The manager remains the sole lifecycle authority |
| Read-only identity seam | `src/api/webui_runtime_identity.py`: Forge requires mapping `/options` with explicit known Forge-only keys **and** `/sd-modules` list, with no conflicting `/sd-vae` signature. A1111 requires readable options without Forge keys, `/sd-vae` list and unavailable `/sd-modules`, without contradictory Forge flags. Weak/malformed/conflicting evidence is `unknown`. `/cmd-flags` is optional. Probes remain GET-only |
| Guard before dispatch | `forge_webui` requires a positively identified Forge; `a1111_webui` rejects a positively identified Forge but tolerates an unclassifiable endpoint (existing A1111-family compatibility); runs after the runtime transition and before any stage call |
| Transport | `ForgeWebUIClient(SDWebUIClient)` overrides only the VAE contract: `get_vae_models` -> `/sd-modules` normalized to the existing `{model_name, filename}` resource shape; `set_vae` resolves against the listing, writes `forge_additional_modules` and **verifies by reading it back**; `get_current_vae` maps module paths to names. Everything else is inherited |
| Backend | `ForgeWebUIImageBackend` shares the A1111 stage translation. The A1111 translation was **extracted unchanged** into `WebUIFamilyImageBackend` (mechanically identical logic, pinned by the existing A1111 parity tests, all still green); the two backends differ only in identity, transition target and the guard. Capabilities: `txt2img`, `img2img`, `adetailer`, `upscale`. No `controlnet` stage |
| Client selection | `DefaultImageRuntimePorts.create_client` builds the client for the configured identity; the controllers are untouched; the client is never swapped under a `Pipeline` |
| Runtime transitions | `RUNTIME_FORGE_WEBUI`. Owned other identity in the shared slot is released only through the manager's own `stop_webui`; external A1111/Forge/Comfy are immutable (target external is used; conflicting external -> `ACTION_REQUIRED`; unknown ownership -> no mutation). An endpoint not positively Forge blocks a Forge target; an unclassifiable endpoint is tolerated for an A1111 target. Comfy/SVD targets release whichever owned WebUI-family runtime exists |

Controller surface: **no ratcheted controller changed** (`AppController`, `PipelineController` and the other ratcheted coordinators are untouched). The only file under `src/controller/` that changed is the runtime-ports factory `src/controller/ports/default_runtime_ports.py`, which owns client construction by design; the controller ratchet passes unchanged.

### Files changed so far (source)

`src/api/webui_runtime_identity.py` (new), `src/api/forge_client.py` (new), `src/api/client.py` (probe + `sd-modules`
startup-grace entry), `src/api/webui_process_manager.py` (declared identity), `src/utils/config.py` (default
setting), `src/controller/ports/default_runtime_ports.py` (client selection), `src/services/runtime_transition_service.py`
(Forge target/policy), `src/image_backends/` (`webui_family_backend.py` and `forge_webui_backend.py` new;
`a1111_webui_backend.py` reduced to its identity; registry/types/exports), `config/forge_qualification_runtime.json`
(new descriptor).

## 4. Historical ADetailer source-review decision (superseded by section 15)

- Initial candidate: **`Bing-su/adetailer` @ `3a599f5d4607d8f9d8b9fc5a15526197418dae1a` (v26.2.0)**, the
  maintained upstream. It ships a Forge ControlNet bridge, and every `modules.*` symbol it imports exists in
  Neo at the frozen commit. That is static evidence only.
- **Detector acquisition is the hard gate.** The extension resolves `face_yolov8n.pt`/`hand_yolov8n.pt` through
  `huggingface_hub.hf_hub_download` (network, HuggingFace cache), not from `models/adetailer`, and
  `--forge-ref-a1111-home` does **not** map an A1111 `models/adetailer` directory. In an isolated Forge venv the
  first launch would therefore download them. Downloads are not authorized, so a fail-closed run needs:
  `--ad-no-huggingface` (local-files-only) **and** the `ad_extra_models_dir` option pointing at an existing local
  directory that already contains both detectors. If they cannot be resolved locally: **STOP before downloading**.
  `--ad-no-huggingface` deviates from the three-flag launch contract and needs explicit owner approval.
- The extension's `install.py` pip-installs `ultralytics>=8.3.75` and `mediapipe>=0.10.13` into the Forge venv on
  first load (package download, owner authorization required). Availability of a `mediapipe` build for CPython
  3.13 on the target machine is **unverified** and can block extension load; if so, STOP and report.
- MediaPipe is not a substitute; StableNew's accepted contract is the REST payload with YOLO detectors.
- Ecosystem compatibility reports for Forge Neo + ADetailer were not verified from the cloud session. Only a
  physical run can show that StableNew's actual `alwayson_scripts` payload, detector identities, prompts,
  confidence, inpaint dimensions, denoise and pass-enable semantics survive, and that LoRA behavior is not lost.

## 5. ControlNet (read-only qualification only)

StableNew has no ControlNet image stage and none is added. Forge's built-in ControlNet
(`extensions-builtin/sd_forge_controlnet`, script title "ControlNet") is to be confirmed read-only on the
running endpoint: listed by `/sdapi/v1/scripts`, and referenced ControlNet model directories visible
(`--forge-ref-a1111-home` maps `ControlNet` and `ControlNetPreprocessor`). Nothing is mutated or downloaded.
Read-only capability is now observed: script, script-info, model-list and module-list API evidence.
**FORGE_CONTROLNET_RUNTIME_CAPABILITY_PRESENT**. `/controlnet/version` is unavailable; no inference,
download or StableNew ControlNet stage was added.

## 6. Deterministic validation (mocks only; no real HTTP/GPU/model/user data)

New and extended tests (all green at this checkpoint):

| # | Contract point | Evidence |
|---|---|---|
| 1 | durable `forge_webui` identity | `tests/image_backends/test_forge_webui_backend.py` |
| 2 | default remains `a1111_webui` | same, plus registry test |
| 3 | historical no-ID stays A1111 | same (backend + runner mismatch case) |
| 4 | replay preserves identity, new lineage | same |
| 5 | registry contains Forge, not default | same |
| 6 | unsupported stages fail before dispatch | same (registry + backend) |
| 7 | A1111/Forge mismatch fails before generation POST | backend tests and `tests/integration/test_pr_img_forge_100_canonical_path.py` (zero generation POSTs, zero options writes) |
| 8 | detection read-only and deterministic | `tests/api/test_webui_runtime_identity.py` |
| 9 | VAE/module normalization | `tests/api/test_forge_client.py` |
| 10 | txt2img preserves prompt/negative/model/VAE/sampler/scheduler/steps/CFG/geometry/seed | backend test + canonical-path payload assertions |
| 11 | img2img preserves input image/denoise/model/VAE | backend test |
| 12 | ADetailer keeps the current payload | canonical chain test (`alwayson_scripts.ADetailer`, `ad_model`) |
| 13 | upscale keeps the extras path | canonical chain test (`extra-single-image`) |
| 14 | cancellation reaches `/sdapi/v1/interrupt` | `tests/pipeline/test_pr_img_forge_100_cancellation.py`, client test |
| 15 | failure before POST is safe | mismatch tests, unknown-VAE refusal |
| 16 | ambiguous post-dispatch failure is not replayed | canonical-path test (one POST, job FAILED) |
| 17 | artifact normalization records `image_backend_id=forge_webui` | backend + canonical-path tests |
| 18 | history records Forge identity | canonical-path test (snapshot + result metadata) |
| 19 | A1111 adapter parity | existing suites green; Forge/A1111 translation equality test |
| 20 | no controller/GUI builds backend payloads | `tests/safety/test_forge_backend_isolation_safety.py` |
| 21 | owned vs external A1111/Forge transitions | `tests/services/test_runtime_transition_forge.py` |

Also: `tests/controller/test_default_runtime_ports_forge.py`, `tests/api/test_webui_process_manager_identity.py`,
`tests/system/test_forge_qualification_descriptor.py`, and the stateful `tests/helpers/fake_webui_transport.py`
(Forge/A1111 flavors; only `requests.Session.request` is replaced). A mutation check (guard disabled) turned 9
tests red, confirming they bite.

### Checkpoint validation (exact tree of the checkpoint commit)

- Deterministic regression pass across `tests/image_backends`, `services`, `api`, `controller`, `pipeline`,
  `integration`, `safety`, `app`, `queue` and the seed-propagation test: **1683 passed, 1 skipped** (the skip is
  a Windows-only branch). The new `tests/system/test_forge_qualification_descriptor.py` (4 passed) was added after
  that pass.
- `python tools/ci/run_pr_gate.py`: **PR gate OK** (completeness, controller ratchet, Ruff, mypy smoke, collection
  of 4341 tests, required smoke 184 passed). `git diff --check`: clean.
- The informational full suite and exact-head GitHub CI have **not** been run for this package yet.

## 7. Initial matrix proposal (structure retained; current provenance in section 15)

Source/runtime/extension (proposed): Forge Neo `d70373eb…` on CPython 3.13.x in a dedicated venv; Neo's default
install resolves `torch 2.13.0+cu130` / `torchvision 0.28.0+cu130` and its `requirements.txt` pins; launch flags
`--api --port 7871 --forge-ref-a1111-home <A1111 root>` (port outside StableNew's 7860-7869 discovery range);
ADetailer `Bing-su/adetailer` `3a599f5d…`. Machine facts (Python/Torch/CUDA actually installed, driver, model
hashes) are captured at run time, not asserted here.

Owner decisions/inputs required before any physical step:

1. Authorize dependency/package downloads into the isolated Forge venv (Forge requirements, torch, and the
   extension's `ultralytics`/`mediapipe`). Checkpoint/VAE/LoRA/ControlNet/detector downloads stay unauthorized.
2. Approve `--ad-no-huggingface` and supply the existing local directory holding `face_yolov8n.pt` and
   `hand_yolov8n.pt` (for `ad_extra_models_dir`).
3. Supply the existing SDXL checkpoint, VAE, one LoRA (with strength) and one frozen img2img input image; the
   A1111 root for `--forge-ref-a1111-home`; the qualification install root.
4. Authorize the physical run of the 8-job matrix on the RTX 4070 Ti 12 GB machine.

Matrix (maximum 8 real jobs; each scenario runs as a matched A1111/Forge pair; no pixel identity required):

| Scenario | Stages | Frozen between arms |
|---|---|---|
| A | txt2img (SDXL baseline) | prompt/negative, seed, checkpoint, VAE, sampler, scheduler, steps, CFG, geometry |
| B | A + one existing LoRA | A + LoRA name + strength |
| C | img2img / reprocess | frozen input image (hash), denoise, model, VAE |
| D | txt2img -> ADetailer -> upscale | A + ADetailer pass settings (face + hands YOLO), upscaler/factor |

Proposed starting values (to be frozen by the owner at matrix approval, not yet frozen): sampler Euler a,
scheduler Karras, steps 24, CFG 5.5, geometry 832x1216, seed 424242. If real cancellation cannot be closed
deterministically, ONE additional inexpensive Forge cancellation run requires separate authorization. No retries
to obtain a PASS. Device loss: stop, preserve evidence, classify only the tested workload.

## 8. Physical results

Not run. Visual owner verdict, resource table, artifact/history/replay proof on the real runtime, contact
sheets, and the final classification (`FORGE_TECHNICAL_PASS / PRODUCT_PARITY_PASS`, `… PARITY_PENDING`,
`FORGE_CONDITIONAL`, `FORGE_NO_GO`) are recorded here only after the owner-authorized physical run. Until then
Forge is registered for explicit selection only, never default, with no GUI selector.

## 9. Remaining work (for the Local/Desktop session)

Qualification tooling under `tools/qualification/img_forge_100/` (`provenance.py`, `preflight.py`,
`runtime_capture.py`, `run.py`, `compare.py`, `contact_sheet.py`) has been added locally. Product matrix jobs enter through NJR -> JobService -> SQLite ->
`PipelineRunner.run_njr` -> the Forge backend (never direct `/txt2img`). Final closeout updates only affected
`STATUS.md`, `docs/CODEX_MAP.md`, `docs/StableNew Roadmap v2.6.md` (and `docs/ARCHITECTURE_v2.6.md` only if durable
architecture changed) and must not describe Forge as default or promoted.

## 10. Handoff contract (Cloud -> Local)

The receiving session starts from the pushed branch head recorded in the handoff message, reads this document and
`config/forge_qualification_runtime.json`, does **not** redo discovery, and does **not** rerun the deterministic
evidence above unless relevant source changed. Before any Forge installation, runtime setup, process-manager
validation, A1111 model-reference validation, ADetailer qualification or generation it must: verify branch/SHA and
worktree, re-fetch `neo` and compare with the frozen commit, and obtain the owner decisions in section 7. The
`WebUIProcessManager`, runtime-transition and configuration changes made in the cloud are deterministic and mocked;
they have **not** been validated against the actual machine state and are the first thing to validate locally.

## 11. Local continuation: bounded source and metadata review

### Execution Profile + Model/Reasoning Recommendation

Standard, bounded qualification tooling and read-only workstation evidence. Preferred host: Local/Desktop.
Codex: GPT-6.1 Sol XHigh; Claude Code: Sonnet 5.5 XHigh. The canonical admission, immutable evidence,
endpoint isolation and fail-closed execution checks justify XHigh to reduce total retry/rework cost.
No architecture redesign or production source repair is part of this continuation.

Controller Surface Assessment: the tooling calls the existing runtime-port factory and the existing
PipelineController queue-to-runner bridge. No controller or coordinator source or ratchet ceiling changes.
Each arm has its own fixed client/Pipeline; no client is swapped under a Pipeline. Runtime transitions
receive explicit endpoint observers and no process manager handles, so they cannot adopt or stop a PID.

Token-Efficient Validation Plan: reuse the accepted a8971ebf production evidence; run only the new tooling
tests and affected descriptor tests, inspect the scoped diff and run `git diff --check`. Run the PR gate
once near the settled local source checkpoint. Missing local tooling is a blocker, not authorization to
install packages or change the supported interpreter. Required compatibility evidence remains Python 3.14.

### One-commit Forge adjudication

GitHub commit metadata confirms that `d70373eb` has the single parent `97b26fb4`, message `bump`, and
one changed file (`requirements.txt`, one addition/one deletion). The complete change is:

```diff
-comfy-kitchen==0.2.36
+comfy-kitchen==0.2.37
```

Classification: **NON-MATERIAL FOR THE PROPOSED FP16 SDXL MATRIX**, based on source review. Forge's API
routes (including cmd-flags, sd-models, sd-modules, options, generation, extras, progress and interrupt),
Python requirement, Torch/CUDA pins, model/VAE/loading code, A1111-reference code and ControlNet code are
byte-for-byte unchanged in this commit. The dependency release changes CUDA/HIP quantized kernels and
Ascend paths. It is not a universal runtime-equivalence claim: quantized checkpoint/LoRA offload behavior
is outside this matrix. The candidate checkpoint header has 2515 F16 tensors, embedded VAE weights and
no quantization keys. `--use-ck-attention` is opt-in and absent from the frozen launch flags.

Sources: [Forge commit](https://github.com/Haoming02/sd-webui-forge-classic/commit/d70373ebcf1a96d210b78cd6f77196459e783e2a),
[Kitchen release comparison](https://github.com/Comfy-Org/comfy-kitchen/compare/v0.2.36...v0.2.37),
[Forge attention selection](https://github.com/Haoming02/sd-webui-forge-classic/blob/d70373ebcf1a96d210b78cd6f77196459e783e2a/backend/memory_management.py).

### ADetailer: existing detectors and Python 3.13 metadata

Both required detector files already exist in the local Hugging Face snapshot. Their exact paths/hashes
belong in machine-local evidence, not this portable document. Point the isolated Forge `config.json`
`ad_extra_models_dir` at that existing snapshot directory, and add **`--ad-no-huggingface`** after owner
approval. For Forge, use an empty isolated `HF_HUB_CACHE` so cached default lookups cannot take precedence
over the explicitly selected snapshot directory. No copy, symlink, A1111 edit or detector download is needed.
The flag is required even with an
extra directory: `get_models()` first attempts its default detector list, then merges directory results.
With the flag it uses `hf_hub_download(..., local_files_only=True)`; missing cached defaults are removed,
and existing `.pt` files in the extra directory are then available by filename. Preflight requires both
selected names to be present in `/adetailer/v1/ad_model` and the no-download flag to be true.

The extension pins a source revision, but its installer declares lower bounds, not exact dependency pins:
`ultralytics>=8.3.75`, `mediapipe>=0.10.13`, `rich>=13.0.0`. Proposed versions are **Ultralytics 8.3.253,
MediaPipe 0.10.31, Rich 14.3.4**. Metadata provides a universal Ultralytics wheel and a non-yanked
`mediapipe-0.10.31-py3-none-win_amd64.whl`. MediaPipe declares numpy without an upper bound and no protobuf
constraint. Ultralytics 8.3.75's `numpy<=2.1.1` conflicts with Forge's `numpy==2.3.5`; 8.3.253 removes that
upper bound. Rich is already a Forge pin. No package bytes were downloaded or installed.

MediaPipe is an installer dependency, not operationally required by the accepted YOLO face/hand path:
the extension imports MediaPipe inside MediaPipe predictor functions, while selected `.pt` models use
`ultralytics_predict`. This does not qualify MediaPipe predictors or replace the YOLO contract. Direct
metadata feasibility is established. The machine-local metadata artifact closes 45 package versions
against Windows CPython 3.13.16 wheel tags and the shared Forge direct pins, with no remaining requirement
conflict in that ADetailer closure. It does not close the complete Forge bootstrap or prove compiled-wheel
imports/runtime behavior. Neither install success nor YOLO runtime behavior is asserted.

Sources: [ADetailer installer](https://github.com/Bing-su/adetailer/blob/3a599f5d4607d8f9d8b9fc5a15526197418dae1a/install.py),
[detector resolver](https://github.com/Bing-su/adetailer/blob/3a599f5d4607d8f9d8b9fc5a15526197418dae1a/adetailer/common.py),
[predictor routing](https://github.com/Bing-su/adetailer/blob/3a599f5d4607d8f9d8b9fc5a15526197418dae1a/scripts/!adetailer.py),
[MediaPipe metadata](https://pypi.org/pypi/mediapipe/0.10.31/json),
[Ultralytics metadata](https://pypi.org/pypi/ultralytics/8.3.253/json).

### Previous HOLD: install-plan blocker and local validation status

The unchanged Neo launcher requests **Gradio 4.40.0**, whose declared requirement is
`Pillow>=8.0,<11.0`; Neo's requirements pin **Pillow 12.3.0**. This is an unresolved bootstrap dependency
conflict, present before the one-commit Kitchen drift. The isolated installation proposal is therefore
**BLOCKED**, not a consistent package lock. No source/pin substitution, package download or installation
was attempted. Return this conflict for adjudication before bootstrap work.

Sources: [Neo bootstrap](https://github.com/Haoming02/sd-webui-forge-classic/blob/d70373ebcf1a96d210b78cd6f77196459e783e2a/modules/launch_utils.py),
[Neo requirements](https://github.com/Haoming02/sd-webui-forge-classic/blob/d70373ebcf1a96d210b78cd6f77196459e783e2a/requirements.txt),
[Gradio metadata](https://pypi.org/pypi/gradio/4.40.0/json).

The available StableNew test venv uses Python 3.12.14; the project requires Python 3.14. Its diagnostic
tooling run produced **19 passed, 1 failed**. The canonical queue test is blocked on import of the unchanged
`LoraRuntimeConfig` self annotation under 3.12, before queue execution. No test was skipped or weakened.
The installed base Python 3.14.8 lacks pytest and mypy. The single PR-gate invocation stopped at that
tooling preflight, before gate checks ran. Scoped Ruff validation passed using the existing venv.
Tooling is implemented but remains
unvalidated on the supported interpreter; it is not an accepted physical-execution checkpoint.

Source inspection also shows that the current ADetailer executor's img2img payload omits `seed`.
An immutable NJR seed alone therefore cannot establish matched ADetailer seeds for scenario D.
The proposed matrix records this unresolved qualification blocker; production code is unchanged.
Do not claim seed agreement or dispatch this proposal until that gap and the validation/install blockers
are closed. The content digest freezes the proposal only; clean final StableNew SHA, installed runtime
provenance and owner approval must be frozen again before any physical execution.

### Explicit endpoint and tooling boundary

The runtime-port factory accepts `base_url` and an explicit `forge_webui` identity; the client stores that
URL and the identity guard probes that exact URL. The qualification observer injection uses that client's
identity, without creating a WebUIProcessManager or calling generic discovery. Thus **7871 can be targeted
explicitly without expanding discovery**. Existing manager discovery fallback is not invoked by this path.
The A1111 arm has a separate client at its explicit endpoint. No physical endpoint behavior is claimed yet.

The explicit Comfy observer uses the inventoried endpoint supplied by the matrix, rather than stale
settings in another checkout. It receives no manager handle and can only observe/block an external runtime.

The CLI previews only (`python -m tools.qualification.img_forge_100.run <matrix.json>`). Physical execution
is the explicit `execute_matrix` operator API, requiring the exact owner-approved matrix digest, matching
content-addressed provenance, passing preflights, and a new evidence directory. It admits one NJR at a time
only after all proposal execution blockers are removed. The current machine proposal is blocked.
When admitted, work proceeds
through JobService and preserves SQLite snapshots, each NJR, every terminal result and all pipeline artifacts.
Any failure stops later submission; a timeout records ambiguous state and forbids replay. No ninth case,
hidden retry, runtime launcher, process adoption or raw generation API is included. Contact sheets are CPU-only
paired layouts; comparison reports missing evidence and leaves visual parity to the owner.

Forge remains explicit/non-default and unqualified. ControlNet is source-reviewed only; a runtime capability
verdict remains **FORGE_CONTROLNET_RUNTIME_CAPABILITY_NOT_OBSERVED** until a physical endpoint is authorized.

## 12. Pre-install StableNew blocker closure (historical checkpoint)

Execution Profile + Model/Reasoning Recommendation: Standard bounded repair/verification within the
accepted architecture; Local/Desktop, GPT-6.1 Sol XHigh or Sonnet 5.5 XHigh. Retaining the session context
and checking the canonical boundary minimizes successful-work cost. Controller Surface Assessment:
no controller/coordinator or ratchet changes; no new submission, queue, history, runner or process authority.
Token-Efficient Validation Plan: reuse unaffected a8971ebf evidence, run focused ADetailer/shared backend,
canonical Forge and tooling tests under supported Python 3.14, then one final PR gate. The old 1683-test
sweep and mutation campaign are not repeated.

### Canonical ADetailer seed repair

`PipelineRunner` already derives `ImageExecutionRequest.seed` from immutable NJR provenance. The shared
non-txt2img translation omitted that field, and `run_adetailer()` omitted seed from its outer img2img
payload while reporting `config.seed` as requested. The bounded repair forwards `request.seed` when it
is not `None`, includes `config.get("seed", -1)` in that payload using the existing img2img convention,
and reads `requested_seed` from the payload. There is no extension-specific or backend-specific authority.
Zero and -1 are retained exactly; a missing seed retains the existing -1 default. `actual_seed` still
comes only from generation response info. NJR/compiler semantics and normalization are unchanged.

Ten new regressions failed before the repair because payload seed was absent, then passed after repair.
Four executor cases cover fixed, zero, -1 and missing seed, including serialized manifest metadata;
six canonical SQLite/JobService cases cover both A1111 and Forge with fixed/zero/-1 seeds, conflicting
stage extras, response-derived actual seed, durable result metadata and immutable NJR preservation.
The previously Python-3.12-blocked canonical queue test passes on Python 3.14.8. The isolated test venv
uses repository requirements/dev extras and Windows constraints, with no ML runtime extras installed.
Focused ADetailer/config/backend/Forge/descriptor/tooling/cancellation validation: **102 passed**;
the tooling file contributes **20 passed**. Scoped Ruff and test-environment `pip check` pass.
The single supported-interpreter PR gate passed: repository completeness, controller ratchet, Ruff,
mypy smoke, isolated collection (**4371 collected**) and required smoke (**184 passed**).

### Unexecuted upstream installation protocol

The Gradio 4.40.0 / Pillow 12.3.0 published-constraint inconsistency remains unchanged. It is an upstream
runtime/package qualification finding, not a StableNew dependency repair. The owner-directed next protocol
uses the exact d70373eb source, an isolated Python 3.13.16 venv and Neo's supported **`--uv`** hook.
No Gradio/Pillow downgrade/upgrade, Forge patch/fork, `--no-deps`, constraint override or alternate source.

The machine-local `reports/img_forge_100/forge-install-protocol.md` contains exact PowerShell commands,
paths and evidence filenames. Its sequence is: clone/verify pinned Forge and ADetailer; create only the
isolated Forge venv; bootstrap uv there and capture its version; write the reviewed detector config and
explicit proposed ADetailer direct constraints; invoke upstream `launch.py --uv --exit
--skip-torch-cuda-test` with the proposed runtime arguments and offline model environment; capture installer
exit/log, all installed distributions, `uv pip check`, `pip check`, and source hashes even on failure.
`--exit` returns after preparation before the server/model runtime starts. Skipping the installer CUDA
availability test is installation-only; later physical readiness must establish CUDA separately.

Record whether upstream fails resolution, installs an inconsistent environment, or uses upstream-supported
handling. A successful install with failed consistency is not silently called a pass or a runtime failure;
retain both facts and require separately authorized runtime/API preflight. The three ADetailer direct
constraints freeze the proposed reviewed extension dependencies only; they do not override Forge's
Gradio/Pillow constraints or apply the earlier 45-package metadata closure as a full Forge lock.

Future process-only environment isolates uv/HF/YOLO caches, suppresses model downloads and YOLO
autoinstall, and targets the existing exact detector snapshot through `ad_extra_models_dir` plus
`--ad-no-huggingface`. Nothing is written into A1111 or Comfy. Port 7871 and the exact eight A/B/C/D
pair structure are retained. All selected asset hashes/prompts/settings remain in machine-local matrix
evidence; only final StableNew SHA and blocker/provenance status are refrozen after the local commit.
Forge installation, extension installation, package downloads into Forge, runtime start and physical
generation remain **NOT AUTHORIZED / NOT PERFORMED**. A1111 remains default; FORGE-110 is not started.

Sources: [Neo uv hook](https://github.com/Haoming02/sd-webui-forge-classic/blob/d70373ebcf1a96d210b78cd6f77196459e783e2a/modules_forge/uv_hook.py),
[Neo launcher](https://github.com/Haoming02/sd-webui-forge-classic/blob/d70373ebcf1a96d210b78cd6f77196459e783e2a/launch.py),
[uv environment/constraints](https://docs.astral.sh/uv/reference/environment/),
[uv consistency checks](https://docs.astral.sh/uv/pip/inspection/).

## 13. Authorized isolated installation — PREFLIGHT_BLOCKED (historical checkpoint)

Execution Profile + Model/Reasoning Recommendation: Standard bounded local runtime qualification;
Local/Desktop, GPT-6.1 Sol XHigh or Sonnet 5.5 XHigh, preserving the accepted context and evidence.
Controller Surface Assessment: no controller/coordinator or production source changes; the single
WebUIProcessManager design remains unchanged. Token-Efficient Validation Plan: reuse accepted Python
3.14 source/gate evidence, capture actual upstream install/package state, and run only focused descriptor
checks for this documentation/evidence update. No old sweep, mutation campaign or PR-gate rerun.

The owner authorized frozen Forge/ADetailer source and isolated package installation plus non-generation
runtime preflight. The exact prior machine-local protocol was executed with its approval guard enabled.
The earlier current-Neo-tip guard was superseded by the owner's explicit instruction to keep d70373eb
independently of branch advancement; exact checkout verification was retained. Forge and ADetailer
checkouts match the frozen commits and remain clean. No source, dependency pin or installer was patched.

Neo's supported `--uv --exit --skip-torch-cuda-test` installation completed with exit code **0**.
Actual isolated runtime metadata: Python **3.13.16 Windows AMD64**, Torch **2.13.0+cu130**,
torchvision **0.28.0+cu130**, Torch CUDA build metadata **13.0**, uv **0.12.22**. This is installed
metadata, not a CUDA readiness or generation result. ADetailer's reviewed direct pins were installed:
ultralytics **8.3.253**, mediapipe **0.10.31**, rich **14.3.4**. Neo's builtin extension installers also
ran as part of that upstream process. Complete installed freeze and installer stdout/stderr are retained.

Both **`uv pip check` and ordinary `pip check` exited 1** and reported two incompatibilities:

- Known: Gradio **4.40.0** requires Pillow **>=8,<11**, while **12.3.0** is installed. This conflict
  remains unresolved; installer completion is not a clean packaging pass.
- Additional: MediaPipe **0.10.31** is unsupported on this platform. Its installed WHEEL declares
  **`cp39-cp39-linux_x86_64`**, incompatible with Windows CPython 3.13, and its RECORD lists
  `mediapipe/tasks/c/libmediapipe_c_lib.cpython-39-x86_64-linux-gnu.so`. The installer log names
  `mediapipe-0.10.31-py3-none-win_amd64.whl`. This is contradictory artifact/platform evidence;
  no import/inference test was used to bypass it. The prior package-index/filename metadata feasibility
  finding was insufficient to establish the compatibility of installed contents.

Owner classification rule C therefore requires **STOP before startup**. Final state:
**PREFLIGHT_BLOCKED**, with an additional installed dependency/platform incompatibility. No replacement
version, wheel metadata edit, package removal, `--no-deps`, Gradio/Pillow change or Forge patch was tried.
The observed install also has protobuf **7.36.2**, despite Neo's requirements listing **4.25.9**:
upstream extension installation can alter packages and its final `requirements_met` check only rejects
versions below a pin. This is recorded drift, not a third package-manager incompatibility or a repair.

Runtime/API identity, checkpoint/VAE/LoRA visibility, ADetailer detector discovery, upscale/ControlNet
capability and the physical managed-runtime smoke are **NOT EXECUTED** because the install prerequisite
failed. No Forge server PID or runtime ownership was established; installation subprocesses exited.
The no-download flag/config/offline cache environment was applied to installation, but actual detector
discovery remains unproven. The isolated HF cache is empty and Forge model directories contain only
source placeholder text files; no model/detector weights were downloaded. Existing A1111/Comfy and the
protected dirty worktree were untouched. No generation endpoint was called; no physical jobs ran.

The exact eight-job A/B/C/D structure, assets, hashes, prompts and settings are unchanged. Installed
package evidence cannot yet authorize execution. Owner adjudication of the additional MediaPipe
artifact/platform issue is required before a further bounded installation action or runtime start;
physical qualification still requires separate approval after successful preflight and frozen provenance.
Forge remains unqualified/non-default, A1111 remains default, and FORGE-110 was not started.

Machine-local evidence: installer exit/log, installed freeze and package metadata, both consistency
checks, MediaPipe WHEEL/RECORD platform evidence, passive runtime capture and complete HOLD report.
An initial `pip inspect` console capture failed on cp1252 encoding of a package-description emoji;
the read-only capture was repeated with `-X utf8` successfully, retaining the original partial output.
This did not mutate packages or change the installer/consistency verdict.

## 14. Owner-adjudicated YOLO-only profile — PREFLIGHT_BLOCKED

Execution Profile + Model/Reasoning Recommendation: Standard bounded local qualification;
Local/Desktop, GPT-6.1 Sol XHigh or Sonnet 5.5 XHigh. Reuse accepted source/validation context to avoid
rediscovery. Controller Surface Assessment: no controller/coordinator or production implementation
changes. Token-Efficient Validation Plan: capture the authorized isolated dependency removal, run both
package checks, perform GET-only runtime preflight, stop at hard gates, and validate only updated
descriptor assertions. Accepted Python 3.14 source/gate evidence remains applicable.

The owner adjudicated MediaPipe outside the accepted ADetailer YOLO face/hand product contract.
The bad **0.10.31** distribution was captured one final time, then removed with the isolated Forge
interpreter's `python -m pip uninstall --yes mediapipe` (exit **0**). No replacement was installed.
Verification found no `mediapipe*` package/dist-info paths, no import spec and no installed distribution.
Both `uv pip check` and ordinary `pip check` then reported exactly one inconsistency: Gradio **4.40.0**
requires Pillow **>=8,<11** while **12.3.0** is installed. No installed distribution reported missing
MediaPipe. Package classification: **FORGE_INSTALL_WITH_KNOWN_METADATA_CONFLICT**. The same result and
unchanged package freeze were verified after runtime shutdown.

The qualification launch retained the frozen source/interpreter/endpoint/reference/offline environment
and added owner-approved **`--skip-install`** alongside **`--ad-no-huggingface`**. This profile deliberately
disables extension installers after environment preparation, preventing reintroduction of the known
broken artifact. It is not a FORGE-110 production policy. No tuning flags or source patches were used.
Logging-only UTF-8/unbuffered environment overrides captured startup output without the prior console
encoding limitation. A1111/Comfy configuration and installations were untouched.

Forge started and listened at **127.0.0.1:7871**. Startup reported **30.3 seconds**, Torch CUDA device
RTX 4070 Ti and default PyTorch attention. Qualification-owned launcher/child PIDs and parent chains
are preserved in machine-local evidence. The ADetailer module printed version **26.2.0**, **9 models**
without MediaPipe installed. This proves module import/initial model-list initialization only, not
successful script registration, detector API discovery or YOLO inference.

Two distinct required runtime contracts failed:

- **ADetailer script construction:** its `get_ultralytics_device()` reads
  `shared.cmd_opts.use_cpu`; the frozen Forge namespace lacks that attribute. The script constructor
  fails with `AttributeError`, for both script runners. Hard gate **2** applies. The earlier initialization
  message cannot be treated as a registered/callable ADetailer script.
- **Forge runtime identity API:** `GET /sdapi/v1/cmd-flags` returns **HTTP 500**. Frozen Forge's dynamic
  `FlagsModel` infers `str | None` when a parser default is `None`, but `get_cmd_flags()` returns raw
  parsed values. Response validation rejects integer `port=7871` and the `WindowsPath`
  `forge_ref_a1111_home` value. Positive StableNew endpoint identity cannot be established; classifier
  evidence remains **unknown** and the Forge guard rejects unknown before dispatch. Hard gate **6** applies.

Only readiness GETs to cmd-flags occurred, including HTTP404 before API registration and HTTP500 after
registration. No generation/options POST, ADetailer/upscale inference or other API capability probe ran.
On observing the failures, only this session's owned launcher and child were stopped after command and
parent-chain verification. They exited; port 7871 is free afterward. No restart/alternate candidate was tried.
The managed WebUIProcessManager smoke was not executed because direct preflight failed; no external
PID was adopted or stopped. A detached extension HEAD also caused a Git-info UI diagnostic, recorded
without changing refs; it is not used as a third required-runtime contract finding.

The isolated HF cache remained empty. `--ad-no-huggingface`, offline environment and the existing
`ad_extra_models_dir` snapshot were retained; no detector download occurred. Exact face/hand API
discovery, checkpoint/VAE/LoRA/upscaler API normalization and ControlNet API capability remain
**NOT QUALIFIED / NOT OBSERVED**, not silently inferred from startup messages. ControlNet's UI callback
did register in startup logs, but the required read-only API verdict is not established.

Required qualification modes remain **YOLO face / YOLO hands**. MediaPipe face, mesh and eyes are
explicitly **NOT QUALIFIED**, outside this package's contract and not StableNew regressions.
The eight-job structure/assets/settings are unchanged; no physical jobs ran. Final state:
**PREFLIGHT_BLOCKED** despite the now-acceptable known-only packaging conflict. Owner adjudication of
the two frozen upstream runtime-contract failures is required before further runtime work. No StableNew,
Forge or ADetailer production repair, alternate extension, dependency substitution or architecture change
was attempted. A1111 remains default; FORGE-110 was not started.

## 15. Owner-adjudicated identity repair and ADetailer-Neo preflight

Execution Profile + Model/Reasoning Recommendation: Standard bounded repair and Local/Desktop runtime
qualification; GPT-6.1 Sol XHigh or Sonnet 5.5 XHigh. Reuse accepted exact-source evidence; the cost of
losing the installed-runtime context outweighs a nominally cheaper model. Controller Surface Assessment:
no controller/coordinator change or ratchet increase; one existing WebUIProcessManager remains owner.
Token-Efficient Validation Plan: focused identity/guards, shared ADetailer payload, descriptor/tooling,
GET-only direct and managed smoke, scoped Ruff/diff check, and one final Python 3.14 PR gate. No 1683-test
sweep, old mutation campaign, image inference or optimization experiment.

### Identity repair

The prior classifier made `/cmd-flags` mandatory. The frozen Forge response model cannot validate its
integer port and WindowsPath reference-home values, so HTTP 500 erased otherwise sufficient endpoint
evidence. Forge source remains unpatched. The repaired classifier independently probes options,
modules, VAE and optional flags. Positive Forge requires an options mapping containing at least one
explicit known key (`forge_additional_modules`, `forge_preset`, `forge_unet_storage_dtype`) together
with a module list and unavailable A1111 VAE route. Unknown Forge-like keys alone are insufficient.
Malformed/contradictory opposite-route evidence remains unknown. A1111 requires readable non-Forge
options, a VAE list, unavailable modules, and no contradictory Forge flags. An unavailable optional
flag probe cannot defeat independent positive evidence. No process/install/model-name inference.

The guard, immutable NJR semantics, default identity and process architecture are unchanged. Tests
include cmd-flags HTTP500 with Forge acceptance, explicit/historical A1111 rejection before any mocked
POST, weak/malformed/conflicting evidence, unknown Forge rejection and unchanged A1111 compatibility.
Qualification preflight likewise treats cmd-flags as optional; offline-flag evidence must still come
from that endpoint or the recorded command of a qualification-owned process. External command claims
cannot substitute for readable flag evidence.

### Frozen ADetailer-Neo and payload gate

The owner rejected Bing-su/adetailer `3a599f5d…` for the missing `shared.cmd_opts.use_cpu` constructor
dependency, without patching it. The isolated runtime disables that extension; A1111 is untouched.
New frozen candidate: **Haoming02/ADetailer-Neo `af228eba7a3f3691a25bcd1fc94aa95e600dd3e6`**.
Bounded inspection confirmed Forge-specific `shared.device` YOLO execution, no `use_cpu` dependency,
lazy MediaPipe predictor imports, inherited fixed seeds/tab policy, Forge-aware checkpoint/modules/VAE
handling and the existing `ADetailer` script name. No history review or source patch.

Its installer requests ultralytics 8.3.253 and MediaPipe 0.10.35, but **was not run**. Existing ultralytics
8.3.253 satisfies the YOLO requirement. MediaPipe remains absent, with no replacement, distribution,
import spec or residual package files. MediaPipe face/mesh/eyes remain **NOT QUALIFIED**.

The exact frozen standalone Pydantic parser accepted both proposed face and hand dictionaries before
launch. Its generated schema is pinned in `tests/data/contracts/adetailer_neo_af228eba_schema.json` and
matches the live `/adetailer/v1/schema` response exactly. Field compatibility for both dictionaries:

| StableNew field | Classification |
|---|---|
| positional enable / skip-img2img booleans (`True`, `False`) | SAME |
| two face/hand pass dictionaries | SAME |
| `ad_model` | SAME |
| `ad_tab_enable` | SAME |
| `ad_prompt` | SAME |
| `ad_negative_prompt` | SAME |
| `ad_confidence` | SAME |
| `ad_mask_filter_method` | SAME |
| `ad_mask_k` | SAME |
| `ad_mask_min_ratio` | SAME |
| `ad_mask_max_ratio` | SAME |
| `ad_dilate_erode` | SAME |
| `ad_mask_blur` | SAME |
| `ad_mask_merge_invert` | SAME |
| `ad_x_offset` | SAME |
| `ad_y_offset` | SAME |
| `ad_inpaint_only_masked` | SAME |
| `ad_inpaint_only_masked_padding` | SAME |
| `ad_use_inpaint_width_height` | SAME |
| `ad_inpaint_width` | SAME |
| `ad_inpaint_height` | SAME |
| `ad_use_steps` | SAME |
| `ad_steps` | SAME |
| `ad_use_cfg_scale` | SAME |
| `ad_cfg_scale` | SAME |
| `ad_denoising_strength` | SAME |
| `ad_use_sampler` | SAME |
| `ad_sampler` | SAME |
| `ad_scheduler` | SAME |
| `ad_mask_only_top_k_largest` | RENAMED / TRANSLATABLE to existing filter-method + k controls |

The last key was not a field in **either** frozen extension schema; both forbid extra keys. StableNew
sent a redundant invalid key. The smallest neutral repair removes it from both dictionaries; existing
`ad_mask_filter_method="Area"` and `ad_mask_k` still implement largest-mask selection. Neo's
`filter_k_by` explicitly routes Area to `filter_k_largest`. No required behavior is dropped, no new
backend policy or seed authority is introduced. Deterministic tests cover custom top-k, face/hand enable,
sampler/scheduler and fixed/zero/random NJR seeds on both backend translations. Actual inference and
broader extension value ranges remain physical/product qualification questions, not preflight verdicts.

### Installed/runtime evidence

Runtime remains frozen Forge **d70373eb…**, Python **3.13.16**, Torch **2.13.0+cu130**, torchvision
**0.28.0+cu130**, CUDA build metadata **13.0**. Command: isolated venv Python `launch.py --uv --api
--port 7871 --forge-ref-a1111-home <existing A1111 root> --ad-no-huggingface --skip-install`.
Existing offline HF/YOLO cache environment and detector snapshot routing are retained. No tuning flags.
All **147 installed distributions are unchanged** before/after startup. Both final consistency checks
exit **1** with exactly the known Gradio **4.40.0** requirement Pillow **>=8,<11** against installed
**12.3.0**; no additional conflict or missing MediaPipe dependency. This is not a clean packaging pass.

An initial harness capture was premature (core routes preceded app-started extension callbacks), and
the harness incorrectly expected a wrapped schema response. It was preserved and corrected without a
product/runtime workaround. Complete capture waits for the ADetailer model endpoint; the live schema
is the direct schema mapping. No generation or hidden job retry occurred.

| Read-only surface | Complete result |
|---|---|
| core health, options, model/module lists, scripts/script-info, samplers/schedulers/upscalers, extensions, memory/progress | HTTP 200 |
| `/cmd-flags` | HTTP 500; same upstream response-validation defect, retained evidence |
| `/sd-vae` | HTTP 404; expected Forge absence |
| repaired identity / backend guards | positive forge_webui; Forge accepted, A1111 rejected |
| checkpoint | cyberrealisticXL_v90-16fp.safetensors visible at referenced A1111 path |
| VAE | ten modules normalized; `sd_vae=Automatic`, additional modules empty, client reports Automatic |
| LoRA | add-detail-xl visible |
| ADetailer | Neo registered as ADetailer; version/schema/model APIs HTTP 200 |
| detectors | face_yolov8n.pt and hand_yolov8n.pt visible from existing snapshot |
| upscale | 4xUltrasharp_4xUltrasharpV10 visible; extras route advertised, never dispatched |
| ControlNet | script/script-info plus model/module APIs HTTP 200; version route HTTP 404 |
| explicit endpoint | 127.0.0.1:7871; no discovery invoked |

No reference model was selected by an options POST; the ambient UI checkpoint was a different 32fp
model. Visibility and Automatic representation are proven, not loading/inference/parity of the proposed
16fp checkpoint. The later physical NJR must explicitly select the frozen candidate.

Neo's `--ad-no-huggingface` skips its **entire** default download branch (HF, Ultralytics and MediaPipe
URLs); it scans the existing `ad_extra_models_dir` afterward. Both accepted detector hashes are retained.
The API enumerates five already-existing YOLO files, including the two required detectors. The isolated
ADetailer model directory has no .pt files and the isolated HF cache is empty. No detector/model download.

Complete direct launch: launcher PID **40372**, serving child **8892**, ready in **14.19 seconds**.
Managed launch: WebUIProcessManager PID **30488**, serving child **26272**, ready in **14.16 seconds**.
Parent chains and every worker PID/command are preserved in machine-local evidence. GUI lock admission
was mocked in the headless smoke; actual manager launch, PID ownership, explicit-port health, classifier
and owned stop were real. No second manager or adoption. Both trees stopped; manager clears owns/pid,
port 7871 is free. Manager-initiated Windows termination recorded exit 1, not a spontaneous startup crash.
All **55 recorded HTTP requests were GETs**; the harness rejected non-GETs before dispatch. Zero
generation, ADetailer or upscale inference requests. Existing A1111/Comfy and protected dirty VID-192
checkout remained untouched. **FORGE_CONTROLNET_RUNTIME_CAPABILITY_PRESENT**.

The eight-job A/B/C/D structure, prompts, seed 424242, Euler a/Karras, 24 steps/CFG5.5, asset hashes,
Automatic VAE, add-detail-xl 0.82, athlete input/denoise0.30, face/hand settings and 1.5x upscale remain
unchanged. Provenance changes are the owner-approved extension SHA, repaired StableNew source SHA and
the truthful preflight status; no physical execution. Remaining decision: owner approval of this installed
profile/known packaging conflict and the freshly frozen eight-job physical matrix.

Final runtime classification: **PREFLIGHT_PASS_WITH_KNOWN_PACKAGING_CONFLICT**. Forge remains
unqualified/non-default; no technical/product image parity classification; no push, merge or FORGE-110.
Machine-local evidence is under `evidence-install-d70373eb/neo-adetailer-preflight-complete`, including
runtime/package freeze, process trees, GET responses, logs, schema/payload comparison and shutdown.

Validation: **166 focused tests passed**, including identity, Forge client/backend guards, canonical
SQLite/JobService ADetailer seed translation, executor/schema, tooling/descriptor, runtime ports,
transition ownership and process-manager surfaces. Tooling contributes **23 passed**. Scoped Ruff
and `git diff --check` pass. The single final Python **3.14.8** PR gate passes: completeness, controller
ratchet, Ruff, mypy smoke, **4392 collected**, **184 smoke passed**. No old full affected sweep was repeated.
Exact-head remote CI is not asserted; commits remain local. Recommendation is recorded above;
actual model/effort and token/cost/elapsed usage metrics are unavailable in this host's reported metadata.

## 16. Owner-authorized physical pass: admission HOLD (2026-10-03)

Original classification **FORGE_NO_GO**, superseded by the owner's
**QUALIFICATION_INFRASTRUCTURE_BLOCKED** adjudication in section 17, for the attempt at StableNew
`f636f0e9702f0e1c4824353b780cceec05fc0214`. Exactly one ordinary NJR was submitted through
JobService, SQLite and PipelineRunner.run_njr; it failed before generation. Seven remaining cases
were not submitted. No Forge generation or technical/product image parity verdict is available.
No production repair, retry, tuning, cancellation case, push, merge or FORGE-110 work occurred.

Execution Profile: **Standard / LOCAL desktop**. Recommendation: GPT-6.1 Sol XHigh (Claude Code
Sonnet 5.5 XHigh equivalent) for bounded canonical-path execution and failure evidence; expected
successful-work cost favors retaining exact source/runtime context. Controller Surface Assessment:
no controller/coordinator source changes or ratchet changes. Token-Efficient Validation Plan:
reuse accepted exact-source Python3.14 gate; verify frozen assets, evidence hashes, SQLite integrity,
JSON descriptor and final whitespace. Do not repeat source suites for physical evidence.

### Freeze and runtime provenance

The accepted proposal digest is
`cc37bc5067a20a2e972ebe9c6eca3906d2609a2792265582345008c0b9b53cca`.
The operational copy clears only the owner-approval blocker after explicit authorization, producing
`3434b4f36b1027ff750f5a7b2c4f732d73b662f1efdc549ddd599a96df4864c5`.
All cases, settings, prompts, seeds and assets are unchanged. The existing tool requires interleaved
A-A1111/A-Forge/B-A1111/B-Forge/C-A1111/C-Forge/D-A1111/D-Forge order; the owner explicitly allowed
that frozen-tooling exception. All eight immutable records were compiled; only the first is a
persisted executable job. Others are planned identities, not claimed completed/history jobs.

Both read-only preflights passed before submission. One WebUIProcessManager started and stopped
each qualification-owned tree. The headless canonical service session held the real application
singleton lock; no GUI widgets were involved. Explicit endpoints were used; discovery was blocked.
No pre-existing A1111, Forge or Comfy process was present or adopted.

- A1111: existing source `92b90ee4efc0e8355bb14981e4ae6c7a9b998741`, Python3.10.6,
  Torch2.1.2+cu121 / CUDA12.1; existing Bing-su ADetailer `3a599f5d…`. Existing owner source/batch
  changes were preserved and captured, not repaired. Its venv Python ran `launch.py --xformers
  --api --port 7860 --skip-prepare-environment --ad-no-huggingface --ui-settings-file
  <qualification settings copy> --ui-config-file <qualification UI copy>`. Baseline xformers was
  preserved; no tuning flags were added. Supported separate settings copies prevent ordinary owner
  settings writes. Existing HF cache was read offline.
- Forge: source `d70373ebcf1a96d210b78cd6f77196459e783e2a`, ADetailer-Neo
  `af228eba7a3f3691a25bcd1fc94aa95e600dd3e6`, Python3.13.16, Torch2.13.0+cu130 / CUDA13.0.
  Accepted command/environment unchanged: venv Python `launch.py --uv --api --port 7871
  --forge-ref-a1111-home <existing A1111 root> --ad-no-huggingface --skip-install`; isolated offline
  HF/YOLO caches and existing detector directory. No MediaPipe distribution in Forge.
- RTX4070Ti, 12282MiB, driver617.14. Startup/model loading occurred; inference did not.

Forge's 147-package freeze is unchanged; pip and uv checks exit1 with **only** Gradio4.40.0 requiring
Pillow>=8,<11 against12.3.0. That production-promotion issue remains unresolved. Separately, the
existing A1111 pip check reports baseline debt: MediaPipe0.10.14 requires protobuf>=4.25.3,<5 but
has3.20.0; opencv-contrib-python4.12.0.88 requires NumPy>=2,<2.3 but has1.26.2. No packages changed,
and these are not additional Forge conflicts. Their effect on inference is untested.

| Frozen local asset | SHA-256 |
|---|---|
| cyberrealisticXL_v90-16fp.safetensors | `4f2dc6418c8d93737e2d0a5f022707977c783851e79ccd23aed1fda8397ac10e` |
| add-detail-xl.safetensors, strength0.82 | `0d9bd1b873a7863e128b4672e3e245838858f71469a3cec58123c16c06f83bd7` |
| frozen athlete input,480x832 | `9c7915509bd7ac8961b255bda4ac1eca282056977389742eb782235c2aa74ec5` |
| face_yolov8n.pt | `70b640f8f60b1cf0dcc72f30caf3da9495eb2fb6509da48c53374ad6806e6a9c` |
| hand_yolov8n.pt | `3991202eb69e9ddcb3b9ba80cdeb41e734ffaf844403d6c9f47d515cd88c6f29` |
| 4xUltrasharp_4xUltrasharpV10.pth | `a5812231fc936b42af08a5edba784195495d303d5b3248c24489ef0c4021fe01` |

All six hashes matched before and after the pass. VAE is Automatic/embedded checkpoint semantics;
no external VAE selected. Full frozen prompts/settings and path-specific provenance are preserved
in machine-local evidence. Face/hand registry visibility passed; detector inference and D's fixed-seed
dispatch/response agreement remain untested. No MediaPipe predictor was used.

### Failure and lifecycle

First submitted job: **forge100-3434b4f36b1027ff-A-a1111_webui**. Runtime identity was positively
A1111; checkpoint16fp was loaded. Executor admission logged `poisoned`, cause `duplicate_process`,
then refused txt2img. SQLite's terminal error is `No images were generated successfully`; logs retain
the more specific cause. Captured owned tree: launcher18808 -> serving child40956. Both carry
`launch.py`. The process-risk code counts WebUI-like PIDs rather than ownership trees; >1 makes the
state critical. Thus the captured Windows venv parent/child pair explains the refusal. This is source
analysis supported by the captured tree; current executor logs do not emit its full per-PID risk
snapshot, so that snapshot is not claimed as directly observed.

StableNew automatically restarted its **owned** runtime once,18808 ->40668 (serving child31500),
then still refused admission. No generation request had been sent, and no job was resubmitted or
replayed. This automatic recovery is disclosed separately from generation retry. Qualification stopped
at the first failed terminal job; no guard was mocked/bypassed and no repair was made.

Every planned ID has prefix `forge100-3434b4f36b1027ff-`:

| Suffix / backend | Lifecycle | Requested / actual seed | Wall / repository time | Observed peak GPU memory |
|---|---|---|---|---|
| A-a1111_webui / a1111_webui | FAILED before dispatch |424242 / unavailable |25.659s including startup /14.369s |7943MiB, includes model startup/recovery |
| A-forge_webui / forge_webui |NOT_SUBMITTED |424242 / unavailable |unavailable |unavailable |
| B-a1111_webui / a1111_webui |NOT_SUBMITTED |424242 / unavailable |unavailable |unavailable |
| B-forge_webui / forge_webui |NOT_SUBMITTED |424242 / unavailable |unavailable |unavailable |
| C-a1111_webui / a1111_webui |NOT_SUBMITTED |424242 / unavailable |unavailable |unavailable |
| C-forge_webui / forge_webui |NOT_SUBMITTED |424242 / unavailable |unavailable |unavailable |
| D-a1111_webui / a1111_webui |NOT_SUBMITTED |424242 / unavailable |unavailable |unavailable |
| D-forge_webui / forge_webui |NOT_SUBMITTED |424242 / unavailable |unavailable |unavailable |

No seed was dispatched or response-derived. No generated image artifacts, stage output manifests,
contact sheet, visible-difference assessment or pair timing/VRAM comparison exist. Failed run metadata,
canonical NJRs, repository fingerprint/lifecycle, diagnostics result and logs are retained and hashed.
Parent lineage is absent as intended; no replay was used. SQLite integrity_check is **ok**: exactly
one failed row, zero queued/running rows, no orphan. Final manager has no PID/ownership; both runtime
ports released. All owned children stopped. A later read-only owner-PID check found the completed
session already exited and performed no out-of-band termination.

Five-second survivor samples record job/backend/PID, log tails, runtime progress/memory, GPU and host
RAM. Four job samples observed peak7943MiB GPU memory,35C, host used19190857728 bytes; sampled GPU
utilization0%. Those are total device observations, not inference allocation peaks. No device loss,
CUDA OOM or ambiguous POST occurred; System event4101 query found no matching events. Final GPU
remained accessible,714MiB/0%/35C. This is not a generation stress/stability pass.

No package/model/detector download observed; installers disabled, HF/YOLO offline, selected hashes
unchanged. Original A1111 tracked-source/owner-config hashes unchanged; protected dirty VID-192
worktree retains its original branch/HEAD/status; Comfy untouched. A1111 remains default.

Machine-local evidence set: **physical-f636f0e-pass1**, under the existing qualification evidence root,
including `hold-report.json`, `evidence-inventory.json` (41 files), `freeze.json`, package/runtime freeze,
exact launch profiles, `events.jsonl`, owned process trees, WebUI logs, `run/jobs.sqlite3`, all eight
compiled NJRs, first-job failed result and `run_metadata.json`. Large runtime responses and binaries
are not committed to Git. Source gate evidence at f636f0e is reused; only factual docs/descriptor changed.

Remaining owner decision: adjudicate the canonical owned-tree/process-risk admission blocker and
existing A1111 package debt; authorize any bounded repair separately, then authorize a new frozen
pass with new identities. No repair or retry during this stopped pass. A ninth cancellation generation
is not warranted by the available evidence and was not executed. Forge remains unqualified; product
visual parity and production promotion remain undecided.

## 17. Process-tree admission repair and owner reclassification (2026-10-03)

The owner reclassified section 16's stopped attempt as **QUALIFICATION_INFRASTRUCTURE_BLOCKED**,
not FORGE_NO_GO: no generation request reached either backend. The underlying defect was StableNew
runtime admission counting a legitimate owned Windows venv launcher and serving child as two
independent WebUI authorities. The failed job remains terminal evidence, not a Forge inference failure.
Original reports, logs, failed result, immutable NJR and SQLite database are retained without rewriting.

Execution Profile: **Standard / LOCAL desktop**, recommended **GPT-6.1 Sol XHigh** for Codex and
**Sonnet 5.5 XHigh** for Claude Code. A bounded ownership/recovery repair benefits from sustained
reasoning and avoiding retries rather than the lowest nominal model cost. Controller Surface
Assessment: no controller/coordinator/process-manager source or ratchet changes. Changes are in the
existing process inspector and executor admission, preserving one WebUIProcessManager. Token-Efficient
Validation Plan: deterministic ancestry/recovery fixtures, existing manager ownership/stop tests,
qualification tooling/descriptor tests, scoped Ruff/whitespace, one real owned A1111 no-generation
smoke, then one Python3.14 canonical PR gate. No old 1683-test sweep, GPU inference or dependency work.

### Grouping and recovery contract

`_independent_process_tree_roots(candidates, processes)` walks each candidate's parent PID through
the observed Python process map, including non-matching intermediates. A candidate is a root only
when it has no matching candidate ancestor. Root PIDs are sorted for stable diagnostics. Missing
ancestors do not prove a relationship; cycles cannot justify merging candidates. Neither shared
executable, directory, port, model nor installation path establishes a component.

WebUI and significant StableNew-main duplicate severity now use independent matching tree counts.
One launcher/child chain has one authority; two independent chains remain critical. Individual
matching members receive duplicate reasons only when their matching class has multiple independent
trees. The significant-main RSS threshold is retained; unrelated high-RSS/stale-pytest warning
behavior is unchanged. Raw process counts remain intact:

| Diagnostic | Meaning |
|---|---|
| `webui_process_count`, `main_process_count`, `significant_main_process_count` | raw matching PIDs |
| `webui_runtime_tree_count`, `webui_runtime_tree_roots` | independent matching WebUI ancestry roots |
| `significant_main_tree_count`, `significant_main_tree_roots` | independent significant-main ancestry roots |

Executor `_ensure_runtime_admissible` rejects `duplicate_process` before soft recovery, preserving
evidence without interrupt/orphan cleanup or restart. If a recovery re-probe finds a duplicate, it
also refuses before the restart decision, including under high/unsafe pressure. An owned restart
cannot resolve another independent/external authority. Existing managed connection-failure recovery,
stale-progress recovery and guarded-profile behavior retain their established paths. No manager
ownership policy changed; no FORGE-100 special case or admission bypass was introduced.

Deterministic coverage includes one PID, parent/child, non-matching bridge, two roots with/without
children, main launcher/child and independent main trees, unknown/cyclic ancestry, retained suspicious
process warnings, actual inspector-to-executor risk translation, duplicate refusal without manager
restart, re-probe duplicates, and continued managed connection-dead restart. The old duplicate-main
fixture incorrectly modeled parent/child; it now models independent roots, with separate regression
coverage for benign ancestry. Descriptor coverage now asserts the owner-adjudicated infrastructure
classification, zero dispatches, preserved terminal identity and pending new-attempt approval.

### Real owned A1111 smoke: no generation

The same manager-owned Windows venv/launch.py path was used with existing A1111 packages and
baseline xformers, explicit port7860, skip-prepare-environment, ad-no-huggingface, offline HF/YOLO
environment and fresh qualification settings/UI copies. The headless service harness held the real
application singleton lock. All HTTP mutations were forbidden before dispatch; runtime admission and
process enumeration were real. No JobService generation submission or direct inference occurred.

Observed tree: qualification owner16732 -> WebUI launcher**21640** -> serving Python child**26568**.
Readiness took **10.815s**. Real inspector evidence: raw WebUI PID count**2**, runtime-tree count**1**,
root21640, risk**normal**, no suspicious members. Actual executor admission was **healthy**, with no
duplicate cause or recovery trace; manager restart calls**0**, discovery calls**0**. All **8** recorded
HTTP requests were GETs. No-generation true-duplicate behavior is proven by deterministic fixtures;
no second real external runtime was launched.

The manager owned its launcher/tree throughout and stopped both PIDs; no survivors or listeners on
7860/7871/8189, singleton lock released, final manager PID/ownership cleared. Windows owned termination
recorded exit1 as in prior smokes, not a spontaneous runtime failure. Source/config hashes in existing
A1111 and the failed qualification database/result are unchanged. External runtimes and protected
VID-192 owner files were untouched. Zero generation, detector/model/package download or package change.
Forge was not launched in this repair pass; its accepted preflight/packaging evidence remains applicable.

The MediaPipe/protobuf and OpenCV-contrib/NumPy findings in existing A1111 are **current non-blocking
environment debt**, not the admission cause. They were not repaired; inference impact remains untested.
Forge Gradio4.40.0/Pillow12.3.0 packaging inconsistency remains separate and unresolved. A1111 remains
default; Forge/MediaPipe modes are not promoted or physically qualified; FORGE-110 was not started.

Machine-local evidence: **admission-repair-aa24dba/result.json**, exact launch profile, actual observed
Python ancestry/risk, runtime admission, GET inventory, logs and before/after ownership/hash evidence.
The prior **physical-f636f0e-pass1** evidence is untouched; an additive owner-adjudication record
references it. Validation results and the resulting local commit are recorded at this HOLD.

### Next physical attempt

After owner acceptance and separate authorization, freeze the accepted repaired StableNew source SHA
and provenance while preserving every generation setting/asset in the original eight-case matrix.
Never requeue/reuse/delete `forge100-3434b4f36b1027ff-A-a1111_webui`. Create a new Pair-A A1111 identity
and preserve qualification lineage referencing that failed infrastructure attempt. A fresh matrix
source digest naturally gives new compiled identities and avoids the old terminal ID; annotate the
qualification evidence with the failed attempt, without inventing replay semantics. Submit any new
jobs through the unchanged JobService/SQLite/run_njr path. The seven unsubmitted old identities have
no lifecycle rows and require no state mutation. No physical matrix was resumed during this repair.

Final validation: **43 process-inspector/admission tests passed**, **68 manager/qualification-tooling
tests passed** (including23 qualification-tool tests), and **5 updated descriptor tests passed**.
One stale descriptor assertion from the prior physical checkpoint initially expected NOT_AUTHORIZED;
it was updated to the explicit owner adjudication and now asserts the preserved terminal identity
and zero-dispatch evidence. Scoped Ruff and `git diff --check` pass. The single final Python**3.14.8**
PR gate passes: completeness, controller ratchet, Ruff, mypy smoke, **4414 collected /184 smoke passed**.
No expensive unrelated sweep was run. Recommendation is recorded above; actual model/effort and
token/cost/elapsed usage metrics are unavailable in the host's reported metadata.

## 18. Resumed physical cohort: prompt-intent infrastructure HOLD

Owner-authorized execution used clean StableNew source
`333bdbf71113984ecb9a4c1fad9328d6b7a18459`. Forge and ADetailer-Neo source pins and all six frozen
asset SHA-256 values were unchanged. Installed Forge metadata matched the accepted package freeze,
including absent MediaPipe and the unresolved Gradio4.40.0/Pillow12.3.0 packaging conflict. Accepted
preflight/source gate evidence was reused, with short live readiness/resource/identity/ownership
checks only. No broad preflight, old deterministic sweep or PR gate was repeated.

Execution Profile: **Standard / LOCAL desktop**, recommended **GPT-6.1 Sol XHigh** (Codex) and
**Sonnet5.5 XHigh** (Claude Code). Controller Surface Assessment: no production/controller source
changed. The evidence wrapper reused unchanged qualification `execute_matrix`/`build_services`, real
JobService, SQLite, PipelineRunner.run_njr and the selected adapter. Token-Efficient Validation Plan:
exact-source/assets/package-freeze verification, lightweight survivor telemetry, passive dispatch
guard, then JSON/hash/SQLite/evidence integrity and scoped diff checks. Preserve accepted gate evidence.

The new cohort **physical-333bdbf-pass2** has matrix digest
`d115bc2353d7b612aa2c40d9da89c69b49d28eb8f4a342b137708d35299f7796` and eight fresh compiled NJR IDs:
`forge100-d115bc2353d7b612-{A,B,C,D}-{a1111_webui,forge_webui}`. Generation settings, prompts, assets
and case structure match the original authoritative proposal exactly; only source/cohort/lineage and
approval metadata changed. Evidence lineage is **resumed physical cohort after admission infrastructure
repair**, without product replay or invented parent_job_id. Frozen tooling requires interleaved order,
as permitted by the owner's ordering exception.

Only **forge100-d115bc2353d7b612-A-a1111_webui** was submitted; it is now a normal terminal **failed**
SQLite/history identity. The seven remaining frozen records were never submitted and have no lifecycle
rows. Prior terminal **forge100-3434b4f36b1027ff-A-a1111_webui**, its database/result and all historical
planned identities were untouched. All **45** previous-cohort files and **eight** protected A1111/VID-192
files matched their captured before/after byte hashes.

### Admission succeeded; exact prompts did not survive translation

Actual managed A1111 tree: qualification owner31484 -> launcher**35024** -> serving Python**20748**.
Read-only identity/resource checks passed: correct A1111 identity, exact checkpoint, LoRA, required
upscaler and both YOLO detector names visible; port7860 belonged to the owned tree. Captured process
risk was **normal**, raw WebUI PIDs**2**, independent runtime trees**1**, root35024. Runtime admission
progressed to generation payload construction, without duplicate refusal or restart.

The passive guard refused the first generation call before its underlying HTTP request because the
product changed both prompts. Logs show positive chunks reordered and global negative terms appended
before negative optimization. The frozen negative prompt was
`lowres, blurry, deformed hands, extra fingers, text, watermark`; the would-be payload instead contained
`lowres, deformed hands, malformed, extra fingers, blurry, text, bad quality, distorted, ugly, watermark, nsfw, nude, naked, explicit, sexual content, adult content, immodest`.

Bounded read-only source/config analysis established two related intent-plumbing gaps:

- Qualification `compile_case` writes top-level global enable booleans, blank global terms and
  `global_prompt_policy_source=frozen_njr`, but does not use the canonical
  `apply_global_prompt_policy` pipeline stage flags. `has_frozen_global_prompt_policy` therefore returns
  false, and the executor consults legacy runtime defaults/terms. The immutable snapshot contains the
  requested values; the qualification construction is not a complete canonical policy.
- `WebUIFamilyImageBackend._txt2img_executor_config` does not forward the NJR's explicit
  `prompt_optimizer={enabled:false}`. The executor receives no optimizer config and defaults to enabled.
  Pure adapter/config evidence confirms this without Pipeline execution, HTTP or GPU work.

No production or qualification execution code was repaired, and no prompts/settings were changed to
rescue the pass. These findings require owner adjudication before another physical attempt.

The existing client made **three local send attempts** after the guard's exception. All were refused
before network dispatch: **zero generation POSTs**, **zero HTTP generation retries**, **zero ambiguous
dispatches**, **zero job resubmissions**. The two local retry attempts are preserved explicitly; they
must not be described as a clean absence of all retry behavior. No automatic runtime restart occurred.

### Evidence and cleanup

Pair A is infrastructure-blocked before A1111 inference; its Forge arm and pairs B/C/D are
**NOT_SUBMITTED**. Requested seed424242 is frozen in every NJR; dispatched/actual seeds are absent.
There are no generation-stage timings, output images, stage manifests, contact sheet or visual parity
findings. Pair-A A1111 elapsed time including startup was **18.528s**; repository running duration
**4.713s**. Cold runtime startup/pre-dispatch peak observed VRAM was **8008MiB**, not a generation peak.
Five-second survivor samples recorded no GPU telemetry error, CUDA OOM or device-loss signal. No system
Display4101 event was returned for the observation window, and no display loss was reported. This is
not a generation stability test.

The owned A1111 tree was stopped cleanly: neither PID survived; manager PID/ownership cleared,
qualification ports released, no external process mutation. Forge was not started during this cohort.
SQLite `integrity_check=ok`, no foreign-key violations, **one failed / zero queued / zero running**;
normal failed run_metadata.json and the canonical snapshots/results are retained. No model/detector/
package download or YOLO/MediaPipe inference occurred. Existing A1111 package debt remains non-blocking
environment debt; no inference evidence adjudicates it. A1111 remains default and FORGE-110 is unstarted.

Full machine-local evidence is retained in **physical-333bdbf-pass2/hold-report.json**,
**prompt-translation-evidence.json**, **evidence-inventory.json**, **events.jsonl**, **session.log**,
**run/jobs.sqlite3**, eight frozen NJRs and the terminal failed result. The report carries exact runtime
profiles, package provenance, six asset paths/hashes, process trees, timing/telemetry and preservation
checks. Large generated binaries were not committed; no images exist for this cohort.

Final classification: **QUALIFICATION_INFRASTRUCTURE_BLOCKED**, not a Forge execution verdict.
Next decision: authorize a bounded canonical prompt-policy/optimizer preservation repair, then accept
its focused evidence before separately authorizing a fresh physical cohort. Preserve both failed job
IDs and all unsent historical identities. No ninth cancellation case is warranted or authorized.

## 19. Canonical prompt-intent preservation repair: no generation

Attempt2 remains **QUALIFICATION_INFRASTRUCTURE_BLOCKED**, with zero generation requests reaching
A1111 or Forge. Both terminal failed job identities and their preserved databases/results remain
historical evidence. The process-tree admission repair is unchanged; its accepted evidence is reused.

Execution Profile: **Standard / LOCAL desktop**, recommended **GPT-6.1 Sol XHigh** for Codex and
**Sonnet5.5 XHigh** for Claude Code. The bounded repair shares one immutable-intent outcome and benefits
from precise end-to-end verification instead of repeated physical attempts. Controller Surface
Assessment: no controller/coordinator/executor or ratchet changes. Token-Efficient Validation Plan:
focused global-policy/optimizer/shared-adapter tests, eight frozen-case pre-dispatch previews, Pair-A
TEST-only JobService/SQLite integration, existing affected qualification/contract tests, scoped Ruff
and whitespace, then one Python3.14 PR gate. No runtime launch, inference or old1683-test sweep.

### Existing canonical seams repaired

Qualification `compile_case` now calls `src.pipeline.global_prompt_policy.apply_global_prompt_policy`.
The complete policy contains frozen recorded global text (blank in the current matrix),
`global_prompt_policy_source=frozen_njr`, and all five stage flags explicitly false:
`apply_global_positive_txt2img`, `apply_global_negative_txt2img`, `apply_global_negative_img2img`,
`apply_global_negative_adetailer`, `apply_global_negative_upscale`. This replaces the incomplete manual
policy; `has_frozen_global_prompt_policy` returns true and mutable runtime/global files are not used.
No positive/negative prompt text, order, settings, asset, LoRA placement or generation intent changed.

The shared `WebUIFamilyImageBackend` now forwards explicit `prompt_optimizer` alongside the existing
global-policy fields in both `_txt2img_executor_config` and `_stage_executor_config`. That covers
txt2img, img2img, ADetailer and upscale for both identities without Forge-specific policy. The
qualification NJR already explicitly freezes `{enabled:false}`; it now reaches the executor.
Omission is still omission and retains the enabled product default. Explicit enabled optimizer and
global policy retain their ordinary behavior. No optimizer implementation/default, global-policy
helper, immutable NJR semantics, executor generation guard or retry behavior was changed.

### Exact intent evidence across all four pairs

The checked-in frozen-intent fixture copies the authoritative proposal's **settings and eight cases
exactly**, without machine-local asset paths. Test assets/state are temporary and transports are
synthetic; actual frozen qualification assets remain untouched. All eight physical-intent previews
construct NJRs without JobService submission. The real PipelineRunner request construction, shared
adapter and executor build payloads intercepted before HTTP generation dispatch.

| Pair | No-generation pre-dispatch proof, both backend identities |
|---|---|
| A | positive/negative prompts exactly equal frozen text; seed424242 |
| B | same exact text, final `<lora:add-detail-xl:0.82>` token/order preserved; seed424242 |
| C | exact img2img positive/negative text; seed424242; frozen480x832/denoise0.30 intent unchanged |
| D | exact txt2img and outer ADetailer prompts/seed; exact face/hand prompt/negative dictionaries; correct YOLO names; upscale prompt/provenance exact, frozen1.5x unchanged |

Each comparison asserts character equality and **UTF-8 byte equality**. Complete disabled global
policy and optimizer intent reach stage configs. Runtime global files are deliberately changed after
NJR creation in the tests; they cannot alter results. The original NJRs remain immutable. Separate
tests include repeated chunks and Unicode to prove disabled optimizer performs no reordering/dedupe.

Pair A additionally traverses the actual JobService/SQLite/PipelineRunner.run_njr path for A1111 and
Forge, using distinct **TEST-only** identities and temporary repositories. Payloads are intercepted
before even fake HTTP generation, while fake read-only API identity/options preserve normal adapter
flow. These TEST jobs are deterministic regression fixtures, not a third physical cohort or reuse of
terminal qualification identities. Enabled-policy controls prove frozen global terms still apply;
existing optimizer regressions prove ordinary enabled/default behavior remains intact.

The prior retry observation was inspected only at the existing client exception boundary: generic
`RuntimeError` is handled by local retry logic; ambiguous generation transport errors are recognized
separately and refuse POST replay. The prompt guard raised locally before network dispatch, so no
backend request had an unknown outcome. No new retry-policy workstream or change was introduced.

Focused validation: **152 passed**, including **24 new shared-adapter/optimizer cases** and **14 new
qualification-intent cases** (all eight previews and both Pair-A canonical integrations). Updated
descriptor checks also pass (**5**). Scoped Ruff and `git diff --check` passed. The single final
Python**3.14.8** PR gate passes: completeness, controller ratchet, Ruff, mypy smoke,
**4452 collected /184 smoke passed**. No expensive unrelated sweep was run. Machine-local
**prompt-intent-repair-666b9ef/eight-njr-preview.json** records eight dry preview identities (never
submitted), **12** stage translations, full flag/config evidence, exact prompt UTF-8 hashes and parity.
The checked-in settings/cases match the authoritative proposal exactly; all six asset hashes,
45 prior-cohort files,42 resumed-cohort inventory files and eight protected owner files are unchanged.
Known Forge Gradio/Pillow conflict and existing A1111 package debt are unchanged.
Zero physical generation, runtime launch, detector/package download, process mutation or cohort3
submission. A1111 remains default; FORGE-110 remains out of scope. Next action requires owner acceptance
of this source checkpoint and renewed physical-cohort authorization with fresh job identities.
