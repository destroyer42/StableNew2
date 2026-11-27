# RG-160 — Phone actions queued while the PC is away

Status: **phase 1, design only (2026-11-27). No code. Questions answered
("Decisions on the open questions" below). Phase 2 waits for PHONE-FAST to merge and for the orchestrator's go.**
Builds on [RG-100](RG-100_phone_review_gateway.md) (invariants and controls), [RG-140](RG-140_phone_actions.md) (phone
actions) and [`REVIEW_GATEWAY.md`](../Subsystems/ReviewGateway/REVIEW_GATEWAY.md). Payloads:
[`stablenew.review-gateway-sync.v1`](../schemas/stablenew.review-gateway-sync.v1.json).

## Objective

Owner request (2026-11-27): "on phone when StableNew is down, off, or disconnected, ability to save queue requests
(rework or send to movie clips), and forward when reconnected. If the phone site kept the latest information on available
StableNew models and settings that could be selected, it wouldn't need a direct connection to the app to know what the
choices are. Then it could store those choices and queue requests and send and process when connection is made again."

- **Outcome:** with the PC away, the owner picks a phone action, with the same choices as when it is there, and taps
  **Queue when the PC is back**. The request waits on the gateway. When the PC reconnects it is checked against what is
  true then and queued, or refused with a reason. The owner does nothing in between.
- **Preferences that apply:** warn, don't block (refuse only certain failures); no quotas; simple screens.
- **Non-goals:** a second queue, compiler or admission path; the gateway deciding anything; new phone actions; live job
  progress; opening the phone page with no network at all.

## Facts from the current code that shape the design

1. Both RG-140 steps need the PC. A confirm names a prepare that expires after 30 minutes (`PREPARE_TTL`), so a request
   that waits cannot use the two steps.
2. A review phone has no PC liveness signal. `pc_status` is shown to `admin` phones only and sent only when remote
   update is attached.
3. The sync worker starts as soon as the window is up, so it can pull before the image backend (Forge) is connected.
   With empty lists the fixes refuse `adetailer_unavailable` and "another model" refuses `model_unavailable`. Replaying
   waiting requests through today's code could refuse them for a state that passes by itself (from reading the code,
   not observed).
4. Forge being down does not matter after admission: the queue already holds image jobs until it is back.
5. The phone page has no service worker. It cannot be opened without reaching the gateway.

## Approaches considered

| Approach | Trade-off |
|---|---|
| **A. One-step deferred request in the existing outbox** (chosen) | A new `step: "queue"`: the PC compiles and admits through the RG-140 path, with no confirm. Small and reuses everything. The owner does not see the compiled summary before it queues. |
| B. Keep two steps and confirm automatically on reconnect | Something other than the owner would "confirm" a summary they never saw. Same loss as A, with more records and a confirm rule that means nothing. |
| C. The PC publishes summaries ahead of time, so the owner confirms offline | Needs a compile per image, action and choice. Impossible for typed words, stale as soon as a setting changes. |

## Design

### 1. Choice catalog (PC to gateway)

`PUT /sync/v1/choice-catalog`, schema `$defs/choice_catalog`, sent only to a gateway whose health lists the feature
`deferred_actions`. The gateway keeps the latest one with the time it arrived.

It holds exactly what the phone can choose today, and no more:

| Field | Content | Bound |
|---|---|---|
| `models` | `{id, label, warnings}`: the RG-140 choice id (hash of the name), the file name, indexes into `warnings` | 200 entries, labels 120 characters |
| `warnings` | `{code, title, why, fix}`, each text once, from `shown_warning_for` | 20 entries, 300 characters each |
| `ratios` | `{id, label}` from `ASPECT_RATIOS` | 16 entries |
| `video` | `{available, label}`: the approved Make Video workflow that would run | one |
| `models_as_of` | when the model list was last read from the image backend | |
| `image_backend_ready` | whether that list is loaded now | |
| `truncated` | true when entries were left out | |

