# QUAL-IMGQ0-FAILFAST - IMG-Q0 fail-fast safety repair and evidence closeout

Status: closed locally 2026-11-05; owner decisions of 2026-11-06 in section 6; second and third attempts (PASS) in sections 8 and 9; the cold-Forge run in section 10. Continues `QUAL-CLOSEOUT-860_Existing_Capability_Reconciliation.md` (the IMG-01 candidate
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

### 2.2 Image review (2026-11-06, requested by the owner; reviewed by the assistant from the unsealed copy)

Observation, not an operator verdict and not a quality qualification:

- Content: a dusk coastline with an orange and yellow sunset, water on the left, a dark headland with a path, grass in the
  foreground and a small structure at upper right. The oil-painting direction of the prompt is visible (thick, brushy strokes).
- Prompt adherence is weak: the "lighthouse" is not legible (a blocky, high-contrast shape at the cliff top).
- Technical quality is poor: heavy over-saturation, noisy and speckled edges, and a ring-like artifact near the sun.
- Context: the plan is a smoke test (512x512 with an SDXL checkpoint, 6 steps), far below SDXL's native resolution and a normal step
  count, so this output tests that the GUI path dispatches and saves, not the model's quality. The result is consistent with those
  settings and does not indicate a pipeline fault. The manifest shows the requested prompt, seed 424242 and model were applied.

The ledger quality dimension stays NOT TESTED; a real quality test needs production-like settings and its own plan.

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

## 6. Owner decisions (the next physical test is BLOCKED until a new plan exists)

The ledger `next_test` keeps `admissible: true` (it is still the smallest valid test, and the offline plan builders key on that
field) and adds `blocked: true` with `blocked_reason`. The tooling does not enforce `blocked`; a physical run still needs a
new frozen plan, an owner authorization and the typed phrase.

Decided by the owner in chat on 2026-11-06:

1. **Status proposal A is accepted.** `IMG-Q0` stays PARTIALLY QUALIFIED; `e5` stays a failed attempt (ledger evidence `e6`).
2. **The host-RAM floor may be decreased** in a new plan. Reference for attribution: the NO-GO was judged against a **6 GB
   available-RAM floor** (plan `74ad40503fda`, limit `min_available_ram_gb` 6); the host started at 8.7 GB and the lowest sample
   was **2.63 GB**. Any later RAM trip or failure under a lower floor can be compared with these numbers. The new value is not chosen
   yet, the sealed archive and its verdict are unchanged, and the lowered plan is a new plan: it needs its own digest, owner
   authorization and typed phrase. The 6 GB floor was not weakened by this package.
3. **The image was reviewed** (section 2.2); the quality dimension stays NOT TESTED.

The owner chose **2 GB** on 2026-11-06. A new plan with `min_available_ram_gb` 2 (every other limit, target and journey equal to
plan `74ad40503fda`) was built after the final commit of this package and left **unauthorized**, outside Git at
`C:\Users\rob\qual\qual860-evidence\plan_img01_floor2gb_UNAUTHORIZED.json`. A plan freezes the repository SHA, so its digest and
commit cannot be recorded in a tracked file of that commit; read them from the plan file and the readiness summary beside it
(`readiness_floor2gb_*.md`). The run must start from a checkout at the frozen commit, which includes the fail-fast repair. Readiness
is read-only; no runtime was started and no run was made.

Still open: the owner authorization of the new plan; whether and when to rerun (the authorization for `74ad40503fda` covered one
attempt and is not reused).

- Forge `127.0.0.1:7860` (pid 41936, started in the previous package at the owner's request) was left running; stopping it is
   an owner action.

## 7. Validation

Focused: `tests/tools/test_operator_journey_failfast.py` (10 passed), operator-journey harness, ai-isolation and model-evidence
suites, golden-path contract/component/evidence/advanced/Blender-833 suites and the four `test_qual840_*` files (non-journey
selection): 290 passed, 1 skipped (Blender opt-in) before the ledger edit; re-run results are in the completion report. The
ledger live check, `ci_truth`, ruff and the canonical PR gate are reported there with their exact outcomes.

## 8. Second attempt, 2026-11-06: functional PASS, safety PASS

The owner authorized the 2 GB-floor plan (digest `d055e1a3cf575d6c8fa7f05ac656fc0dfa8e80892e45c273c81b315c3cc8fa7b`, frozen at
`bb8e21d1351261b1550b4baf8d761a3b8fe89623`, clean tree) and launched it from the worktree. Archive:
`C:\Users\rob\StableNewAcceptance\golden-paths\20261106T125628Z_physical_bb8e21d1_maximized_acceptance_f0a2bb`.

- **Verified.** The harness verifier says OK; an independent re-hash found 24 listed files, 0 mismatches, nothing unlisted or
  missing; `COMPLETE` records `MANIFEST.json` sha256 `210f4617f6c419a73dd81980178123bd5505056eb9f76e32fa1326343a2109c4`. The archived plan digest,
  limits, job count, journeys, environment and model SHA equal the authorized plan; the authorization block is preserved
  (approved by Rob, owner; expires 2026-11-06T20:53:40Z). Provenance reports a clean tree.
- **Result.** Overall PASS, 17 of 17 journey checks, no abort, hold or NO-GO. Journey 127 s (12:54:20 to 12:56:27Z). Job
  `70e4ff07...` created 12:55:47.97, started 12:55:48.90, completed 12:56:01.61 (12.7 s), no error; `submitted_once_through_job_service`,
  `model_in_njr`, `image_decodes`, `history_artifact_is_the_job_image` and `history_record_present` all pass.
- **Resources.** 66 samples over 133 s: available RAM 8.98 GB at start, minimum **8.61 GB**, VRAM 6,818 MiB at start and 6,962 MiB
  peak, commit peak 27.7 GB. No limit came close: not the 2 GB floor and not the original 6 GB floor.
- **Why the first attempt's dip did not recur.** The first attempt cold-loaded the checkpoint (VRAM 1.4 GB to 6.6 GB while RAM fell
  to 2.63 GB). Here Forge already held the checkpoint (VRAM 6.8 GB at the start), so no load happened. This PASS therefore does not
  show that a cold load stays above the 2 GB floor. The 2 GB floor was not what let this run pass.
- **Image.** Unlike the first attempt this archive contains the image (`image_media_5ca779a116d8.png`, sha256
  `5ca779a116d854059ffb70a7f2a85bf9dcf159625cf358e282a7660354f9be98`, 512x512 RGB). Observation (assistant review, not an operator verdict): a
  lighthouse is clearly legible at upper right on a headland above a sunset sea, with brushy oil-painting strokes. The colors are
  strongly over-saturated, with streaked, noisy edges. Prompt adherence is better than the first image; technical quality is
  still poor, consistent with 512x512 and 6 steps. Quality stays NOT TESTED.
- **Scheduler differed between the attempts.** The manifests show `scheduler` `Normal` in the first and `automatic` in the second
  (same plan, prompt, seed, sampler and model), which is why the two images differ. The frozen plan does not set the scheduler. The
  cause is not established. A candidate (no registry evidence for the checkpoint in the first run only) is refuted: all three
  attempts report the same "No registry evidence" status. The third attempt (section 9) used `Normal` again.
- The runtime admission warning (the harness process counted as a "suspicious" StableNew-like process) repeats; it did not block the job.

### 8.1 Dimensions and status (owner chose: keep as declared, 2026-11-06)

Declared status and dimensions are unchanged (PARTIALLY QUALIFIED; resource PQ, quality NOT TESTED, integration PQ). Ledger
evidence `e7` records this run as GUI-driven, verified-source, functional and safety PASS.

- **Proposal 1 (chosen by the owner, ledger `e8`):** keep all dimensions as declared. One run at smoke settings with a resident checkpoint does not
  cover the failure path of the first attempt, and quality is untested, so QUALIFIED is not available in any case.
- **Proposal 2 (not applied):** raise the integration dimension to QUALIFIED on `e7` alone (GUI to queue to backend to History, exact source). It is
  defensible as an integration statement and is the owner's call.

Remaining gap: one GUI-driven run that starts with the checkpoint not resident in Forge, under the 2 GB floor. That needs the owner
to unload or restart the external Forge, a new frozen plan and a new authorization. No further physical run is authorized.
The authorization file for the 2 GB plan stays valid until 2026-11-06T20:53:40Z; the typed phrase is the only gate against a repeat launch.

## 9. Third attempt, 2026-11-06: checkpoint switch, functional PASS, safety PASS (would have failed the 6 GB floor)

The owner unloaded the model by selecting a different checkpoint in the running Forge (`babesByStableYogiSDXL_v60FP32`, VRAM 6,915 MiB
resident; not an empty GPU), then granted authorization of plan `184c94c2861399d5b9e8ebad18331fcecdf5dbed8dc70c40c1d8efd7b0108a44`
(identical limits to the previous 2 GB plan, frozen at `d657198060b4a61cfc6bdcb9793e08c22e3f4d9c`, clean tree) and launched it.
Archive: `C:\Users\rob\StableNewAcceptance\golden-paths\20261106T130725Z_physical_d6571980_maximized_acceptance_113001`.

- **Verified.** Harness verifier OK; independent re-hash 24 files, 0 mismatches, nothing unlisted or missing; `MANIFEST.json` sha256
  `1ef000f75c367c089a688b734a2a6e42baa68f843c214a026ae6358a7566864a`; archived plan, limits, environment, model SHA and authorization match the authorized plan.
- **Result.** Overall PASS, 17 of 17 checks, no abort, hold or NO-GO; journey 100 s (13:05:45 to 13:07:25Z). Job `5191b642...`
  13:06:46.89 to 13:06:59.54 (12.7 s), no error.
- **The checkpoint switch dipped RAM under the original floor.** 53 samples over 104 s. Available RAM started at 10.42 GB and the
  sample at monitor t=74.11 read **5.73 GB** (VRAM 2,041 MiB, commit 30.5 GB: the old checkpoint unloaded, the new one not yet on the
  GPU); two seconds later it read 9.06 GB, then 12.42 GB with VRAM at its 8,793 MiB peak. **Exactly one sample is under 6 GB.**
  Under the original 6 GB floor this attempt would have been NO-GO at that sample; it passed because the floor is now 2 GB. The
  limits that did not change (VRAM 10,500 MiB, commit 40 GB) held.
- **Attribution record.** The three attempts give the load-time RAM minimum: 2.63 GB (empty-GPU load, start 8.9 GB), 5.73 GB
  (checkpoint switch, start 10.4 GB), none (resident, minimum 8.61 GB). A floor of 2 GB passed all three recorded patterns, but the
  empty-GPU case sits only 0.63 GB above it.
- **Image.** Archived, 512x512, sha256 `b54a17ff92db927aecce289689e3f23814e8af507df96ae8d87bd3921bf53976`. Observation: it shows the
  same composition as the first attempt's image (scheduler `Normal` in both; mean absolute pixel difference 1.3 to 1.5 of 255, not
  bit-identical, so the GPU path is not strictly deterministic). The "lighthouse" is again an illegible blocky shape at the cliff top;
  the colors are over-saturated and the edges noisy. The second attempt's image (scheduler `automatic`) differs strongly (mean difference 50 to 66). Quality stays NOT TESTED.
