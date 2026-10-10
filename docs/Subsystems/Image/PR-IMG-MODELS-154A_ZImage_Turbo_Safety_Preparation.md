# PR-IMG-MODELS-154A — Z-Image-Turbo FP8-scaled: safety preparation only

Status: **PREPARATION COMPLETE (local branch); hosted CI and independent review pending.**
Package classification: **`PASS_PREPARATION_ONLY`**. That means the preparation implementation and deterministic monitor simulations passed. The current host preflight is a separate disposition: **REFUSED or INCONCLUSIVE is unacceptable for physical qualification**, regardless of a preparation implementation PASS. No numeric threshold
is proven, no stop rule is enforceable, and physical qualification is neither authorized nor implemented.

Execution profile: Standard, qualification-only (`tools/qualification/img154/`, no production `src/` change). Claude Code
Sonnet 5.5 High / Codex GPT-6.1 Sol High, Windows Local/Desktop. Controller Surface Assessment: no controller touched.
Token-efficient validation: failing-before-fix synthetic regressions, focused PR-154A tests, the unchanged related PR-115/151/152/153 suites, one final `run_pr_gate.py`, hosted `required`/applicable `affected`, and one independent read-only targeted review. No new live probe or physical run in this repair. High effort is selected for expected successful-work cost: interacting freshness, missing-data and no-replay contracts make retries more expensive than the nominal model saving. Base: `origin/main` `668b4dc8` (PR-153 and PR-REFINE-160 already integrated; no overlap with either).

## Absolute boundary

The package contains no callable path to launch Forge, load or select a model, send a generation request, cancel or terminate
anything, or change a driver, pagefile or setting. The AST/source guard discovers all qualification Python modules and resolves
aliased/from imports and simple callable aliases. Narrow exceptions cover fixed read-only host queries, fixed read-only Git
revision/status commands, loopback TCP observation, and the existing evidence writer/rotation. Static checking is limited source
shape evidence; runtime fakes and behavioral tests are also required and it does not prove all transitive non-execution.
The CLI has exactly `manifest`, `dry-run`, `read-only-probe`. Lifecycle remains `WebUIProcessManager`'s alone and is not imported.
A later package (PR-IMG-MODELS-154B) must add and separately review execution, then obtain another explicit owner approval.

## What was built

| Module | Role |
| --- | --- |
| `core.py` | `Observation` (value, units, source, timestamp, status), strict numeric validation (missing/error/stale/NaN/inf/bool/negative/wrong-unit/future-dated are refused, never zero), canonical digest. |
| `manifest.py` | D1: versioned **proposed** manifest: three exact assets (bytes + full SHA-256), Forge pin, frozen txt2img intent, forbidden request keys, served-relative paths, revisions and a digest. Independent of the git commit. `verify_assets` / `verify_served_files` (a source match never substitutes for the served file) / `verify_runtime_pin` / `verify_intent`. |
| `isolation.py` | D2: pure root/ancestry validation in both directions, link/junction escape, layout and target checks, same-volume hardlink assumption, loopback/unique port, competing-runtime and foreign-owner conflicts. Only reports; acts on nothing. |
| `preflight.py` | D3: fail-closed evaluator: `NOT_ASSESSED`, `REFUSED_<reason>`, `INCONCLUSIVE`, `PREPARED_FOR_OWNER_REVIEW` (never go/safe/ready/qualified), with threshold provenance and a staleness/manifest binding. |
| `monitor.py` | D4: deterministic state machine over injected samples and a fake clock; explicit comparators, units, debounce, gaps, precedence and latching; emits `WARN`, `REQUEST_OWNER_STOP`, `CANNOT_VERIFY_SAFE_STATE`, `HARNESS_FAULT` and executes nothing. |
| `evidence.py` | D5: redaction, fsync-per-record bounded rotating JSONL, fault baseline/after classification (never "no faults"), dispatch ledger (attempt recorded before any send; no retry/replay), result classes. |
| `probes.py` | Opt-in read-only host facts (see below). The only module with a subprocess. |
| `report.py` | D6: redacted bounded operator packet, deterministic monitor dry run, three-subcommand CLI. |

## Threshold disposition (provisional candidates; none proven)

