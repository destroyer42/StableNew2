
---

### 3.5. `docs/codex_context/PIPELINE_RULES.md`

> This keeps all your “how the pipeline should behave” stuff in one place.

```markdown
# PIPELINE_RULES

> Invariants and behavioral rules for StableNew pipelines.

---

## 1. Execution Stages

Standard stages (in order):

1. **txt2img**
2. **optional adetailer / face-fix pass**
3. **img2img refinement** (optional)
4. **upscale** (optional, but common)
5. **post-processing / metadata tagging**

Stages must be **composable** and individually testable where possible.

---

## 2. Core Invariants

1. **Single source of truth for config**
 - Pipeline config is a structured object, not ad-hoc dicts spread across layers.
  - Controllers must route all run submissions through `PipelineConfigAssembler` before queueing or executing work (no direct `pipeline_func` shortcuts).

2. **No hard-coded paths**
   - Use config/env; never bake in user-specific paths.

3. **Safe defaults**
   - Respect sane defaults for sampler, steps, CFG, and resolution.
   - Enforce a max megapixel limit for any generation or upscale.

4. **Deterministic and loggable**
   - Given the same seed + config, runs should be reproducible.
   - Log config and seed for each stage.

5. **Error handling**
   - Fail fast with clear error messages when:
     - WebUI not reachable
     - Invalid config (e.g., resolution too large)
     - Missing models/checkpoints

---

## 3. Adetailer / Face-Fix Handling

- Adetailer is treated as its **own stage**, not a hidden side-effect.
- Configurable via pipeline config (enable/disable, model choice, target regions).
- Logging:
  - Whether adetailer ran.
  - Parameters used.
  - Any failures should not crash the entire pipeline—fallback to delivering base output when possible.

---

## 4. Upscale Rules

- Tile sizes must be computed with **safety constraints**:
  - Respect `img_max_size_mp`.
  - Separate tile limits for ESRGAN and DAT if supported.
- Must avoid “runaway” tile sizes causing multi-minute hangs.

---

## 5. Learning Hooks

- Pipeline runner should emit **structured events** (start, stage start, stage end, error).
- Learning system should consume these events to build `LearningRecord`s.
- Learning hooks must be **opt-in** and must not break pipeline if disabled.

---

## 6. Notes For AI Agents

- When adding stages, ensure:
  - Config is part of the main pipeline config object.
  - Stage is represented in learning events (if enabled).
- When touching upscale/tiling:
  - Always update tests and add new fixtures for edge cases.

## 7. Output Settings (GUI V2)

- Output directory/profile, filename pattern, image format, batch size, and seed mode are surfaced via `OutputSettingsPanelV2`.
- These values flow GUI → `GuiOverrides` → `PipelineConfigAssembler` and are stored under `config.metadata["output"]`; the pipeline runner consumes them as part of config metadata (no direct filesystem writes in GUI).
- Defaults come from `app_config`; keep them centralized and avoid hard-coded paths in widgets or assemblers.

---

## 8. Model Manager (GUI V2)

- Model selection lives in `ModelManagerPanelV2` (model + optional VAE) and must not perform direct filesystem scans.
- Names flow GUI → `GuiOverrides` → `PipelineConfigAssembler`; assembler maps `model_name` to the main `PipelineConfig.model` and stores `vae_name` in metadata for downstream consumers.
- Defaults come from `app_config` (env overrides allowed); refresh uses existing WebUI client APIs via a thin adapter.

---



## 10. WebUI Connection & Run Gating

- WebUI connectivity is managed by `WebUIConnectionController`; GUI startup is non-blocking.
- Pipeline runs are gated on WebUIConnectionState.READY; runs bail early otherwise.
- GUI exposes reconnect controls/status; autostart/health timeouts live in app_config (env overridable).

---

## 9. Queue-Backed Execution Mode

- Controlled by configuration (`queue_execution_enabled`, default False).
- When enabled, PipelineController submits jobs via QueueExecutionController using `PipelineConfig` as the job payload.
- Cancellation in queue mode must use queue semantics (`cancel_job` on the queued/running job) rather than direct thread cancellation.
- When disabled, execution follows the existing direct path without queue indirection.


## 10. WebUI readiness and launch

- WebUI availability is a precondition for pipeline runs; controllers gate runs on `WebUIConnectionState.READY`.
- WebUI autostart uses detection/config (no hard-coded paths); defaults come from `app_config` + detection of `stable-diffusion-webui`.
- GUI exposes launch/retry controls but never blocks startup if WebUI is offline.

---