- Status, dimensions and the owner's "keep as declared" decision (`e8`) are unchanged. Ledger evidence `e9` records this run.

The remaining gap is an empty-GPU load under the 2 GB floor (needs Forge fully unloaded or restarted by the owner, a new plan and a
new authorization). The authorization of this plan stays valid until 2026-11-06T21:04:48Z; the typed phrase is the only gate.

## 10. Fourth run: Forge started cold as part of the authorized run (owner request, 2026-11-06)

The owner asked for Forge to be started as part of the authorized run, to cover the one gap left (an empty-GPU checkpoint load under
the 2 GB floor). The harness is unchanged: it never launches Forge (`physical.py`, `webui_autostart_enabled=False`) and the plan still
declares Forge as external. The start is a wrapper step outside Git, beside the plans:
`C:\Users\rob\qual\qual860-evidence\run_img01_cold_forge.py <authorized plan>`.

- **State found.** The owner believed Forge was closed. It was not: pid 41936 (and children 6932, 26520), the Forge started in the first
  package at the owner's request, was serving `127.0.0.1:7860` with `cyberrealisticXL_v90-16fp` loaded (VRAM 8,751 MiB). With the owner's
  stated intent (a cold Forge) this package stopped that process tree. Afterwards: no listener on 7860, VRAM 1,312 MiB, 14.2 GB RAM free.
