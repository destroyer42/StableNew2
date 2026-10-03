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
- Reviewed and frozen commit: **`97b26fb404314a11dad7cdde2706da57ea53f4f2`** (2026-10-02). `neo` was
  re-fetched on 2026-10-03 and equals the discovery-time reviewed SHA: **no drift**. Re-fetch and compare
  again before any installation; if `neo` moved, re-review the API matrix instead of advancing the pin.
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

Source/runtime/extension (frozen): Forge Neo `97b26fb4…` on CPython 3.13.x in a dedicated venv; Neo's default
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
`runtime_capture.py`, `run.py`, `compare.py`, `contact_sheet.py`) is intentionally **not written yet**: it must be
validated against the actual machine state. Product matrix jobs must enter through NJR -> JobService -> SQLite ->
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
