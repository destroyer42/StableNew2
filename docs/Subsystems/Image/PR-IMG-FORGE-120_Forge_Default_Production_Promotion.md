# PR-IMG-FORGE-120 — Forge Default Production Promotion

Status: IMPLEMENTED / PHYSICALLY ACCEPTED / READY FOR OWNER REVIEW (not published). `NEW_WORK_DEFAULT_FORGE_PASS`.

This package promotes the already-qualified StableNew-managed Forge Neo runtime to the default production still-image
backend. It is a default-policy and runtime-selection promotion only. It does not requalify Forge, change a Forge or
ADetailer revision, Torch or any dependency pin, retire A1111, integrate Comfy images, add a GUI or per-stage backend
selector, or qualify a model. Reused evidence: the accepted managed install (Forge Neo `d70373eb`, ADetailer-Neo
`af228eba`, CPython 3.13, Torch `2.13.0+cu130`, the exact package lock), the managed-runtime reproducibility pass, the
Forge production-promotion and capability qualification (txt2img, LoRA, img2img, ADetailer, upscale) and the Forge
module-baseline normalization (D110).

## Two different defaults

| Meaning | Constant | Value |
| --- | --- | --- |
| Product default for NEW still-image work | `NEW_IMAGE_BACKEND_DEFAULT_ID` | `forge_webui` |
| Compatibility default for a HISTORICAL record with a missing or blank image backend identity | `LEGACY_MISSING_IMAGE_BACKEND_ID` | `a1111_webui` |

`DEFAULT_IMAGE_BACKEND_ID` is removed because the phrase had become ambiguous. The adapters keep their identities
(`A1111_IMAGE_BACKEND_ID`, `FORGE_IMAGE_BACKEND_ID`), both stay in the registry, and an explicit persisted identity is
never rewritten. Persisted work is never reinterpreted: `resolve_image_backend_id` still resolves a missing identity to
A1111, and replay (`compile_replay_intent`) clones the persisted NJR, so a replay keeps the source's backend semantics.

## Configured selection

| `webui_runtime_identity` | Result |
| --- | --- |
| missing or blank (also the `STABLENEW_WEBUI_RUNTIME_IDENTITY` fallback) | `forge_webui` |
| `forge_webui` | Forge |
| `a1111_webui` | A1111 (the supported rollback; never auto-migrated to Forge, even if it was written before this change) |
| anything else | `WebUIRuntimeConfigurationError` |

Selection fails closed. There is no degradation to either backend: an unrecognized identity, an unreadable settings
object, or a corrupt `settings.json` raises `WebUIRuntimeConfigurationError` from `configured_image_backend_id()`,
`DefaultImageRuntimePorts`, and `build_default_webui_process_config()` before anything is selected or dispatched.
`ConfigManager` records why `settings.json` was unreadable (`settings_load_error`); `load_backend_settings()` turns that
into the configuration error, because silently reading defaults could hide an explicit A1111 rollback. The application
therefore refuses to start with an invalid backend configuration and says why.

## Identity-aware endpoint

`resolve_effective_webui_base_url` is the single resolver: the explicit `webui_base_url` setting, then
`STABLENEW_WEBUI_BASE_URL`, then the identity default (Forge `http://127.0.0.1:7871` from the managed manifest, A1111
`http://127.0.0.1:7860`). It is used by the process-config builder, application bootstrap, `AppController`, the
connection controller, the CLI, the runtime transition service and the pipeline fallback runner, and `ConfigManager.
load_settings` presents the effective value (the Engine Settings dialog shows the endpoint actually used).

Decision for owner review: every settings file written before this change persists `webui_base_url` as the flat default
`http://127.0.0.1:7860`, including the repository's tracked `presets/settings.json`. That value carries no operator intent
for Forge, so for Forge it resolves to the Forge default; for an explicit A1111 it stays authoritative. A genuinely
different explicit URL stays authoritative for both and is validated: a Forge endpoint must be loopback
`http://127.0.0.1:<port>` and, with an explicit `forge_runtime_profile_path`, must equal the profile's endpoint.

## Managed Forge as the default runtime

