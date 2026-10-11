# PR-IMG-MODELS-156 - Z-Image canonical production acceptance

Implementation-only capability; no physical result claimed. PR-154B remains
`INSTRUMENTATION_GAP`. No startup, model loading/selection, generation, publication
or merge is authorized by this package.

Execution Profile + Model/Reasoning Recommendation: **Standard**, bounded tooling
with high hardware-consequence risk. Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5
High, Local/Desktop. Known production seams permit a small package; High minimizes
expected successful-work cost because authorization, dispatch and attribution
mistakes are expensive to repair. One coding session and one independent read-only
aggregate/security review.

Controller Surface Assessment: no production controller/coordinator or ratchet
changes. Reuse `img_forge_100_acceptance.build_stack`: JobService, SQLite repository,
JobQueue, SingleNodeJobRunner, PipelineController and `PipelineRunner.run_njr`.
The normal Forge backend owns served-file verification, selection and projection.

Token-Efficient Validation Plan: fake transport with real production construction
and queue execution; focused PR-156 and affected PR-155/PR-116/acceptance/ownership
regressions; scoped Ruff, applicable mypy smoke, one final local PR gate and final
aggregate review. Reuse unchanged production evidence. Hosted Python 3.14 CI is a
separate integration verdict after explicitly authorized publication.

Local implementation verification: 25 focused tests pass; scoped Ruff/mypy and the
final PR gate pass (8,349 tests collected; 386 required tests passed). The affected
suite records 286 passes and one environment-blocked failure in the unchanged
IMG-FORGE-100 real-manager/fake-server test: its fake tree coexisted with an
already-running Forge tree, correctly triggering duplicate-runtime admission.
No existing runtime was stopped to obtain a green test. Independent read-only
aggregate and security reverification pass after one bounded repair of session
replacement fencing and post-cleanup telemetry applicability. Production `src/`
is unchanged. Hosted CI and physical acceptance remain unverified; the package is
ready for publication review with the affected-suite limitation explicit.

## Dry-run and review

Use Python 3.14 from a clean committed checkout. Choose a new evidence directory
outside the checkout and all earlier qualification evidence; even existing empty
directories refuse.

```powershell
python -m tools.acceptance.img_156_zimage_acceptance --dry --reports-dir C:\Users\rob\qual\img156-attempt-1
```

`build_cli_njr` freezes exactly one txt2img NJR with the PR-154B teapot prompt and
seed 424254. No Forge startup, generation network activity or model reading occurs.
Review the complete `intent.json`: immutable `z_image_turbo_fp8_scaled@v1`, Forge,
1024x1024, Euler/Beta/9 steps/CFG 1, `distilled_cfg_scale` 9, one image, no negative
prompt or modifiers. The asset trio and pin are the merged PR-155 profile.

The canonical SHA-256 approval digest binds the full packet, including source SHA,
dirty state, unique attempt ID and output root, excluding only its digest field.
Physical mode resumes that same packet once. Only `intent.json` may be present;
changed, relocated, partial or consumed roots refuse. Exclusive `attempt.json`
claims the attempt before preflight; subsequent refusal still consumes it.

## Explicit owner permission

**The approval digest is not consent.** Rob must newly authorize this precise
normal-path physical attempt after packet/risk review. Implementation permission,
old PR-154B permission and file presence cannot substitute. After consent the
operator supplies an owner-issued JSON record outside the evidence root:

```json
{
  "owner": "Rob",
  "action": "one_normal_queued_zimage_generation",
  "attempt_id": "<intent.json attempt_id>",
  "approval_digest": "<intent.json approval_digest>",
  "source_sha": "<intent.json source.sha>",
  "reports_dir": "<intent.json reports_dir>",
  "issued_at": "<timezone-aware ISO consent timestamp>",
  "expires_at": "<timezone-aware ISO expiry>"
}
```

This is a local operator attestation, not a cryptographic identity service. The
tool verifies binding/current validity but cannot authenticate its writer. Agents
must never create it or infer owner consent. After separate authorization:

```powershell
python -m tools.acceptance.img_156_zimage_acceptance --reports-dir C:\Users\rob\qual\img156-attempt-1 --approved-digest <reviewed-digest> --owner-authorization <owner-record.json> --model-home <existing-model-reference-home>
```

