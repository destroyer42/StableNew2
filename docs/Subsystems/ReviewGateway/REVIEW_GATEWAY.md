# Phone review gateway

Status: Living document. The following exist and are deployed and in use (proven live 2026-11-26):

- the gateway service (RG-110);
- the PC sync worker (RG-120);
- the gateway's Immich uploader (RG-130).

Phone actions: RG-140 slice 1 (fixes, more like this) is proven live. Slice 2 (another model, aspect ratio, prompt
tweak, Make Video, and "more like this" for whole recipes) and the inbox grouped by N5 batch (section 3.1) are tested
hermetically only. They have not been run on the live phone or with a real backend. See section 7 and
[RG-140](../../work_packages/RG-140_phone_actions.md).

Requests made while the PC is away (RG-160, section 10) are tested hermetically only and are not deployed.

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
| `deferred.py` | RG-160: waiting requests, cancel, the PC's last-seen time and the choice catalog |
| `upload_queue.py` | What Immich is still owed and the receipts for the PC, in the same SQLite file |
| `timing_store.py`, `timing_routes.py` | Image open times, in a SQLite file of their own (section 11) |
| `uploader.py`, `immich.py` | The upload worker (its own thread) and the only calls made to Immich |
| `phone_app.py` | Phone web app and API, loopback `:8443`, published by `tailscale serve` |
| `sync_app.py` | PC-facing API, one LAN address `:9443`, TLS, bearer sync secret |
| `config.py`, `server.py`, `__main__.py` | Settings and listener rules, the two servers, the admin CLI |
| `static_files.py` | The closed table of page files and their version, read once at start |
| `static/` | Bundled front end as native ES modules, no build step; no CDN, no inline script or style |

The gateway never compiles, admits or decides anything. It has no job, lifecycle, review-evidence or file-path concept.

