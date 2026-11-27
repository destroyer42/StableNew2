# Phone review gateway

Status: Living document. The following exist and are deployed and in use (proven live 2026-11-26):

- the gateway service (RG-110);
- the PC sync worker (RG-120);
- the gateway's Immich uploader (RG-130).

Phone actions: RG-140 slice 1 (fixes, more like this) is proven live. Slice 2 (another model, aspect ratio, prompt
tweak, Make Video, and "more like this" for whole recipes) and the inbox grouped by N5 batch (section 3.1) are tested
hermetically only. They have not been run on the live phone or with a real backend. See section 7 and
[RG-140](../../work_packages/RG-140_phone_actions.md).

Remote update and restart from the phone (LAUNCH-UPDATE-2) is built and tested hermetically only, against a fake
gateway, fake Git and the real update service with an injected updater; no real checkout was updated. See section 8.

Decisions, invariants and security controls: [RG-100](../../work_packages/RG-100_phone_review_gateway.md). Payloads:
[`stablenew.review-gateway-sync.v1`](../../schemas/stablenew.review-gateway-sync.v1.json). Deploy and operate:
[runbook](../../runbooks/review_gateway.md).

## 1. What it is

`services/review_gateway/` is a separate deployable: its own hash-pinned `requirements.txt`, its own virtual environment,
Python 3.11 or newer, and no import of `src/` (nor `src/` of it). It is a **projection and outbox**. StableNew's
repository and review evidence stay the only authorities; everything here can be rebuilt by publishing again, except
decisions the PC has not yet answered and Immich uploads still owed. Its one side effect of its own is the upload to
Immich after an explicit Keep (RG-100 invariant 5).

| Module | Owns |
|---|---|
| `contract.py` | Strict validation against the one schema file (whole-string patterns, time-zoned timestamps) |
| `store.py` | SQLite (WAL, `synchronous=FULL`): items, the decision outbox, offers, devices, retention |
| `media.py` | Content-addressed cache; a stored file is always complete and digest-verified |
| `upload_queue.py` | What Immich is still owed and the receipts for the PC, in the same SQLite file |
| `uploader.py`, `immich.py` | The upload worker (its own thread) and the only calls made to Immich |
| `phone_app.py` | Phone web app and API, loopback `:8443`, published by `tailscale serve` |
| `sync_app.py` | PC-facing API, one LAN address `:9443`, TLS, bearer sync secret |
| `config.py`, `server.py`, `__main__.py` | Settings and listener rules, the two servers, the admin CLI |
| `static/` | Bundled front end; no CDN, no inline script or style |

The gateway never compiles, admits or decides anything. It has no job, lifecycle, review-evidence or file-path concept.

## 2. Sync HTTP binding (v1)

The schema fixes payloads; this fixes how they travel. A change here must be agreed by both sides.

The port speaks TLS with a self-signed certificate made at install. The PC pins it by SHA-256 over its DER bytes (64
lowercase hex) before it sends anything; no CA or host name is checked. A non-loopback `sync_host` without a certificate
is refused at startup, so there is no plain-HTTP LAN mode. Every request carries `Authorization: Bearer <sync secret>`
(401 otherwise). JSON bodies are one schema payload, UTF-8, at most 64 KiB. Errors are `{"error": "<code>"}`.

| Method and path | Body | Success |
|---|---|---|
| `GET /sync/v1/health` | - | `{"status":"ok","schema_version":...,"features":[...]}` (rule 13) |
| `POST /sync/v1/items` | `item_manifest` | `{"status":"ready"\|"incomplete"\|"purged","missing":[sha256,...]}` |
| `HEAD /sync/v1/media/{sha256}` | - | 200 stored, 404 not |
| `PUT /sync/v1/media/{sha256}` | raw bytes | 201 stored, 200 already stored |
| `GET /sync/v1/outbox?cursor=&limit=` | - | `outbox_page` (limit default 200, max 500) |
| `POST /sync/v1/acknowledgements` | `acknowledgement` | `{"status":"recorded"\|"already_acknowledged"}`; 404 `unknown_record` |
| `POST /sync/v1/pairing-offers` | `pairing_offer` | `{"status":"accepted"}`; 409 `offer_conflict`; 422 `offer_expired` |
| `POST /sync/v1/device-revocations` | `device_revocation` | `{"status":"revoked"\|"unknown_device"}` |
| `POST /sync/v1/withdrawals` | `item_withdrawal` | `{"withdrawn": n}` (section 3.0) |
| `GET /sync/v1/immich-receipts?cursor=` | - | `immich_receipt_page` (section 5); 400 `invalid_cursor` |
| `PUT /sync/v1/pc-status` | `pc_status` | `{"status":"stored"}` (section 8). A PC treats 404 as "not offered yet". |

