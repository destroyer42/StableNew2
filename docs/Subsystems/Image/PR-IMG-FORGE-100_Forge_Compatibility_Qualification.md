# PR-IMG-FORGE-100 — Forge Neo Compatibility / A1111 Successor Qualification

Status: **CHECKPOINT 1 — deterministic implementation complete; physical qualification NOT started.**
Forge is an explicit, **non-default** backend identity (`forge_webui`). `a1111_webui` remains the
default. Nothing here promotes Forge (that is `PR-IMG-FORGE-110`, a separate owner decision) and no
final classification has been reached.

Base: `origin/main` `715e352f28640cb0eb3225a5b1752fc5e192c778` (PR #35 / PR-TEST-TRUTH-210 merged).
Execution host so far: Claude Code cloud session (source review, deterministic implementation, mocked
tests). Everything that touches the real machine continues in a Local/Desktop session.

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
| runtime flags | `GET /sdapi/v1/cmd-flags` | same (`vars(cmd_opts)`); also the Forge identity evidence |
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
| Read-only identity seam | `src/api/webui_runtime_identity.py`: classifies the connected endpoint from evidence only (Forge = `forge_ref_a1111_home` in `/cmd-flags` **and** `/sd-modules` list; A1111 = no `forge_*` flags **and** `/sd-vae` list and no `/sd-modules`; else `unknown`). `SDWebUIClient.probe_runtime_identity()` uses bare GETs |
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

## 4. ADetailer extension decision (source-reviewed, NOT installed, NOT qualified)

- Selected candidate: **`Bing-su/adetailer` @ `3a599f5d4607d8f9d8b9fc5a15526197418dae1a` (v26.2.0)**, the
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
**Not yet run.**

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

## 7. Frozen matrix returned to the owner (physical run NOT authorized)

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