A second, staging gateway tries each merge before production (PHONE-CORE PS-1): its `environment_label` setting shows in
the phone header, and only the operator tools hold its settings; StableNew never syncs to it
([runbook](../../runbooks/review_gateway.md#staging-gateway-and-promotion)).

**The page's files** (PHONE-CORE PC-1a and PC-1b; design
`docs/work_packages/PHONE-CORE_installable_offline_phone_app.md`):

- `static/core/` holds what every screen shares (start-up, DOM, API, router, store, outbox, session, wording, slots
  and the bus). `static/features/<id>/` holds one screen or feature each, entered through its `feature.js`
  (`id`, `order`, `routes`, `start(core)`). `index.html` loads one module, `core/main.js`, which imports every feature
  named in `<meta name="rg-features">` before the first screen; every import is relative.
- A feature imports only `core/` and its own directory, and the core imports no feature. Features meet through named
  slots (`core/slots.js`: render, ask, claim), notifications (`core/bus.js`, no return values) and the route table
  (`core/router.js`). Slot contributions run in feature `order`. Adding a slot or a topic is a core change.
- Shared state is read and changed through functions (`core/store.js`, `core/router.js`, `core/session.js`).
- Caps: 300 lines a core file, 400 a feature file, checked by `test_static_rules.py`. No file is over its cap; an
  exception listed there may only shrink.
- At start the phone app reads `static/` once. Only `.js`, `.css`, `.png`, `.svg` and `.webmanifest` files are
  published. The version is 12 hex digits of a SHA-256 over their paths and digests, the `index.html` template,
  `sw.js` and the manifest.
- `GET /` is `index.html` with that version, the feature names and each feature's `<id>.css` written in, in feature
  `order` (`no-cache`).
- `GET /s/<version>/<path>` answers from the table only, `public, max-age=31536000, immutable`; any other version or
  path is 404. `sw.js` and the manifest are not in that table: each has one fixed address. `GET /s/<version>/files.json`
  lists each path with its SHA-256, and under `shell` the SHA-256 of `/` and of the manifest. The old `/static/...`
  addresses are gone.
- `GET /api/session` also returns `static_version` and `commit` (the release's `source.json`, or `dev`).
- `install.sh` copies the whole `static/` tree.

**The installable app** (PHONE-CORE PW-1):

- `GET /manifest.webmanifest`: start URL, scope and id are all `/` (an app already installed from this origin stays the
  same app), standalone, portrait; icons in `static/icons/`.
- `GET /sw.js` (`no-cache`) is `static/sw.js` behind one line, `const VERSION = "<v>", COMMIT = "<sha12>";`, so every
  deploy changes its bytes. Like the page, it needs no pairing.
- The worker stores the shell only, in `rg-shell-<v>`: every listed file, `/` and the manifest, each checked against
  its SHA-256 before any is stored. It answers those from that cache and leaves every other request alone: `/api/`,
  `/rating-media/`, `/media/` (originals included) are never answered by it or stored. With no gateway the app opens and
  says it is offline; nothing else works offline yet.
- `core/sw-client.js` registers it through the one Trusted Types policy, `rg-sw`, which accepts only `/sw.js`; the CSP
  adds `trusted-types rg-sw`. It asks for a new worker when the app comes back into view and every 30 minutes, and
  requests persistent storage.
- A new worker waits. The page shows "Update available · <commit>" with Reload, which sends any held decision, lets the
  worker in and reloads. Ignored, the new version starts after the app is fully closed. Nothing is forced.
- **Settings** (a button at the end of the home screen and of the "could not reach" screen; `#/settings`) shows the
  version and commit and offers **Repair this app**: unregister the worker, delete `rg-shell-*` and `rg-media-*`,
  reload. The pairing cookie, unsent work and settings stay. Without the gateway it asks first.

## 2. Sync HTTP binding (v1)

The schema fixes payloads; this fixes how they travel. A change here must be agreed by both sides.

The port speaks TLS with a self-signed certificate made at install. The PC pins it by SHA-256 over its DER bytes (64
lowercase hex) before it sends anything; no CA or host name is checked. A non-loopback `sync_host` without a certificate
is refused at startup, so there is no plain-HTTP LAN mode. Every request carries `Authorization: Bearer <sync secret>`
(401 otherwise). JSON bodies are one schema payload, UTF-8, at most 64 KiB (256 KiB for the rating payloads of
section 9). Errors are `{"error": "<code>"}`.

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
| `POST /sync/v1/item-sources` | `item_sources` | `{"labelled": n}` (section 3.4) |
| `POST /sync/v1/withdrawals` | `item_withdrawal` | `{"withdrawn": n}` (section 3.0) |
| `GET /sync/v1/immich-receipts?cursor=` | - | `immich_receipt_page` (section 5); 400 `invalid_cursor` |
| `PUT /sync/v1/pc-status` | `pc_status` | `{"status":"stored"}` (section 8). A PC treats 404 as "not offered yet". |
| `PUT /sync/v1/choice-catalog` | `choice_catalog` | `{"status":"stored"}` (section 10) |

The rating routes are in section 9, the open-times route in section 11.

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
   `device_id`. With the query `device_fields=last_seen_at` (PHONE-CORE PP-1) each device also carries `last_seen_at`,
   when it last made an authenticated request (to the hour; absent if it never has). Only a PC that asks gets the
   field, because an older PC refuses an unknown one and with it the page; an older gateway ignores the query. So
   the gateway and the app can be updated in either order.
8. Decision records never pair `delete` with `favorite` or `needs_fix`; the PC still checks.
9. Authenticated uploads are read to the end before they are answered. A wrong secret is refused at once, so a client
   sending a large body may see a reset connection instead of the 401: check `health` first.
10. Uploads that would leave under 1 GiB free are refused with 507 `storage_unavailable`, so decisions can still be
    written. Sending an already stored digest again also shows any item that was left waiting for it.
11. Decisions a phone made before it was revoked stay in the outbox. A revoked device is absent from
    `enrolled_devices`; the PC decides whether to refuse its records (`revoked_device`).
12. Action requests (RG-140) are outbox records of kind `action_request`, listed in the same pages. They never become
    an item's decision. They never change `latest_record_id`, an Immich upload or the decision state. Only a cancel
    or a Delete supersedes one (section 10). Their answer is the ordinary acknowledgement; its `receipt` may carry
    `choices`,
    `action_summary`, `job_ids` and `detail` (section 7).
13. `features` in the health reply lists the optional parts of v1 this gateway accepts. The PC sends an optional part
    only to a gateway that lists it, because an older gateway's schema refuses the whole payload. A gateway from before
    the list has no `features`, so it gets none of them. Today: `item_batch`, the manifest's `batch`
    (section 3.1); `item_parent`, the manifest's `parent`; `item_withdraw`, the withdrawals route (section 3.0).
    `item_source`, the manifest's `source` and the item-sources route (section 3.4);
    `item_input`, the manifest's `input` and `input_missing` (section 3.6); `deferred_actions`, the choice catalog
    (section 10); `item_info`, the manifest's `info` (section 3.7).

13. Admin requests (LAUNCH-UPDATE-2) are outbox records of kind `admin_request` with no `target`, listed in the same
    pages. The PC leaves one unanswered while its update runs (it can take an hour to drain, then the app restarts),
    so it is listed again every cycle until the PC acknowledges it. Its receipt carries `update` (section 8).

`immich_receipt` has no place in `outbox_page`, so it has its own route (section 5).

## 3. Phone behavior

- Enrollment sets `rg_session` (`HttpOnly; Secure; SameSite=Lax`, so links from other apps arrive paired; JSON APIs still require the custom header); only its SHA-256 is stored. Every request reads the
  device row, so revocation applies to the next request. Every data and media route needs an enrolled device with the
  `review` scope. Action requests also need the `queue` scope (D6), chosen per phone when it is paired (section 7).
- JSON APIs require `X-Review-Gateway: 1`. Every response carries `default-src 'self'` CSP with trusted types (one
  policy name, `rg-sw`, section 1); metadata is put on screen with `textContent` only. Originals are `private, no-store`; thumbnails and image renditions `private, max-age=604800, immutable`; other
  derivatives `private, max-age=3600`.
- Inbox grouped by named batch, else by run folder, with counts (section 3.1); a group's grid; triage with Keep,
  Favorite, Delete buttons and swipes (right, up, left) and the six reason tags. A refused item counts as "to review"
  again.
- A decision is shown at once and kept on the phone until the gateway accepts it, resent with the same idempotency key.
  States: sending, waiting for PC, applied, refused (with the PC's reason).
- A decision the gateway will not take (for example an item it no longer has) moves to a "not saved" list on the phone,
  with Try again and Dismiss; it is never dropped silently. The unsent list is shared safely between tabs.
- The decision buttons and swipes stay off until the item has loaded. If it cannot load, the owner may retry or choose
  to decide without seeing it.

- The phone prefetches the next 4 image renditions while triaging.

### 3.0 What the PC publishes (PHONE-FAST)

- **Only authoritative outputs** (`src/app/review_gateway_sources.py`). Finished images and clips are published from
  the job output folders and from any folder the owner made under Output. StableNew's working files are not: prepared
  video and driving-video sources, eval plan media, storyboard and continue-clip frames, temporary and hidden folders,
  the Photo Optimize workspace except an asset's results, and conditioning or sequence folders inside a run folder.
  An image under `movie_clips`, an image a video manifest lists as a frame or names as the clip's poster, and a
  retained un-smoothed clip are not published either. While a job runs, an image that may be one of its frames waits.
- **Nothing blocks the rest.** A row whose file is gone is recorded as `missing` and looked at again after a day; a row
  that fails for another reason is set aside for a while, longer each time (up to 10 minutes). A published item's
  ledger row is never overwritten.
- **Window.** The last 3 days, or back to when the publisher last caught up if that is older; never before the first
  window.
- **Rate.** Up to 8 items per cycle while idle; one item per 30 s while a job runs, with nothing transcoded. When a job
  completes, its new outputs publish at once even if the next job is already running.
- **Phone rendition.** Every image is sent with a WebP (JPEG where WebP is unavailable) of at most 1080 px on its long
  side, never enlarged. Images published before this get one a few at a time while the PC is idle.
- **No PC paths** (invariant 3). A video's original is sent as a bit-exact copy of its picture and sound without any
  container, stream or chapter metadata (no re-encode), and the mobile copy is made the same way. An image's original
  keeps its pixels and its prompt and settings text; fields of its embedded metadata that are only a path are removed,
  and a path inside longer text keeps its file name (`src/app/review_gateway_scrub.py`). The PC's files are never
  touched. A changed item is known to the gateway and Immich by the SHA-256 of the bytes sent; the PC maps a decision
  back to its file (`public_digest`). Media that cannot be cleaned is not sent. Items sent before this are not sent
  again, so they keep their metadata.
- **One-time withdrawal.** Frames, un-smoothed clips, working files and eval outputs (section 9) published before the
  rules above are withdrawn once: the PC
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

### 3.3 Triage and status (PHONE-FAST)

- **One stream.** "Review all" goes through everything still to review, across runs and batches: the group with the
  newest activity first, oldest first within it (`GET /api/runs/all`).
- **Undo.** The last decision (or a compare's pair) is held on the phone for 8 seconds and can be undone. The next
  decision, hiding or closing the page, or the time running out sends it. The gateway has no "undecide".
- **Run grid.** "Keep the rest" keeps what is left to review. "Delete this run" asks first, then deletes everything not
  kept; items sent for rework stay.
- **Status.** `GET /api/status` gives every review phone the PC's last reported queue (state and number queued, with
  when it arrived) and the cache size. A PC reports it only where live update is available. This is the one status
  route.

### 3.4 Review sections (PHONE-FAST)

The phone's home screen lists one folder per source of outputs: Pipeline runs, Learning runs, Reprocess and rework,
Movie clips, Test runs and Other. The PC derives the category from the top output folder and the kind (a learning
output stays under Learning; any other video is a movie clip) and sends only the category id (`source`, to a gateway
listing `item_source`). A rework result takes its original's section. Items published earlier are named once from the
PC's publish ledger (`item_sources`); until then they count as Other.

- `GET /api/sections?<id>=<stamp>` returns, per non-empty section, `total`, `unreviewed` and `new`. `new` counts what
  arrived since that stamp, the gateway's own time when this phone last opened the section; a section never opened
  counts what is left to review. The stamps and the badge choice (to review, or new) are kept on the phone.
- `GET /api/runs?source=<id>` lists one section's groups; `GET /api/runs/all:<id>` is its review stream.
- Evaluation sittings are not a section. They belong to the phone's rating tab (RG-170).

### 3.5 Viewing (PHONE-FAST, phone page only)

- **Compare.** A rework and its original as side by side, flip, or a before/after slider (original left of the divider).
  The choice is remembered on the phone.
- **Scroll.** The home, section and run lists return to where they were left.
- **Full resolution.** Double-tapping a picture loads the `original` variant with pinch zoom and pan; double-tapping
  returns to fit, and from fit closes it. A single tap keeps its meaning after a short wait. Videos are unchanged.

### 3.6 A desk reprocess beside its input (PHONE-FAST)

For an image whose job recorded an input image (reprocess started at the desk), the PC reads that path from the job's
immutable NJR snapshot, hashes the file and names the Output Library item with those bytes (`input`: ids only). A job
with several inputs is matched through the run's stage manifests. If no library item can be named, the manifest says
`input_missing`. Images published earlier are looked at once, a few at a time when the PC is idle.

The phone shows the same compare views, with "Keep both" beside the two picks. Unlike a phone rework, the result is
not regrouped: it stays in its own folder. A result whose input the gateway does not hold (never sent, deleted or
already purged) is shown alone and says "original not found". Retention keeps an original while a result made from it
is still to be judged.

### 3.7 More info (NAME-INFO)

Every item, and each side of a compare, has **More info**: the stage path (`txt2img → ADetailer`, `img2img`,
`clip (A14B) from <source model>`, `storyboard take (...)`), the short and full model or workflow name, prompt pack,
prompt number and variant, date and time, seed and batch name. The PC derives them when it publishes
(`src/review/output_info.py`) from the file's embedded metadata, its run manifest and the job's immutable snapshot,
all read only; a reprocess or clip job takes pack and prompt from the job of its input, at most four hops back. They
travel as the manifest's optional `info`, a closed list of bounded fields with paths reduced to their last part, only
to a gateway that lists `item_info`. Short names come from `src/pipeline/output_naming.py` and
`config/output_model_names.json`. An item published without `info` shows what it already has (model, batch, seed,
date); items already on the phone are not published again for it. The page's code is `static/features/info/moreinfo.js`.
A file named by the descriptive scheme (NAME-INFO slice 2) also sends its name (only to a gateway that lists
`item_file_name`), and Immich uploads under it; no other file name and no folder leaves the PC.

### 3.8 Pairing again from a QR code (PHONE-CORE PP-1)

- **PC.** The pairing dialog shows the code as text, as before. Once **Phone app address** is entered (the `https://`
  address phones open; only `https://host[:port]` is accepted, and nothing is built in), it also draws a QR of
  `<address>/#/pair/<code>`. The QR is drawn on screen only, goes with the code when it is used or expires, and is
  never saved or logged. Both pairing buttons show it. The address is kept in the PC's sync ledger and is removed by
  **Forget**.
- **Phone.** `#/pair/<code>` fills the code into the pairing form and at once rewrites that history entry to
  `#/pair`. Nothing pairs until **Pair this phone** is pressed. A phone that is already paired can pair again this way
  or go back.
- **Typing the code** works as before, with or without an address or a camera.
- **The code** keeps every property of section 2, rule 4: single use, five minutes, attempt limits. It travels in the
  URL fragment, which a browser sends to no server and in no `Referer`. The browser's own history may still hold the
  scanned address; by then the code is used, or dies within five minutes.
- **Device list.** The desktop shows **Last seen** for each phone, so a phone that lost its pairing can be told from
  the one in use and revoked. "not reported" means the gateway has not said (an older gateway, or a phone that has
  asked for nothing since it paired).

## 4. Retention (D4)

Hourly, and by `review-gateway-admin purge`. An item is purged only when it has no unanswered record and its latest
record was answered: 48 hours after an applied discard, 14 days after anything else (including a refusal). A kept
item is purged only after Immich has it: nothing is purged while an upload is owed or failing. An item nobody has decided is purged 30 days after
it arrived (`undecided_days`, 0 for never), counted again from any later action request, and never while a request
waits for the PC; the PC's file is not touched. A kept item waits for Immich to be configured and reachable. An
unanswered action request also keeps the item's media. A cache over `cache_warn_gib` (20 by default, 0 for never) is
reported to the phone and the log; nothing is refused or removed for it. Purging removes cached media only (shared files stay
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

`test_static_serving.py` covers the page-file table, its version, traversal refusal, the session fields, `/sw.js`,
the manifest and its icons, and the Trusted Types directive.
`test_open_timing.py` covers the open-times routes, their caps and refusals; `tests/phone_e2e/test_open_timing.py`
what the page sends and drops; `tests/tools/test_gate_report.py` the PC report.
`test_static_rules.py` reads the page's files: no markup sinks or inline handlers, every import resolves inside
`static/` to a name its target exports, no module exports a binding that changes, the import boundary, a `feature.js`
per feature and the size caps.

**The phone page in a real browser** (PHONE-CORE PC-0, `tests/phone_e2e/`):

- Headless Chromium (Playwright) with a Pixel-class viewport and real touch drives the page from `static/`, served by
  the real phone app on loopback.
- The PC is played through the real sync API: publish real PNG renditions, offer a pairing code, list the outbox,
  answer action prepares and confirms, report `pc_status`, register a rating task.
- The journeys cover:
  - pairing and the HttpOnly cookie, and revocation back to pairing;
  - swipes and tags, Undo, Keep the rest and Delete this run;
  - rework compare;
  - the two-step Fix face with its summary shown as text;
  - Not saved;
  - a decision made while unreachable, and a lost reply resent with the same key;
  - To rate;
  - the Update screen;
  - the installable shell (`test_installable.py`): the manifest and the controlling worker, opening with no gateway,
    a new version offered then taken by Reload, a damaged download refused, nothing but the shell ever stored, Repair
    and the Trusted Types limit. Headless Chromium gives no installability verdict, so that is checked on the phone.
- Journeys that send decisions assert what reached the gateway's outbox, not only the screen.
- The suite runs only with `STABLENEW_PHONE_E2E=1` and its own hash-pinned lock (`tests/phone_e2e/requirements-e2e.txt`),
  in the `phone-e2e` CI job. `full-suite` waits for that job and fails when it failed.
- The suite has a cheap contract test in the census (`test_phone_e2e_contract.py`) that keeps the lock and the wiring
  in step.
- Run it locally with the commands in `tests/phone_e2e/conftest.py`.

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

- **Continue clip** (V1-6, video items only, the one action a video has): the desktop's *Continue a clip*, from the
  clip's last generated frame, with the owner's optional words (else the clip's own prompt), its own length and a new
  seed. The PC finds the job by its recorded output path and queues one take in the clip's Storyboard, creating it when
  needed; preparing writes and queues nothing. A clip whose engine cannot make takes is offered as a Make Video of its
  last frame, and the summary says so. It is never left waiting for an away PC (no `queue` step). Update the gateway
  before the phone offers it. Code: `src/app/site_phone_continue.py`.

`rerun_clip` (N8) stays reserved and is refused (`invalid_record`). It will call V1's shared functions.

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

## 9. Ratings: the "To rate" tab (RG-170)

Built and tested hermetically; not deployed, and no sitting has been rated on the live phone.
[Design and decisions](../../work_packages/RG-170_phone_rating_tab.md).

**What.** **To rate**, a button above the review folders, lists every rating sitting and question the owner has been asked, with
its state: to rate, partly done, waiting for the PC, done, or not accepted with the reason. Kinds: A/B pairs, 1-5 and
yes/no scores per clip, an N-way ordering, and a pick-one question. Answers are saved per item as they are given.
**Submit** is explicit and final; the PC then writes the eval's own file and sends back the reveal.

**Navigation hook** (`static/features/rating/rating.js`). Its `entry(unavailable)` returns the full-width "To rate" button with its
open-count badge; the home screen puts it above the review folders. On a gateway without rating tasks it hides itself
and calls `unavailable`. The hash routes under `#/rate` belong to ratings. Evaluation runs appear only here, never
as a review folder.

**Register a sitting** on the PC (nothing else is needed on the gateway):

```powershell
python -m tools.review_gateway_rating pairs <blind folder> --task-id <id> --title "<title>"
python -m tools.review_gateway_rating scores <blind folder> --task-id <id> --title "<title>" --pick "<value>=<label>" --pick "<value>=<label>"
python -m tools.review_gateway_rating choice --task-id <id> --title "<title>" --question "<question>" --option "<value>=<label>" --option "<value>=<label>" --recommended <value>
python -m tools.review_gateway_rating register <rating set.json>
python -m tools.review_gateway_rating list
python -m tools.review_gateway_rating withdraw <id>
```

A registration is one `stablenew.rating-set.v1` file in `%LOCALAPPDATA%\StableNew\review-gateway\rating_tasks`
(`src/video/video_eval_rating_task.py`, `register_rating_task()` from code). The sync worker
(`src/app/review_gateway_ratings.py`) publishes it, re-sends it every 10 minutes, and withdraws it when the file is
removed. It encodes at most four clips per cycle and none while a job runs.

| Route | Use |
|---|---|
| `POST /sync/v1/rating-tasks` | `rating_task` to `{status, missing}`; 409 `task_conflict` when a used task id changes shape |
| `PUT`/`HEAD /sync/v1/rating-media/{sha256}` | rating clip and picture bytes, stored in `<media_dir>/rating/` |
| `GET /sync/v1/rating-submissions` | `rating_submission_page`: submitted, unanswered ratings |
| `POST /sync/v1/rating-acknowledgements` | `rating_acknowledgement`: applied (with reveal tables) or refused |
| `GET /api/rating/tasks`, `GET /api/rating/tasks/{id}` | the phone's list and one task with its saved answers |
| `POST /api/rating/tasks/{id}/answers`, `.../submit` | save one item; submit all |
| `GET /rating-media/{id}/{sha256}` | a task's media, enrolled `review` phones only |

Rules:

1. Only ids, text and media leave the PC: no path, file name, case id or key file. Clips are re-encoded (H.264 CRF 18,
   at most 1280 px) and pictures re-saved with **all metadata dropped**; StableNew clips otherwise carry their workflow,
   backend and a PC path, which would also unblind the rating.
2. A submission is a request. The PC refuses it from an unpaired or revoked phone, checks every answer again, and writes
   all or nothing: a different value already in the eval's file refuses it (`already_rated`) and the task reopens. The
   key file must give an arm for every clip of every item: registration refuses it otherwise, such a set is not
   published, and a key that breaks later refuses the submission with nothing written.
3. Gateway retention: a finished task and its media go 14 days after the PC answered, a withdrawn one after 48 hours;
   an unanswered submission is never purged.
4. A gateway lists `rating_tasks` in health; a PC sends nothing about ratings to one that does not. Deploy the gateway
   first, then update the PC.

**Eval outputs are not review items.** The publisher skips anything under `video_eval` and any output whose run
manifest names a job an eval's `run.json` lists. Clips published before that rule are withdrawn by the one-time
withdrawal of section 3.0, which runs once more for this rule.

## 10. Requests made while the PC is away (RG-160)

Built and tested hermetically only: not deployed, not run on the live phone or with a real backend. Design and owner
answers: [RG-160](../../work_packages/RG-160_offline_phone_queue.md).

**What.** With the PC away, a phone with the `queue` grant picks one of the eight actions of section 7, with the same
choices, and taps **Queue when the PC is back**. One tap queues; there is no summary first, and the warnings are listed
on the receipt afterwards (owner decision 2026-11-27). A request never expires.

**Choice catalog.** `PUT /sync/v1/choice-catalog` (`$defs/choice_catalog`), sent only to a gateway listing
`deferred_actions`, when its content changes, after a reconnect and every 10 minutes. It holds what the phone can choose
today: checkpoints (hashed id, file name, warnings), the warning texts, the aspect ratios, whether a Make Video
workflow is approved and its name, and when the model list was read. No paths; at most 60 KiB. A PC without a connected
image backend repeats the last non-empty model list. The gateway shows it only to a `queue` phone and decides nothing
from it. Without a catalog the phone behaves as before.

**When the phone offers it.** At once when the PC's last outbox request is older than 3 minutes or the gateway cannot be
reached; after 10 s without an answer to a prepare or confirm; and when a prepare is refused only because Forge's lists
are not loaded. A confirm is turned into a waiting request only if the PC never received it.

**On the PC.** Step `queue` of the same outbox record, with the same grant, item and digest checks. The record id is the
admission receipt, so job ids are deterministic and a restart before the answer never admits twice. While the detector
list (fixes) or model list (another model) is not loaded, or the app is busy or closing, the record is left unanswered
and asked again; a request that is ready is not held up by one that waits. Otherwise it is compiled against what is true
then, admitted at the priorities of section 7 with the warnings frozen as accepted on the phone, or refused with the
same codes. The outbox is read to its last page every cycle.

**Phone API.**

| Route | Use |
|---|---|
| `GET /api/status` | also `pc_seen_at`, `image_backend_ready` and this phone's `waiting` count |
| `GET /api/catalog` | the latest catalog and when it arrived |
| `GET /api/requests` | this phone's waiting requests, and those answered or cancelled in the last 7 days |
| `POST /api/actions/{record_id}/cancel` | `cancelled`, `cancel_sent` (the PC had it), `delivered` (a confirm the PC has is left alone), or the answer already given |

**Cancel and Delete.** A cancelled record leaves the outbox. If the PC had received it and answers `applied` anyway, the
gateway records that and the row reads "Queued (too late to cancel)". Deleting an image cancels what waits for it; the
phone warns first, including when "Keep rework" would delete an original with a request waiting.

**Phone offline.** A page already open saves the request in the same local list as unsent decisions, in order, and sends
it with the same idempotency key; the catalog is kept on the phone. Opening the page with no connection is not covered.
A request refused as `too_many_pending` moves to the "not saved" list so it does not hold up later decisions.

**Rollout.** Deploy the gateway first, then update the PC. The first catalog needs one session with Forge connected to
list checkpoints. A gateway database gains `outbox.cancelled_at` and a `pc_note` table when opened.

## 11. Image open times (PHONE-FAST gate)

Built and tested hermetically only: not deployed, and no time from a real phone yet. It measures the gate "median image
open time on the phone". There is no figure from before PHONE-FAST; only sizes are known for then.

**What is timed.** From an item becoming current in triage or compare to its `preview` rendition's `load` event. Where
the bytes came from is read from the browser's resource timing: `network` (asked for at this view), `prefetch` (fetched
ahead), `cache` (seen before, or answered by the browser's cache) or `unknown`. Not timed: videos, items without a
rendition, the grid and the full-resolution viewer, a load that fails, a page that goes hidden while loading, and a view
left before its image loaded (so the figures lean slightly towards faster views).

**What is sent.** `features/timing/` only watches: it is asked first on the `item.view` slot and never claims it. It
sends `POST /api/timings` (same session, `review` scope and header as every phone API):
`{"idempotency_key": <16-128 of A-Za-z0-9_->, "samples": [{"ms": 0-600000, "source": ..., "bytes": 0-104857600 or
null}]}`, 1 to 100 samples, body at most 16 KiB. Any other field or value refuses the whole batch (422
`invalid_record`). The answer is `{"state": "stored"|"duplicate"}`. A batch goes 45 seconds after the first time waiting
for it, and when the page is left (`pagehide`, a `keepalive` request). Offline, it is dropped; a network or server error
is retried once with the same key. There is no outbox, and nothing is kept on the phone.

**What is stored.** `timing.sqlite3` in the data directory, one row per view: when the gateway received it, the device
id, `ms`, `source`, `bytes`, and the batch key (so a resent batch is stored once). No item id, path, prompt, address or
device name. Rows older than 30 days or beyond the newest 100,000 are removed (on insert and by the hourly retention).
It is not part of `gateway.sqlite3`, which this adds nothing to.

**PC read.** `GET /sync/v1/open-timings?cursor=` behind the sync secret:
`{"rows": [{"at", "ms", "source", "bytes"}], "next_cursor": n|null}`, oldest first, 5,000 a page, without device ids.
400 `invalid_cursor`. It is not part of the sync schema file; a PC treats 404 as "not offered yet".

**Report.** `python -m tools.gate_report` (`--json`) on the PC, read only: per local day and overall, the views, median
and p90 milliseconds, the cache-hit share (`cache` and `prefetch`, of the views whose source is known), the count of each
source and the median rendition size. It uses the gateway settings of this Windows user and no running app.