Rules:

1. Manifest before media: a digest no manifest declares is 409 `unknown_media`. Upload exactly the `missing` digests.
   `purged` means the gateway is finished with the item.
2. `item.sha256` equals `media.original.sha256` (else 422 `item_digest_mismatch`), so the phone decides on the bytes the
   PC re-checks. Each upload must match the declared size and SHA-256 (`size_mismatch`, `digest_mismatch`).
3. An item reaches the phone once every variant its manifest declares is stored.
4. Pairing: `code_sha256 = sha256((code_salt + code).encode("utf-8"))`, `code_salt` as the hex string sent, `code`
   uppercased with spaces and hyphens removed. An offer lives at most 5 minutes from receipt, works once and defaults to
   5 attempts; a wrong code counts against every live offer, and 20 failures in 10 minutes pause all pairing.
5. The outbox lists every unacknowledged record, oldest first; `next_cursor` is null on the last page. Start each cycle
   without a cursor and acknowledge each record.
6. A record the PC has never listed is withdrawn when the user re-decides. After listing, a new decision is a new record;
   apply in page order.
7. `enrolled_devices` lists all active devices on every page (a superset of "since the last acknowledgement"): upsert by
   `device_id`.
8. Decision records never pair `delete` with `favorite` or `needs_fix`; the PC still checks.
9. Authenticated uploads are read to the end before they are answered. A wrong secret is refused at once, so a client
   sending a large body may see a reset connection instead of the 401: check `health` first.
10. Uploads that would leave under 1 GiB free are refused with 507 `storage_unavailable`, so decisions can still be
    written. Sending an already stored digest again also shows any item that was left waiting for it.
11. Decisions a phone made before it was revoked stay in the outbox. A revoked device is absent from
    `enrolled_devices`; the PC decides whether to refuse its records (`revoked_device`).
12. Action requests (RG-140) are outbox records of kind `action_request`, listed in the same pages. They never become
    an item's decision. They never change `latest_record_id`, an Immich upload or the decision state, and they are
    never superseded. Their answer is the ordinary acknowledgement; its `receipt` may carry `choices`,
    `action_summary`, `job_ids` and `detail` (section 7).
13. `features` in the health reply lists the optional parts of v1 this gateway accepts. The PC sends an optional part
    only to a gateway that lists it, because an older gateway's schema refuses the whole payload. A gateway from before
    the list has no `features`, so it gets none of them. Today: `item_batch`, the manifest's `batch` (section 3.1); `item_parent`, the manifest's `parent`; `item_withdraw`,
    the withdrawals route (section 3.0).

13. Admin requests (LAUNCH-UPDATE-2) are outbox records of kind `admin_request` with no `target`, listed in the same
    pages. The PC leaves one unanswered while its update runs (it can take an hour to drain, then the app restarts),
    so it is listed again every cycle until the PC acknowledges it. Its receipt carries `update` (section 8).

`immich_receipt` has no place in `outbox_page`, so it has its own route (section 5).

## 3. Phone behavior

- Enrollment sets `rg_session` (`HttpOnly; Secure; SameSite=Strict`); only its SHA-256 is stored. Every request reads the
  device row, so revocation applies to the next request. Every data and media route needs an enrolled device with the
  `review` scope. Action requests also need the `queue` scope (D6), chosen per phone when it is paired (section 7).
- JSON APIs require `X-Review-Gateway: 1`. Every response carries `default-src 'self'` CSP with trusted types; metadata
  is put on screen with `textContent` only. Originals are `private, no-store`; derivatives `private, max-age=3600`.
