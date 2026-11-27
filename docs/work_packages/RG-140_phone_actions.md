# RG-140 — Phone actions from the review gateway (slices 1 and 2)

Status: **slice 1 implemented and proven live (2026-11-26). Slice 2 implemented with hermetic evidence only: no live
phone, real backend or generated output yet** (section "Slice 2" below). Contract and decisions:
[RG-100](RG-100_phone_review_gateway.md) (D6, D8, invariants 1–6, controls S4, S8, S12). Payloads:
[`stablenew.review-gateway-sync.v1`](../schemas/stablenew.review-gateway-sync.v1.json). Living document:
[`REVIEW_GATEWAY.md`](../Subsystems/ReviewGateway/REVIEW_GATEWAY.md).

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
  - A per-phone queueing flag, on by default and revocable from the desktop. Idempotency and receipts. No
    quota (owner decisions below).
  - Gateway routes, the gateway store, phone UI, the PC sync worker, PC admission, and the desktop pairing checkbox
    and queueing toggle.
  - Tests and documentation.
- **Explicit exclusions (later slices, each its own package):** another model, aspect ratio, prompt tweak, make video
  (all four done in slice 2, below), re-run a clip and continue a clip (N4/N8 remainder). The N8 video actions (re-run a clip with tweaks, continue a
  clip) must call the V1 facade, not build jobs themselves. V1 is
  [`V1_motion_controls.md`](V1_motion_controls.md) section 7: the intent snapshot, the tweak vocabulary and the Tk-free
  `continue_clip` facade. Slice 1's image actions do not need them. Also excluded:
  - live job progress on the phone after the receipt;
  - telling the gateway when the desktop withdraws a phone's queueing (a `device_grant` payload). Until then the
    phone still shows the action buttons, and the PC refuses the requests as `not_granted`;
  - "more like this" for multi-stage recipes (Q2, owner decision: a later slice; done in slice 2);
  - the touch-up lane on the AI worker (RG-145);
  - eval ratings on the phone (RG-150).

## Decisions taken in this package (A3 and A4 as amended by the owner; see the owner decisions below)

| # | Decision | Taken |
|---|---|---|
| A1 | How the phone gets the summary and warnings before queueing (S12) | **Prepare, then confirm.** The phone's `prepare` request makes the PC compile exactly what it would queue. The PC admits nothing and acknowledges with an `action_summary`: a title, PC-written lines, the job count, the queue position and the N1 warnings. The phone shows that screen. Queue sends a `confirm` naming the prepare record and the summary's revision. The PC compiles again. If the revision is unchanged, it admits and freezes the shown warnings into provenance as `surface: phone`. Otherwise it refuses with `summary_changed` and returns the new summary to show. The warnings are therefore always the ones the real compile produces. Nothing is computed per item at publish time. |
| A2 | Front of the queue (D8 first step) | **The existing durable priority.** Touch-ups (`fix_*`) are admitted with `SubmissionPolicy(priority=JobPriority.HIGH)`. `JobQueue` already orders by priority and then FIFO, and `JobRepository` persists the priority. So a touch-up runs after the current job and before NORMAL queued work, and never preempts. `more_like_this` is NORMAL and joins the back. No new queue semantics. |
| A3 | Queueing flag (D6 as amended) | **On by default, revocable.** The pairing dialog's checkbox, "Allow queueing on phone", is ticked by default and puts `queue` in the offer's scopes. Phones paired before RG-140 get `queue` once, through a migration on each side: the gateway's runs when its outbox gains the `kind` column, and the PC ledger's is guarded by a meta key. The owner's current phone therefore needs no new pairing. The desktop's "Queueing on/off" button withdraws or restores one phone's queueing, and the PC, as the authority, then refuses its action requests (`not_granted`). The gateway accepts action requests only from devices whose scopes include `queue`. |
| A4 | Limits (S4 as amended) | **No quota.** No per-phone or daily cap on admitted jobs, prepares or action requests, on the PC or the gateway. What remains are input and technical bounds, none of which is a quota: <br>• 1 to 8 seeds for `more_like_this` (4 by default), as an input bound; <br>• a 64 KiB JSON body, as before; <br>• at most 1,000 *unanswered* action requests per phone on the gateway (`too_many_pending`). This bound protects the outbox and the PC's next sync from a phone stuck resending in a loop; answered requests never count, and a whole 300-item batch fixed while the PC sleeps fits under it. |
| A5 | Idempotency (S8) | **Two layers.** (1) The gateway is unique per device and idempotency key, and a key reused for a different request is a 409. (2) The PC ledger answers a re-sent record with its first outcome, and it admits at most once per prepare record. A second confirm of the same prepare is a `duplicate` that carries the first receipt. |
| A6 | Admission path (invariant 6) | **One phone admission service.** `site_phone_admission.phone_records` is factored out of `PhoneQueueAdmission`, and the hosted relay and the gateway both use it. It derives the deterministic phone job ids and the `phone_submission` claim. Next to it, `admit_phone_records` admits a gateway request. It reads back an existing receipt instead of admitting twice, refuses while dispatch is fenced, freezes the accepted warnings with `surface: phone`, and crosses `JobService.submit_njrs` exactly once (fixes go through `submit_reprocess_njrs`). |
| A7 | Compilers reused | **Existing compilers only.** Fixes use `prepare_review_batch(stages=["adetailer"])` with a new `adetailer_passes` override that sets the face and hand pass flags after the recorded baseline. They inherit the N1b SDXL verdict (`target_verdict`) as pending warnings and refuse when no detector for the pass is listed. `more_like_this` takes the History source NJR through the follow-up service's verification, factored out as `verified_history_source`, then `HistoryVariationDraft.with_edits(seed=…)` and `compile_history_variation`. The jobs carry the model's shown N1 warning. |
| A8 | Schema | **Additive changes; `schema_version` unchanged.** The action enum gains `fix_both`. `action_request.params` is typed (`step`, `count`, `summary_revision`, `prepared_record`). Three reason codes are added: `summary_changed`, `action_unavailable` and `prepare_required`. The receipt gains `action_summary` and `detail`. Old peers never send or receive any of these: an RG-110 gateway refuses to create action records, and an RG-120 PC refuses them. |
| A9 | Paths and text (invariant 3, S7) | **No paths or free text cross.** Every warning text and subject is scrubbed of absolute paths before it crosses (only the last path component is kept). Compile errors cross only as closed `detail` codes, never as their message text (those can contain paths). The phone renders everything with `textContent`. |

