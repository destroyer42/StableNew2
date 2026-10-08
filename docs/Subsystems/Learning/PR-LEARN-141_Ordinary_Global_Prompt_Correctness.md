# PR-LEARN-141 — Ordinary Learning Global Prompt Correctness

## Execution Profile + Model/Reasoning Recommendation

Standard, bounded known-root-cause freeze/persistence repair. Codex GPT-6.1 Sol
High; Claude Code Sonnet 5.5 High. Retain the current Local/Desktop session for
exact worktree, Tk and accepted-context continuity. Expected total successful
work cost favors the known architecture and focused evidence over escalation.

## Controller Surface Assessment

`LearningController` delegates ordinary source/global freeze, saved-preview
validation, config/base consistency and rating evidence to
`src/learning/ordinary_prompt_freeze.py`. It coordinates existing policy/LoRA
validation, snapshots and admission. Physical lines decrease from 4,022 to
4,018. No `src/controller/*` surface or ratchet ceiling changes.

## Global prompt ownership

New ordinary Designed Learning previews use the canonical PromptPack resolver
without preapplying Global Negative. Row negatives, Matrix expansion and LoRA
order remain canonical. Global Positive/Negative text and complete enablement
are frozen in baseline config through the canonical global-policy helper;
explicit stage flags are preserved. The executor applies the frozen terms.
SDXL row negative `bad` plus enabled `GLOBAL` dispatches `bad, GLOBAL`; a
global-only negative has an empty base and dispatches `GLOBAL`. Disabled terms
are not injected. Global Positive remains executor-owned.

The existing schema-2 Learning snapshot adds source evidence:

```
executor_base_contract = learning_executor_base/1
prompt_semantics = executor_base_before_globals_and_optimizer
```

Authored row and first canonical Matrix vector stay in `prompt_source`.
Rendered source fields and frozen top-level prompt strings describe the
executor base. Global intent and participation belong to `baseline_config`.
All variants inherit those facts, seeds and frozen definitions. After ordinary
LoRA overrides, workload and executable config prompt fields agree. No terms
are removed by string substitution, no renderer is added, and PromptPacks are
not mutated. Modern Run never reads mutable GUI/global-prompt files.

Globals and Prompt Optimizer may still change final dispatch. Fresh ordinary
ratings explicitly label base semantics and separately retain existing
`final_prompt` / `final_negative_prompt` readback when available. Missing
readback is not invented. Ordinary rating kind, causality, compatible Model
envelopes and recommendation classification remain unchanged.

## Saved-preview and replay policy

Run validates new base fields and complete frozen policy before admission.
Mismatches or saved previews without frozen global policy are refused with
**Rebuild Preview** guidance before any mutable policy is read.

An older unmarked Pack preview with nonempty Global Negative, enabled txt2img
participation at the old freeze, and enabled Global Negative on its execution
stage is conservatively refused. The old producer rendered that term into the
base. This includes global-only previews where merge equality happened to
avoid duplication. Rebuild deliberately adopts the new freeze; Run never edits
or guesses apart a persisted rendered string.

Older complete-policy previews with disabled global contribution, custom base
sources, or disabled execution-stage application remain admissible unchanged.
Programmatic callers without Preview freeze supplied global intent once on
their existing materialization path. Completed NJRs and replay stay outside
preview validation and retain exact immutable workloads and frozen/legacy
global policy, including historical behavior. No migration or retroactive
correction occurs.

## Preserved boundaries

Model Comparison's planner, arm contract, evidence and SDXL/Klein behavior are
unchanged. Its controller branch bypasses ordinary helpers; ordinary rating
additions are inert for other study types. Generic PromptPack compilation,
executor/global merges, backend, queue, repository and replay are unchanged.
All variants compile before one existing atomic `JobService.submit_njrs` call;
one failure admits none.

## Separate existing row-negative duplication

The Experiment Design UI supplies its selected row negative as
`selected_prompt_negative_text`. The existing ordinary source resolver then
receives that same text as `pack_negative` alongside the row's own negative
phrases. With `bad` in both inputs, the old resolver renders
`GLOBAL, bad, bad`; this repair preserves the authored base `bad, bad` and the
executor dispatches `bad, bad, GLOBAL`. Global Negative is applied once, but
the selected row contribution remains duplicated. A separate source-ownership
repair should address that existing behavior; PR-LEARN-141 does not normalize
or remove authored negative terms.

## Token-Efficient Validation Plan

First reproduce duplication with the unchanged ordinary producer and real
txt2img merge/payload path, mocking external runtime boundaries. Cover row,
global-only/disabled negatives, positive once, Matrix/source/global/seed freeze,
multi-variant policy, LoRA tokens, stage flags/img2img dispatch, saved-preview
rebuild/no rewrite, historical replay and ordinary rating readback. Run affected
Learning, PromptPack/Matrix/globals, 130D, 140 and import-safety regressions;
retain exact-source evidence for unchanged authorities.

Kill preapplication while executor apply remains enabled; restore exact bytes
and rerun focused contracts. Run scoped Ruff/mypy and `git diff --check`, then
invoke `tools/ci/run_pr_gate.py` once on settled source. No environment changes
or physical generation. Publication and hosted required Python 3.14 CI require
separate owner authorization.