- Inbox grouped by named batch, else by run folder, with counts (section 3.1); a group's grid; triage with Keep,
  Favorite, Delete buttons and swipes (right, up, left) and the six reason tags. A refused item counts as "to review"
  again.
- A decision is shown at once and kept on the phone until the gateway accepts it, resent with the same idempotency key.
  States: sending, waiting for PC, applied, refused (with the PC's reason).
- A decision the gateway will not take (for example an item it no longer has) moves to a "not saved" list on the phone,
  with Try again and Dismiss; it is never dropped silently. The unsent list is shared safely between tabs.
- The decision buttons and swipes stay off until the item has loaded. If it cannot load, the owner may retry or choose
  to decide without seeing it.

### 3.0 What the PC publishes (PHONE-FAST)

- **One-time withdrawal.** Frames and un-smoothed clips published before the rule above are withdrawn once: the PC
  classifies its publish ledger and posts `item_withdrawal` to a gateway listing `item_withdraw`. The gateway purges
  those items without recording a decision or touching Immich, and leaves any item with a decision or a request the
  PC has not refused. No PC file changes.

### 3.1 Inbox grouped by batch

A packs × models batch (N5) writes many run folders, but the owner queued it as one thing. Every N5 job records
`provenance.metadata.batch` (`batch_id`, `name`, `cell`).

- **PC.** For an image, the publisher reads the job id embedded in the file and that job's immutable snapshot in the
  job repository (read only; `job_batch_reader` in `src/app/review_gateway_publish.py`). It puts the batch in the
  manifest as `batch`: `batch_id`, `name` (up to 120 characters), and `cell` with the PromptPack name and the
  checkpoint file name. Paths are reduced to their last part, as for `display`. A batch with no name is left out,
  such as a Video Workflow or retry batch, which share the key. So is one that cannot be read: the item is then grouped
  by run folder and is never held back. Only a gateway that lists `item_batch` gets the field (section 2, rule 13).
- **Gateway.** `item.batch_id` and `item.batch` are stored with the item; a database made before them gains both
  columns when it is opened. `GET /api/runs` lists one group per named batch, with `run_id` `batch:<batch_id>`,
  `kind` `batch` and the batch `name`, and one group per run folder for everything else, with `kind` `run` and a null
  `name`. Groups are ordered by their newest item. `GET /api/runs/batch:<batch_id>` lists that batch's items across
  all its run folders, and `name`. A batched item appears under its batch only. Each item carries `batch`, which is
  null when it has none.
- **Phone.** A batch card shows the batch name and the word "Batch". The item's info panel shows the batch and its
  cell.
- **Compatibility.** An older PC sends no `batch`, so its items stay grouped by run folder. A newer PC sends nothing
  new to an older gateway. Items published before both sides were updated are not published again, so they keep
  their run folder groups.

### 3.2 Sent for rework, then compare (PHONE-FAST)

- **Rework** actions are those with one result to compare: Fix face, Fix hands, Fix both, Another model and Aspect
  ratio. More like this, Tweak prompt and Make video do not change the original.
- A queued rework (a `confirm`, or a one-step `queue`, that the PC has not refused and the phone has not cancelled)
  gives an undecided original the state `rework`: it counts as reviewed and can still be decided from the grid. A
  refusal returns it. The state is derived from the outbox and is not a decision.
- **PC.** Every admitted rework job is recorded with its original (`rework_jobs`). When an image of such a job is
  published, the lineage is kept (`rework_result`) and the manifest names `parent`, only to a gateway that lists
  `item_parent`.
- **Gateway.** A result sits beside its original: it takes the original's batch, or its run folder group when the
  original has no batch (so a kept result goes to the original's Immich album).
- **Phone.** While the original is on the gateway and not deleted, the result is shown beside it. Tap one to see it
  alone and tap or swipe to flip, then **Keep original** or **Keep rework**. The pick is two ordinary decisions: keep
  one, delete (archive) the other. The kept one keeps its Favorite mark and tags.

## 4. Retention (D4)

Hourly, and by `review-gateway-admin purge`. An item is purged only when it has no unanswered record and its latest
record was answered: 48 hours after an applied discard, 14 days after anything else (including a refusal). A kept
item is purged only after Immich has it: nothing is purged while an upload is owed or failing. Undecided items are never
purged, so the cache grows until they are decided (and until Immich is configured and reachable). An unanswered
action request also keeps the item's media. Purging removes cached media only (shared files stay
while another item needs them); the item row and records remain, so republishing does not bring it back. Abandoned
partial uploads and unreferenced files older than a day are swept.

## 5. Immich upload (D3)

**When.** A Keep (or Favorite) queues the upload in the same transaction as the decision, and it leaves 60 seconds later,
so a mis-tap can be taken back. It does **not** wait for the PC's acknowledgement: D3 requires uploads while the PC
sleeps, and the PC would otherwise be the one thing every keeper waits for. The record is still only a request
(invariant 4), so:

- a later Delete, or a PC refusal, cancels an upload that has not happened yet; a refused Delete leaves the earlier
  Keep in force;
- an upload already made stays in Immich. The gateway never deletes, trashes or restores anything there (its key
  cannot), so removing such an asset is done in Immich;
- an unanswered Keep from a phone that has since been revoked waits until the PC answers it.

**What.** The original file (never a phone rendition), named `<run_id>_<first 8 of sha256>.<ext>`, dated with the item's
`created_at`, into an album named exactly `run_id` (found by name, else created; made again if it was deleted in
Immich). Favorite sets Immich's favorite flag; taking Favorite back clears it only if the gateway set it, so a mark made
in Immich is left alone.

**Never twice.** Before sending anything the gateway asks Immich whether it has the bytes (`bulk-upload-check`, SHA-1),
and sends `x-immich-checksum` with the upload. A copy already there is reused and reported as `duplicate`. A copy that is
in Immich's trash is reported as failed (`immich_asset_trashed`) until it is restored there.

**Failures.** Review never waits for Immich: the worker holds no database transaction while it talks to it. Nothing is
given up.

| What happened | Retry | Receipt |
|---|---|---|
| Immich unreachable | All uploads pause, 30 s doubling to 15 min; other items then go first | none |
| Key, permission, redirect or version below 2 (`immich_unauthorized`, `immich_forbidden`, `immich_redirected`, `immich_unsupported_version`) | The same pause; resumes once fixed | `failed` at once |
| Immich error 429 or 5xx, or an upload cut off | That item, 30 s doubling to 15 min | `failed` from the fifth try |
| Immich refuses the item (`immich_rejected_<status>`, `immich_unsupported_media`, `immich_asset_trashed`, `immich_album_refused`) | That item, same backoff | `failed` at once |

**Receipts.** Each is the schema's `immich_receipt`, keyed by the decision record: `uploaded` (this gateway created the
asset), `duplicate` (it was already there, including a later record for the same item) or `failed` with `error_code`.
A later success replaces a failure. `GET /sync/v1/immich-receipts` answers
`{"schema_version", "type": "immich_receipt_page", "receipts": [...], "next_cursor"}`: up to 200 receipts added or
replaced after `cursor`, oldest first. `next_cursor` is the position after the page, and null only when the page is empty.
The cursor is opaque and names the database, so a rebuilt gateway is read from the start. The PC keeps the last cursor,
stores receipts only for items it published, and shows no Immich state yet.

