# PR-AI-111: Stage 1 safety reconciliation and authorized downloads

All four models: **NOT TESTED**. Physical qualification: **BLOCKED**.
Five D12-authorized artifacts are locally size/SHA-256 verified and staged outside Git.
Nothing has been installed into managed AI directories, extracted for execution, executed, loaded, inferred, promoted or qualified.
No production runtime, GPU or firewall state was changed.

## Execution Profile + Model/Reasoning Recommendation

Standard, bounded lifecycle-sensitive reconciliation in the existing `ai/111-offline-qualification` worktree, starting at
`cdafbd2d71c9fa566918ff8d30b976cf35d95432`. No merge/rebase of current main and no unrelated operator work.
Model recommendation: Claude Code Sonnet 5.5 XHigh / Codex GPT-6.1 Sol XHigh on local Windows.
The lifecycle and PID-reuse proof justify this tier to reduce retries and total successful-work cost.
Expected usage: order of 10M cache-read and 60k output tokens; a planning allowance, not measured consumption.
Controller Surface Assessment: no controller/coordinator changes; no ceiling increases.
Token-Efficient Validation Plan: focused synthetic artifact/corpus/scoring tests and contained Python-child regressions,
one final canonical gate after source stabilization, one security review with bounded reverification;
reuse unchanged accepted evidence. Never execute downloaded artifacts in tests.

## F2 ownership reconciliation

`run_bounded(observe=...)` opts into a read-only capability for its exact launched child.
Existing consumers omit this parameter and retain their interfaces. The bounded runner remains the only lifecycle owner.
On Windows, BELOW_NORMAL priority is a creation flag, applied before resume within the anonymous job.
Job membership is enumerated from the owned job object, including workers independent of the launcher.
Each worker handle is checked using `IsProcessInJob`; memory, CPU and priority are read from that same retained handle.
PID reuse, matching command lines, inaccessible members and early exit grant no priority or termination authority.
No PID-based priority setter remains. The capability expires before container teardown.
Invalid/missing telemetry and failed priority read-back fail closed. Memory cap breaches require two consecutive samples.
Timeout, cancellation and containment regression coverage remains on the original whole-tree teardown path.
Portable diagnostics are read-only and do not establish Windows qualification.

Security review and final reverification: **PASS**, no current blocking findings.
The downloader also rejects pre-existing redirected/nonregular staging entries and empty/unknown artifact selections.

## Download verification

Publisher/runtime packager: `ggml-org/llama.cpp`; CPU-only Windows asset `b11840`,
source commit `36e36e63a54fc8f85b95e9c499a022b597e478dd`.
Models: publishers `Qwen/Qwen3.5-9B` and `Qwen/Qwen3.5-4B`; packagers
`unsloth/Qwen3.5-9B-GGUF` at `3885219b6810b007914f3a7950a8d1b469d598a5` and
`unsloth/Qwen3.5-4B-GGUF` at `e87f176479d0855a907a41277aca2f8ee7a09523`.
Exact source URLs and publisher revisions are retained in the unchanged registry and download JSONL evidence;
all five identities were cross-checked against the original freeze authorization request.
Every observed hash and byte count below equals its recorded expectation.

| Artifact | Exact bytes | Expected = observed SHA-256 | Result |
|---|---:|---|---|
| llama-b11840-bin-win-cpu-x64.zip | 24,156,518 | `f805935dec8a6f527bf3d587419865c1cf486ba6a430dc0381ca97aedf0da034` | VERIFIED |
| Qwen3.5-9B-Q4_K_M.gguf | 5,680,522,464 | `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8` | VERIFIED |
| Qwen3.5-9B-Q5_K_M.gguf | 6,577,841,376 | `dc2a39aef291f91a9116ad214058da0d86eb648743a124bd8c333787c4b9c91c` | VERIFIED |
| Qwen3.5-4B-Q8_0.gguf | 4,482,403,488 | `10cc391b403021dd11c614679d2fd92f611c3681d29e29651b717316965d61e1` | VERIFIED |
| Qwen3.5-4B-Q4_K_M.gguf | 2,740,937,888 | `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4` | VERIFIED |

Total: 19,505,861,734 bytes. Original download evidence:
`C:/Users/rob/projects/StableNew-main/reports/ai111/downloads-20261023/`.
Fresh independent full-byte verification:
`C:/Users/rob/projects/StableNew-main/reports/ai111/downloads-reverified-20261023/`.
The latter also holds passive ZIP member hashes in `binary-entry-hashes.json`; no archive extraction or binary execution occurred.
Available disk after verification: 101100281856 bytes (point-in-time reading).

Operator-controlled staging paths:
- `C:\Users\rob\qual\ai111-downloads\llama-b11840-bin-win-cpu-x64.zip`
- `C:\Users\rob\qual\ai111-downloads\Qwen3.5-9B-Q4_K_M.gguf`
- `C:\Users\rob\qual\ai111-downloads\Qwen3.5-9B-Q5_K_M.gguf`
- `C:\Users\rob\qual\ai111-downloads\Qwen3.5-4B-Q8_0.gguf`
- `C:\Users\rob\qual\ai111-downloads\Qwen3.5-4B-Q4_K_M.gguf`

## Screening versus final qualification

