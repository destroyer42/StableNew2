# DIAG-GPU-160 — GPU device loss resolved by forcing PCIe Gen4: documentation and ledger closeout

Hand-off prompt for a fresh Claude Code or Codex session. Everything needed is below; do not re-run broad discovery.

## Objective

- **Outcome:** every current-state document, hold, open decision and qualification gate that treats intermittent GPU
  device loss ("display crash", black screen, Kernel-PnP remove-veto, `HOLD-GPU-DEVICE-LOSS`, `DIAG-GPU-130` open) as an
  active blocker or concern says instead that the issue is **resolved by owner action** and is no longer a blocker.
- **Owner statement (2026-11-22, the authority for this package — quote it in STATUS/DIAG records):** the GPU display crashed
  "somewhat randomly but periodically". The owner changed the motherboard PCIe link speed for the GPU slot from **Auto to
  Gen4** (explicitly forced). No crash since, after "hours upon hours" of both image and video generation stress. The owner
  considers the issue resolved and wants it treated as no longer a blocker or concern.
- **In scope:** docs, the SYSTEM-840 ledger standing hold, and owner-decision text. Short-form "closed" wording; keep it true.
- **Explicit exclusions:**
  - Do **not** remove or weaken the runtime safety code: `src/controller/gpu_loss_coordinator.py`,
    `src/queue/gpu_loss_assessment.py`, `src/utils/gpu_survivor_telemetry.py`, the device-loss quarantine, or the
    `device loss` **per-run stop conditions** inside qualification plans/harnesses (those are generic safety stops, not a
    standing hold). Keep `tools/diagnostics/gpu_hang_recorder.py` and `tools/diagnostics/correlate_gpu_incidents.py`.
  - Do **not** rewrite dated historical evidence records (DIAG-GPU-100..150 bodies, dated audits/assessments, per-PR
    qualification records). Add a short dated resolution/superseded note at the top instead.
  - Do **not** change the rule that each physical *qualification* run needs its own owner authorization of an exact plan
    (`docs/runbooks/qual_system_840.md` section 2). That rule is about qualification governance, not the GPU fault.
  - Do not change Python harness constants (e.g. `RISK_ID = "DIAG-GPU-130"` in
    `tools/qualification/img154b/authorization.py`, `tools/qualification/img_backend_qual_100/protocol.py`); they are frozen
    historical authorization text whose digests may be pinned by tests. Mention them as historical in the completion report.

## Execution class and model recommendation

- Execution class: **Narrow** (docs + one JSON ledger edit). Local.
- Model recommendation: Claude Code **Haiku 5.5 High** or **Sonnet 5.5 Low**; Codex **GPT-6 Luna Medium**.
- Expected usage: about 2–4M cache-read, 20k output.

## Exact start state

