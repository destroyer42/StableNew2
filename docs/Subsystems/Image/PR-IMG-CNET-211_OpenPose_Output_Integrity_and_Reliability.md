# PR-IMG-CNET-211 — OpenPose Output Integrity and Conditioning Reliability

## Execution Profile + Model/Reasoning Recommendation

Standard: bounded response integrity, conditioning admission and GUI-view diagnostics within understood ownership.
Codex GPT-6.1 Sol XHigh / Claude Code Sonnet 5.5 XHigh per `docs/AI_MODEL_SELECTION.md`: response ambiguity and immutable
intent make retries costly, so the recommendation optimizes successful-work cost. Local/Desktop preserves the Windows
and retained artifact context. One primary session plus the triggered read-only StableNew Security Review.

Worktree `C:/Users/rob/qual/StableNew-cnet211`, branch `codex/img-cnet-211-output-integrity`, base
`bbf855d415a14a1b3b09c0e0a043a608dc71eeba` (current remote main, including PRs #99 and #100). The reviewed `8ded6de`
baseline was superseded by local/live Git truth. The original Photo Optimize checkout and untracked data are preserved.
Authorization is implementation, deterministic validation and local commits only; no publication or physical work.

## Proven causes and retained evidence

1. The PR-IMG-CNET-210 detect-map trimming fix is present at the base. It keeps the first `batch_size * n_iter` images
   whenever extras arrive, without checking Forge's generated-image boundary or whether a returned image is the input.
   A leading grid or missing generation can therefore make truncation select the wrong image; deterministic fixtures
   reproduce these response shapes. This is a proved algorithmic gap, not attribution of every user failure.
2. The request omits `save_detected_map`. Installed Forge source HEAD is exactly
   `d70373ebcf1a96d210b78cd6f77196459e783e2a`; read-only `git show` confirms `ControlNetUnit.save_detected_map = True`
   (`extensions-builtin/sd_forge_controlnet/lib_controlnet/external_code.py:175`). `scripts/controlnet.py:318-322`
   returns before appending/autosaving a detect map when this field is false. `modules/api/api.py` returns
   `processed.images + processed.extra_images`; `modules/processing.py:1146-1174` records a leading grid separately
   through `index_of_first_image`, with generation seeds and generation/grid infotexts. No Forge module was imported.
3. Retained `output/Pipeline/20261013_073001_A_A_A-photoMomenW_v20-none` manifests in the owner's
   `C:/Users/rob/projects/StableNew-main` checkout record `diffusers_xl_depth_full` and
   `ttplanetSDXLControlnet_v20Fp16` receiving the same OpenPose snapshot (SHA-256
   `8e7c2f11eb07e2b648900037f0b2a2e2261cf9c615c9df81e62f5baee9ba043d`), strength 1, guidance 0-1, Balanced,
   Crop and Resize, and one trimmed detect map. Both saved images visibly contain skeleton-like structures.
   This proves dispatch of known depth/tile model names with pose input and continued wireframe influence despite
   trimming. Local bounded safetensors headers establish architecture, but contain no modality metadata; no weights
   were loaded/hashed. Name hints are not cryptographic qualification of the installed weights.
   Creator model cards describe [SDXL depth conditioning](https://huggingface.co/diffusers/controlnet-depth-sdxl-1.0)
   and [TTPlanet Tile](https://huggingface.co/TTPlanet/TTPLanet_SDXL_Controlnet_Tile_Realistic). Their documented modalities
   support the name-based warning/refusal; they do not authenticate the installed files or establish incident causality.
4. The supplied snapshot is a 1024x1024 RGBA image; the saved outputs are portrait-shaped. Pinned Forge
   `modules_forge/utils.py:46-63` composites transparent pixels onto white. Transparency/resize semantics are verified
   risks; their quantitative contribution to these outputs is unproved. Strength, checkpoint/prompt effects, model
   training and Forge's batch-directory override remain hypotheses/limitations requiring controlled physical evidence.
5. A deterministic four-image canonical run exposed first-seed duplication in each per-image manifest. Each
   conditioned image now records its own substantiated seed/subseed. The canonical history stage aggregate stays one
   record with four output paths; no history authority is added.

The historical successful `C:/Users/rob/qual/cnet210/r203300` test only proves that its single pose/model/runtime worked
then; it does not establish the cause of the newer failures. Existing outputs, snapshots, packs and repositories were
read-only and retained. No historical record or frozen intent is migrated.

## Current behavior and ownership

- One supported Forge base-txt2img unit explicitly sends `save_detected_map=False`, alongside `pixel_perfect=False` and
  unchanged operator settings. Other always-on scripts remain untouched; an occupied ControlNet entry still refuses.
- `src/image_backends/openpose_output.py` classifies before any result-image save. Every requested generation needs a
  seed and nonempty infotext, plus Forge's 0/1 generated-image boundary. A leading grid is excluded. Missing/partial or
  ambiguous metadata, malformed images, an input map in a generation slot, and unidentified extras refuse the whole
  response with stable content-free codes and expected/received counts. Trailing maps are accepted only when decoded
  pixels identify the supplied snapshot (including white alpha composition), never solely by position/count. Images
  are bounded at 64 MiB / 64M pixels each. Successful artifacts record the classification, counts, map/grid exclusions,
  input facts, resize/target geometry and explicit suppression.
- `src/conditioning/openpose_diagnostics.py` separates known incompatible model-name hints from SDXL family evidence.
  The two observed depth/tile identities are refused at existing Forge admission and shown as errors in the editor.
  This is an exact known-name rule, not a fuzzy substring classifier or a proof about renamed weights. Other names,
  including OpenPose-looking names, remain explicitly modality-unverified; unknown architecture retains the prior
  labelled admission policy. Non-SDXL family evidence still refuses. No automatic replacement/model selection is made
  for saved declarations. Initial picker auto-selection excludes the two known incompatible names.
- The widget obtains image facts with its existing thumbnail worker. The neutral view explains None passthrough,
  transparent-background risk, canvas size, resize semantics, control-mode priority, strength/guidance influence and
  missing/unverified evidence. Presentation never edits a declaration. No default changes: weight 1, guidance 0-1,
  Balanced, Resize and Fill; all stored settings, zero/False values, snapshot bytes and NJR schema remain intact.
- Existing compiler, Forge backend, executor, GUI-view and canonical queue-first seams remain authoritative. No
  A1111/Klein/Z-Image/img2img support, multiple units, compiler/runner/queue/history or runtime ownership is added.

## Controller Surface Assessment

No controller file changed, and no ratchet ceiling increased. `app_controller.py`, `job_service.py`,
`pipeline_controller.py` and `job_history_service.py` retain base byte identity. Backend admission and executor output
handling own enforcement; GUI owns read-only operator feedback. UI decoding remains off Tk.

## Token-Efficient Validation Plan

Start with new output/diagnostic tests and existing wire/admission/canonical GUI tests; then all OpenPose regressions
(conditioning, family evidence, unsupported targets, PromptPack persistence, Learning refusal and stages/scripts).
Run `python tools/ci/run_pr_gate.py` once on the isolated worktree with every new file staged so completeness and
collection include them. Use Python 3.14 and existing pinned tools, temporary test state, fake HTTP and no GPU.
Inspect the final aggregate diff and `git diff --check`. Reuse exact-source results after documentation-only edits.
Hosted Python 3.14 integration remains pending because publication is not authorized.

## Validation and security evidence

Focused suite: 120 passed; final complete OpenPose regression set: **258 passed, 2 skipped** (existing Windows
file-symlink capability skips). New/modified regression coverage includes exact suppression, one/four-image responses,
grid boundaries, metadata/count disagreements, missing/corrupt images, input maps in generation slots, reencoded maps,
unexpected extras, decode limits, alpha/palette facts, geometry and control-mode feedback, saved setting/NJR preservation,
known incompatible names vs unverified modality, unsupported/disabled conditioning, scripts/stages and queue-first runs.
The older symbolic-image hygiene fixtures now use real PNGs and Forge metadata; their save/log/provenance assertions
remain strong. The fake transport now models suppression and actual generation-count metadata, with an explicit
misbehaving-extension seam to prove legacy map identification.

Required local `python tools/ci/run_pr_gate.py`: **PASS**. Repository completeness (580 tracked Python files), controller
surface ratchet, Ruff and mypy smoke (10 files) passed; isolated collection **9,489 tests**, required smoke **386 passed**,
repository unchanged through both gates. Aggregate `git diff --check` passed. Only documentation changed after this gate;
all tested source and test bytes remain identical. Hosted CI was not run; nothing was published.

Evidence: `C:/Users/rob/qual/cnet211-focused.log`, `cnet211-openpose-final.log`, `cnet211-limits.log`,
`cnet211-pr-gate.log` and `cnet211-security.md`. The initial sandbox run encountered Windows path-resolution
denials in test-owned temporary directories; the same suite ran with ordinary filesystem access and fake requests.
Security review (backend response deserialization/artifact-write classification): **PASS**, no required fix. Low
non-blocking hardening: aggregate response memory budget and temporary RGBA arrays, recorded in the residual limits.

## Residual compatibility and quality limits

- The installed files have no modality metadata. Known-name refusals cannot detect renamed depth/tile weights, and an
  OpenPose-looking filename cannot prove training modality. A cryptographically pinned model qualification policy
  would be a separate product decision; this package preserves unknown-model behavior with clear warnings.
- No semantic skeleton detector, automatic alpha/background rewrite, pose extraction, quality score or geometry
  normalization is introduced. Exact input-pixel rejection cannot identify a transformed/stylized skeleton in a
  metadata-labelled generation. It protects output identity, not aesthetic quality or pose adherence.
- The single-unit fallback recognizes only exact decoded input maps. Unexpected transformed detect maps or
  script-specific result layouts refuse rather than guessing. Metadata must follow pinned Forge's Processed contract.
- Per-image decode limits bound individual work, not total response size. Responses already arrive through the
  existing API client; an aggregate transport/memory budget is separate hardening. NVIDIA quarantine/physical HOLD
  remains in force, with no generation, restart, settings change, download or environment alteration in this package.
- Forge's REST-invisible process-global ControlNet batch-directory override remains the owner-accepted PR-210 limit.
  Provenance establishes submitted bytes, not proof that an overridden runtime used them. No new guard is claimed.

## Focused physical protocol for later explicit approval

1. Obtain fresh owner safety clearance after GPU recovery; inspect the existing GPU quarantine and positively verify
   host health. Confirm runtime/source identity, current model, no batch-directory override and a documented SDXL
   OpenPose weight. Do not clear a quarantine, restart a runtime or change its settings as part of this protocol.
2. Through normal PromptPack preview -> immutable NJR -> JobService/SQLite -> `run_njr`, freeze one opaque black
   background map with a known asymmetric pose and matching generation aspect ratio. Use one fixed seed/checkpoint,
   prompt and the unchanged settings; retain the unit, response metadata/counts, artifact hashes and manifests. Disable
   option writes in any approved harness. Acceptance: one generated artifact, no map/grid artifact, exact suppressed
   unit, substantiated seed and visible pose following without skeleton rendering. Record qualitative uncertainty.
3. Only with separate multi-image/quality authorization, test two generated images and one deliberately differing
   aspect ratio; inspect grid exclusion, per-image seed and crop/pad framing. A matched lower-strength/guidance run can
   assess excessive influence, but must be explicitly approved and never silently change defaults or saved jobs.
4. Stop immediately on device-fault/outcome-unknown evidence, ambiguous response or state drift; no automatic retry,
   backend restart or replay. Failure/root-cause attribution requires matched evidence, not the old PR-210 success.