**Settings and key (S5).** `immich_url` (http or https; redirects are not followed) and `immich_key_file` (default
`immich_api_key` beside the sync secret, mode 0600). Without both, keepers wait. The key is read for every upload, so a
new key needs no restart; it is never logged, stored in the database, passed in the environment or sent to the PC. It
needs exactly `asset.upload`, `asset.update`, `album.read`, `album.create` and `albumAsset.create`;
`review-gateway-admin immich-check` compares that with what the key has and changes nothing. Over plain http the key
crosses the LAN unencrypted; https needs a certificate the container trusts.

**Going forward only.** Keeps recorded before this version was installed are not uploaded, and their cached originals
are not purged.

## 6. Tests

`tests/review_gateway_service/` (hermetic: ASGI test client and temporary directories) runs in the ordinary census. Its
dependencies are exact pins in `requirements-dev.txt` that a test holds equal to the gateway's lock. Immich is a small
fake HTTP server on loopback (`fake_immich.py`) with the request and reply shapes read from Immich's v2.0.0 and v3.4.2
sources; no real Immich has been used.

## 7. Phone actions (RG-140 slices 1 and 2)

**What.** On an image, a phone with the `queue` grant can ask for one of eight actions:

- **Fix face**, **Fix hands** or **Fix both**: the executor's ADetailer face pass, hand pass, or both, on that exact
  image. The existing Review re-work compile writes the result under `Reprocess` and records the parent artifact.