- **What the wrapper does.** It refuses unless the plan is authorized for its digest, the checkout is the frozen commit with a clean
  tracked tree, port 7860 is free and VRAM is at most 3,000 MiB. It starts Forge from the product's pinned launch profile
  (`resolve_default_launch_profile`, the same command as before), samples RAM and VRAM every 2 s until the API answers, records them in
  `forge_cold_start_evidence_<time>.json` (unsealed, with the stdout and stderr logs beside it), and stops the Forge it started without
  running the harness if available RAM falls under the plan floor during startup. Then it runs the harness unchanged and the owner
  types the launch phrase. Forge is left running afterwards. Nothing is retried or resubmitted.
- **Not covered by the sealed archive.** Forge's own startup RAM and VRAM are in the wrapper evidence, not in the archive, because the
  harness monitor starts after Forge is up. The archive's ownership field will still say external.
- **Plan.** The same limits and targets as the earlier 2 GB plans (RAM floor 2 GB, replacing 6 GB), frozen at the final commit of this
  record, authorized by the owner in chat for one attempt; its digest and commit are in the plan file and the wrapper evidence, not
  here, because a plan freezes the commit and cannot be named in a file of that commit.
- **Result.** See the ledger evidence and the next section when the run exists. Until then nothing in the ledger changes.