Historical Stage 1 plan SHA-256: `17814e4050049323dc4f5206417bac67f94307d7791ce580af2948e2310df338`.
Historical corpus SHA-256: `bd09dee88a70252f82455329d7e885e54c1e1883715f8bf7dd3731b5ce17f5d8`.
The 215-case corpus and 30-case-per-arm subset are preliminary screening only; their digest is unchanged.
The original plan's authorization booleans remain historical freeze evidence, not current download authority.

The separate `stablenew.ai111.final.v2` contract freezes 460 cases:
300 rewrites, 100 target/workflow cases, 60 adversarial cases; the 100 allowed-sensitive cases overlap rewrites.
At least 100 decisive blind judgments (ties excluded) are required before GO.
Target oracles are checked against actual deterministic adaptation policy;
workflow eligibility uses actual approved catalog ID/version pairs. These are policy eligibility oracles;
operator preference must still establish suggestion quality.

Final plan SHA-256: `3017c427c7f5c15bc900e6e5d1ef2d3e86b45c7bbb30d3a9d0a0d2f58b1eccbf`.
Final corpus SHA-256: `a89297beb3ae86246eb25214738d91ba3f24dc1e2cd8a4f7547ae49c68a774d5`.
Final frozen evidence: `C:/Users/rob/projects/StableNew-main/reports/ai111/final-freeze-v2-20261023/`.
This supersedes the provisional final-freeze directory generated during reconciliation; neither has model output.
Final GO evaluation refuses screening corpora, missing/duplicate case records, insufficient measured category coverage,
and fewer than 100 decisive judgments. Empty physical records produce NOT TESTED.

## Physical boundary and remaining authorizations

The marker-only session egress/teardown diagnostics are replaced (PR-AI-QUAL-113) by the owned container's process-tree and teardown record.
Connection and file-access channels need a lifetime-complete provider proven by the canary: unprivileged providers are sampled, and the elevated ETW provider (PR-AI-QUAL-113B) has not yet passed its canary on the target host.
A real `run_session` therefore refuses before creating evidence, importing or launching. The injected Python-child seam stays testable.
The physical harness is not ready for model use.

**D12a request (not granted):** authorize extraction of this verified CPU archive into a new evidence-only directory
outside managed runtime/source directories, then only the `llama-cli.exe --version` and `llama-cli.exe --help` commands.
Exact archive: `C:/Users/rob/qual/ai111-downloads/llama-b11840-bin-win-cpu-x64.zip`,
SHA-256 `f805935dec8a6f527bf3d587419865c1cf486ba6a430dc0381ca97aedf0da034`.
Exact member: `llama-cli.exe`, 9,216 bytes,
SHA-256 `c84a4604db9a01cb64ece64c7da5ace4c83c44dfb63f55a9c8d2270b685c0ee7`.
Verify every DLL/member against the passive member-hash manifest immediately before launch.
Host requirements: local Windows x64, quiet host, CPU-only archive, no weights present in the execution directory,
bounded contained child, below-normal creation priority, timeout 10 s per command, stdout cap 64 KiB.
Stop on any hash mismatch, unexpected dependency, containment/telemetry failure, nonzero exit, timeout,
model access, connection attempt or unexpected persistent process. Do not fetch dependencies or alter firewall/runtime state.

**D12b (not granted):** model import and CPU inference need a separate owner-approved package naming verified artifacts,
frozen plan/corpus digests, arms, stage, host resource/egress/teardown requirements and evidence location.
First run the elevated ETW canary on the target host and have it pass.
No Stage A/B run, blind preference session, GPU generation, promotion, `qualified=true`, or merge is authorized.

## Validation and publication

Focused baseline: 293 passed, 2 skipped (Windows account cannot create test symlinks).
Additional final-contract/session regression run: 41 passed; source safety changes are covered separately.
Final canonical gate: **PASS**; 12,333 tests collected and 358 required-smoke tests passed (one warning), with repository unchanged.
The final native-export/type repair and final-contract suite passed 25 tests; generated code-map checks passed 5 tests.
Gate log: `C:/Users/rob/projects/StableNew-main/reports/ai111/reconciliation-pr-gate-frozen-20261023.log`.
Earlier gate attempts stopped at untracked new source, a package-caused mypy error (fixed without raising the baseline),
and a concurrent generated-document update during collection. The final run passed with the worktree frozen.
Only this evidence-report text changed afterward; validated executable source/test content is unchanged.
No binaries/weights are tracked or attached. Architecture ownership is unchanged.

Publication is **pending explicit owner authorization** for push to `ai/111-offline-qualification`
and creation of a draft PR against `main`. No remote branch or draft PR existed at verification.
Hosted CI has not run for this unpublished branch. No merge/rebase/main mutation was performed.

## Model / usage

Codex local Windows; actual executor model `gpt-6.1-sol`, effort High (host log telemetry);
0 published repair passes; local implementation/validation PASS; physical qualification BLOCKED.
The required `--since-commit cdafbd2d --line` output below is the matching project-wide post-commit window,
including other sessions on this host; it is **not** an exact PR-only token total. No missing usage is estimated.

```text
Claude Code claude-sonnet-5-5: 38 requests, fresh input 80, cache read 24.7M, cache write 95.2k, output 70.0k; Codex codex-auto-review: 61 requests, fresh input 220.4k, cache read 3.2M, cache write 0, output 6.2k; Codex gpt-6.1-sol: 186 requests, fresh input 761.1k, cache read 27.3M, cache write 0, output 91.7k (tokens from host session logs; cost not reported)
```
