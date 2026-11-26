# RG-140 — Phone actions from the review gateway (first slice)

Status: **in progress (slice 1).** Contract and decisions: [RG-100](RG-100_phone_review_gateway.md) (D6, D8, invariants
1–6, controls S4, S8, S12). Payloads: [`stablenew.review-gateway-sync.v1`](../schemas/stablenew.review-gateway-sync.v1.json).
Living document: [`REVIEW_GATEWAY.md`](../Subsystems/ReviewGateway/REVIEW_GATEWAY.md).

## Objective

- **Owner outcome:** while reviewing a walk-away batch on the phone, one tap asks the PC to fix the face, fix the hands,
  fix both, or make more like this. The phone shows one summary screen first (what will run, how many jobs, where it
  goes in the queue, and every N1 warning with its why and fix), then a receipt (queued job ids, or the PC's refusal).
  Touch-ups start soon after the current job. The results come back to the phone inbox through ordinary publishing.
- **In scope (slice 1):**
  - The actions `fix_face`, `fix_hands`, `fix_both` (the executor's existing ADetailer face and hand passes, on that
    exact image) and `more_like_this` (the same prompt and model, new seeds), for images only.
  - A two-step outbox protocol: prepare, then confirm. Both steps are outbox requests, and both are answered by PC
    acknowledgements.
  - The queue grant, chosen per phone when it is paired. Caps, idempotency and receipts.
  - Gateway routes, the gateway store, phone UI, the PC sync worker, PC admission, and the desktop pairing checkbox.
  - Tests and documentation.
- **Explicit exclusions (later slices, each its own package):** another model, aspect ratio, prompt tweak, make video,
  re-run a clip and continue a clip (N4/N8 remainder). Also excluded:
  - live job progress on the phone after the receipt;
  - changing an already paired phone's grant without re-pairing (a `device_grant` payload);
  - "more like this" for multi-stage recipes (see Q2);
  - the touch-up lane on the AI worker (RG-145);
  - eval ratings on the phone (RG-150).

## Decisions taken in this package (defaults; owner questions Q1–Q4 below)

| # | Decision | Default taken |
|---|---|---|
| A1 | How the phone gets the summary and warnings before queueing (S12) | **Prepare, then confirm.** The phone's `prepare` request makes the PC compile exactly what it would queue. The PC admits nothing and acknowledges with an `action_summary`: a title, PC-written lines, the job count, the queue position and the N1 warnings. The phone shows that screen. Queue sends a `confirm` naming the prepare record and the summary's revision. The PC compiles again. If the revision is unchanged, it admits and freezes the shown warnings into provenance as `surface: phone`. Otherwise it refuses with `summary_changed` and returns the new summary to show. The warnings are therefore always the ones the real compile produces. Nothing is computed per item at publish time. |
| A2 | Front of the queue (D8 first step) | **The existing durable priority.** Touch-ups (`fix_*`) are admitted with `SubmissionPolicy(priority=JobPriority.HIGH)`. `JobQueue` already orders by priority and then FIFO, and `JobRepository` persists the priority. So a touch-up runs after the current job and before NORMAL queued work, and never preempts. `more_like_this` is NORMAL and joins the back. No new queue semantics. |
| A3 | Queue grant (D6, S4) | **Chosen at pairing.** The desktop pairing dialog gets a checkbox, "Allow queueing from this phone", which is off by default. It puts `queue` in the offer's scopes. The gateway accepts action requests only from devices enrolled with `queue`. The PC re-checks the scope from the offer it issued, so the PC stays the authority. To grant or withdraw queueing for a phone already paired, revoke it and pair again. |
| A4 | Caps (S4) | **PC (authoritative):** one job for each fix; `more_like_this` takes 1 to 8 seeds (4 by default); per device in any rolling 24 hours, at most 64 admitted jobs and at most 200 prepares. **Gateway (early refusal):** at most 20 unanswered action requests and at most 300 action requests per device in 24 hours. |
| A5 | Idempotency (S8) | **Two layers.** (1) The gateway is unique per device and idempotency key, and a key reused for a different request is a 409. (2) The PC ledger answers a re-sent record with its first outcome, and it admits at most once per prepare record. A second confirm of the same prepare is a `duplicate` that carries the first receipt. |
| A6 | Admission path (invariant 6) | **One phone admission path.** `site_phone_admission.admit_phone_records` is factored out of `PhoneQueueAdmission` and now serves both the hosted relay and the gateway. It derives phone job ids and the `phone_submission` claim, refuses while dispatch is fenced, freezes the accepted warnings with `surface: phone`, and crosses `JobService.submit_njrs` exactly once (fixes through `submit_reprocess_njrs`). |
| A7 | Compilers reused | **Existing compilers only.** Fixes use `prepare_review_batch(stages=["adetailer"])` with a new `adetailer_passes` override that sets the face and hand pass flags after the recorded baseline. They inherit the N1b SDXL verdict (`target_verdict`) as pending warnings and refuse when no detector for the pass is listed. `more_like_this` takes the History source NJR through the follow-up service's verification, factored out as `verified_history_source`, then `HistoryVariationDraft.with_edits(seed=…)` and `compile_history_variation`. The jobs carry the model's shown N1 warning. |
| A8 | Schema | **Additive changes; `schema_version` unchanged.** The action enum gains `fix_both`. `action_request.params` is typed (`step`, `count`, `summary_revision`, `prepared_record`). Four reason codes are added: `summary_changed`, `cap_exceeded`, `action_unavailable` and `prepare_required`. The receipt gains `action_summary` and `detail`. Old peers never send or receive any of these: an RG-110 gateway refuses to create action records, and an RG-120 PC refuses them. |
| A9 | Paths and text (invariant 3, S7) | **No paths or free text cross.** Every warning text and subject is scrubbed of absolute paths before it crosses (only the last path component is kept). Compile errors cross only as closed `detail` codes, never as their message text (those can contain paths). The phone renders everything with `textContent`. |

## Owner questions (sent to the orchestrator in one message)

- **Q1 Priority:** should `more_like_this` also go to the front, like fixes do (default: no, it joins the back)?
- **Q2 Multi-stage "more like this":** the existing History variation compiler only varies a single txt2img stage, so
  a PromptPack job with txt2img → ADetailer → upscale is refused (`recipe_not_variable`). Should a later slice widen
  this to re-run the whole recipe with new seeds?
- **Q3 Caps:** are 64 jobs and 200 prepares per phone per 24 hours, and 1 to 8 seeds per request, right?
- **Q4 Grant:** is it acceptable to re-pair a phone to grant queueing? The alternative is a `device_grant` sync
  payload, so the desktop can toggle queueing on a paired phone (a follow-up).

## Protocol (slice 1)

The phone's request (`POST /api/actions`) becomes an outbox record of kind `action_request`:

```json
{"action": "fix_face", "params": {"step": "prepare"}}
{"action": "more_like_this", "params": {"step": "prepare", "count": 4}}
{"action": "fix_face", "params": {"step": "confirm", "prepared_record": "<uuid>", "summary_revision": "<sha256>"}}
```

The PC answers the prepare step:

- `applied`, with `receipt.action_summary`;
- or `refused`, with one of `not_granted`, `revoked_device`, `unknown_item`, `digest_mismatch`, `cap_exceeded`, or
  `action_unavailable` plus a closed `receipt.detail`.

The PC answers the confirm step:

- `applied`, with `receipt.job_ids` and the final `action_summary`;
- `refused`, with `summary_changed` and the new `action_summary`;
- `refused`, with `prepare_required` (an unknown, other-device, other-item or expired prepare);
- `refused`, with `cap_exceeded`, `action_unavailable` or `admission_refused`;
- `duplicate`, carrying the first receipt.

A prepare stays valid for 30 minutes.

`action_summary`: `action`, `revision` (sha256), `title`, `lines` (up to 8 lines, each 200 characters or fewer),
`job_count`, `queue_position` (`next` or `last`), `warnings` (up to 8 items of `code`, `subject`, `title`, `why` and
`fix`), and `expires_at`. The revision is a fingerprint of everything the summary shows plus the compiled recipe
without its ids and seeds, so a recompile that would queue the same work gives the same revision.

Gateway rules:

- Action records never become an item's decision. They do not change `latest_record_id`, Immich uploads or the
  decision state.
- An unanswered action record keeps the item's cached media, through the existing "no pending record" rule.
- `GET /api/actions/{record_id}` returns the record's state and acknowledgement to the device that made it, and only
  to that device.

## Security controls exercised

| Control | How slice 1 meets it |
|---|---|
| S1, S11 | Action routes need an enrolled device session, read on each request. A revoked device is refused on the gateway and the PC. |
| S2 | No new sync route; acknowledgements carry the summary. |
| S4 | Separate `queue` scope from pairing, checked on the gateway and the PC. Closed action list and typed params on both sides. Per-request and rolling daily caps on both sides. Idempotency keys. Admission only through the phone admission function and `JobService.submit_njrs`. |
| S7 | Summary text is PC-authored and path-scrubbed, rendered as text. The JSON APIs keep the custom header. |
| S8 | Outbox until acknowledged; idempotency on both sides; one admission per prepare; PC receipts authoritative and shown. |
| S12 | The phone shows the prepare summary's warnings before Queue. A confirm admits only when the revision (which covers the warnings) is unchanged. The jobs record `accepted_warnings` with `surface: phone`. |
| Invariant 3 | Items by library id plus SHA-256. The path is resolved through the PC's publish ledger and the file re-hashed before compiling. |
| Invariant 6 | A test asserts that a phone action reaches the runner only through `JobService.submit_njrs`. |

## Execution class and model recommendation

- Execution class: Standard-high (security boundary, within the approved RG-100 design; no queue-concurrency change).
- Execution location: Local.
- Model recommendation: Claude Code Opus 5.5 High; Codex GPT-6 Astra High.

## Exact start state and authorities

- Task start: 2026-11-26 (America/New_York). Child session of orchestrator `local_ecb8e9b1-c2ce-4303-95cf-308e8cc92d9e`.
- Repository `destroyer42/StableNew2`. Branch `claude/rg-140-phone-actions-9a8451`, fast-forwarded to `origin/main`
  `7bdaefad` (after N1 #436, #437, #440).
- Authorities: `AGENTS.md`, `STATUS.md` (Operator Site line), `docs/CODEX_MAP.md` (queue submission row), RG-100, the
  sync schema, `REVIEW_GATEWAY.md`, and `src/pipeline/policy_warnings.py` (N1).

## Surface assessment

- **Gateway:** `services/review_gateway/review_gateway/{phone_app,store}.py`, `static/app.js`, `static/app.css` and
  tests.
- **PC:** `src/app/review_gateway_{protocol,apply,store,sync}.py`, a new `src/app/review_gateway_actions.py`,
  `src/app/site_phone_{admission,followup,preview_host,queue}.py`,
  `src/controller/{review_batch_service,reprocess_admission}.py`, `src/app/runtime_stack.py`,
  `src/gui/review_gateway_dialog.py`, and tests.
- **Controllers:** no ratcheted controller grows. Composition stays in `runtime_stack.py`.
- **Architecture authority:** unchanged. The priority used already exists, and the queue-concurrency invariant changes
  only in RG-145.

## Acceptance and evidence

- A phone with the `queue` grant can prepare and confirm `fix_face`, `fix_hands`, `fix_both` and `more_like_this` on a
  published image. The jobs are admitted through `JobService.submit_njrs` (fixes at HIGH priority) with
  `accepted_warnings` of surface `phone`, and the phone receives the job ids.
- These are refused with the right code: no grant, revoked device, digest mismatch, unknown or expired prepare,
  changed summary, caps, a video item, and an unavailable detector or recipe.
- A re-sent record, a reused key or a second confirm never admits twice.
- No path appears in any payload the PC sends. Action records never change an item's decision or Immich state.
- Evidence mode: hermetic tests. Gateway: an ASGI client. PC: a fake gateway, a fake app capture, and a recording
  `JobService`. No qualification claim. Not demonstrated: the live phone, a real Forge ADetailer run, and the live app.

## Token-efficient validation plan

1. `tests/review_gateway_service` (gateway) and `tests/app/test_review_gateway_*` plus the new action tests (PC).
2. The affected suites: `tests/app/test_site_phone_*`, Review batch and reprocess admission tests, and History
   variation tests.
3. `python tools/ci/run_pr_gate.py`, then `tests/system` and `tests/tools` (the gate skips them). GUI journey tests run
   alone.

## Stop conditions

- Front-of-queue would need new queue semantics. It does not, because the durable priority exists; otherwise ask the
  orchestrator.
- Any path that would admit a phone job outside `admit_phone_records` and `JobService.submit_njrs`.
- A compiler would need to change its refusal envelope (for example multi-stage variation, Q2).

## Documentation impact

- `REVIEW_GATEWAY.md`: phone actions, sync binding rules, retention note.
- The schema (A8).
- `STATUS.md`: the Operator Site line.

## Completion report

Filled in at closeout in the PR body per `AGENTS.md` section 8.