## Owner decisions (2026-11-26, relayed by the orchestrator)

The owner's words: "I accept all except for RG-140 3. Caps per phone, per 24 hours, why have caps on phone? No cap on
queued work submitted from phone. Whether it's from the phone or the desktop, they both come from me, so why would I
limit myself. Not sure we need a separate queueing from phone permission, it's only me using this, but if needed turn
on queueing for phone, and 'Allow queueing on phone' should be on by default."

| # | Question | Decision |
|---|---|---|
| Q1 | Should "more like this" also go to the front of the queue? | **Accepted as proposed:** fixes run next (HIGH); "more like this" joins the back (NORMAL). |
| Q2 | Should "more like this" vary multi-stage recipes? | **Accepted as proposed:** slice 1 refuses them (`recipe_not_variable`); widening is a later slice. |
| Q3 | Which caps? | **No caps** on phone work (A4). Idempotency, one admission per prepare and the technical bounds stay. This overrides the caps in RG-100 S4. |
| Q4 | How is queueing granted? | **A per-phone flag, on by default.** Paired phones get it without pairing again, and the desktop can withdraw it (A3). This overrides "separate grant, off by default" in RG-100 D6. |

Device pairing, Tailscale membership, revocation and receipts remain the protection.

## Protocol (slice 1)

The phone's request (`POST /api/actions`) becomes an outbox record of kind `action_request`:

```json
{"action": "fix_face", "params": {"step": "prepare"}}
{"action": "more_like_this", "params": {"step": "prepare", "count": 4}}
{"action": "fix_face", "params": {"step": "confirm", "prepared_record": "<uuid>", "summary_revision": "<sha256>"}}
```

The PC answers the prepare step:

- `applied`, with `receipt.action_summary`;
- or `refused`, with one of `not_granted`, `revoked_device`, `unknown_item`, `digest_mismatch`, or
  `action_unavailable` plus a closed `receipt.detail`.

The PC answers the confirm step:

- `applied`, with `receipt.job_ids` and the final `action_summary`;
- `refused`, with `summary_changed` and the new `action_summary`;
- `refused`, with `prepare_required` (an unknown, other-device, other-item or expired prepare);
- `refused`, with `action_unavailable` or `admission_refused`;
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
| S4 (amended 2026-11-26) | Per-phone `queue` flag, on by default and revocable, checked on the gateway and the PC. Closed action list and typed params on both sides. No quota (owner decision); input and technical bounds only. Idempotency keys. Admission only through the phone admission function and `JobService.submit_njrs`. |
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
  changed summary, queueing withdrawn on the desktop, a video item, and an unavailable detector or recipe.
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