- **More like this**: the same prompt, checkpoint and settings with 4 new seeds (1 to 8 if asked). A single-stage
  txt2img image goes through the History variation compiler. Any other image whose whole recipe can be re-run, such
  as a multi-stage chain or an N5 batch member, is a Replay with only the seed changed (slice 2). A recipe that does
  not start with txt2img, used a source image or makes several images is refused (`recipe_not_variable`).
- **Another model** (slice 2): the Review img2img re-work of that exact image through another checkpoint the PC
  lists. The recorded VAE is dropped and the desktop's current img2img settings apply.
- **Aspect ratio** (slice 2): Review's canvas extension (outpaint) to one of seven ratios. Every original pixel is
  kept; only the new space is generated, from the image's own prompt.
- **Tweak prompt** (slice 2): up to 200 characters of the owner's words appended to the recorded prompt, then the
  Review img2img re-work of the image.
- **Make video** (slice 2): the desktop's Make Video hand-off with the recommended approved workflow (today Wan2.2
  I2V-A14B 4-step) at its default length. The motion prompt is the owner's optional words, or else the image's own
  prompt.

`rerun_clip` and `continue_clip` (N8) stay reserved and are refused (`invalid_record`). They will call V1's shared
functions.

**Picking a checkpoint or a ratio (slice 2).** A prepare of `another_model` or `aspect_ratio` without
`params.choice` is answered `applied` with `receipt.choices`: up to 100 items of `id`, `label` and `current` (the
image's own). It has no summary and cannot be confirmed. The phone shows the list and prepares again with
`params.choice`. That summary's receipt repeats the choices with `selected`, so the phone offers **Change**. A
checkpoint id is a hash prefix of its name, never a path; labels are file names. `params.text` (tweak, video) is one
line of plain text, checked on the gateway and the PC, and only ever used as prompt text. The confirm repeats
neither: the PC confirms what the prepare it remembers chose.

**Queueing flag (owner decision 2026-11-26).** Queueing is a per-phone flag that is on by default.

- The pairing dialog's checkbox, "Allow queueing on phone", is ticked by default and adds `queue` to the offer's
  scopes.
- Phones paired before RG-140 are granted `queue` once, by a migration on each side, so they need no new pairing.
- The desktop's "Queueing on/off" button withdraws or restores one phone's queueing. The PC is the authority, so it
  refuses that phone's action requests (`not_granted`) while its review continues.
- The gateway is not told about a withdrawal yet, so the phone keeps showing the buttons.
- The gateway takes action requests only from a device whose scopes include `queue`.

**Two steps.** Each step is one outbox record, answered by an acknowledgement.

1. *Prepare* (`params.step = "prepare"`). The PC re-hashes the file and compiles exactly what it would queue, but
   admits nothing. It answers `applied` with `receipt.action_summary`, which holds:
   - a title and up to 8 PC-written lines;
   - the job count;
   - `queue_position` (`next` for fixes, `last` for every other action);
   - every N1 warning, with its why and fix;
   - `revision`, a fingerprint of everything shown plus the recipe, without job ids or seeds.

   Every warning text and subject is reduced to the last part of any path it names. The phone shows this screen
   (S12).
2. *Confirm* (`step = "confirm"`, `prepared_record`, `summary_revision`). The PC compiles again. It admits only if
   the fresh revision equals the shown one, then answers `applied` with `receipt.job_ids`. If the revision differs,
   it answers `refused`/`summary_changed` with the new summary. That refused record then counts as a prepare, so the
   phone can confirm it directly.

**Admission.** Through `admit_phone_records` (`src/app/site_phone_admission.py`), the same derivation the hosted
relay uses, into `JobService.submit_njrs`. Fixes go through `submit_reprocess_njrs`.

- Job ids are deterministic from the device and the prepare record, so a resent or repeated confirm never admits
  twice.
- The shown warnings are frozen in provenance as `accepted_warnings` with `surface: phone`.
- Fixes are admitted at `JobPriority.HIGH`, the queue's existing durable priority. They run after the current job and
  before NORMAL work, and never preempt it. Every other action is NORMAL.
- Results come back to the phone through ordinary publishing.

**Refusals.**

| Code | When |
|---|---|
| `not_granted` | The phone has no `queue` grant. |
| `revoked_device` | The phone was revoked. |
| `unknown_item`, `digest_mismatch` | The item is not one the PC published, or its file changed. |
| `invalid_record` | An action reserved for a later slice; from a PC older than slice 2, any slice-2 action (the phone then asks for a PC update). |
| `prepare_required` | The confirm names a prepare that is unknown, from another phone, for another item or action, or older than 30 minutes. |
| `summary_changed` | The summary changed since the phone showed it. |
| `action_unavailable` | The action cannot be prepared. `receipt.detail` gives a closed code: `adetailer_unavailable`, `detector_unavailable`, `model_family_refused`, `provenance_unverified`, `recipe_not_variable`, `source_changed`, `not_an_image`, `compile_failed` and others. Slice 2 adds `choice_unavailable` (the PC no longer lists that option), `no_change` (the image already has that checkpoint or ratio), `prompt_required` (no words and no recorded prompt), `size_unsupported` (the canvas would exceed 4,096 px) and `video_unavailable` (no approved Make Video workflow). Compiler text never crosses. |
| `admission_refused` | The job could not be admitted (for example `app_shutting_down`). |

An unexpected compiler error is answered as `compile_failed`, so it never stalls the records behind it.

**Limits (S4 as amended 2026-11-26).** There is no quota on phone work: phone and desktop are the same owner. What
remains guards against duplicates and malformed input, not against volume:

- Idempotency: the gateway is unique per device and key (a reused key is 409 `idempotency_conflict`). The PC ledger
  answers a re-sent record with its first outcome and admits once per prepare.
- Input bounds: one job per action and 1 to 8 seeds for "more like this"; 200 characters of words; 100 choices;
  JSON bodies of at most 64 KiB.
- A technical bound: at most 1,000 *unanswered* action requests per phone on the gateway (`too_many_pending`). It
  protects the outbox and the PC's next sync from a phone stuck resending in a loop. Answered requests never count.

**Phone API.**

| Route | Use |
|---|---|
| `POST /api/actions` | Body `{library_id, sha256, action, params, idempotency_key}`. Answers `{record_id, state}`, or 404 `unknown_item` or 422 `not_an_image`. |
| `GET /api/actions/{record_id}` | The phone's own request and the PC's answer (`state`, `reason_code`, `receipt`). |
| `GET /api/actions?library_id=&sha256=` | The phone's last 20 requests for one item. |

**Phone (slice 2).** The action row adds Another model, Aspect ratio, Tweak prompt and Make video. Tweak prompt and
Make video first ask for the words (required for the tweak, optional for the video). The two pickers first show the
PC's list. Everything is put on screen as text. The PC ledger's `action_prepares` gains `options` (a slice-2
prepare's choice and words) the first time it is opened.

The phone polls every 2 s while the summary sheet is open.

**Store migration.** A gateway database made before RG-140 gains `outbox.kind` (existing rows are `decision`) and
`outbox.created_at` the first time it is opened.

## 8. Remote update and restart (LAUNCH-UPDATE-2)

**What.** A phone with the `admin` grant shows the PC's commit, `origin/main` and the queue, and can ask the PC to
fast-forward its live checkout to that `origin/main` commit and restart StableNew. The PC does all of it through the
LAUNCH-UPDATE-1 service: preflight, wait for the running job, update, restart, roll back on a failed start. Design and
owner decisions D1–D10: [LAUNCH-UPDATE](../../work_packages/LAUNCH-UPDATE_remote_restart.md).

**Two switches (D2).** Both must be on:

- The `admin` grant. Only the desktop's **Pair for remote update** button issues it, after a confirmation, in an
  offer with `review`, `queue` (unless unticked) and `admin`. Normal pairing never includes it. A phone already paired
  replaces its pairing when it enters the new code; revoke the old entry in the desktop list. Revoking a phone removes
  the grant.
- **Allow remote update** in the desktop Update dialog, off by default. With it off the PC answers
  `remote_update_disabled`.

**Status (D3).** Each sync cycle the PC sends `pc_status` when it changed, and at least every 60 s: `HEAD`, the fetched
`origin/main`, how many commits that is ahead, when origin was last fetched, the queue state (`idle`, `running`,
`paused`) and how many jobs wait, the switch, whether an update is in progress and the last update's receipt. Commit
ids and counts only, no paths and no commit text. The PC fetches origin at most every 15 minutes for it, on its own
thread and never while an update is using Git, and again right after any update attempt. The gateway keeps the latest
one and shows it only to admin phones.

**Request.** The phone sends `{action: "update_and_restart", expected_sha, idempotency_key}` with the `origin/main` it
showed. The gateway refuses early:

| Code | When |
|---|---|
| 403 `not_granted` | The phone has no `admin` grant. |
| 401 `not_enrolled` | The phone is not enrolled or was revoked. |
| 422 `invalid_record` | Not 40 lowercase hex characters, another action, or another field. |
| 409 `status_changed` | Not the `origin/main` the PC last reported, or no status yet. |
| 409 `update_pending` | The PC already has this phone's previous request and has not answered it. |
| 409 `idempotency_conflict` | The key was used for a different request. |

A request the PC has not listed yet is replaced by a newer one (`superseded`).

**On the PC.** The record applier checks the device against the PC's own ledger (`revoked_device`, `not_granted`).
`src/app/live_update_remote.py` then runs `LiveUpdateService.update(source="remote")` on a worker thread. A request
first seen more than an hour after the tap is refused `request_expired`. Until the update has a receipt the record is
not acknowledged. After the restart, the new app answers it from `last_result.json`.

**Receipt.** `receipt.update` holds `status` (`applied`, `refused`, `already_current`), `reason_code`, `old_sha`,
`new_sha`, `target_sha` and `health`. Git and launcher text never cross; the desktop dialog still shows it. `health`
is the updater's start check of the new app:

- `confirmed`: the new app reported in;
- `unconfirmed`: the app was started but did not report within 180 s, so the phone says to check it;
- `exited`: a launch ended early (shown with `rolled_back`).

Refusal codes are the LAUNCH-UPDATE ones (`target_moved`, `environment_drift`, `busy_timeout`, `rolled_back` and the
others in `update_reason`), plus `request_expired` and `update_unavailable` (no update service on this PC).

**Phone API.**

| Route | Use |
|---|---|
| `GET /api/admin` | `{pc_status, received_at, now, requests}`: the PC's last status and the phone's last 5 update requests. |
| `POST /api/admin/updates` | Body `{action, expected_sha, idempotency_key}`. Answers `{record_id, state}`. |
| `GET /api/admin/updates/{record_id}` | One of the phone's own requests and the PC's answer. |

The inbox shows **Update the PC…** on an admin phone. The update screen asks for a confirmation and polls every 5 s
while a request is pending or an update is in progress.

**Rollout.** The changes are additive and `schema_version` is unchanged. An older PC refuses an `admin_request`
(`invalid_record`). An older gateway answers 404 to `pc_status`, so the PC sends nothing and asks again after 10 minutes,
and it refuses an offer with `admin` (the desktop's code then does not work). Install the gateway release first, then
update the PC app. SAFE-UPDATE adds the `not_github_signed` and `github_unavailable` codes the same way: an older
gateway rejects a status or receipt carrying them, so deploy the gateway before updating the PC.