## Managed preflight and execution

The tool derives the canonical managed Forge launch profile, uses qualification
endpoint `http://127.0.0.1:7886`, redirects data/caches into the evidence root and
neutralizes inherited `COMMANDLINE_ARGS`. Application configuration, Forge source,
models, CUDA and pagefile are not modified. Before launch it checks clean source,
pin/marker/launch identity, installed asset bytes, application-lock/process/port
conflicts, storage and total physical RAM at least 32,000,000,000 bytes. Available
RAM, commit headroom and GPU memory are observations: the experimental PR-154A
37-GiB/20-GiB limits are not production gates. Essential missing instrumentation or
a device-loss indication refuses for owner decision.

`ManagedWebUIRuntime` acquires the application lock and uses WebUIProcessManager.
Another instance refuses; external runtimes are never adopted or interrupted.
Production `verify_zimage_assets` binds actual served catalog paths/hashes to the
owned session before selection and POST. Submission is exactly once via JobService.
The completion wait defaults to 900 seconds and cannot exceed 1800.

An observer delegates to the production Session.request method, recording the actual
POST in exclusive, flushed `dispatch.json`; response/error follows in
`response.json`/`dispatch_error.json`. It implements no HTTP client or retry.
A second/unintended generation refuses. A timeout or uncertain response remains
ambiguous even if SQLite records failure. Never replay or submit a replacement.

## Evidence and independent verdicts

`state/jobs.sqlite3` preserves the immutable snapshot and mutable lifecycle/history
projection. Normal outputs/manifests remain under `output/`. Independent validation
requires one nonconstant, decodable 1024x1024 PNG, size/SHA-256, exact 14-field actual
request, requested/effective seed, returned effective sampling/model/module
infotext, profile/served identities, manifest lineage and matching repository
artifact references. A PNG alone cannot pass.

Production GPU survivor telemetry remains active in the run root's
`reports/diagnostics/gpu_survivor`. The timestamped `telemetry.jsonl` reuses PR-154B
native memory, NVML, PDH and owned-process-tree providers without its monitor.
Field status/provenance/latency and missing measurements are preserved. Startup,
loading/generation, completion and cleanup are covered; loading/generation use a
joint phase label when their boundary is unknown. Windows fault snapshots include
the established 120-second post-run observation window. `acceptance.json` reports
extrema, intervals/coverage gaps, runtime identity/PIDs, errors and shutdown:

| Dimension | Values |
| --- | --- |
| Generation | `GENERATION_PASS`, `GENERATION_FAIL`, `GENERATION_AMBIGUOUS` |
| Integration | `CANONICAL_PATH_PASS`, `CANONICAL_PATH_FAIL`, `CANONICAL_PATH_INCOMPLETE` |
| Resources/faults | `OBSERVED_NO_FAULT`, `FAULT_OBSERVED`, `COVERAGE_INCOMPLETE` |
| Cleanup | `CLEANUP_VERIFIED`, `CLEANUP_NOT_VERIFIED`, `CLEANUP_FAILED` |

One normal owned shutdown is attempted. Immediate and settled observations are
separate; later process absence never promotes the immediate verdict. This
procedure retains no persistent runtime and does not use `NOT_APPLICABLE`.
Exit zero requires all dimensions to pass. A valid PNG can receive generation PASS
while cleanup/resource gaps remain explicit. No broad hardware qualification or
repeated-run stability follows from one canary.

## Risk and recovery

Paging, GPU/driver failure and unresolved DIAG-GPU-130 risk remain. Instrumentation
cannot prevent/recover a hard GPU hang. Newly discovered material risk requires an
owner decision, never a relaxed gate or alternate dispatch.

For timeout/unresponsiveness, preserve the evidence root and do not replay or start
another runtime. The tool requests normal owned shutdown once; it has no alternate
kill/restart authority. Inspect recorded PIDs in Task Manager/Resource Monitor;
manual termination requires ownership confirmation. The owner controls hardware
recovery if the whole machine hangs. After recovery retain evidence and collect
Windows fault records. Another attempt requires new explicit permission; earlier
PR-154B evidence remains untouched.