## 11. Delegated launch (remote or agent-driven physical runs)

Owner decision (chat, 2026-11-06): the owner cannot always be at the terminal and wants a physical run to be launchable remotely, or by
the agent walking the journey in the owner's place. The harness previously refused any launch without a live console
(`default_confirm` returns an empty string without a TTY), which is why an agent-piped phrase produced a HOLD with no generation.

- **What changed.** `run_physical` accepts `launch_phrase` (CLI: `--launch-phrase "RUN <digest12>"`, physical mode only). It is honoured
  only when the plan's owner authorization carries `launch = {mode: "delegated", delegate, owner_instruction}`: who may launch and the
  owner's own words granting it. The authorization block is outside the digest, like the approval itself.
- **What did not change.** Every other gate still runs first and unchanged: plan shape, authorization for this digest and journeys,
  expiry, live environment equal to the frozen one, read-only readiness, the exact digest-naming phrase, the refusal in CI and under
  pytest, the resource limits and the never-retry stop conditions. The typed path is unchanged and is still the default.
- **One launch per digest.** A delegated launch exclusively creates `<digest12>.delegated-launch.json` beside the plan; a second
  delegated launch of the same digest is a HOLD. A repeat needs a new authorization and a newly frozen plan.
- **Attribution.** The evidence records `outcomes.launch`: `{"method": "typed"}` or `{"method": "delegated", delegate, owner_instruction}`,
  so a reviewer can always tell who pressed the button.
- **What this is not.** The delegate is the agent acting on the owner's chat instruction, so the owner's message is the control, not a
  second factor. It does not make authorization automatic: no authorization block, no run.
- **Still outside the harness.** Starting Forge (and any unload) stays with the wrapper outside Git, and the wrapper's launch step needs
  the same delegation to be passed through (it runs the harness without `--launch-phrase` today).

## 12. Fourth run result, 2026-11-06: empty-GPU load, functional PASS, safety PASS (would have failed the 6 GB floor)

