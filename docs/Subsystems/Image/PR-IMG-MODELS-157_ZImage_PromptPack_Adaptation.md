# PR-IMG-MODELS-157 - Z-Image PromptPack adaptation

## Execution Profile + Model/Reasoning Recommendation

Narrow: connect Z-Image to the existing model-aware PromptPack compiler.
Codex: GPT-6.1 Sol High. Claude Code: Sonnet 5.5 High. Preferred host:
Local/Desktop. These tiers fit the shared compiler and immutable-job boundary;
using a cheaper tier at the expense of repeated integration repair would raise
the expected total successful-work cost.

## Controller Surface Assessment

No controller/coordinator, process manager, queue, persistence schema or runner
changes. The existing PromptPack builder and shared model policy are the only
production surfaces changed.

## Behavior

Selecting the exact Z-Image model uses the normal PromptPack construction path.
The existing shared adaptation rules flatten explicit weighted attention,
normalize BREAK separators, omit structured LoRAs and their owned triggers,
omit positive/negative embeddings, and omit the entire negative channel.
Operator-authored prose is not semantically rewritten. Saved PromptPack bytes
and the caller's source configuration are preserved.

Before exact-profile validation, the executable negative/global-negative
configuration is cleared, and preset prompt text yields to the structured row.
Source intent remains available to the shared adapter
so the queued immutable NJR records the existing content-free adaptation plan.
Backend validation is unchanged: it checks the effective frozen NJR, not the
unsupported authoring components. Replay uses that frozen NJR without adapting
again.

The path remains Intent -> Compiler -> NJR -> JobService -> SQLite
Queue/Repository -> PipelineRunner.run_njr -> Forge -> Artifacts/History.
Multiple selected entries produce separate one-image jobs and one txt2img POST
per job. There is no direct generation entry point or new process authority.

The exact v1 bundle, pinned managed Forge, Euler/Beta/9/CFG 1 and
distilled_cfg_scale 9 remain required. This change does not expand v1 geometry:
1024x1024 remains the supported size. Unsupported stages, sampling settings,
unresolved inline adapter/embedding syntax and multi-image jobs still refuse.
The GUI policy explains which prompt components are adapted automatically.

## Superseded detail (PR-IMG-MODELS-159)

Inherited sampling, CLIP skip, prompt-optimizer state and global prompt text are now normalized
in the executable configuration and an enabled global positive is composed into the prompt; see
`PR-IMG-MODELS-159_ZImage_Effective_Configuration_Adaptation.md`. The restrictions in the
previous paragraph that refer to those inherited values no longer apply.

## Token-Efficient Validation Plan

Use neutral temporary native packs to verify automatic adaptation, source-byte
preservation, adaptation provenance and refusal of unresolved execution syntax.
Run four separately compiled jobs through the real JobService/SQLite/queue/
runner with a fake Forge transport; assert four single-image POSTs, deterministic
request seeds, immutable snapshots and artifact references. Reuse existing
exact-profile tests for bundle, settings, admission and ambiguous-dispatch
restrictions; run affected compiler, policy, GUI projection and integration
tests. Run Ruff, the applicable mypy smoke and run_pr_gate.py once near final.
No physical generation, runtime start or PromptPack content inspection is part
of this revised compiler package. It makes no new physical qualification claim.

## Local validation evidence

- Affected compiler, adaptation, exact-profile, GUI projection and canonical
  integration suites: 1,254 passed. The neutral four-job test exercised the real
  queue/runner and verified four one-image requests, snapshots and history.
- Final local run_pr_gate.py invocation: completeness, controller surface,
  Ruff, mypy smoke (10 source files) and isolated collection (8,351 tests,
  repository unchanged) passed. Required smoke stopped at the sandbox's
  WinError 10013 restriction on a deterministic localhost fake server after
  186 passes. Running only run_required_smoke.py outside that sandbox passed
  all 386 tests with the repository unchanged. No tests were skipped or weakened.
- Final scoped diff and git diff --check passed. Source stayed unchanged after
  the affected suites; the later additions only recorded validation evidence.
- No physical batch, publication or merge was performed. Physical qualification
  and 576x1024 support remain outside this compiler change.

## Model / usage

Implementation used the primary Codex Local/Desktop session. Actual session
model/effort identifiers and host-reported token/cost metrics are unavailable;
the recommendations above are not a claim about measured usage.
