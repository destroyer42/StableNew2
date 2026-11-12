# StableNew Focused Assessment — P4-2 Unified NJR Compiler Design — 2026-11-12

Framework: v1.2. Assessment class: Focused. Execution class: Architectural (research and design only).
Status: draft for owner review. Completeness: COMPLETE for the compile path; PARTIAL where marked "not re-run" or
"reachability unverified". Decision required: whether to authorize the first package (P4-2A) in
[the work-package plan](../work_packages/P4-2_unified_njr_compiler_migration.md).

This report is a decision aid. It does not supersede `AGENTS.md` or `STATUS.md`, changes no production code, test,
golden snapshot, schema or ratchet baseline, and authorizes none of the packages it proposes.

## Source lock and scope

- Repository `destroyer42/StableNew2`; base `origin/main` `67e0e559d1998321d567e78f9b4e16cf4e6d9807` (PR #288 merge),
  verified by `git fetch` at task start (2026-11-12T18:01:31-05:00). Branch `design/p4-2-unified-njr-compiler`, created
  from that SHA in a dedicated worktree. The owner's `main` checkout (one unrelated modified file,
  `presets/settings.json`) was not touched.
- Evidence is static source reading plus one deterministic check: `pytest tests/golden` (12 passed at the locked SHA).
  No application, GPU, Forge, A1111, Comfy, SVD, PR gate or test census was run. No user database or generated output
  was read.
- Authorities read: `AGENTS.md`, `STATUS.md`, `docs/CODEX_MAP.md`, `docs/AI_MODEL_SELECTION.md`,
  `docs/ARCHITECTURE_v2.6.md` sections 6-7, `docs/assessments/README.md` and template,
  `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`, and the compiler-relevant passages of the PromptPack, Image, Learning and
  Testing subsystem documents. The 2026-10-16 audit (finding C2, package P4-2) and the 2026-11-10 ARCH-DESIGN-950
  assessment are historical comparison only.
- Excluded: P4-3 (Learning out of the GUI), P4-4 (typed stage settings), P4-5 (exact-profile plugins), P3-2 (runtime
  composition), GUI redesign, and any behavior change.

## 1. Executive findings

1. **The audit's "8 hand-built sites" is still the right count but no longer the right list.** `NormalizedJobRecord(`
   is called at seven compile sites and one read-path site in `src/`. The two Learning sites moved out of the GUI into
   `src/learning/`. Two of the seven are fan-in points that serve many workflows: `ReprocessJobBuilder` builds every
   image-input and every video job, and `learning_njr.assemble_txt2img_njr` builds three Learning study types.
2. **There is a second, uncounted kind of site: derivation.** Five functions create a new job identity from an existing
   record with `dataclasses.replace` (replay, history variation, stage-checkpoint resume, sequence resume and replay).
   They never reach a `NormalizedJobRecord(` call, so a grep-based "one construction site" criterion misses them.
