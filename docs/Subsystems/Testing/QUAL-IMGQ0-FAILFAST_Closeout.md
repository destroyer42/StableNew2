# QUAL-IMGQ0-FAILFAST - IMG-Q0 fail-fast safety repair and evidence closeout

Status: closed locally 2026-11-05. Continues `QUAL-CLOSEOUT-860_Existing_Capability_Reconciliation.md` (the IMG-01 candidate
and its owner-authorized plan). No physical run, Forge start/stop, plan change, threshold change or evidence deletion was
performed by this package.

## 1. Result

The first GUI-driven physical attempt (IMG-01, plan digest `74ad40503fda`) is **NO-GO**. Three things are true at once and
must not be merged into one verdict:

| Question | Answer | Evidence |
|---|---|---|
| Did the backend execute the job? | **Yes.** One job, `completed`, 1 of 1 image saved, no error, 26.2 s, seed 424242 honored, 512x512, 6 steps, DPM++ 2M, requested model | `jobs.sqlite3` row, `txt2img_..._568ec62d.json` (`expected/returned/saved_images` 1/1/1) |
| Did the full operator workflow pass acceptance? | **No (FAIL).** The journey never recorded the terminal state; it ended in `JourneyTimeout` after 900 s | `evidence.json` journey `abort_reason`, `actions.jsonl` `wait_timeout` at journey t=962.9 s |
| Was resource safety respected? | **No (NO-GO).** Host available RAM fell below the recorded 6 GB floor and reached 2.63 GB | `resource_telemetry.jsonl`, `evidence.json` outcomes |

Visual quality of the image is **PENDING_OPERATOR_REVIEW**; no quality verdict exists.

## 2. The sealed evidence

Archive: `C:\Users\rob\StableNewAcceptance\golden-paths\20261106T041636Z_physical_a2794072_maximized_acceptance_819765`

- Verified read-only with the harness verifier for this format (`python -m tools.operator_journey --verify-archive`: OK) and
  independently re-hashed with a separate script: 21 listed files, 0 size/SHA-256 mismatches, no unlisted and no missing file,
  `COMPLETE` records the `MANIFEST.json` hash `9bbb57d1ee3f78e9c54121ccc2ff549f943fe2f91e3e9b38d8b336c0c2a1d001`.
  Other hashes: `evidence.json` `3c5dda01...d60f`, `plan.json` `2865b9e6...9143`, `resource_telemetry.jsonl` `46308b41...8210`.
- Frozen plan: the archived `plan.json` digest equals the owner-authorized plan digest `74ad40503fda22cd4d51265fcc196b3e7cf84ea00f9297ea8b6f2622d802baaa`;
  limits, job count, expected artifacts and journeys are equal; the authorization block is preserved (approved 2026-11-05, expires
  2026-11-07T03:51:40Z).
- Observed source identity: repository `a2794072a624ec75572916e403fd1f74afb19fcb`; the only dirty tracked file is
  `presets/settings.json` (sha256 `818257bab7d1e3972d188c7cfe85ce34ae05967b98d85bcc965be2808bc7047d`, recorded in provenance; it
  is an application settings file, not code); model `cyberrealisticXL_v90-16fp.safetensors` with sha256
  `4f2dc6418c8d93737e2d0a5f022707977c783851e79ccd23aed1fda8397ac10e`, equal to the plan and to the accepted baseline. The image
  journey has no source image.
- The archive was not modified. `MANIFEST.json` `overall_verdict` reads `FAIL` (the journey result) while the run outcome reads
  `NO-GO` (the safety result); both are correct for their dimension and neither was rewritten.

### 2.1 Not in the sealed archive