- Repo `destroyer42/StableNew2`, start from `origin/main` (at hand-off: `d8ea1c86`). Use an isolated worktree (memory:
  the owner's live app runs from the main checkout `C:\Users\rob\projects\StableNew-main`; do not edit there).
- Branch: `docs/diag-gpu-160-pcie-gen4-resolution`.
- Record task-start timestamp and session ID before work (`docs/AI_MODEL_SELECTION.md`).

## Research already done — the exact edit list

New record (create): `docs/Subsystems/Runtime/DIAG-GPU-160_PCIe_Gen4_Resolution.md`
- Status line: **RESOLVED BY OWNER PLATFORM CHANGE (owner-accepted 2026-11-22).**
- Content: the owner statement above; the change (UEFI PCIe link speed for the CPU-attached x16 GPU slot `PCIE1`, Auto →
  Gen4; hardware per DIAG-GPU-150: PNY RTX 4070 Ti on the CPU root port, ASRock board); that DIAG-GPU-150's *planned*
  variable was Gen3 (section "Next single platform variable: force the GPU slot to PCIe Gen3", line ~79), and the owner
  instead forced Gen4 — i.e. the fault correlated with **link-speed auto-negotiation**, not with Gen4 bandwidth itself;
  the evidence class (owner-observed multi-hour image+video stress without a loss; no recorder log is claimed unless the
  owner supplies one); what stays (quarantine, per-run stop conditions, recorder tool as optional diagnostics);
  recurrence rule: *any new device loss reopens this record and re-instates a hold by owner decision*.
- Link it from `docs/Subsystems/Runtime/QUEUE_AND_RUNTIME.md` evidence table (line ~310-313) and from STATUS.

Edits (line numbers at `d8ea1c86`; confirm before editing):

| File | Where | Change |
|---|---|---|
| `STATUS.md` | Holds bullet 1, lines 125-129 | Replace with one bullet: GPU device loss resolved 2026-11-22 by forcing PCIe Gen4 (owner), link DIAG-GPU-160; quarantine remains as a safety net; each physical *qualification* run still needs its own exact-plan authorization (keep the existing qual_system_840 / roadmap pointer). Keep within the 150-line cap. |
| `STATUS.md` | Open owner decision 3, line 104 | Mark decided: "`DIAG-GPU-130` closed 2026-11-22 by DIAG-GPU-160 (PCIe Gen4)". Prefer editing the line, not adding one. |
| `STATUS.md` | Holds line 131-132 ("Comfy image slice needs resource and fault clearance") | Fault clearance is satisfied by DIAG-GPU-160; resource clearance remains. |
| `STATUS.md` | `Updated:` header | 2026-11-22 (or the actual date). |
| `docs/Subsystems/Runtime/QUEUE_AND_RUNTIME.md` | invariant 12 (line 227) and section 13 heading/first paragraph (lines 232-236) | Heading → "GPU constraints (device loss resolved 2026-11-22)". Say the root fault was resolved by owner platform change (DIAG-GPU-160); quarantine stays. Keep the hermetic-test and "do not weaken containment" bullets unchanged. Add DIAG-GPU-160 row to the evidence table (lines 310-313); relabel DIAG-GPU-100 row "behind the former HOLD". |
| `docs/Subsystems/Image/IMAGE_PIPELINE.md` | item 11, line 365 | Add "the device-loss fault was resolved 2026-11-22 (DIAG-GPU-160)". |
| `docs/StableNew Roadmap v2.6.md` | lines 538-546 ("physical execution HOLD after the October 12 GPU device-loss incident. Clear the fault…") | Note the fault is cleared (DIAG-GPU-160); matched-evidence authorization still required. |
| `docs/Subsystems/Testing/QUAL-CAMPAIGN-920_Wave0_Capability_Campaign_Plan.md` | line 21 (standing hold) and line 171 ("at most about four GPU runs per sitting because of `HOLD-GPU-DEVICE-LOSS`") | Retire the standing hold (dated note, cite DIAG-GPU-160). Pace: keep the owner's accepted pace text but drop the hold as its reason, or ask the owner whether the four-per-sitting cap still applies — **default: keep the cap, remove the hold reason** (the cap is an owner pace decision). Keep "GPU arms never run concurrently". |
| `docs/Subsystems/Testing/QUAL-CLOSEOUT-860_Existing_Capability_Reconciliation.md` | item 4 (lines 102-106), line 183, section 3.3 item 1 (lines 187-189), line 204 | Add dated note: resolved by DIAG-GPU-160; section 3.3 item 1 (decide if a GPU run is acceptable given loss markers / whether the PCIe variable was applied) is answered: yes, Gen4 forced. Do not delete the historical counts. |
| `tools/qualification/system840/ledger.v1.json` | `standing_holds` entry `HOLD-GPU-DEVICE-LOSS` (lines 45-49) | Remove the entry (it is referenced only there — verified one occurrence; no capability `holds` array names it). The ledger rule "a status changes only by an owner-accepted, reviewed edit of the ledger JSON" is satisfied by this owner request; say so in the PR body. If the ledger schema keeps history, prefer a `resolved` marker only if `tools/qualification/system840/ledger.py` already supports one (it does not at hand-off — validation at `ledger.py:227` only checks capability holds exist). |
| `docs/runbooks/qual_system_840.md` | line ~72 stop classes | No change (per-run stop classes stay). Verify no text names the standing hold; if it does, update. |
| `tools/qualification/README.md` | line 5 | Add "the device-loss fault was resolved 2026-11-22 (DIAG-GPU-160)"; the per-run authorization rule remains. |
| `docs/Subsystems/Runtime/DIAG-GPU-100…150` (six files) | top `## Status` block of each | Prepend one dated line: "**Superseded 2026-11-22:** resolved by owner platform change, see DIAG-GPU-160." Do not edit bodies. DIAG-GPU-130's status ("ACTIVE OBSERVATION / EXIT CRITERION NOT MET") and DIAG-GPU-150's ("ROOT CAUSE NOT ATTRIBUTED") get this line too. |
| `docs/audits/2026-10-26_product_capability_roadmap.md` (lines 65, 101), `docs/audits/2026-10-20_video_experience_roadmap.md` (line 82) | — | Dated audits: add a single superseded note near line 101 / 82 only if the roadmap is still the *active* owner-selected roadmap (2026-10-26 is — STATUS "Active"). Otherwise leave. |
| `docs/research/stablenew-experience/workflows/runtime-settings-and-recovery.md` (lines 7, 16) | — | Leave (research snapshot) unless `ci_truth` or a living doc links it as current. |
| `docs/CODEX_MAP.md` row "GPU device-loss containment" | — | Optional: append `; resolution record docs/Subsystems/Runtime/DIAG-GPU-160_PCIe_Gen4_Resolution.md`. 60-line cap. |

Also sweep once for anything this table missed: `git grep -n -iE "HOLD-GPU|device[- ]loss.*(unresolved|no root cause|intermittent)|DIAG-GPU-130.*open|physical-GPU hold"` over `*.md` and `*.json`, excluding the dated records listed as "leave".

Memory: the Claude auto-memory has no GPU-hold entry; nothing to update there.

## Acceptance criteria

1. No living doc (STATUS, the eight subsystem living docs, CODEX_MAP, runbooks, active roadmap, campaign plan, qualification
   README) describes GPU device loss as unresolved, a standing hold, a blocker, or an open owner decision.
2. `DIAG-GPU-160` exists, states owner-reported evidence honestly (no claim of a recorder trace or root-cause proof beyond the
   owner's observation), and states the reopen rule.
3. `HOLD-GPU-DEVICE-LOSS` removed from the ledger; ledger still validates.
4. Runtime quarantine code, per-run stop conditions and tests are untouched (`git diff --stat` shows only `.md` files plus the
   one ledger JSON).
5. `STATUS.md` ≤150 lines and passes `ci_truth`; every referenced path exists.

## Token-efficient validation plan

1. `python tools/ci/ci_truth.py` (STATUS cap, stale markers, path existence; also checks CODEX_MAP).
2. `python -m pytest tests/tools/test_qual840_ledger.py -q` and the SYSTEM-840 CLI validate if present
   (`python -m tools.qualification.system840.cli --help` to find the validate/status subcommand).
3. `git diff --check`; `git diff --stat` to confirm scope.
4. Docs-only + one JSON: per memory "docs-only change skips CI" the JSON edit means run the focused ledger test; the full PR
   gate is not needed unless `ci_truth` or the ledger test fails.

## Stop conditions

- A test pins the ledger hold list or a digest of the ledger file → stop and report the test name rather than editing the test.
- Any text implies the qualification authorization rule should be removed → out of scope; leave it.

## Completion report

Per `AGENTS.md` section 8: outcome, branch/SHA, files changed, validation output, the historical harness constants left as-is,
`Model / usage` line. Commit on the feature branch; push/PR only if the owner authorized publication.