One launch-profile authority now exists: `src/utils/managed_forge_runtime.py` (standard library only, because the
verifier runs under the managed runtime's Python 3.13). `build_launch_profile` and `check_launch_command` moved there from
the verifier; `tools/runtime/verify_managed_forge.py` imports them (its only `src` import) and
`build_default_webui_process_config` consumes the same functions. For the default Forge path
`resolve_default_launch_profile`:

1. resolves the canonical install the manifest names (`%LOCALAPPDATA%\StableNew\Forge\neo-<revision8>`);
2. requires the bootstrap's ownership marker with `status: verified` for exactly the pinned revision, plus the venv
   interpreter, `source/launch.py` and the data directory;
3. resolves the model-reference home from `webui_workdir`, then the app-config default, then the supported detection
   (only its location is used: no A1111 command, launch profile, cache or process);
4. builds the profile on the manifest default port 7871 (or an explicit loopback port) and checks the qualified flags
   (`--api --skip-install --ad-no-huggingface --uv --forge-ref-a1111-home`; no tuning or exposure flags).

No profile file is needed. `forge_runtime_profile_path` remains an advanced override. If anything is missing,
`ManagedForgeUnavailable` explains it and points at `scripts/bootstrap_managed_forge_windows.ps1`; StableNew never
installs Forge, downloads a package, detector or model, or falls back to A1111. The default check is structural and
cheap; full drift detection stays the verifier (`bootstrap_managed_forge_windows.ps1 -CheckOnly`).

## Runtime ownership

Unchanged: one `WebUIProcessManager`, no `ForgeProcessManager`; an external A1111, Forge or Comfy process on the
endpoint is never adopted, killed, restarted or reconfigured, and an ambiguous generation POST is never replayed. One
hardening: a failed Forge health check no longer runs the A1111 port-discovery fallback that could rebind the manager to
whatever answers on 7860-7870.

## Forge capability projection

Making Forge the default must not expose controls the pinned Forge Neo cannot honor. Two mismatches are closed here.

**Hypernetworks (the pinned Forge Neo removed them).** `ImageBackendCapabilities.supports_hypernetworks` is a typed
capability: true for A1111, false for Forge.
- Execution: `ForgeWebUIImageBackend.validate_njr_intent`, which the runner calls before any dispatch for every Forge job,
  refuses any Hypernetwork intent (a stage or top-level `hypernetwork` that is not `None`, or a Randomizer sweep entry)
  with `ForgeUnsupportedIntentError`: the runtime does not support Hypernetworks, generation was not dispatched, and
  `webui_runtime_identity = a1111_webui` restores the feature. No generation request is sent (asserted for every stage).
  Explicit A1111 keeps the feature unchanged.
- Presentation: the Randomizer's Hypernetwork matrix row is projected through the same capability: under Forge it is
  inactive, disabled, relabeled as unavailable, and contributes nothing to the plan even if forced on or loaded from a
  saved config. Known pre-existing debt, not repaired here: `RandomizerPanelV2` cannot be constructed on `main` (a Tk
  `-background` error on its preview `ttk.Treeview`) and the Pipeline tab does not mount it, so there is no live surface
  presenting the row today; the projection is correct for when it is mounted and its logic is tested directly.

**ADetailer detectors.** The managed runtime only guarantees the manifest's two YOLO detectors (`face_yolov8n.pt`,
`hand_yolov8n.pt`; no MediaPipe).
- `ForgeWebUIClient` no longer inherits the generic fallback list (yolov8s variants, person segmentation, MediaPipe): when
  the endpoint's own detector list is unavailable it returns the managed runtime's accepted set; a list the endpoint does
  return is shown as is.
- The ADetailer stage card's static choices follow the configured backend, so an unavailable resource refresh can no longer
  leave the combobox advertising detectors that are not installed. Explicit A1111 keeps the generic choices.
- `accepted_detector_names()` in the shared managed-Forge module reads the manifest once and is the single source;
  `src/image_backends/backend_capabilities.py` exposes capability facts to presentation layers. Those helpers are tolerant
  (an unresolvable configuration yields the legacy A1111 presentation) because enforcement is separate and fails closed.

## Historical work and replay

A historical NJR with no image backend resolves to A1111 and stays A1111 on replay. The application has one WebUI-family
runtime client, so replaying A1111 work while configured for Forge is refused before dispatch by the existing runtime
identity guard, now with `ACTION REQUIRED` guidance to select the A1111 rollback explicitly. No dynamic per-job runtime
switching was added.

## A1111 rollback

Set `webui_runtime_identity` to `a1111_webui` in `presets/settings.json`, and set `webui_base_url` to the A1111 endpoint or
remove it (an explicit A1111 with no URL uses `127.0.0.1:7860`). The A1111 path reads no Forge profile, needs no managed
Forge install, and uses the existing `webui_workdir`, launch profile commands and cache. New work is then stamped
`a1111_webui`. Rollback is configuration only.

## Test environment

