# Phone review gateway

Status: Living document. The gateway service (RG-110) and its Immich uploader (RG-130, tested against a fake Immich only)
exist; nothing is deployed. Of the PC sync worker (RG-120) only the Immich receipt pull is described here. Phone actions
(RG-140) are not built.

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
| `GET /sync/v1/health` | - | `{"status":"ok","schema_version":...}` |
| `POST /sync/v1/items` | `item_manifest` | `{"status":"ready"\|"incomplete"\|"purged","missing":[sha256,...]}` |
| `HEAD /sync/v1/media/{sha256}` | - | 200 stored, 404 not |
| `PUT /sync/v1/media/{sha256}` | raw bytes | 201 stored, 200 already stored |
| `GET /sync/v1/outbox?cursor=&limit=` | - | `outbox_page` (limit default 200, max 500) |
| `POST /sync/v1/acknowledgements` | `acknowledgement` | `{"status":"recorded"\|"already_acknowledged"}`; 404 `unknown_record` |
| `POST /sync/v1/pairing-offers` | `pairing_offer` | `{"status":"accepted"}`; 409 `offer_conflict`; 422 `offer_expired` |
| `POST /sync/v1/device-revocations` | `device_revocation` | `{"status":"revoked"\|"unknown_device"}` |
| `GET /sync/v1/immich-receipts?cursor=` | - | `immich_receipt_page` (section 5); 400 `invalid_cursor` |

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

`immich_receipt` has no place in `outbox_page`, so it has its own route (section 5).

## 3. Phone behavior

- Enrollment sets `rg_session` (`HttpOnly; Secure; SameSite=Strict`); only its SHA-256 is stored. Every request reads the
  device row, so revocation applies to the next request. Every data and media route needs an enrolled device with the
  `review` scope. Action requests are refused even with a `queue` grant (D6).
- JSON APIs require `X-Review-Gateway: 1`. Every response carries `default-src 'self'` CSP with trusted types; metadata
  is put on screen with `textContent` only. Originals are `private, no-store`; derivatives `private, max-age=3600`.
- Inbox grouped by run with counts; a run's grid; triage with Keep, Favorite, Delete buttons and swipes (right, up,
  left) and the six reason tags. A refused item counts as "to review" again.
- A decision is shown at once and kept on the phone until the gateway accepts it, resent with the same idempotency key.
  States: sending, waiting for PC, applied, refused (with the PC's reason).
- A decision the gateway will not take (for example an item it no longer has) moves to a "not saved" list on the phone,
  with Try again and Dismiss; it is never dropped silently. The unsent list is shared safely between tabs.
- The decision buttons and swipes stay off until the item has loaded. If it cannot load, the owner may retry or choose
  to decide without seeing it.

## 4. Retention (D4)

Hourly, and by `review-gateway-admin purge`. An item is purged only when it has no unanswered record and its latest
record was answered: 48 hours after an applied discard, 14 days after anything else (including a refusal). A kept
item is purged only after Immich has it: nothing is purged while an upload is owed or failing. Undecided items are never
purged, so the cache grows until they are decided (and until Immich is configured and reachable). Purging removes cached media only (shared files stay
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