`artifacts.json` is `[]`: the generated PNG was left in the isolated workspace and was not captured. An **unsealed** corroborating
copy was made outside the archive (never inside it) at `C:\Users\rob\qual\qual860-evidence\imgq0-corroborating-unsealed\`:

| File | SHA-256 |
|---|---|
| `txt2img_p01_v01_golden_img_568ec62d.png` (427,801 bytes) | `5efbd78e78c645830e03f4949a8dc20f71328139f59d35fe983de3b5e738303c` |
| `txt2img_p01_v01_golden_img_568ec62d.json` (manifest) | `d1d51efb3203b8455859b354ec5559bcc821fba06ed7d1831e45476f1fc6e3fc` |
| `run_metadata.json` | `111fe36b720ada1bbe240809b6292411981bd3d7d2ad1abf8ff7448625a241f2` |

These are corroboration for the operator review, not sealed evidence. The original remains at
`%TEMP%\gpj_oma7exmo\output\Pipeline\20261105_230112_golden_img01-cyberreali-16fp-none\`.

## 3. Correlated timeline

Journey time `t` and monitor time `t` are separate clocks. The monitor clock origin is not recorded; it is estimated at about
04:00:02Z by aligning the last telemetry sample (t=992.74) with the journey end (04:16:35Z) and cross-checked against the VRAM
load and the job window (agreement within about 3 s). Wall times are UTC; the owner saw them as 23:xx local.

| Wall (UTC) | Event | Source |
|---|---|---|
| 04:00:08 | Journey IMG-01 starts; GUI maximized | `evidence.json`, `actions.jsonl` t=15 |
| 04:01:10 | `Add to Queue` clicked (journey t=62.7) | `actions.jsonl` |
| 04:01:12.56 / .75 | Job `ac4dcc7c...` created and started | `jobs.sqlite3` |
| about 04:01:20 (monitor t=78.7) | Model switch: VRAM 1,406 to 6,580 MiB; available RAM begins to fall (8.6 to 7.3 GB) | telemetry |
| about 04:01:25 (monitor t=82.76) | **First sample under the floor: 5.26 GB**; the monitor trips with reason `available RAM 5.3 GB is below the plan floor` | telemetry, `summary.md` |
| monitor t=84.8 / 86.9 / 88.9 | 4.00 / 3.20 / **2.63 GB (minimum)**; VRAM 7,964 then 8,404 MiB (peak); commit 32.9 GB (limit 40) | telemetry |
| monitor t=91 | RAM recovers to 8.35 GB; samples under the floor: 4 of 488 | telemetry |
| 04:01:38.97 | Job `completed`, 1 image, `error_message` empty | `jobs.sqlite3` |
| journey t=62.7 to 962.9 | The journey polls for a terminal job state; `JourneyNoGo` raised by the probe on every poll is stored as the "last probe error" | `abort_reason` |
| 04:16:35 | `JourneyTimeout` after 900 s; failure screenshot; window closed; archive sealed | `actions.jsonl`, MANIFEST |

Only the RAM floor tripped. The other plan limits held: VRAM peak 8,404 MiB (limit 10,500), commit peak 32.9 GB (limit 40),
telemetry never lapsed, and the run stayed inside its timeout budget for the job itself. The host started the run at 8.7 to 8.9
GB available; the 6 GB floor therefore left about 2.7 GB of headroom against a model-switch draw of about 6 GB.

The pipeline recorded `runtime_admission: degraded` (`process_warning`, "suspicious long-lived StableNew-like processes
detected"). The two processes counted include the operator-journey harness process itself; it did not block the job. That is a
harness side effect worth knowing about when reading the warning, not a product defect found by this package.

## 4. Root cause and repair

**Root cause.** `TkDriver.wait_until` (`tools/operator_journey/tk_driver.py`) wrapped the polling predicate in
`except Exception`, so the `JourneyNoGo` that `GoldenRun.wait_jobs_terminal` raises when the resource monitor has tripped was
recorded as a transient probe error and polled again until the wait timed out. The safety monitor had already ended the
safety question 80 s into the run, yet the journey ran 16 more minutes with the GUI in the foreground and Forge idle.
`JourneyAbort`, `JourneyHold` and `JourneyNoGo` lived in `golden/session.py`, which the driver cannot import without a cycle.

**Repair** (harness only; no production generation, queue, NJR, Forge or runtime code changed):

- `tools/operator_journey/control.py` (new): `JourneyControl(RuntimeError)` with `JourneyAbort`, `JourneyHold`, `JourneyNoGo`.
  It imports nothing from the drivers or runners.
- `tk_driver.py`: `wait_until` lets any `JourneyControl` propagate immediately (trace entry `wait_stopped` with the original
  reason) and keeps retrying legitimate transient probe errors until the normal timeout.
- `golden/session.py` and `journeys/learning_lora_strength.py` import the shared classes (the same identity everywhere); the
  runner's classification, evidence collection, GUI teardown and archive behavior are unchanged.
- `tests/tools/test_operator_journey_failfast.py` (10 tests; 7 fail on the previous driver): NO-GO on the first poll, HOLD and
  ABORT keep type and reason, a stop after transient failures, transient recovery, an unsatisfied predicate still times out with
  diagnostics, shared-contract identity and no import cycle, a real `ResourceMonitor` at 5.3 GB ending `wait_jobs_terminal` with
  zero repository reads and zero submissions, and the golden-path runner recording the NO-GO, shutting down, writing evidence and
  dispatching nothing further. All use a stand-in Tk root, synthetic probes and a fake backend.

**Known limitation (not changed).** Only `wait_jobs_terminal` consults the monitor (`abort_check`). Other long waits in a
journey do not poll the monitor and will only notice a trip at the next job wait. Widening that is a separate harness change.

**Ledger rule closed while recording the attempt.** `_qualified_problems` (`tools/qualification/system840/ledger.py`) accepted any
GUI production-workflow evidence for QUALIFIED, including a recorded NO-GO. A new `is_failed_attempt` helper (result contains
NO-GO or FAIL) now excludes failed attempts from that requirement, with a regression test
(`test_a_failed_gui_attempt_is_history_not_qualifying_gui_evidence`). Without it, recording `e5` would have made the GUI
requirement look satisfied.

## 5. IMG-Q0 qualification dimensions

Recorded in `tools/qualification/system840/ledger.v1.json` (`IMG-Q0.sdxl-forge-baseline`, evidence `e5`).

| Dimension | Before | After (declared) | Note |
|---|---|---|---|
| Resource | PARTIALLY QUALIFIED | PARTIALLY QUALIFIED | Driver-path evidence `e1`, `e2` stands; `e5` adds a GUI-path RAM NO-GO on this host |
| Quality | NOT TESTED | NOT TESTED | Image exists; operator review pending |
| Integration | PARTIALLY QUALIFIED | PARTIALLY QUALIFIED | GUI to queue to backend to History ran and the job completed; the journey did not observe it, so there is no GUI pass |
| Status | PARTIALLY QUALIFIED | PARTIALLY QUALIFIED | No qualification promotion; no NO-GO acceptance |

### 5.1 Capability-status proposal (NOT accepted)

The ledger declares nothing beyond the failed-attempt evidence. For the owner:

- **Proposal A (recommended):** keep `IMG-Q0` PARTIALLY QUALIFIED; keep `e5` as a failed attempt; require the headroom decision
  below before any rerun. The backend path is evidenced twice on the driver surface and once through the GUI-driven queue, and
  the only failed dimension is a host-RAM margin, which is a property of the host and the plan, not of the capability.
- **Proposal B:** declare the resource dimension NO-GO for the GUI path on this host until the owner changes the host or the plan.
  This moves the status to NO-GO, makes the next test non-authorizable in the ledger, and is the stricter reading.

Either is a product-level status decision. Neither is applied.

## 6. Owner decisions and outstanding review (the next physical test is BLOCKED)

The ledger `next_test` keeps `admissible: true` (it is still the smallest valid test, and the offline plan builders key on that
field) and adds `blocked: true` with `blocked_reason`. The tooling does not enforce `blocked`; a physical run still needs a
new frozen plan, an owner authorization and the typed phrase.

1. **Host RAM headroom.** Free host memory so that the model switch cannot cross the 6 GB floor, or issue a new plan with its own
   digest and authorization. The recorded 6 GB floor was not weakened and the verdict was not changed retroactively. Changing a
   limit is an owner decision.
2. **Operator review of the image** (the unsealed copy above) to set the quality dimension.
3. **Choose Proposal A or B** for the ledger status.
4. **Whether to rerun** once (1) is decided. The authorization for plan `74ad40503fda` covered one attempt and the plan's safety limits
   failed it; this package does not reuse it, and a rerun needs the owner's explicit decision.
5. Forge `127.0.0.1:7860` (pid 41936, started in the previous package at the owner's request) was left running; stopping it is
   an owner action.

## 7. Validation

Focused: `tests/tools/test_operator_journey_failfast.py` (10 passed), operator-journey harness, ai-isolation and model-evidence
suites, golden-path contract/component/evidence/advanced/Blender-833 suites and the four `test_qual840_*` files (non-journey
selection): 290 passed, 1 skipped (Blender opt-in) before the ledger edit; re-run results are in the completion report. The
ledger live check, `ci_truth`, ruff and the canonical PR gate are reported there with their exact outcomes.