Tests that drive a deterministic fake A1111-style WebUI (the PromptPack vertical slice, config passthrough, and the
operator-journey fake backend) now select the A1111 rollback explicitly, because a fake cannot be positively identified
as Forge. Default-selection behavior is asserted in `tests/api/test_forge_production_selection.py`.

## Validation

- Focused: image backend, Forge selection, runtime identity, process-manager profile ownership, runtime ports,
  transition, managed-runtime contract and acceptance-driver tests; extended in their existing owners.
- Mutation: forcing the default identity back to A1111 turns 16 tests red; for the capability closure, declaring Forge
  Hypernetwork-capable turns 7 red, dropping the Forge client's detector fallback 1, and ignoring the card's fallback 2.
- Validation plan: the PR changes a CI-authority file (the controller-ratchet ceiling), so a full census is required; it
  is run locally (sharded) and hosted CI routes it too.
- `python tools/ci/run_pr_gate.py`: OK at the executable SHA (350 smoke, 5,147 collected); controller ratchet OK
  (`app_controller.py` 7,731 to 7,730 and its ceiling lowered; no other controller grew).
- Affected-lane run on the executable SHA: every target passed except two load/order-sensitive tests that pass on rerun and
  are unrelated, classified and not repaired: `test_pr_harden_009_r1a_txt2img_cancellation::test_canonical_txt2img_completes_once_when_not_cancelled`
  (passes in its module context; also fails in isolation on the pre-change baseline) and
  `gui_v2/test_pr_mvp_060_phase3a_r1_queue::test_queue_panel_manual_and_auto_run_worker_lifecycle` (passes alone, twice).
  `test_efficiency_impact::test_executor_metrics_show_switch_overhead_reduction`, a wall-clock comparison, failed once
  under load and passed in isolation.

## Physical default-path acceptance

One canonical SDXL txt2img job (the frozen Pair-A intent) on the target machine (RTX 4070 Ti), driven by
`tools/acceptance/img_forge_120_default_acceptance.py`, which injects nothing: no backend or runtime-identity argument, no
backend options, no launch-profile file, no endpoint. Evidence:
`C:\Users\rob\qual\img_forge_120\physical-cfc6d5d\` (`run\acceptance.json`, `prerun-gate.json`, `postrun-integrity.json`), run on the
executable code that includes the capability closure. An earlier run of the same frozen intent on the pre-closure code
(`physical-d75b20a`) also passed; the closure adds a pre-dispatch check to every Forge job, so the run was repeated.

- Effective configuration: the repository's real `presets/settings.json` has no `webui_runtime_identity`, no
  `forge_runtime_profile_path` (stored `webui_base_url` is the legacy `7860`); the environment has neither override. It
  resolves to `forge_webui` at `http://127.0.0.1:7871`.
- New work: the production `build_cli_njr` produced `backend_options.image.backend_id = "forge_webui"` from the default alone.
- Runtime: `build_default_webui_process_config()` produced the launch command; it equals the shared authority's output
  (command, working directory and environment), has no contract problems and no A1111 launcher, and the manager
  (`WebUIProcessManager`) owned the process (ready in 28.5 s). The managed verifier was green before the run.
- Client and guard: `DefaultImageRuntimePorts()` built `ForgeWebUIClient` on the process endpoint and the runtime identity
  guard positively classified the endpoint `forge_webui`.
- Path: `JobService.submit_njrs -> SQLite -> SingleNodeJobRunner -> PipelineController -> PipelineRunner.run_njr`; the job
  `completed` in 15.3 s (peak VRAM 11,264 MiB), one artifact (`4f8ceff0...`, 1,150,097 bytes). Image quality and pixel
identity are not under test in this promotion.
- Identity evidence: SQLite NJR snapshot and the job result record `forge_webui`.
- No fallback and no collateral: no other runtime was started; the managed tree exited and nothing listens afterwards; the
  owner's preset and PR-VID-193 files, the A1111 config files and source inventory, and the managed `config.json` are
  byte-identical before and after; the main checkout's status is unchanged.

## Known limits

- A Forge job whose persisted config names a Hypernetwork now fails at the capability check (by design) rather than
  attempting an `/options` write the runtime cannot honor.
- ADetailer detector choices are validated by presentation only; a hand-edited config that names a detector the endpoint
  lacks fails at the endpoint, as before.

- A corrupt or invalid backend configuration stops application startup (by design: nothing may be guessed).
- Some legacy direct-API helper paths in `AppController` now use the configured client; the GUI has no backend selector
  (a separate product package).
- Replaying historical A1111 work while configured for Forge requires switching to the A1111 rollback.