Launch history: the wrapper run first refused (authorization expired, nothing started); the second launch started Forge cold but the
harness returned HOLD with no generation because the phrase was piped (no console); after the delegated-launch change (section 11) the
same targets and limits were frozen again at the committed change and launched with `--launch-phrase`. Only the last launch generated.

- **Archive.** `20261106T225054Z_physical_bb4df491_maximized_acceptance_0208ef`, MANIFEST.json sha256
  `ce365a9af773b927572aabfdb3e8a25ce4875a3bd6a3a5c6768ee860753fcff4`. The product verifier reports OK and an independent re-hash agrees.
  The archived plan digest equals the authorized plan digest (5f401871b8ec) and its targets, limits, journeys, suite version and
  environment equal the authorized plan. Clean tree at bb4df491. `outcomes.launch` records method `delegated`, the delegate and the
  owner's quoted instruction.
- **Result.** PASS: functional 17 of 17 checks, safety PASS, visual quality PENDING_OPERATOR_REVIEW. One job, 23.0 s, image 512x512
  recorded in History; sha256 `9ddd5146b24b2dd697f925022746a68cee18d71d0c82d687194b712c7f7b05e8` equals the archived artifact record.
  Dispatched settings: DPM++ 2M, scheduler Normal, 6 steps, CFG 7.5, seed 424242.
- **Start state.** Forge was started fresh from the product launch profile (44 s to API ready; RAM minimum 10.37 GB, VRAM at most
  1,491 MiB during startup, recorded in the unsealed wrapper evidence). No checkpoint was resident when the run began: VRAM 1,473 MiB.
- **Load-time telemetry (sealed).** Available RAM 12.12 GB at start, falling from 12.0 GB at t=76 s to a minimum of 5.84 GB at t=86.6 s
  while the checkpoint loaded (about 7 GB over 10 s), then 12.5 GB at t=88.6 s. VRAM 1,473 to a peak of 8,834 MiB. Commit used 23.7 GB
  at start, 30.0 GB peak (limit 56.7 GB).
- **Against the floors.** Under the original 6 GB floor this sample is NO-GO by 0.16 GB; under the 2 GB floor it is PASS with 3.84 GB of
  headroom. The first attempt's empty-GPU load reached 2.63 GB from a starting 8.9 GB, so the minimum differs by run: 2.63 (empty GPU,
  8.9 GB start), 5.73 (switch, 10.4 GB start), 5.84 (empty GPU, 12.1 GB start) and 8.61 GB (resident). The load costs roughly 6 to 7 GB
  of available RAM when the start is high, and the minimum depends on what else holds memory.
- **Image (observation, not a verdict).** Reviewed from the unsealed copy: over-saturated, high-contrast and noisy at 512x512 and
  6 steps, an oil-painting-like coastal scene with a path in the foreground; a structure on the upper right headland is not clearly a
  lighthouse. I did not compute similarity against the earlier images. Quality remains NOT TESTED.
- **Unsealed copies** are under `qual860-evidence/imgq0-attempt4-unsealed` (image, manifest, run_metadata, Forge-start evidence and
  console log).
- **Dimensions.** Unchanged: resource PARTIALLY QUALIFIED, quality NOT TESTED, integration PARTIALLY QUALIFIED. All three load cases now
  have one PASS under the 2 GB floor. Whether to propose a dimension change, or a floor between 2 and 6 GB, is an owner decision; this
  record proposes nothing new beyond section 5.1.
- **Forge** was left running with the checkpoint loaded.

### 12.1 Owner decision after the fourth run (2026-11-06)

The owner reviewed section 12 and decided: "I think the 2 gb floor is fine." Recorded as ledger evidence e11: the 2 GB host-RAM floor
is accepted (the original 6 GB stays recorded in e6), and the dimensions stay as declared (e8). No dimension change and no intermediate
floor is proposed. The next physical test stays unauthorized and is no longer needed for the baseline load cases; quality is still NOT TESTED.