- The whole payload stays under the existing 64 KiB JSON limit. If it would not, warning `why` and `fix` go first, then
  models from the end, with `truncated: true`. This is a transport bound, not a quota.
- **No paths.** Labels are the last path component; warning text goes through the existing summary scrub. The schema is
  closed (`additionalProperties: false`) and refuses `\` and `/` in labels.
- The PC remembers the last non-empty model list in its sync ledger, so a session without Forge never publishes an
  empty list over a good one.
- It is sent when its content changes, after a reconnect, and every 10 minutes (a rebuilt gateway gets it back).
- No checkpoint "family" field: no phone control would use it, and what matters about it is already a warning.
- No motion presets or duration bounds: the phone's Make Video has no such picker today (it takes optional words only).
  They join the catalog when the phone offers them.
- No catalog revision on requests: the PC validates against what is true on arrival, so nothing would read it.

The catalog is also the capability signal. Only an RG-160 PC publishes it, so a phone never sends the new step to a PC
that would refuse it as `invalid_record`. Without a catalog the phone behaves as today.

### 2. Is the PC there?

The gateway records `pc_seen_at` on every outbox pull (the PC pulls every 5 s, and backs off to 60 s at most after a
failure). `GET /api/status` (review scope) returns `pc_seen_at`, `now`, `image_backend_ready` and this phone's waiting
count. "Away" means older than the existing `STATUS_STALE_MS` (3 minutes). `GET /api/catalog` returns the catalog and
its `received_at`; it needs the `queue` scope. PHONE-FAST (f) plans `/api/status`; extend that one, do not add a second.

### 3. The deferred request

`POST /api/actions` as today, with:

```json
{"action": "fix_face", "params": {"step": "queue"}}
{"action": "another_model", "params": {"step": "queue", "choice": "<id>"}}
{"action": "make_video", "params": {"step": "queue", "text": "turns towards the window"}}
```

`count`, `choice` and `text` follow the prepare rules; `choice` is required for the picker actions. Same outbox, same
idempotency key rules, same scopes, same `MAX_PENDING_ACTIONS` bound, same media retention (an unanswered record keeps
the item's media). **It never expires.**

When the phone offers **Queue when the PC is back**:

- at once, when the PC is away;
- after about 10 s without an answer to a prepare, when the PC was thought to be there;
- when a prepare is refused only because the image backend is not ready.

A prepare left behind is cancelled, so the PC does not compile it for nothing. A pending **confirm** is turned into a
deferred request only if it can be cancelled cleanly (the PC never received it); otherwise the phone says the PC already
has it, so one tap can never queue twice.

### 4. What the PC does with it

`GatewayActions.handle` gains the `queue` step. `RecordApplier` checks are unchanged (device, scope, ledger lookup,
re-hash).

1. **Already admitted?** The receipt id is the record id, so the job ids are deterministic. `PhoneQueueView.receipt` is
   read before anything else; a restart between admission and acknowledgement answers `applied` with the same jobs.
2. **Not ready yet?** The record is left unanswered (the existing `IN_PROGRESS` outcome, used today for remote update),
   so it stays on the gateway and is asked again. Closed list: the action needs the model list or detector list (fixes,
   another model) and none is loaded yet; the app is busy (`app_busy`); the app is shutting down. This check comes
   before the file is re-hashed, so waiting records cost almost nothing each cycle.
3. **Compile and admit** with the existing compilers and `admit_phone_records` into `JobService.submit_njrs`, with the
   same priorities (fixes HIGH, everything else NORMAL). The claim records `deferred: true`.
4. **Answer** `applied` with `job_ids` and the compiled `action_summary` (the receipt shows what was queued and every
   warning), or `refused` with the existing reason and `detail` codes. Certain failures only: source gone or changed,
   chosen model gone, no matching detector once the list is loaded, operation the backend cannot perform, recipe that
   cannot be re-run, no approved video workflow, grant withdrawn, phone revoked.

**Order.** Records are handled in the order made. One waiting for Forge does not hold up a ready one behind it (a clip
need not wait for Forge). All Forge-dependent requests wait on the same condition, so they keep their order among
themselves. The pull follows every outbox page, so a long waiting list never starves later decisions.

**Settings at run time.** Everything is compiled from what is true on arrival: the recorded recipe for "more like this"
(new seeds drawn then), the desktop's current img2img and ADetailer settings, and today's approved video workflow.

### 5. Cancel

`POST /api/actions/{record_id}/cancel`, only for the device that made the request. The record leaves the outbox
(`status = superseded`, new column `cancelled_at`; no table rebuild). If the PC never received it, the phone says
**Cancelled**. If the PC had received it, the phone says **Cancel sent**; should the PC's answer then arrive as
`applied`, the gateway records it and the row reads **Queued (too late to cancel)**.

### 6. Phone offline

If the phone cannot reach the gateway, the request goes into the page's existing local storage list, the same list as
unsent decisions, so their order is kept, and is sent with the same idempotency key. The catalog is kept in local
storage too. This works for a page already open; opening the page with no connection is out of scope (fact 5).

### 7. Screens

```
Header:   [3 waiting for PC]                      (hidden when zero)

