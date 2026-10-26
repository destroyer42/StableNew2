# WF-740 — Model/Profile/Learning End-to-End Assurance and Bounded Repairs

**Type:** Full proposed implementation PR contract. **Status:** unimplemented; requires separately authorized coding session and feature-branch publication. **Priority:** next primary product package in [2026-10-26 roadmap](../audits/2026-10-26_product_capability_roadmap.md).  
**Class:** Standard with lifecycle/persistence sensitivity; stop and reclassify if a material architecture decision appears.

## Objective

An operator can select an identity-verified checkpoint, choose a compatible Research/Custom or explicitly selected qualified Learning generation profile, change allowed working settings, Preview the effective configuration, queue precisely that immutable NJR through JobService and SQLite, run a controlled Learning experiment, rate verified results, explicitly publish a qualified immutable Learning profile revision, reselect it, and generate a subsequent Preview/NJR with the exact intended settings.

**A correct evidence-only PASS with zero code changes is an acceptable result.** Do not create behavior solely to justify a PR. Initial work must identify actual gaps in the recently merged solution, not design a second profile system.

## Model and usage recommendation

- **Claude Code:** Sonnet 5.5 **XHigh**.
- **Codex:** GPT-6.1 Sol **XHigh**.
- **Preferred host:** Local/Desktop, either currently productive coding host, because real Tk, Windows config state and SQLite persistence boundaries matter. Avoid a switch that discards useful session context.
- **Lowest likely tier:** XHigh for cross-file state precedence, immutable queue admission, Learning record qualification and concurrent immutable revisions; normal High would be enough for a narrow confirmed code bug alone, but not the full integration contract. Escalate to Opus 5.5 / GPT-6 Astra only on discovered material architecture ambiguity.
- **Expected usage:** order of magnitude **25M cache-read and 120k output tokens** including review/repair/closeout. Record time and session IDs before discovery, measure the complete window according to docs/AI_MODEL_SELECTION.md, and investigate category ratios over 3x. Never invent a missing measurement.

## Exact start-state authority

