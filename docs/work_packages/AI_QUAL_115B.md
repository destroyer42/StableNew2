# AI-QUAL-115B — contract harness and capture aggregation

**HOLD — incomplete implementation draft, not ready for S2.** The independent
review confirmed three materially distinct blocking failure classes. The supplied
package's greater-than-two-class stop condition is met. No functional repair or
further validation is authorized under this package; a new bounded repair scope
needs the owner's decision. This document preserves the draft and evidence and
does not represent implementation acceptance.

Execution Profile: Standard, high-risk security/lifecycle and cross-file work.
Model recommendation: Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh.
Local/Desktop fits the Windows containment and ETW contracts. Expected usage:
approximately 15M cache-read / 65k output tokens (planning estimate, not measured).

Parent: `7234a3b37137ea3cc9e79cd83b32b1f46e268daf`, verified against remote main.
Branch: `codex/ai-qual-115b-contract-harness`. Clean checkout before work.
Session: `codex:01a18941-ba6f-7f81-bb22-ec25f9487557`, local desktop.
Pre-discovery measurement boundary: `2026-10-29T20:02:28.694Z`, the fresh host
session's logged `session_meta.payload.timestamp`; all work in this session is
this package. The first explicit clock reading was `2026-10-29T20:02:40.4704987Z`.
Actual logged executor: Codex `gpt-6.1-sol`, High; the recommendation remains XHigh.

## Acceptance and evidence contract

Keep the frozen LFM3 document/digest
`41e65d6769cd4090dc0e8f978014c97e82fd23c3351261f3ff276efd8a129f60`,
Qwen plans, sampling, corpus and production configuration unchanged. Explicit
contract selection must bind runtime, member, model, sampling, cases and approvals.
Unknown or incomplete evidence fails closed. Preparation and synthetic tests
authorize no extraction, binary/model execution, capture, installation, firewall
change, promotion, publication or merge.

Controller Surface Assessment: no GUI/controller/coordinator change or ceiling
increase; qualification tools and the default-preserving AiRuntime argument
builder seam. `capture_control.py` additionally accepts an optional preallocated
capture identity using its existing closed grammar, privilege/protection guards,
fresh-directory and no-active-session checks. No new elevation or process owner
is added; any future run needs a fresh protected copy and applicable canary.
Existing service, validator, owned runner and cancellation remain the execution
path. No production configuration, readiness or Suggest flag changed.

## Token-Efficient Validation Plan

1. Establish focused new-contract failures using synthetic metadata and inert runners.
2. Validate contract selection, integrity, argv, approvals, Stage A and Stage B flow.
3. One independent security/integrity review of the completed implementation.
4. At most one batched repair/reverification for confirmed in-scope blockers.
5. Run the canonical local PR gate once near closeout, inspect scoped diff and
   `git diff --check`. Hosted required/full-suite/windows await publication authority.

Stop on a frozen-criteria change, new owner/security boundary, unsafe capture split,
more than two materially distinct failure classes, or exhausted repair budget.
All physical work remains NOT TESTED and BLOCKED pending separate approvals.

## Validation evidence

- Python 3.14.9 from the existing `.venv`; no packages installed.
- Consolidated focused run: **337 passed, 1 skipped** (the existing Windows
  junction test cannot create a junction in this sandbox). Tests use synthetic
  archives and fake runners; no downloaded artifact was read or extracted.
- A positive Stage A simulation and exact 30-case attribution negatives exercise
  the existing judge. The first positive fixture copied an injection canary and
  was correctly REJECTed; its simulated answer was corrected without changing
  the judge, gates or acceptance criteria.
- Synthetic Stage B flow: deterministic 46 segments at 10 cases per segment,
  exact ordered 460-case traversal, per-segment evidence pointers, private paired
  data and label-free evaluator views. Synthetic evidence remains INCONCLUSIVE.
- Production argv equality and LFM3/matched-Qwen argv routing are covered by inert
  runner checks. Frozen contract and all Qwen digest assertions pass.
- Scoped Ruff checks and `git diff --check` pass; generated code map is current
  (its generator covers `src`, so qualification-only modules need no regeneration).
- Canonical gate: **NOT RUN**, because the independent review reached the explicit
  stop condition first. Hosted checks remain NOT RUN; no publication is authorized.

## Independent security/integrity review — HOLD

Read-only review thread: `01a18956-5734-7332-8f08-6d8ce573629d`. No source edits
were made by the reviewer. Three current P1 findings were independently reproduced
with inert runners/services; no real runtime, model or ETW capture was used:

1. **Monitor protocol mismatch.** `RetrospectiveMonitor` identifies as
   `host_retrospective`, but the new admission and record checks require `host`.
   The authentic LFM3 CLI path refuses. Fixtures using `host` missed this mismatch.
2. **No-launch attribution mismatch.** The frozen delimiter cases correctly
   return `INVALID_REQUEST / reserved_marker_in_text` before invoking a runner.
   The implementation incorrectly requires an owned execution record for every
   row and aborts on these cases. Stage A's first case is
   `adversarial_delimiter-0006`; A has three no-launch delimiter cases and B ten.
   Repair must record explicit, verifiable no-launch evidence without inventing
   child observations or changing the corpus/acceptance criteria.
3. **Lifecycle continuation after uncertain teardown.** `_lifecycle_probes` can
   proceed from timeout to cancellation after incomplete ownership, survivors or
   an ownership violation. An inert reproduction observed two calls after a first
   probe reported `complete=False`, `active_after_teardown=1`. The probe loop must
   stop before any subsequent request when teardown/ownership is uncertain.

No additional confirmed findings were reported. No repair batch was performed;
the stop threshold was reached before the one permitted repair could begin.
Repair passes: **0**. Passing synthetic tests do not supersede these findings.

## Closeout and next decision

The branch preserves the code/test draft for a separately scoped repair. No
architecture ownership or production configuration changed. Living capability
documents were restored to their pre-package state because acceptance is unmet;
their unaccepted proposed changes are preserved outside Git at
`C:\Users\rob\qual\ai115b-closeout-20261029\unaccepted-canonical-doc-proposal.patch`.
The source diff, new modules, tests and this HOLD record constitute the local draft.

Next owner decision: authorize a new bounded repair package covering the three
confirmed classes and their integration tests, or retain the draft on HOLD.
S2 is **not technically prepared, not authorized and NOT TESTED**. The eventual
physical prerequisites remain protected Python/capture copy, fresh applicable
canary, firewall attestation, authentic host DLL provenance, selected-member D12a,
and independently verified S2/S3/S4 grants. No physical phase may begin from this
draft. Final token measurement is reported at closeout, including the review
session when telemetry is available.

## Evidence and authorization limits

No archive extraction, downloaded executable/model execution, model import,
ETW session, protected installation, firewall/GPU/service change, promotion,
push, PR or merge occurred. Host loaded-module observation is not added by this
package: absent authentic dependency provenance stays UNMEASURED and blocks PASS.
The supplied frozen contract document/digest and corpus/selection criteria are
unchanged; default-preserving validator code accepts the existing Stage A
sensitivity disposition for Stage B and refuses any truncated help PASS.