| Measurement | Value | Status | Observable via | Enforceable in 154A |
| --- | --- | --- | --- | --- |
| Commit headroom at launch | >= 37 GiB (PR-153 high analogue 30.7 GiB x 1.2) | provisional | `GetPerformanceInfo` CommitLimit-CommitTotal, no privilege | no (no launcher) |
| Available physical RAM at launch | >= 20 GiB | provisional (judgment) | `GetPerformanceInfo` PhysicalAvailable | no |
| Pagefile-volume free space | >= 30 GiB | provisional; relevance unproven (allocated pagefile is a fixed 18 GiB) | CIM + disk usage | no |
| Dedicated VRAM at launch | <= measured quiescent baseline + 512 MiB | baseline-relative; remains INCONCLUSIVE until independently validated device/boot-bound, timestamped quiescent evidence exists | `nvidia-smi` via the existing inspector | no |
| Stop: RAM available | < 1 GiB for > 10 s | provisional, **uncalibrated** | `GetPerformanceInfo` | no |
| Stop: commit headroom | < 4 GiB (2 samples) | provisional | `GetPerformanceInfo` | no |
| Stop: dedicated VRAM | >= 95% of total (2 samples) | provisional | `nvidia-smi` | no |
| Stop: shared GPU memory | > baseline + 1 GiB (2 samples; needs a measured baseline) | provisional | `\GPU Adapter Memory(*)\Shared Usage` | no |
| Stop: temperature | >= 80 C (2 samples) | provisional, operator signal | `nvidia-smi` | no |
| Stop: GPU fault event / device or telemetry loss | any | provisional | event logs, WER/LiveKernel listing, sample gaps | no |
| Stop: stage stall | none configured | **unconfigured** (no evidenced deadline) | n/a | no |

Internal consistency is tested: a launch at the 37 GiB minimum still leaves more than the 4 GiB commit stop after the
30.7 GiB high analogue. Hard faults are named by the counter that measures them (`\Memory\Pages Input/sec`), not the total
`Page Faults/sec`. Encoder, transformer and VAE phases are recorded as **not observable** in a public endpoint; `denoise`
is an unproven Forge-API candidate; `unknown` is always valid and a stage is never inferred.

## Read-only host evidence (this workstation, redacted)

One opt-in probe pass (no admin, about 10 s) obtained every essential counter: system commit total/limit/headroom, available
and total physical RAM, dedicated VRAM used/total, GPU temperature/utilization/board power, shared GPU memory, hard-fault page
reads, pagefile allocation and volume free space, device presence, boot identity, and System/Application/WHEA event queries plus
the WER ReportArchive/ReportQueue folder listing (including 48 LiveKernel folders; access was permitted). The System and Application
queries return a bounded 100-record window (`bounded_lookback`: continuity must be proven by overlap at diff time).