Action sheet, PC away:
  Another model
  PC last seen 2 h ago · list as of 06:10
  [ modelA ] [ modelB ⚠ ] [ modelC ]
  ⚠ modelB: <warning title and why>
  The PC checks this when it is back and queues it with any warnings.
  [Cancel]  [Queue when the PC is back]

Waiting list (from the header):
  PC last seen 2 h ago
  [thumb] Fix face        Waiting for PC            [Cancel]
  [thumb] Make video      Queued, 1 job             [Dismiss]
  [thumb] Another model   Refused: model not there  [Choose again] [Dismiss]
```

- `GET /api/requests` returns this device's deferred requests: all unanswered, and answered ones from the last 7 days.
- A delivered but unanswered request reads "Waiting for Forge on the PC" when `image_backend_ready` is false.
- Queueing the same action on the same image again asks "Already waiting. Queue another?" (a warning, not a block).
- The online path (prepare, summary, Queue) is unchanged while the PC is there.

### 8. The original image

- A waiting or applied **fix** counts as PHONE-FAST's "sent for rework": it leaves the unreviewed stream, and returns
  with the reason if refused or cancelled. PHONE-FAST derives that state from a non-refused fix `confirm`; it must also
  accept a non-refused, non-cancelled fix `queue`.
- Other actions do not change the original's state; its tile shows a waiting mark.
- **Delete with a request waiting:** the phone warns "A request for this image is waiting. Deleting cancels it." On yes,
  the gateway cancels it in the same transaction as the decision (the source would be archived, so it could not run).
- PHONE-FAST (f)'s 30-day purge of undecided items must skip items with an unanswered action record.

### 9. Results that arrive later

They are ordinary published items. The admission path is the same one, so PHONE-FAST (d)'s `rework_result` mapping must
record deferred admissions as it records confirmed ones; the compare view then works unchanged. Decided (relayed with
this task): a rework joins the original's batch group. **PHONE-FAST owns it** (orchestrator, 2026-11-27); this
package treats it as already present. If it is not on `main` when phase 2 starts, report that to the orchestrator
instead of building it here.

## Decisions taken as agent defaults

One-step `queue` through the existing outbox; no catalog revision, family, motion presets or durations in the catalog;
gateway-observed PC liveness; not-ready waits instead of refusing; a waiting Forge request does not hold ready ones;
priorities unchanged (so fixes gathered while away all run ahead of NORMAL queued work); cancel semantics above.

## Decisions on the open questions (2026-11-27, relayed by the orchestrator)

| # | Question | Decision | Decided by |
|---|---|---|---|
| Q1 | No summary before queueing when the PC is away? | "One tap, warnings after". The tap on "Queue when the PC is back" is the opt-in, including for any N1 warning the compile finds; warnings are shown on the sheet where known and listed on the receipt. The one-line amendment to `AGENTS.md` section 2 and RG-100 S12, which today tie the opt-in to the summary, is approved. | Owner, in chat |
| Q2 | Expiry? | Never; cancel by hand. | Orchestrator |
| Q3 | What is "send to movie clips"? | The phone's **Make video** button. Adding images to a Movie Clips assembly is out of scope. | Owner, in chat ("Make video") |
| Q4 | Delete an image that has a request waiting? | Warn, then cancel the waiting request (section 8). | Orchestrator |
| Q5 | Open the phone page with no connection to the gateway? | Not in this package; an already open page still saves requests. | Orchestrator |

The orchestrator also accepted: liveness from outbox pulls, no motion presets in the catalog, and waiting while the
image backend's lists load.

## Security

| Concern | Control |
|---|---|
| Catalog leaks paths or private text | Closed schema, count and length bounds, last path component only, scrubbed warning text, test that no path-like string crosses |
| Who can write or read the catalog | Written only through the sync listener (pinned TLS, sync secret); read only by an enrolled phone with `queue` |
| Deferred step as an unconfirmed queueing route | Same device, grant, item, digest and idempotency checks on gateway and PC; closed action list and params; admission only through `admit_phone_records` and `JobService.submit_njrs` |
| Stored catalog tampered on the phone | Ids are re-resolved on the PC against its own current list; unknown is `choice_unavailable` |
| Rendering | `textContent` only; CSP unchanged |

## Compatibility and rollout

Additive; `schema_version` unchanged; new gateway column and meta rows; one new health feature. Older PC with a new
gateway: no catalog, so no deferred button. New PC with an older gateway: no feature, so nothing new is sent. A PC rolled
back after publishing a catalog refuses `queue` as `invalid_record`, shown as "update StableNew on the PC". Deploy the
gateway first, then update the PC; the first catalog needs one session with Forge connected to list models.

## Package facts

- **Execution class:** Standard-high (security boundary; amends the N1 opt-in wording, approved under Q1; no queue,
  runner or compiler change).
- **Model recommendation:** Claude Code Opus 5.5 High; Codex GPT-6 Astra High.
- **Surface:** gateway `{phone_app,store,sync_app}.py`, `static/{app.js,app.css,index.html}`; PC
  `src/app/review_gateway_{protocol,actions,apply,sync,client,store}.py`, a small catalog module, and composition in
  `src/app/runtime_stack.py`; the schema. **Controller Surface Assessment:** no controller code changes.
- **Order:** after PHONE-FAST merges; same gateway files.
- **Docs:** `REVIEW_GATEWAY.md`, the schema, `STATUS.md`, `CODE_MAP.md`, and the one-line `AGENTS.md` section 2 and
  RG-100 S12 amendment (Q1). The PR body quotes the owner's "One tap, warnings after".

## Acceptance and validation plan

- Gateway (ASGI): catalog accept, bounds, scope and path refusals; `pc_seen_at`; `queue` step validation, idempotency,
  cancel before and after delivery, late `applied` after cancel; delete cancels; rework state.
- PC (fake gateway, recording `JobService`): catalog content and scrub, last non-empty list kept; each not-ready case
  leaves the record unanswered and later admits; each certain failure refuses; restart between admission and
  acknowledgement admits once; order; all pages followed.
- End to end: the real gateway app and the real sync worker in process; PC away, three requests, one cancelled, PC back
  with Forge down then up; jobs admitted once, in order, receipts visible to the phone.
- `tests/review_gateway_service`, `tests/app`, `tests/system`, `tests/tools`, `tools/ci/run_pr_gate.py`; Linux CI.
- Evidence will be hermetic. The live phone, deployed gateway and real Forge are not demonstrated.