1. On local machine inspect git status --short --branch, git rev-parse HEAD, git remote -v, compare current local and origin/main ancestry and diff (including ignored/untracked user work) and inspect branch conflicts. **Historical remote assessment base was 2142e9d95aceaa72c152a89e1a27a0c83d226a5e; do NOT treat it as a required fresh base.**
2. Check whether existing [#223 IMG-EMBED-720](https://github.com/destroyer42/StableNew2/pull/223) is still open or integrated, and whether it overlaps tested prompt/preview source. No implicit stack/merge/reimplementation. If the current source differs, re-fingerprint accepted evidence rather than restarting the entire analysis.
3. Read AGENTS.md (highest repo rules), STATUS.md (current decisions/holds), CODEX_MAP, CODE_MAP, CODEX_WORK_PACKAGE_TEMPLATE, AI_MODEL_SELECTION, the living Image/Model Profiles/Learning documents and only relevant tests/code. Record task-start offset-aware ISO time, host and all session IDs before discovery.
4. Reuse [#208](https://github.com/destroyer42/StableNew2/pull/208) profile/startup, [#210](https://github.com/destroyer42/StableNew2/pull/210) Learning UX, [#212](https://github.com/destroyer42/StableNew2/pull/212) Learning baseline, [#213](https://github.com/destroyer42/StableNew2/pull/213) publication, [#216](https://github.com/destroyer42/StableNew2/pull/216) Prompt Slot, [#218](https://github.com/destroyer42/StableNew2/pull/218) LoRA, [#220](https://github.com/destroyer42/StableNew2/pull/220) Embedding and [#222](https://github.com/destroyer42/StableNew2/pull/222) Prompt x Model exact-source tests/evidence whenever still valid.

## Source ownership and permitted repairs

Find current paths from CODEX_MAP and relevant living docs. Candidate investigation homes are src/generation_profiles/, src/controller/generation_profile_controller.py, src/gui/generation_profile_strip.py, src/gui/app_state_v2.py, current Pipeline working-settings/Preview projections, src/learning/profile_publication.py, src/learning/execution_controller.py, src/learning/ordinary_njr.py, src/learning/learning_controller_services/, src/gui/controllers/learning_controller.py, src/pipeline/prompt_pack_job_builder.py and src/pipeline/config_contract_v26.py. Relevant tests are under tests/gui_v2, tests/learning_v2, tests/pipeline and tests/controller. These are navigation clues, not a frozen file whitelist.

**Controller Surface Assessment:** If controller/coordinator source is touched, record file line/import counts before and after. Extract new logic into an owned domain/service, never append responsibility inline to a ratcheted god controller; lower improved baselines using the corresponding tool --update and never raise ceilings.

**Architecture unchanged:** Intent -> Compiler -> immutable NJR -> JobService.submit_njrs -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History. GUI owns authoring projections, not backend payloads, a parallel compiler, queue, job lifecycle or runner. Replay lineage and ModelPolicy final executable authority remain intact.

**Excluded:** new model families/geometry theories, new controlled experiment types, a global model winner, automatic Learning publication or favorite/setting changes, new queue/runner/history/persistence authority, prompt schema migration, experimental Comfy still-image path, Qt migration, GPU/Forge/SVD/Comfy/AI inference and restart, external network/download, real user-store mutation or historical NJR rewriting. Exact unsupported values must be reported/refused, not silently dropped as a workaround.

## First-pass gap inventory and falsification

Before changing source, trace current production wiring with a compact T01–T12 evidence table: reachable UI action -> projection/controller -> actual domain author -> compiler -> NJR -> JobService/SQLite -> outcome, existing test at current source SHA, and missing proof. Classify each finding as: **verified blocking current defect; missing assurance; intentionally unsupported; stale/already fixed; unrelated debt**.

A source change is justified only for a confirmed in-scope defect that affects the operator outcome. If all existing components already agree, provide evidence-only acceptance and do not make cosmetic churn or duplicate existing tests.

## Acceptance (T01–T12)

| ID | Controlled setup | Expected observable result |
| --- | --- | --- |
| T01 | Exact model file, renamed same hash, reused name with different bytes, stale policy version | Exact identity/profile match or explicit conflict; no substring identity or stale compatible claim |
| T02 | Switch among verified SDXL, Klein 4B, Z-Image and an unverified checkpoint in fake resource inventory | VAE, sampler/scheduler, steps, CFG and geometry never leak unsupported family defaults; no invented evidence for unknown models |
| T03 | Research, Custom, qualified Learning, favorite and explicit operator selection | One truthful chosen profile and per-setting provenance; ModelPolicy overrides profile where it owns a fixed/unsupported setting |
| T04 | Save and restart startup defaults, delayed registry arrival, missing selected model | Restore allowed model/settings and stage flags without source image, mask, file paths, jobs, experiment or generated artifact; no backend launch or silent replacement |
| T05 | PromptPack saved config, Override OFF/ON, current working card values | Source/precedence is visible; no surprise PromptPack write; Preview reflects the same selected source the eventual NJR will freeze |
| T06 | Change checkpoint, profile, override or stage after a Preview | Stale Preview refuses admission until recomputed; verified final effective settings == persisted admitted NJR (model, VAE, sampler, scheduler, steps, CFG, geometry, seed and enabled stages) |
| T07 | Learning editable independent baseline -> Preview -> Run | Snapshot/variants frozen, no fresh reading of mutable Pipeline; atomic one-call JobService admission, double-submit prevented, uncertain admission requires operator attention |
| T08 | Completion and restart with fake persisted repository records | Only exact admitted job identity, actual seed, model and request evidence reconcile; missing/mismatched readback labeled uncontrolled, never made into fabricated controlled evidence |
| T09 | Rate a completed controlled variant, reload ratings; attempt unsupported/descriptive study recommendation | Durability or visible write failure; only qualified varied-setting evidence can recommend. Two-Axis, Model Comparison, Prompt Slot, LoRA Composition, Embedding and Prompt x Model remain descriptive where mandated |
| T10 | Explicit publish eligible settings, simultaneous next-revision writes and stale/checkpoint-changed evidence | Immutable atomic revision/no overwrite; ineligible or competing proposal refused; no auto-select/favorite/startup change |
| T11 | Explicitly choose published Learning profile, Preview and enqueue another normal job | Frozen next NJR contains only admissible selected values, old jobs and profiles preserved; lineage/evidence references valid |
| T12 | Negative recovery: failed store write, stale callback, visibility changes, changed design, duplicate clicks and unavailable resources | Work preserved; no false saved/queued/qualified success, race-driven overwrite, GUI thread violation or second authority |

Tests should inspect the real compiled/queued payload and return path, not rely only on mocked UI labels. Use temporary user roots, fake AssetRegistry/Policy/JobService/SQLite, exact deterministic image identities and minimally necessary real-Tk tests. No production process/network/GPU interaction, test modification to conceal failure, or assertions weakened to go green. Check both positive and fail-closed scenarios.

## Required validation / independent review

1. Reproduce confirmed production defect against **unmodified** current base before a repair; if existing tests already prove a T-case, reuse them. Avoid a new broad test suite just to restate coverage.
2. Focused tests for changed behavior first, one coherent source implementation pass, no more than one batched repair/reverification per confirmed failure class. Run independent aggregate architecture/lifecycle review: identity and policy, immutable NJR, atomic publication, Tk dispatch, restore/races, downstream backend safety, process ownership and no duplicate submit.
3. Run local Python 3.14 python tools/ci/run_pr_gate.py once near source freeze if implementation actually changes. Hosted **required/full-suite/windows** is the exact-SHA merge verdict after separate authorized publication. Do not parallelize two full local pytest runs or contact an ambient Forge/WebUI.
4. Verify git diff --check, code-map freshness if modules change, ratchet baselines and exact feature branch worktree/parent/HEAD. Categorize current review findings into in-scope blockers, non-blocking debt, stale/duplicate or future hardening; only confirmed blockers trigger repair.
5. Update only current living Image/Model Profiles/Learning docs if behavior changed, STATUS.md only if its supported capability, owner decision, hold or next action truth changed. Never add a PR log to STATUS.

## Stop and authority limits

**Stop** if source contradicts assumptions, any new material operator-default/auto-publication or data migration decision is required, a single composition root or novel lifecycle owner becomes necessary, unrelated user work is threatened, more than two failure classes appear, a higher execution class is needed, or a separate objective begins. Ask for an owner decision on the concrete conflict; do not silently widen.

An authorized local implementation session may branch, edit, test and commit scoped work. This document does **not** authorize push, open/update PR, merge, tag, release, user-data deletion, runtime restart or physical generation. Publishing/merge need explicit action-and-target authorization.

## Completion report / exit

Provide start parent and final SHA, branch/worktree state, full T01–T12 evidence matrix, focused fixes (or no-change PASS), source effect, ratchet effect, local/hosted CI evidence, unresolved qualified/physical risk and owner decision. Finish with one **Model / usage** line for each participating exact-session window using docs/AI_MODEL_SELECTION.md (actual model, effort, passes, PASS/FAIL/BLOCKED, fresh input/cache read/cache write/output including reasoning within output); missing telemetry is unavailable, never an estimate.