## Slice 2 (2026-11-26)

### Objective

- **Owner outcome:** four more one-tap asks on an image, through the same prepare and confirm flow: run it through
  another of the PC's checkpoints, change its aspect ratio, add a few words to its prompt, or make a video of it.
  "More like this" also works for multi-stage recipes and for images from an N5 batch.
- **In scope:** the actions `another_model`, `aspect_ratio`, `prompt_tweak` and `make_video`; "more like this" for
  whole recipes; the schema, the PC codec and compilers, the gateway's accepted list and the phone UI.
- **Explicit exclusions:** `rerun_clip` and `continue_clip` (N8) stay reserved and are refused as
  `invalid_record`. They will call V1's shared functions. Also excluded: resize-and-img2img for the aspect ratio, a
  free-form prompt editor, and per-model recipes for "another model".
- **Same package, separate commit:** the phone inbox grouped by N5 batch (`REVIEW_GATEWAY.md` section 3.1).

### Decisions taken in this slice (agent defaults; owner questions below)

| # | Decision | Taken |
|---|---|---|
| B1 | How the phone picks a model or a ratio | **The PC lists, the phone picks, then the normal prepare.** A prepare of `another_model` or `aspect_ratio` without `params.choice` is answered `applied` with `receipt.choices` (`action_choices`: up to 100 items of `id`, `label`, `current`). It has no summary, so it cannot be confirmed (`prepare_required`). The phone prepares again with `params.choice` set to one id. That summary's receipt carries the choices again, with `selected`, so the phone can change it. A checkpoint id is the first 16 hex characters of the SHA-256 of its name: stable, and never a path. Ratio ids are fixed: `1x1`, `4x5`, `2x3`, `9x16`, `5x4`, `3x2` and `16x9`. |
| B2 | Another model | **The Review img2img re-work of that exact image with the checkpoint swapped.** `prepare_review_batch` gains `model_override`. The recorded VAE is dropped, because it belongs to the recorded checkpoint, and every other recorded setting is kept. The desktop's current img2img settings, denoise included, fill the rest, as for any Review re-work. The checkpoint list is what the model picker has (`app_state.resources["models"]`). Choosing the image's own checkpoint is refused as `no_change`. N1: the checkpoint's model warning is shown (`shown_model_warnings`). |
| B3 | Aspect ratio | **Outpaint, not resize-and-img2img.** It uses Review's canvas extension (`prepare_outpaint_edit`), so every original pixel is kept and restored at finalization. Only the new space is generated, from the image's own recorded prompt. Space is added evenly on the two short sides and aligned to 8 (`extents_for_aspect`). An image within 2% of the ratio is `no_change`. A canvas beyond 4,096 px on a side is `size_unsupported`. A target that cannot outpaint is refused as `operation_unsupported` (N1b real block); an unclassified SDXL checkpoint runs with its warning. |
| B4 | Prompt tweak | **Words appended to the recorded prompt, then the Review img2img re-work** (`prompt_mode="append"`, the existing prompt delta). Same checkpoint. `params.text` is required: one line of plain text, 1 to 200 characters, no control characters. The PC collapses its whitespace, and a blank one is `prompt_required`. The words are shown back in the summary, scrubbed like every summary line. |
| B5 | Make Video | **The desktop's Make Video hand-off, compiled without the Video Workflow tab** (`gateway_make_video` in `src/app/site_phone_video.py`). It uses the recommended approved workflow (`make_video_default`, today Wan2.2 I2V-A14B 4-step) at its default frame count and default negative prompt, one clip, with a fresh seed at each step. The motion prompt is the optional `params.text`, or else the image's own recorded prompt; with neither it is `prompt_required`. The prepared source is frozen and verified as the desktop does it. No approved workflow is `video_unavailable`. |
| B6 | More like this, widened (Q2 follow-up) | **A single-stage txt2img image keeps slice 1's path** (the History variation compiler). **Any other image whose whole recipe can be re-run is a Replay with a new seed per job** (`ReplayIntent.seed`, `reseed_refusals`). That covers multi-stage chains such as txt2img → ADetailer → upscale, N5 batch members and Matrix-expanded jobs. Every frozen value is kept and only the seed changes. The parent's batch keys are archived under `replay_origin`, as for every Replay. The proof is of identity (`verified_recipe_source`): the embedded job id names a completed History job that recorded exactly this file, and the embedded NJR fingerprint matches its snapshot. A recipe that does not start with txt2img, used a source image, makes several images or is a Learning arm stays `recipe_not_variable`. |
| B7 | Priorities and limits | **Unchanged owner decisions.** Only the fixes are HIGH; the four new actions and "more like this" are NORMAL (`queue_position: last`). There is no quota. Input bounds: one job per action (1 to 8 for "more like this"), 200 characters of text and 100 choices. Queueing stays on by default. |
| B8 | Compatibility | **Additive schema, no version bump.** New: `params.choice` and `params.text`, with which actions and step they belong to; `choice_id`; `action_choices`; `receipt.choices`; and five detail codes (`choice_unavailable`, `no_change`, `prompt_required`, `size_unsupported`, `video_unavailable`). An older gateway refuses the new actions (422) and never forwards them, so it never sees `receipt.choices`. An older PC refuses them as `invalid_record`; the new phone then says the PC needs updating. The PC ledger's `action_prepares` gains an `options` column (the prepare's choice and text) when it is opened. |