3. **Policies are not applied unevenly by accident alone.** Three distinct, legitimate contracts exist today: *fresh*
   work (policy is applied at compile), *frozen* work (Learning arms are validated at Preview and must not be
   re-adapted at Run) and *derived* work (a replay must carry its parent's values). A single core must encode these
   three states, not erase them.
4. **Four inconsistencies are confirmed in current source** (section 4): generic Pipeline-tab jobs are labeled
   `SourceKind.CLI`; PromptPack jobs are compiled twice with the model policy applied twice; exact-profile NJR
   validation runs at different times depending on the builder; and an explicit CLI seed of `0` becomes `-1`.
5. **The existing golden suite does not yet protect a migration.** Six happy-path snapshots exist. None covers an exact
   profile, a Matrix, the randomizer, an image edit, any Learning study, any video job, a history variation or a
   refusal. Coverage has to come first, as its own package.
6. **Recommendation:** an envelope-shaped typed draft and one assembly core (`compile_njr` for one fresh or frozen
   record, `derive_njr` for a new identity from a parent), with source planners keeping ownership of cardinality and of
   source-specific preparation. Six bounded packages, tests first, PromptPack last. No NJR schema change, no persisted
   migration, no dependency on P3-2, P4-4 or P4-5.

## 2. Compilation inventory (Deliverable A)

### 2.1 Construction sites at `67e0e559`

`git grep -n "NormalizedJobRecord(" -- src tools` (definitions and docstrings removed):

| # | Site | Role | Class |
|---|---|---|---|
| S1 | `src/pipeline/cli_njr_builder.py:108` | `build_cli_njr`, one txt2img-led image job | Externally supported |
| S2 | `src/pipeline/job_builder_v2.py:176` | `JobBuilderV2.build_jobs`: generic image jobs, and the inner fan-out for PromptPack | Production-active |
| S3 | `src/pipeline/prompt_pack_job_builder.py:586` | `_build_jobs_for_entry`: rebuilds each S2 record as a PromptPack job | Production-active |
| S4 | `src/pipeline/reprocess_builder.py:341` | `build_reprocess_job`: image-input and all video workloads | Production-active |
| S5 | `src/pipeline/training_njr_compiler.py:59` | `compile_training_intent` | Production code, feature on HOLD |
| S6 | `src/learning/learning_njr.py:53` | `assemble_txt2img_njr`: Model Comparison, Two-Axis Grid, Prompt x Model Matrix | Production-active |
| S7 | `src/learning/ordinary_njr.py:237` | `_materialize_txt2img`: ordinary and controlled single-variable studies | Production-active |
| R1 | `src/pipeline/njr_core_v26.py:1276` | `migrate_legacy_njr`: read path for legacy flat snapshots | Read path, not a compiler |
| T1 | `tools/qualification/img_forge_100/run.py:106` | Operator-only harness | Not production |

Drift from the audit: `learning/model_comparison.py:783` and `gui/controllers/learning_controller.py:1276` are gone;
S6 and S7 replace them. No site remains under `src/gui/` (consistent with ARCH-DESIGN-950 section 5).

### 2.2 Derivation sites (new identity from an existing record)

| # | Site | What changes | Class |
|---|---|---|---|
| V1 | `src/pipeline/replay_njr_compiler.py:85` `compile_replay_intent` | `job_id`, source becomes `HISTORY_REPLAY` with parent lineage, batch membership archived | Production-active |
| V2 | `src/pipeline/history_variation_compiler.py:374` `compile_history_variation` | V1 plus edited prompt, seed, steps, CFG; stale tags reconciled | Production-active |
| V3 | `src/pipeline/replay_engine.py:161` | Stage-checkpoint resume: new `job_id`, new inputs and `start_stage` | Runtime-internal; reachability not traced |
| V4 | `src/video/sequence_resume.py:232` with `build_resume_njr`, `build_replay_njr` | V1 plus a resume or replay directive in stage `extra` and config | Production-active |
| V5 | `src/learning/ordinary_njr.py:98` | Re-identifies an S4 record for a non-txt2img Learning variant | Production-active |

### 2.3 Routes

Every route ends at `JobService.submit_njrs` unless stated. "Refusal" names where an unsupported request is rejected
today.

| Route | Entry and call chain | Site | Source kind written | Expansion | Refusal today |
|---|---|---|---|---|---|
| PromptPack | `PipelineController._build_njrs_from_pack_bundle` (`pipeline_controller.py:97`) -> `PromptPackNormalizedJobBuilder.build_jobs` -> `_prepare_entry` -> `_build_jobs_for_entry` -> `JobBuilderV2.build_jobs` -> S3 | S2 then S3 | `prompt_pack` | Matrix (`matrix_expansion_plan`) x randomizer x batch runs | Compile: model policy, Klein LoRA review, AnimateDiff, Z-Image NJR check. A pack with no config is skipped with a log line, not refused |
| Generic Pipeline tab | `get_preview_jobs_for_request` -> `_build_normalized_jobs_from_state` (`pipeline_controller.py:185`) -> `JobBuilderV2.build_jobs` | S2 | `cli` | config variants x randomizer x batch runs | Compile: effective config, model policy, Z-Image NJR check. Any exception is logged and returns no jobs (`pipeline_controller.py:339`) |
| CLI | `src/cli.py:134` -> `build_cli_njr` -> `runner.run_njr` | S1 | `cli` | none | Model policy at compile; profile NJR check only in the backend. **Does not cross `submit_njrs`** |
| Reprocess, Review, Photo Optimize, curation | `AppController` (`app_controller.py:1780`, `1894`, `1935`), `review_batch_service.py:118`, `photo_optimize/submission.py:77`, `curation_workflow_builder.py:102`, `review/workflow_adapter.py:263` -> `build_grouped_reprocess_jobs` -> S4 -> `reprocess_admission.submit_reprocess_njrs` | S4 | `reprocess` | groups by prompt, model, config, output dir; chunked by batch size | Build: missing input, invalid stage, AnimateDiff. Admission wrapper: `require_njr_operation`, frozen-mask checks |
| Image edit (masked inpaint, outpaint, `AppController` image edit) | `masked_edit_service.py:210` (outpaint reuses it through `build_frozen_edit_preview`), `app_controller.py:1986` -> `build_grouped_reprocess_jobs` -> S4 | S4 | `image_edit` | one | `require_njr_operation` in the service and the admission wrapper. Edit Image from History hands its source to Review and was not traced as a separate compile |
| Regenerate with Changes | `get_preview_jobs_for_request` -> `compile_history_variation` | V2 | `history_replay` | one | Compile: `variation_refusals`, `assess_njr`, Z-Image NJR check |
| History replay | `AppController.on_replay_history_job_v2` (`app_controller.py:1736`) -> `HistoryHandoffService.replay_job_from_history` -> `compile_replay_intent` | V1 | `history_replay` | one | Compile: retired AnimateDiff and secondary motion only |
| Batch retry | `batch_operations_service.py:385`, `:493` -> `compile_replay_intent` | V1 | `history_replay` | selected jobs | V1 plus `require_njr_operation` |
| Learning ordinary and controlled studies | `LearningController._build_variant_njr` (`learning_controller.py:1201`) or a `learning_controller_services/*` service -> `ordinary_njr.materialize_njr` | S7, or S4 then V5 | `learning` | one per variant; whole experiment admitted by `ExperimentAdmissionService.compile_all` | Freeze time: `apply_model_compile_policy`, `validate_experiment`. Run: strict baseline and Preview-parity checks |
| Learning frozen-arm studies | `model_comparison.materialize_njr`, `two_axis_grid.materialize_njr`, `prompt_model_matrix.materialize_njr` -> `arm_njr` -> `assemble_txt2img_njr` | S6 | `learning` | one per arm or cell | Freeze time: per-arm policy and `verify_arms_admissible`. Run: equality with the frozen arm, `validate_profile_njr` |
| Comfy Video Workflow | `VideoWorkflowNjrBuilder.build_job` (`video_workflow_njr_builder.py:573`) -> S4 | S4 | `video_workflow` | one per source (batch, experiment arms) | Build: form validation, hash re-verification. Admission: `require_workflow_admission` |
| Native SVD | `SVDController._build_svd_njr` (`svd_controller.py:309`) -> S4 | S4 | `video_workflow` | one per source | Before build: `validate_config`, `get_svd_preflight` |
| Multi-segment sequence | `video_sequence_controller.py:47` -> `sequence_admission` -> `build_job(sequence_plan=...)` or `build_sequence_njr` -> S4; resume and replay -> V4 | S4, V4 | `video_workflow`, `history_replay` | one job, N internal segments | Plan freeze; `SequenceResumeError` before any record |
| Movie Clips | `movie_clips_submission_service` -> `build_movie_assembly_njr` (`movie_assembly_compiler.py:378`) -> S4 | S4 | `video_workflow` | one | `MovieAssemblyAdmissionError` at freeze |
| Character Training | `app_controller.py:5864` -> `compile_training_intent` | S5 | `training` | one | `validate_train_lora_execution_config` |

Uncertain or dormant: `PipelineController.on_replay_history_job_v2` (`pipeline_controller.py:1556`) calls
`JobExecutionController.replay` (`job_execution_controller.py:430`), which submits to the queue directly and skips
`JobService.submit_njrs`. The History panel resolves `on_replay_history_job_v2` on its controller; `AppController`
defines its own that uses the canonical path, so the `PipelineController` variant is probably unreferenced, but
reachability was not traced. `create_adetailer_fixup_jobs` and `build_reprocess_jobs_batched`
(`reprocess_builder.py:961`, `:1144`) have no caller in `src/`.

### 2.4 Current shape

```text
 PackJobEntry ─► PromptPackNormalizedJobBuilder ─► JobBuilderV2 ─► [S2 record, discarded] ─► S3
 Pipeline-tab state ───────────────────────────► JobBuilderV2 ─► S2
 CLI args ─────────► build_cli_njr ─► S1 ─────────────────────────────► runner.run_njr (no queue)
 Review / edit / Photo Optimize / curation ─┐
 Learning non-txt2img variant ──────────────┤
 Video Workflow form, SVD config, ──────────┼─► ReprocessJobBuilder.build_reprocess_job ─► S4
 sequence plan, movie spec ─────────────────┘
 Learning ordinary txt2img ─► ordinary_njr ─► S7        Learning frozen arms ─► learning_njr ─► S6
 TrainingIntent ─► S5
 stored NJR ─► compile_replay_intent (V1) / compile_history_variation (V2) / sequence_resume (V4)

 S2..S7, V1, V2, V4 ─► [reprocess_admission | ExperimentAdmissionService | direct] ─► JobService.submit_njrs
                       └─ require_execution_admission (retired execution, video workflow admission), all sources
```

## 3. Policy ownership (Deliverable B)

Legend: **C** applied at compile or freeze; **A** applied by an admission wrapper before `submit_njrs`; **J** applied
inside `submit_njrs`; **R** only at run time in the backend; **F** validated once when the experiment was frozen;
**i** inherited unchanged from the parent record; **-** not applied; **n/a** not meaningful for the workload.

| Policy (current implementation) | CLI S1 | Generic S2 | PromptPack S3 | Reprocess / edit S4 | Video S4 | Learning S6, S7 | Replay V1 | Variation V2 | Training S5 |
|---|---|---|---|---|---|---|---|---|---|
| 1. Model-family compatibility, `apply_model_compile_policy` (`model_policy.py:500`) | C | C | C twice | - (Klein only, via `prepare_klein_edit_item`) | n/a | F | i | i | n/a |
| 2. Exact identity and registry evidence, `CompileEvidence`, `resolve_model_policy` | - | - | C | - | workflow catalog identity | F | i | i | n/a |
| 3. Profile-owned value normalization, `normalize_profile_owned_values` | - | C (`prepare_effective_config`) | C (own call, then again inside S2) | - | n/a | F (`prepare_candidate_baseline`) | i | i | n/a |
| 4. Source versus effective configuration | - | evidence block `effective_configuration` | separate `source_config`, adaptation manifest | - | n/a | frozen arm carries both | i | i | n/a |
| 5. Precedence and deep merge | caller | `ConfigMergerV2` | `ConfigManager.resolve_config` | `_merge_nested_dicts` | none | frozen baseline | i | targeted key edits | caller |
| 6. Stage selection and capability | `pipeline.*_enabled` flags | txt2img, plus ADetailer when no `stages` key | `_normalize_stage_flags`, `_build_stage_chain` | caller list checked against `VALID_REPROCESS_STAGES` | caller | `authoring.require_stage`, `stage_capabilities` | i | i | fixed |
| 7. Prompt adaptation and rendering | verbatim | verbatim; Z-Image global terms composed | structured intent, `adapt_pack_intent`, render | verbatim | verbatim | frozen per arm | i | verbatim edit | synthetic |
| 8. LoRA, embedding, ControlNet | - | - | C (Klein LoRA selection, `compile_units`, OpenPose) | - | workflow-declared inputs | F (inventories, readback) | i | reconciled against edited text | n/a |
| 9. Expansion, seeds, randomization | none; seed `or -1` | config variants x randomizer x batch | Matrix x S2 fan-out, index recombined | grouping and chunking | per-source seed freeze | frozen seed policy | i | edited seed | n/a |
| 10. Source, workload and lineage identity | `CLI` | **`CLI`** | `PROMPT_PACK` with id, revision, row | alias table; any video stage forces `VIDEO_WORKFLOW` | `VIDEO_WORKFLOW` | `LEARNING` with `LearningJobContext` | `HISTORY_REPLAY` with parent | same plus variation block | `TRAINING` |
| 11. Output plan and naming | default `output` | `OutputSettings` dir | `pipeline.output_dir` | caller dir | caller dir, `output_route` | resolved dir and template | i | i | train output dir |
| 12. Provenance and evidence | `execution_source` | `effective_configuration`, `adetailer_mode` | `prompt_adaptation`, `matrix_expansion`, `conditioning` | `reprocess` schema block | `video_workflow` block, hashes | study metadata, arm record | `replay`, `replay_origin` | `history_variation` block | training metadata |
| 13. Backend selection, `normalize_image_backend_options` | C | C | C over `derive_backend_options` | C | n/a | F, equality-checked at Run | i | i | `derive_backend_options` |
| 14a. Intent canonicalization, `canonicalize_intent_config` | C | - | C | - | - | - | i | edited | C |
| 14b. Exact-profile NJR check, `validate_zimage_njr` / `validate_profile_njr` | **R** | C | C twice | A via operation policy | n/a | C (S6); F only (S7) | R | C | n/a |
| 14c. Operation policy, `require_njr_operation` / `assess_njr` | - | - | - | A (`reprocess_admission.py:27`), C in edit services, per-row in Review | n/a | - | A for batch retry; - for History replay | C | n/a |
| 14d. Retired execution (AnimateDiff, secondary motion) | R (runner, `pipeline_runner.py:835`) | J | C and J | C and J | J | J | C and J | J | J |
| 14e. Video workflow admission, `require_workflow_admission` | n/a | n/a | n/a | n/a | J | n/a | J | n/a | n/a |

Future owner of every row: the named policy function stays where it is (its subsystem owns the rule); the **decision of
whether and when it runs** moves to the assembly core, driven by the draft's declared policy state (section 5.2).

## 4. Discrepancy register

Classes: **I** intentional and contractually valid; **D** confirmed defect; **P** potential defect needing
reproduction; **S** stale finding; **M** material product or architecture decision.

| ID | Finding and evidence | Consequence | Class |
|---|---|---|---|
| X1 | Generic Pipeline-tab jobs are written with `SourceKind.CLI` (`job_builder_v2.py:180`; `tests/golden/njr/job_builder_v2.json` freezes `"kind": "cli"`). The legacy alias table also maps `"manual"` to `CLI` (`njr_core_v26.py:1191`) | History, replay lineage (`original_source_kind`) and `prompt_source` say "cli" for work authored in the GUI. A GUI job and a real CLI job cannot be told apart from the record | **D**; the fix is **M** (a new `SourceKind` value, audit decision 13) |
| X2 | PromptPack compiles every job twice. `_prepare_entry` applies `apply_model_compile_policy` (`prompt_pack_job_builder.py:410`); `JobBuilderV2` then builds a complete `CLI`-sourced NJR, applying `prepare_effective_config` and `apply_model_compile_policy` again (`job_builder_v2.py:151-152`) and `validate_zimage_njr` (`:207`); S3 discards that envelope, rebuilds it and validates again (`:665`) | Correct output depends on every profile policy being idempotent, which no test asserts. Each job pays two constructions and two validations. A transient record with the wrong source kind exists mid-compile | **D** (duplication confirmed; no wrong output demonstrated) |
| X3 | Exact-profile NJR validation timing differs by route: compile for generic, PromptPack, variation and Learning S6; admission wrapper for reprocess; run time only for CLI and single History replay | The same unsupported request is refused before Preview on one route and after dispatch preparation on another | **D** as an inconsistency; unifying it is **M** (it changes refusal timing) |
| X4 | `build_cli_njr` reads the seed as `int(txt2img.get("seed", -1) or -1)` (`cli_njr_builder.py:140`) | An explicit seed `0` is recorded as `-1` (random) | **D**, low severity |
| X5 | `intent_config` is canonicalized by CLI, PromptPack and training only; generic, reprocess, video and Learning records carry an empty `intent_config` | Any reader of `intent_config` (adaptive refinement and secondary-motion intent) sees nothing for those sources | **P**; no consumer failure was traced |
| X6 | The generic path swallows every compile exception and returns no jobs (`pipeline_controller.py:339-341`) | A profile refusal on the generic path may reach the operator as an empty Preview with no reason | **P** |
| X7 | PromptPack silently drops an entry whose pack config cannot be loaded (`prompt_pack_job_builder.py:375`) | A batch can be admitted with fewer jobs than selected | **P** |
| X8 | `StageConfig` is populated differently per builder: generic sets four typed fields from flat keys and no `extra`; CLI copies the whole section into `extra`; Learning sets `extra={}`; PromptPack curates `extra` per stage | Record accessors (`sampler_name`, `scheduler`, `vae`) resolve through different fallbacks per source | **I** for P4-2 (frozen by parity); owned by P4-4 |
| X9 | Three source-kind mappings: `_legacy_source_kind` (`njr_core_v26.py:1180`), `source_aliases` (`reprocess_builder.py:301`), and `JobService._job_from_njr` | Duplicate tables can drift | **D**, low; consolidate in P4-2F |
| X10 | Every video stage forces `SourceKind.VIDEO_WORKFLOW`, including native SVD and Movie Clips (`reprocess_builder.py:309-313`) | SVD and assembly jobs carry the kind `video_workflow` | **I**: the envelope has one video source kind and `_validate_source_workload` requires it |
| X11 | Learning Run performs no adaptation and checks equality with the frozen arm (`learning_njr.py:97-102`, `model_comparison.py:834`) | Policy is applied once, at Preview | **I** |
| X12 | Replay re-applies no model policy (`replay_njr_compiler.py`; `forge_zimage_profile.py:268` "persisted/replayed work must already carry v1 values") | A replay reproduces its parent | **I** |
| X13 | The legacy (non-strict) Learning path hard-codes defaults and the controller still falls back to the literal prompt "a test prompt" (`ordinary_njr.py:207-215`, `learning_controller.py:1318`) | Only snapshots frozen before independent baselines take this path; it has a named retirement condition | **I** (compatibility); the GUI-side fallback is P4-3 |
| X14 | The CLI calls `runner.run_njr` directly (`src/cli.py:140`) | CLI work is not queued and never crosses `submit_njrs` | **M**, outside P4-2; pre-existing |
| X15 | Dormant direct-queue replay (`job_execution_controller.py:452`), see 2.3 | If reachable, a replay would skip `submit_njrs` validation | **P**, outside P4-2; a removal candidate of the ARCH-951 kind |
| X16 | Audit claims re-checked: "NJRs built in the GUI controller" | Construction moved to `src/learning/` | **S** |
| X17 | Audit claim "7 deep-merge implementations" | At least seven merge helpers exist by name; three sit on a compile path (`ConfigManager._deep_merge_dicts`, `ConfigMergerV2._merge_nested_dict`, `ReprocessJobBuilder._merge_nested_dicts`). Bodies were not compared | **P**, low |

No new high-severity data-integrity or runtime-ownership defect was confirmed. X14 and X15 are pre-existing
deviations from the queue-first rule that the owner should classify; neither blocks this design.

## 5. Architecture (Deliverable C)

### 5.1 Alternatives

| Criterion | A. Shared finalization | B. Typed canonical core | C. Central coordinator | **Recommended: A with typed drafts and policy states** |
|---|---|---|---|---|
| Behavioral parity | High: builders keep their order | Low: one order imposed on all sources | High | High: order kept where a source needs it |
| Duplication removed | Construction only | Construction and policy | Little; adds a facade | Construction, the double PromptPack compile, and the "when does a policy run" decision |
| Source flexibility | Full | Poor: PromptPack must normalize before it has read source intent | Full | Full |
| Model-family extensibility | Unchanged | Family logic tends to collect in the core | Unchanged | Core calls only neutral seams; family names forbidden in it |
| Typed contract, testability | Weak | Strong | Medium | Strong at the one boundary that matters |
| NJR compatibility | No change | No change intended, high accidental risk | No change | No change |
| Migration risk | Low | High, effectively one large cut-over | Low | Low to medium; PromptPack isolated as the last step |
| Coupling and direction | Sources -> pipeline | Sources -> pipeline | **Pipeline -> learning, video** (the coordinator must import every source) | Sources -> pipeline only |
| Run-time cost | Neutral | Neutral | Neutral | Removes one construction and one validation per PromptPack job |
| Implementation and CI cost | Small | Large | Medium | Medium, spread over six packages |
| Cost of the next model family | Unchanged | Lower only if family logic is kept out | Unchanged | One place decides when its policy and validator run |

B is rejected because it requires a common configuration representation. The evidence against it is specific:
PromptPack must keep the operator's `source_config` separate from the executable one and must read the stored global
positive terms *before* profile normalization blanks them (`prompt_pack_job_builder.py:393-409`); Learning must not
transform a frozen arm; video, movie assembly and training configurations share no keys with image configuration.
C is rejected because it inverts the dependency direction and consolidates no policy. A alone is insufficient because
it cannot express "this policy has already been applied", which is exactly the defect in X2.

### 5.2 Recommended design

One module, `src/pipeline/njr_compiler.py`, owns record assembly. It is the only place outside the read path
(`NormalizedJobRecord.from_dict`, `migrate_legacy_njr`) that constructs a record or assigns a new `job_id`.

```python
class PolicyState(Enum):
    RAW = "raw"              # merged config; the core applies the fresh-work policies
    EFFECTIVE = "effective"  # the planner already ran the shared steps in its own order
    FROZEN = "frozen"        # values come from a validated frozen snapshot; never transformed

@dataclass(frozen=True, slots=True)
class NjrDraft:
    """Envelope-shaped: the eight NJR parts before validation. Not a configuration IR."""
    job_id: str
    workload_kind: WorkloadKind
    source: SourceDescriptor
    workload: Workload                      # ImageWorkloadSpec | VideoWorkloadSpec | TrainingWorkloadSpec
    stages: tuple[StageConfig, ...]
    output_plan: OutputPlan
    provenance: NJRProvenance
    policy_state: PolicyState
    checks: frozenset[CompileCheck]         # which post-construction checks this source runs today

def compile_njr(draft: NjrDraft) -> NormalizedJobRecord: ...            # one draft, one record
def derive_njr(parent: NormalizedJobRecord, change: NjrDerivation) -> NormalizedJobRecord: ...
```

- **Cardinality.** `compile_njr` returns exactly one record. Planners return sequences of drafts and own Matrix,
  randomizer, batch, arm and per-source expansion, including index arithmetic and whole-batch decisions (Klein LoRA
  review, `verify_arms_admissible`). Batch atomicity stays with `ExperimentAdmissionService.compile_all`,
  `reprocess_admission` and `submit_njrs`.
- **Shared steps.** The existing functions become the core's named steps, each with one owner and one call site in the
  core: `prepare_effective_config`, `apply_model_compile_policy`, `compile_adetailer`,
  `normalize_image_backend_options`, `canonicalize_intent_config`. A planner that needs a step early (PromptPack)
  calls the same step through the core's public function and hands over an `EFFECTIVE` draft.
- **Order for a `RAW` image draft:** (1) effective-config preparation, (2) model compile policy, (3) stage-conditional
  compile (ADetailer, which needs the final positive prompt), (4) backend-option normalization, (5) intent
  canonicalization, (6) construction, (7) declared checks. For `EFFECTIVE`: steps 6-7. For `FROZEN`: step 6, an
  equality check against the frozen values, then step 7. Video and training drafts run steps 6-7 only.
- **Checks** are declared per source so that migration changes no refusal timing: `PROFILE_NJR`
  (`validate_profile_njr`), `OPERATION` (`require_njr_operation`), `RETIRED` (`require_no_retired_execution`). A
  source declares exactly what it runs today (section 3, rows 14b-14d).
- **Refusals.** The core raises the existing exception types unchanged (`ZImageProfileError`,
  `OperationNotSupportedError`, `KleinSelectionError`, `AnimateDiffRetiredError`, `HistoryVariationRefused`,
  `ValueError`). Callers format `str(exc)` into per-row reasons (`video_workflow_batch.py:676`,
  `review_batch_service.py:168`), so message text is part of the frozen contract. A common refusal type is a later,
  separate decision.
- **Provenance.** The draft carries complete `SourceDescriptor` and `NJRProvenance` values built by the planner; the
  core never invents or drops evidence. `derive_njr` owns lineage: parent job id, parent artifact id,
  `original_source_kind`, and the batch-membership archive now in `compile_replay_intent`.
- **Model-family extension.** The core imports only the neutral seams in `src/image_backends/model_policy.py`,
  `exact_model_profile.py` and `operation_compatibility.py`. P4-5 can later replace what is behind them without
  touching the core. A guard test forbids family identifiers in `njr_compiler.py`.
- **Ownership.** `src/pipeline/njr_compiler.py`: drafts, steps, assembly, derivation. `src/pipeline/*_builder.py`,
  `src/learning/*`, `src/video/*`: planners. `JobService.submit_njrs`: admission, unchanged. The core takes no runtime
  service, registry handle or configuration manager; evidence a planner needs is resolved by the planner as today.

```text
 authoring input ─► source planner (cardinality, source rules, early steps) ─► NjrDraft(s)
                                         │ may call shared steps
                                         ▼
                    njr_compiler.compile_njr / derive_njr ─► NormalizedJobRecord
                      steps by PolicyState ─► single construction ─► declared checks
                                         ▼
               existing admission wrappers ─► JobService.submit_njrs (unchanged)

 imports:  src/learning, src/video, src/controller ─► src/pipeline/njr_compiler ─► src/image_backends seams
           njr_compiler never imports learning, video, controller or gui
```

## 6. Parity and compatibility (Deliverable D)

### 6.1 Existing golden coverage (`tests/golden/test_njr_golden_p4_2.py`, 12 tests, passing)

| Snapshot | Live path | Quality limits |
|---|---|---|
| `cli.json` | Yes, S1 | One ordinary model; no ADetailer; no profile |
| `job_builder_v2.json` | Yes, S2 | Flat minimal config; no config variants, randomizer or ADetailer; freezes X1 |
| `prompt_pack.json` | Yes, S3 | One row, no Matrix, randomizer off, no LoRA, embedding, ControlNet or exact profile |
| `reprocess.json` | Yes, S4 | Upscale only; random `job_id` masked rather than injected |
| `training.json` | Yes, S5 | Adequate for a held feature |
| `replay.json` | Yes, V1 | Parent is a CLI record only; no PromptPack parent, batch membership or sequence directive |

### 6.2 Coverage matrix and gaps

| Route | Record golden | Refusal baseline | Queue admission through `tests/helpers/njr_queue_harness.py` |
|---|---|---|---|
| CLI | Exists | Missing | Not applicable (no queue) |
| Generic | Partial | Missing: exact-profile refusal, swallowed exception (X6) | Partial |
| PromptPack | Partial | Subsystem tests only | Partial |
| Reprocess, image edit, masked, outpaint | Partial (upscale only) | Subsystem tests only | Partial |
| Learning ordinary, strict and legacy | **Missing** | Subsystem tests only | Missing |
| Learning frozen arms (three study types) | **Missing** | Subsystem tests only | Missing |
| History variation | **Missing** | Subsystem tests only | Missing |
| Replay, batch retry | Partial | Missing | Partial |
| Video Workflow, SVD, sequence, Movie Clips | **Missing** | Subsystem tests only | Missing |
| Training | Exists | Missing | Not required while on HOLD |

Missing tests, to be written before any migration (P4-2A): a golden per missing route; PromptPack with a 2x2 Matrix,
with the randomizer on, with a LoRA and an embedding, and with one exact profile; generic with config variants and
ADetailer; reprocess with img2img and with a mask; replay of a PromptPack parent that belonged to a batch; a sequence
resume; one refusal table per route recording exception type and message for an unsupported profile operation, an
enabled retired stage, an empty prompt and a missing input; and a fake-backend admission check per route family.

### 6.3 Behavioral freeze requirements

1. `record.to_dict()` is byte-identical before and after each migration, for every golden, with injected ids.
2. Refusal type, message text and the point of refusal (build, wrapper, admission) are identical.
3. Order and count of expanded records, seeds, and all index and total fields are identical.
4. A stored snapshot written before the migration reads to an equal record after it (`read_njr` round trip).
5. A golden file changes only in a commit whose message names the intended contract change and its authorization. A
   migration package that needs a golden change stops and reports.
6. Defects X1 and X4 are frozen as they are. They are corrected only by their own authorized change.

### 6.4 Evidence reuse

Golden and refusal baselines are generated once, on unchanged `main`, in P4-2A. Each later package re-runs only
`tests/golden`, the touched route's subsystem tests and the harness tests, then the PR gate once. Subsystem suites for
untouched routes are reused at their accepted SHA.

## 7. Migration (Deliverable E)

Six packages, detailed in [the work-package plan](../work_packages/P4-2_unified_njr_compiler_migration.md):

| Order | Package | Outcome | Depends on |
|---|---|---|---|
| 1 | P4-2A Baseline characterization | Every active route has a record golden, a refusal baseline and an admission check | Owner authorization only |
| 2 | P4-2B Assembly core and leaf routes | `njr_compiler.py` exists; CLI, training and the derivation routes (V1, V2, V4) assemble through it | A |
| 3 | P4-2C Reprocess and video | `ReprocessJobBuilder` assembles through the core; covers edits, Review, Photo Optimize, SVD, Video Workflow, sequences, Movie Clips, Learning non-txt2img | B |
| 4 | P4-2D Learning | S6 and S7 assemble through the core as `FROZEN` drafts | B, C |
| 5 | P4-2E Generic and PromptPack | One compile per PromptPack job; model policy applied exactly once | B; D recommended first |
| 6 | P4-2F Guard and cleanup | An architectural test fails on a new construction or derivation site; duplicate tables and proven-dead helpers removed; canonical documents updated | C, D, E |

The suggested ordering in the request was changed in two ways. Derivation is migrated with the first leaf routes,
because `derive_njr` is half of the core's contract and its callers are small. PromptPack moves last instead of
mid-sequence, because it is the only route where the core changes control flow rather than only the constructor.

## 8. Independent critical challenge (Deliverable F)

Method: the design in section 5 was derived from the inventory (what is common). The challenge works the other way: it
starts from concrete counterexamples and traces each through current source to see whether the proposed core would
change an observable result.

| # | Hypothesis challenged | Failure scenario and evidence | Verdict | Response |
|---|---|---|---|---|
| H1 | One construction site improves correctness | `NormalizedJobRecord.__post_init__` already centralizes structural validation for every site and for every `replace`. Counting call sites measures nothing about policy | **Confirmed** | Acceptance is restated as invariants: each policy step runs at most once per record (asserted), and no identity-changing `replace` exists outside the core. The grep count is a guard, not the goal |
| H2 | All builders should share one intermediate representation | A Video Workflow form, an `SVDConfig`, a `MovieAssemblySpec` and a merged image config have no common keys | **Confirmed** | The draft is envelope-shaped. No configuration IR is introduced |
| H3 | Source policy differences are accidental | X11 and X12 are documented contracts; X10 is forced by the envelope; X3 for the CLI has no stated rationale | **Partly refuted** | Three policy states encode the intentional differences; the rest are frozen and listed as decisions |
| H4 | Moving validation into a core does not change refusal timing | Review builds every record, then reports per-row reasons from `assess_njr` (`review_batch_service.py:168`). If the core validated at construction, the first unsupported row would abort the whole preview | **Confirmed** | Checks are declared per source and default to today's set. No package adds a check |
| H5 | Configuration normalization is safe before prompt adaptation | For Z-Image, `normalize_profile_owned_values` replaces global prompt terms and pops prompt channels; PromptPack reads them first and keeps `source_config` for the adaptation manifest | **Confirmed unsafe** | The `EFFECTIVE` state lets the planner order the shared steps; the core never normalizes a draft it did not receive as `RAW` |
| H6 | Source and effective settings can be unified without losing intent | The adaptation manifest and `effective_configuration` evidence both need the pre-normalization values | **Refuted** | Both stay; the draft carries the evidence the planner produced |
| H7 | A common compiler simplifies new families without generic branches | Builders already import family symbols (`zimage_selected`, `klein_selected`, `validate_zimage_njr`). A core is the natural place for the next `if` | **Plausible** | Core restricted to neutral seams with a guard test; removal of the existing branches is P4-5, not P4-2 |
| H8 | Existing goldens prove compatibility | Section 6.1: six happy paths, no profile, Matrix, Learning, video or refusal; two snapshots freeze known defects | **Refuted** | P4-2A is a hard prerequisite |
| H9 | Consolidation is independent of P3-2 | Compile functions are pure. The only composition coupling is where `PromptPackNormalizedJobBuilder` is constructed (`prompt_pack_preflight.py:140`), which the core does not touch | **Confirmed independent**, with one constraint | The core must not grow a context object that resolves services; if it did, it would become a second composition point |
| H10 | The benefit justifies the risk | Benefits are real but mostly enabling. The measurable ones: one fewer construction and validation per PromptPack job; one decision point for policy timing; full golden coverage. Risk concentrates in P4-2E | **Plausible** | P4-2A is worth doing even if nothing follows. A stop after P4-2D plus the guard is a valid end state: all sites but generic and PromptPack unified, X2 documented |

Counterexamples traced:

- **PromptPack Matrix.** Variant indexes are recombined after the inner fan-out
  (`prompt_pack_job_builder.py:548-552`), and the Klein LoRA review completes for the whole batch "before the first
  NJR exists". A per-record core is compatible only if planners finish all batch decisions before producing drafts and
  supply final indexes. The design requires exactly that.
- **Multi-model Learning.** If the core applied `apply_model_compile_policy` at Run, a profile change between Preview
  and Run would alter a frozen arm without the equality check noticing a compensating change. `FROZEN` forbids it.
- **Historical replay.** A parent hydrated through `migrate_legacy_njr` may not satisfy today's compile policy.
  `derive_njr` runs only the checks V1 runs today.
- **Video workflow validation.** File hashes are re-verified inside `build_job`; admission is in `submit_njrs`. The
  core adds nothing between them.
- **Partial batch failure.** Video batches collect `str(exc)` per row; PromptPack drops an unloadable pack (X7); the
  generic path returns no jobs (X6). All three are frozen as observed and listed as potential defects, not fixed.
- **Model-profile overrides** (generation profiles) are applied during configuration merge, upstream of every
  compiler. Not traced further; residual uncertainty, low.

Revision after challenge: the initial design had a single `compile_njr` and treated replay as a planner. H1 and the
replay counterexample showed derivation is a distinct contract, so `derive_njr` was added and the acceptance criterion
changed from a site count to the two invariants in H1. H4 changed "the core validates" to "the core runs the checks the
source declares".

Residual uncertainty: reachability of V3, X15 and the two unreferenced reprocess helpers; whether any consumer depends
on empty `intent_config` (X5); idempotence of profile policies under a second application (assumed by today's code,
untested).

## 9. Owner decision gates

| ID | Decision | Recommendation | Blocks |
|---|---|---|---|
| OD-1 | Authorize P4-2A (tests only, no source change) | Yes | Everything |
| OD-2 | Add a GUI/manual `SourceKind` to correct X1 (audit decision 13). It is an additive enum value; a record carrying it cannot be read by an older build | Decide separately; not part of P4-2A-F. If approved, a seventh package after F | Nothing in this plan |
| OD-3 | Change any refusal timing (X3: CLI, reprocess at construction, single History replay) | Preserve today's timing through P4-2F; revisit with the core in place | Nothing |
| OD-4 | Adopt a canonical configuration shape | No. Rejected in section 5.1; typed stage settings are P4-4 | Nothing |
| OD-5 | Does the core depend on P3-2? | No, subject to the H9 constraint | Nothing |
| OD-6 | Must P4-4 precede any migration? | No. P4-2 freezes X8; P4-4 then has one construction boundary to type | Nothing |
| OD-7 | Backend or family ownership moves | None in P4-2. Removing family branches from builders belongs to P4-5 | Nothing |
| OD-8 | Include the held Character Training compiler in P4-2B | Yes: constructor swap only, golden exists, the hold is not relaxed. The owner may exclude it and accept one documented exception to the guard | P4-2B scope |
| OD-9 | Classify X14 (CLI runs without the queue) and X15 (dormant direct-queue replay) | Outside P4-2; X15 fits an ARCH-951-style removal after a reachability proof | Nothing |
| OD-10 | `STATUS.md` decision 9 (store the Model Comparison snapshot once per experiment) touches `arm_njr` metadata | Keep it a separate NJR-contract package; do not combine with P4-2D | P4-2D scope |
| OD-11 | Authorize P4-2E only after reviewing P4-2A-D results | Yes; E is the one package that changes control flow | P4-2E |

## 10. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A golden is regenerated to hide a changed contract | Medium | High | Freeze rule 6.3(5); the update environment variable is never set in a migration package |
| PromptPack single-compile changes a Z-Image or Klein record | Medium | High | Exact-profile goldens in P4-2A; E is last and separately authorized |
| The core accumulates family branches | Medium | Medium | Guard test on identifiers; P4-5 owns the plugin protocol |
| The transitional period leaves two ways to build a record | Certain, temporary | Low | Removal condition is P4-2F; each package deletes the old constructor it replaces |
| Exception text changes break per-row reasons | Low | Medium | Refusal baselines record message text |
| Concurrent work (ARCH-951 branch, P4-3) edits the same files | Medium | Low | Each package rechecks `origin/main` and rebases its goldens only by re-running, never by editing |

## Work-package decision

Outcome: authorize P4-2A. Scope: tests under `tests/golden/` and reuse of `tests/helpers/njr_queue_harness.py`; no
`src/` change. Smallest validation: `pytest tests/golden`. Full gate: `python tools/ci/run_pr_gate.py` once before
publication. Physical authorization needed: none. Claude Code: Sonnet 5.5 High; Codex: GPT-6.1 Sol High.
Publication and merge: **not authorized by this assessment**.

## Review quality

Method diversity: inventory-driven design, then counterexample-driven challenge. Negative cases examined: refusal
timing per route, swallowed exceptions, silent entry drop. Not done: no test other than `tests/golden` was run; no
defect was reproduced by execution (X1-X4 are established by reading and by the golden files); reachability of dormant
paths was not traced; merge-helper bodies were not compared. Evidence that would reverse the recommendation: a golden
in P4-2A showing that a second application of a profile policy changes a record (X2 would become a wrong-output defect
and P4-2E would move earlier), or a consumer that requires route-specific `intent_config` (the draft would need a
further field).

## Evidence links

- Work-package plan: [`docs/work_packages/P4-2_unified_njr_compiler_migration.md`](../work_packages/P4-2_unified_njr_compiler_migration.md)
- Audit finding C2 and package P4-2: `docs/audits/2026-10-16_repo_audit_and_roadmap.md`
- Prior static design record: [`2026-11-10_arch_design_950_coordination_hotspot_decomposition.md`](2026-11-10_arch_design_950_coordination_hotspot_decomposition.md)
- Golden suite: `tests/golden/test_njr_golden_p4_2.py`, `tests/golden/njr/`