Measured facts: commit limit 49.76 GiB (matches PR-153's estimate), 18.0 GiB allocated pagefile. Readings were workload
dependent: with the managed Forge running, commit headroom 3.3-3.6 GiB, available RAM 7.1 GiB, 8.8 GiB VRAM in use; later,
with only the application and development tools open, commit headroom 23.4 GiB, available RAM 15.6 GiB, 1.8 GiB VRAM in use.

Feasibility: the **37 GiB commit headroom is reachable in principle** (limit 49.76 GiB) **but only when current commit total is
at most about 12.8 GiB**, which neither reading approached; the 20 GiB RAM minimum likewise needs a near-idle desktop. Neither was
met in either reading. The **first saved probe's readings were stale** and cannot establish the reported resource refusals.
The subsequent fresh probe supplied the reported commit/RAM resource refusals; the running managed Forge also produced
`REFUSED_RUNTIME_CONFLICT` (observed and left untouched). The policy is never lowered, and no setting
is changed, in response.

## Findings and remaining uncertainty

- The RAM stop rule may fire on benign paging: the only clean baseline (PR-IMG-115) reached 0.01 GB available. The duration of
  that dip is unknown.
- A simulated threshold passing says nothing about a real 1 Hz Windows sampler, rule latency during a driver hang, or any control
  path; a black screen, driver hang or reset cannot be recovered by software (DIAG-GPU-130 stays unresolved, unattributed).
- Request semantics (guidance 0.0 on the model card versus the pinned preset CFG 1.0 / shift 9.0 / Euler-Beta) are marked
  `provisional_unreconciled` and must be proven against the pinned source before a physical request is accepted.
- File provenance is unverified; exact bytes and digests are frozen, not authenticated.
- Fault evidence is delayed or inaccessible by nature: `classify_faults` can return only `NEW_EVENTS`, `BOOT_CHANGED`,
  `UNKNOWN_COVERAGE_GAP` or `NO_NEW_EVENTS_COMPLETE_COVERAGE` (complete coverage, continuity proven, settle interval elapsed).
- Served-file proof cannot exist in Phase A: no isolated layout may be created or linked here.

## Entry conditions for PR-IMG-MODELS-154B

Independent review of this package; a new owner decision; reconciled request semantics; served-file hash proof at the isolated
paths; independently validated device/boot-bound quiescent VRAM baseline; re-measured preflight immediately before dispatch; stable owner-authorized case identity and ledger attempt recorded before any send (the ledger is append-only and never rotates; attempts need the single-instance
lock because the check-then-append is not atomic across processes); `WebUIProcessManager`-only
lifecycle; baseline and post fault snapshots with a settle interval; explicit acceptance of the residual GPU hard-failure risk.
The packet lists these as the one-case acceptance checklist.

## Method and validation

Tests: `tests/tools/test_img154_manifest_isolation.py` (T01-T06), `test_img154_preflight_monitor.py` (T07-T15),
`test_img154_evidence_guard.py` (T16-T21 and seven mutation probes: inverted commit comparison, ignored stale sensor, accepted
wrong SHA, same-name different-path file, skipped foreign-runtime conflict, missing event log read as clean, retried ambiguous
ledger; each regression passes on the real code and fails on its mutant). T22: PR-115/151/152/153 suites unchanged and green.
Hosted CI and the independent review are pending.

Run (all read-only; reports go to an ignored directory such as `reports/`):

```
python -m tools.qualification.img154.report manifest
python -m tools.qualification.img154.report dry-run --out reports/img154/dry_run.json
python -m tools.qualification.img154.report read-only-probe --models-root <models dir> --forge-install <managed install> \
    --qualification-root <proposed isolated root> --reserve <path> --out reports/img154/probe.json
```

`--hash` reads and hashes only the three named files (about 14.5 GB), **before** time-sensitive resource observations.
The 30-second policy is unchanged. `--vram-baseline-mib` is an unverified operator assertion, never a fresh measurement,
and cannot satisfy the baseline-relative threshold. Phase A implements no independent baseline acquisition/validation path.
Live CLI `REFUSED` or `HOLD` exits 1 after writing the packet; offline dry-run exits 0 when its simulation packet is produced.
Packets preserve per-source fault coverage, record IDs and `not_compared` continuity; a single snapshot cannot prove continuity.
Live packets identify Git HEAD as clean/dirty/unverifiable and hash the actual qualification source files; offline fake packets
explicitly mark revision evidence `not_collected` and cannot be used as a physical operator packet.
 The packet carries no raw prompt, profile path or hardware
identifier; the evidence writer redacts the same way.

## Focused safety-contract repair (S1-S8)

Missing data breaks physical-duration/debounce continuity, but never erases observed violation evidence. An unresolved per-field
unknown interval exceeding 10 seconds escalates to `CANNOT_VERIFY_SAFE_STATE`, even with alternating missing/violating samples;
only confirmed fresh recovery clears that interval. Actual contiguous violations retain their existing thresholds and latching.
All clocks, timestamps, ages and age limits reject invalid/non-finite values. Skipped sample IDs and stale samples break physical continuity. Invalid/reversed fault-snapshot times, disappeared complete-coverage records and missing baseline sources preserve explicit uncertainty. The append-only ledger stores full manifest/request
provenance and uses stable case identity independent of policy or request edits. A new case identity is an owner decision,
never automatic retry/replay. Legacy/malformed/unreadable ledger history fails closed and is not migrated or repaired.
Redaction retains guidance/CFG/sampler/scheduler/shift while protecting personal paths with spaces. Empty reserved paths are
refused, and duplicate valid asset hashes are detected before role-specific mismatch returns.

Preparation implementation evidence and workstation preflight remain separate. This repair performs no physical qualification;
served-file proof, baseline provenance, payload semantics, actual sampler latency, enforceable stopping, the cross-process ledger
lock and residual GPU risk remain prerequisites for separately authorized PR-154B. Hosted CI and independent targeted review
must be assessed on the final repair SHA before merge consideration.
