# IMG-EMBED-730 — Conditional Post-720 Aesthetic Preview/Evidence Fidelity

**Status:** **NO-GO for duplicate syntax repair; conditional proposed follow-up only.**
**Current existing repair:** [PR #223 / IMG-EMBED-720](https://github.com/destroyer42/StableNew2/pull/223), head cfdd922d9ec05bf2286eb7f0e337fb1b16bf3cdf at preparatory assessment. Full-suite, Windows and required CI jobs were green. Do **not** infer merge authorization.
**Roadmap:** [2026-10-26 capability priorities](../audits/2026-10-26_product_capability_roadmap.md). This is not the next primary PR; WF-740 is.

## 1. Collision and root-cause adjudication (mandatory)

The user's originally requested aesthetic embedding repair already has an implementation PR. #223 changes both txt2img and img2img fallback to use the shared, validated textual-inversion invocation.

**Action 1:** Recheck main/PR state and review #223 final diff, merged ancestor, required check conclusions and current review threads. If it is still open, recommend acceptance or in-scope repair.

**Action 2:** Only if a distinct, user-material problem survives the accepted #223 change may IMG-EMBED-730 become a new authorized implementation package. The two *candidate*, **not yet established** residual concerns are:
- Preview does not currently project an executor-time aesthetic prompt injection. This is not automatically a bug: compiled Preview may truthfully promise only input/effective settings, not final executor composition.
- img2img response handling may observe textual-inversion report data without projecting that report into stage metadata. Do not call this a defect unless required artifact/provenance semantics prove it.

If there is no meaningful defect, **return NO-PR/PASS**, and mark IMG-EMBED-730 unnecessary. Do not create code churn or tests simply to satisfy the name.

## 2. Model and execution contract

- **Class:** Narrow known-root-cause *if* a single residual projection/evidence bug reproduces. **STOP/reclassify Architectural** if resolution needs changes to NJR schema, compiler/runner ownership, or user-visible product semantics.
- **Claude Code:** Sonnet 5.5 **Medium**; **Codex:** GPT-6.1 Sol **Medium**. **Preferred environment:** current productive Local/Desktop Windows session (Tk/effective-Preview and outbound fake-Web/asset state all matter).
- **Why this tier:** #223 already repairs the renderer, so only one bounded source/metadata projection seam may remain; Medium should be sufficient with existing golden tests. Use High only after a confirmed defect, not before.
- **Expected usage if activated:** about **4M cache-read and 25k output** for the complete session/review, measured from start to closeout with host/session IDs and the current docs/AI_MODEL_SELECTION evidence.
- **Initial authority:** on target desktop verify branch, HEAD, clean worktree/untracked files, current origin/main, #223 head/merge CI, AGENTS.md, STATUS.md, CODEX_MAP, CODEX_WORK_PACKAGE_TEMPLATE and current docs/AI_MODEL_SELECTION state before editing.

## 3. Acceptance and falsification

| ID | Before-edit evidence question | Required outcome |
| --- | --- | --- |
| E01 | Does accepted #223 send a validated bare-name fallback, avoid duplicate existing bare/weighted invocations, and reject invalid names for both txt2img and img2img? | Reuse/finally confirm identical semantics; no duplicate or unsafe invocation. |
| E02 | Does the GUI or Preview claim final outbound prompt fidelity while omitting the fallback appended later in the executor? | Only if this is demonstrably misleading, either use the existing final executor semantics or revise documentation/Preview truthfulness. |
| E03 | Is an actual backend textual-inversion consumption report present in the img2img response, but wrongly absent from a user-visible or required provenance surface? | Reproduce loss with a concrete record and fix only the missing projection path. |
| E04 | Malformed, missing, disallowed asset; negative vs positive; compiled weighted invocation already present | No duplication, unsafe invocation, silent substitution, invented consumption or product claim. |
| E05 | Aesthetic Gradients script mode, script args, optimizer, exact profile policy, Prompt x Model Matrix | All maintain their current semantics; matrix still refuses aesthetic conditioning and current policy remains unchanged unless proven wrong. |
| E06 | Stale Preview, reprocess, replay, immutable NJR and error/failure handling | No mutable post-freeze GUI/readback changes or second queue/compiler; old stored artifacts and records remain authoritative. |

**Go/no-go gate:** First produce E01–E06 source/test/contract evidence on current integrated source. Classify as verified defect, documented intentionally limited Preview, missing qualification, or no defect; only then act.

## 4. Candidate work surface and explicit exclusions

Inspect existing src/pipeline/executor.py aesthetic handling, src/utils/embedding_prompt_utils.py, the current Pipeline/Prompt effective Preview projection, request/result TI extraction and relevant installer docs.

**Do not:** repeat #223 syntax changes; add a second embedding renderer; change script Aesthetic Gradients arguments, Prompt x Model Matrix governance, PromptPack persisted syntax, model policy or downstream execution semantics without a direct proven defect.

**Controller Surface Assessment:** no controller change expected; if necessary, first show before/after ratchet and confirm this is still Narrow. Lower ratchets only.

## 5. Validation, review and completion

1. Observe #223's accepted exact-SHA CI and review first. No new test for behavior it already proves. For a residual defect, demonstrate failing regression on the unmodified integrated source before fixing.
2. One bounded source repair plus focused deterministic tests. Preserve exact code-path ordering, prompt text and response metadata. Do not call an unsigned/missing backend report proof of consumption.
3. One canonical Python 3.14 python tools/ci/run_pr_gate.py near source freeze if source changed; hosted required/full-suite/windows after **separately authorized** publication. Review aggregate evidence from all required checks.
4. At most one batched repair/reverification cycle per failure class; stop on a second objective or material architecture/product/data-safety decision. Update existing Image/Learning/STATUS living docs only if the facts changed.
5. Report #223 disposition, E01–E06 proofs, reproduced defect or explicit NO-PR verdict, final branch/SHA/diff and check evidence, surviving risk, exact host/effort/repair-pass tokens or unavailable telemetry.

**Authorization:** This document proposes a bounded follow-up; it does not authorize creation/push/publication of a new implementation branch or PR, merge to main, physical generation, restart, production scheduling, or any execution other than a local review of evidence and contract viability.