### Owner questions (defaults are in force until answered)

1. Aspect ratio: is outpainting (add space, keep every pixel) the right default, or should a resize-and-img2img option
   be offered too?
2. Another model: should it apply the chosen checkpoint's saved recipe (N5 decision 3: sampler, steps, CFG, size,
   VAE) instead of the image's recorded settings? Today a cross-family swap, such as SDXL to FLUX, keeps SDXL settings.
3. Prompt tweak: img2img of the image with the words appended (any image, multi-stage included), or "Regenerate with
   Changes" from the recipe with the same seed (single-stage txt2img only)?
4. Make Video: is the image's own prompt a good default motion prompt, and is one clip at the workflow's default
   length right?
5. Should the result of a phone action on an N5 batch image appear in the same batch group on the phone? Today it
   does not: a re-work writes under `Reprocess` and a Replay starts a new submission.

### Acceptance and evidence (slice 2)

- Each new action can be prepared and confirmed on a published image. It is admitted once through `admit_phone_records`
  into `JobService.submit_njrs` at NORMAL priority, with the shown warnings frozen as `surface: phone`. A picker
  lists before it summarizes. A changed choice or text changes the revision. An unlisted choice, an unchanged model,
  blank words and a reserved clip action are refused with closed codes.
- "More like this" on a multi-stage N5 batch image re-runs the whole recipe with new seeds and archives the batch keys.
- Evidence mode: hermetic tests only, no qualification claim.
  - `tests/app/test_review_gateway_actions.py`: the flow, with a fake compiler and the real JobService and
    repository.
  - `tests/app/test_review_gateway_actions_slice2.py`: the application compiler against a recording host; the host
    against the real Review img2img and outpaint compilers; Make Video against the real workflow catalog and NJR
    builder.
  - `tests/pipeline/test_replay_reseed_rg140.py` and `tests/pipeline/test_outpaint_aspect_rg140.py`.
  - The protocol and the gateway's ASGI tests.
- Not demonstrated: the live phone, a real Forge img2img or outpaint, a real A14B run, and the live app.

### Execution class, model and surface

- Execution class: Standard-high (security boundary, within the approved RG-100 design; no queue-concurrency change).
  Model recommendation: Claude Code Opus 5.5 High; Codex GPT-6 Astra High.
- Start: 2026-11-26, branch `claude/rg-140-slice2-batch-inbox` from `origin/main` `dbbd1e87`. Coordinated with
  PR #458 (LAUNCH-UPDATE-2), which also extends the schema; the additions do not overlap.
- PC surface: `src/app/review_gateway_{protocol,actions,store}.py`, `src/app/site_phone_{preview_host,followup,video}.py`,
  `src/controller/review_batch_service.py` (one keyword), and `src/pipeline/{replay_njr_compiler,outpaint_canvas}.py`
  (two pure additions). Gateway surface: `store.py` (the accepted list) and `static/app.js`, `static/app.css`.
  Controllers: no ratcheted controller changes.
- Token-efficient validation: the gateway, protocol and action suites first, then `tests/system`, the PR gate,
  `tests/tools/test_code_map.py`, the ruff ratchets and the gateway's py311 ruff configuration.

## Completion report

Filled in at closeout in the PR body per `AGENTS.md` section 8.
