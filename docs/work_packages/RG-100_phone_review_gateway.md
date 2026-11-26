# RG-100 — Phone Review Gateway: decisions and contract (RG-110 to RG-150)

Status: **approved design, not built.** Owner decisions D1–D9 recorded 2026-11-25. This package is docs only: the decision
record, the architecture contract for the slices that follow, and the versioned sync schema
[`docs/schemas/stablenew.review-gateway-sync.v1.json`](../schemas/stablenew.review-gateway-sync.v1.json). Each later
slice is its own work package in a fresh session and worktree.

## Objective

- **Owner outcome:** after a walk-away batch (usually under 300 items), review every image and clip on the phone, at home
  or away, with no manual copying. Gestures: Keep, Delete, Favorite, optional reason tags (no stars). Every keeper lands in
  Immich. Later: one-tap follow-ups (fix face or hands, more like this, another model, aspect, prompt tweak, make video,
  re-run or continue a clip), with touch-ups able to run on a second GPU without waiting behind the desktop queue.
- **Why now:** today the owner copies outputs to the phone by hand (Windows Phone Link folder sharing), reviews nearly all of
  them there, deletes the bad ones and uploads keepers to Immich manually. None of those judgments reach StableNew. The
  hosted Operator Site relay is slow by construction: the PC polls the hosted relay every 4 s, serves one call at a time,
  and every response crosses the internet twice through hosted storage (`src/app/site_phone_connector.py`,
  `_POLL_INTERVAL = 4.0`, "One polling actor and at most one native call").
- **In scope for RG-100:** this document, the sync schema, a short approved-design paragraph in
  `docs/ARCHITECTURE_v2.6.md` section 11, and the Operator Site line in `STATUS.md`.
- **Explicit exclusions for RG-100:** no code, no container, no Proxmox change (the Proxmox and Tailscale preparation runs as
  an owner-guided session and records its own runbook).

## Owner decisions (2026-11-25)

| # | Decision | Recorded answer |
|---|---|---|
| D1 | A new deployable component and where it lives. | New top-level `services/review_gateway/` with its own pinned requirements, container build and tests. Not app logic in `tools/` or `scripts/`. |
| D2 | Architecture option. | Option C: a gateway that is a **projection and outbox only**. The PC syncs outbound; the PC accepts no inbound connection. StableNew's repository and review evidence stay the only authorities. |
| D3 | Who uploads to Immich. | The gateway, on Keep. It works while the PC sleeps and keeps the Immich key off Windows. |
| D4 | Cache retention. | Cache originals. Keep cached media 14 days after the PC acknowledges the decision; purge discards after a 48-hour undo window. |
| D5 | Phone sign-in. | Gateway device enrollment from a single-use pairing code shown on the StableNew desktop. Tailscale membership (D9) is the outer layer. |
| D6 | MVP phone permissions. | Review only (Keep, Delete, Favorite, tags). Queueing actions arrive in RG-140 under a separate per-device grant. |
| D7 | Same container as the AI worker? | **Separate** unprivileged container on the same Proxmox host, with no GPU. A gateway compromise must not reach models or the GPU. |
| D8 | A touch-up lane on the AI worker's 8 GB RTX 4070. | **Approved.** A second lane in the one queue whose runner dispatches to Forge in the AI-worker container through the PC's SSH forward. Built as RG-145 after RG-140 and N9 (queue-lock responsiveness). First step: phone touch-ups take front-of-queue priority on the existing lane. |
| D9 | Phone access from outside the house. | Tailscale: the Tailscale app on the phone, Tailscale plus `tailscale serve` (private HTTPS name and certificate) inside the gateway container. No public exposure and no router port forward. Fallback if ever needed: Cloudflare Tunnel with Cloudflare Access (owner decision at that time). |

## Architecture contract

### Components

| Component | Owns | Never owns |
|---|---|---|
| **Review gateway** (`services/review_gateway/`, own container) | The phone web app (static, bundled, no CDN); the phone API (inbox by run, item view, decisions, tags, later action requests); device enrollment and sessions; a cache of previews and originals; a durable outbox of decisions and requests with receipts; the Immich uploader. | Jobs, lifecycle, review evidence, any PC file path. It never compiles, admits or decides anything; it records what the phone asked for. |
| **Sync worker** (new StableNew background service under `src/app/`, registered with `src/utils/thread_registry.py`, no Tk) | **Publish:** reads the Output Library index (`src/app/site_library_index.py`, a separate cache, not the job database) and sends each new item's manifest, 320 px and 1080 px previews, mobile video and original, idempotent by SHA-256. **Pull:** fetches pending outbox records, validates them as strictly as `_desktop_call` in `src/app/site_phone_connector.py`, applies them through native services. **Acknowledge:** returns an authoritative receipt per record. | Any second admission or review path. Action requests go through `PhoneQueueAdmission` (`src/app/site_phone_admission.py`) into `JobService.submit_njrs`. |
| **Native services** (existing, extended) | Review evidence (Retain; a new Favorite flag); the archive (a new phone Discard, resolved by library id and digest, through `src/review/archive.py`); admission, receipts and lineage. | Transport. |

### Data flow and network

- PC → gateway sync port (planned 9443) over the LAN, PC-initiated only: publish media and manifests, list outbox
  records, post acknowledgements. Reachable only from the PC's LAN address (Proxmox firewall) and authenticated with a
  per-installation sync secret (DPAPI on Windows, a 0600 secret file in the container).
- Bootstrap: installing the gateway generates the sync secret once; the owner enters it in StableNew's desktop pairing
  settings, which store it with DPAPI. Phone enrollment then works without touching the container: the desktop creates a
  single-use code, shows it, and pushes only a salted hash as a `pairing_offer`; the gateway enforces expiry and attempt
  caps and reports enrolled devices back in the next `outbox_page` so the desktop can list and revoke them.
- Phone → gateway phone port over the tailnet only (`tailscale serve` → localhost). The sync API is never served there.
- Gateway → Immich on TrueNAS over the LAN, the only outbound application connection.
- PC → AI worker (D8, RG-145): the existing operator-managed SSH forward gains `-L 127.0.0.1:17860:127.0.0.1:7860`.
  The gateway container has no route to the AI worker.

### Decision semantics

- **Keep:** StableNew records Retain. The gateway uploads the original to Immich (an album per output run) and reports
  the Immich receipt back; StableNew stores it with the review evidence.
- **Favorite:** Keep, plus Immich's favorite flag, plus a favorite flag in the review evidence. Learning may weight it (N10).
- **Delete:** StableNew moves the file to the central review archive under the Output root (digest re-checked immediately
  before the move); never a delete, never sent to Immich, undoable on the desktop. The gateway purges its copy after the
  undo window (D4).
- **Reason tags** (`face`, `hands`, `anatomy`, `artifact`, `prompt_miss`, and `needs_fix` on Keep) are stored with the
  decision and feed passive Learning.
- **Grouping:** by output run folder first; by the batch identity from N5 once it exists.
- **PC offline:** review continues; decisions wait in the outbox; keepers still reach Immich. A PC refusal (digest
  mismatch, revoked device, unknown item) is shown on the phone and the desktop.

### Invariants (acceptance-binding for every slice)

1. No inbound listener on the PC; every PC connection is outbound.
2. No second queue, history, review or admission authority. Gateway state is rebuildable from the PC by re-publishing.
3. Items are referenced by library id plus SHA-256, never by path. No PC path crosses the sync boundary in either direction.
4. Outbox records are requests: they stay pending until StableNew acknowledges them, and the PC may refuse any of them.
5. The only side effect the gateway owns is the idempotent Immich upload following an explicit Keep.
6. No phone-originated job reaches the runner except through `JobService.submit_njrs` (a test asserts this).

### Touch-up lane (D8, RG-145)

Evidence on `origin/main` at RG-100 start: `JobQueue.claim_next_job` claims "the next runnable job for the single-node
worker"; `pause_running_job` and `cancel_running_job` assume one running job; `src/queue/single_node_runner.py`
(`SingleNodeJobRunner`) runs one job at a time; `src/api/client.py` takes one `base_url` (default
`http://127.0.0.1:7860`). RG-145 therefore needs: a lane identity on the job recorded in provenance; lane-filtered
claiming (the eligibility skip in `_pop_next_eligible_locked` is the natural hook); a second runner thread; pause and
cancel by job id; handler client selection by lane; a pre-dispatch check by file hash that the checkpoint, LoRAs and
embeddings are present on the worker and that the family fits 8 GB, falling back to the desktop lane with a warning
(N1). The worker GPU is one resource shared with Ollama (`OLLAMA_MAX_LOADED_MODELS=1`): touch-ups and AI Assist calls
take turns. Video and Flux-class models stay on the desktop.

RG-145 changes queue concurrency and the "single-node, same-process" wording in `AGENTS.md` section 2 and
`docs/ARCHITECTURE_v2.6.md` sections 1 and 5. D8 approves the direction; RG-145 must present the exact amended invariant
text for owner approval before implementation.

## Security controls (acceptance criteria)

Severity reflects D9 (tailnet-only phone access). The controls stay required regardless, because a tailnet device can be
lost or compromised and a fallback could publish the route.

| ID | Threat | Required control |
|---|---|---|
| S1 | Unauthenticated access to media or actions | Every phone API and media route requires an enrolled device session; enrollment by a single-use, 5-minute, attempt-capped code shown on the desktop; device tokens stored hashed and revocable; cookies `HttpOnly; Secure; SameSite=Strict`. |
| S2 | Sync API exposed | Separate port, never served on the tailnet or any proxy; Proxmox firewall allows only the PC; per-installation sync secret; a test asserts the phone app refuses every sync path. |
| S3 | Forged decisions driving file changes | Closed action list on the PC; id plus SHA-256 only; Discard resolved under the granted Output root through `src/review/archive.py`, refusing symbolic links, using the `open_scoped` pattern (`src/app/site_media_files.py`); digest re-checked before the move; move, never delete. |
| S4 | Job flooding or abusive actions | Per-device scopes (review-only default; queueing a separate grant); admission through `PhoneQueueAdmission` with typed override validation; per-request and daily caps; idempotency keys and receipts; prompt tweaks length-bounded and compiled normally. |
| S5 | Immich key leak | Key only in the gateway as a 0600 secret file; never in the image, environment dumps, logs or StableNew; narrowest permissions the installed Immich supports (upload, album add, favorite). Stop and ask if the installed version cannot scope keys. |
| S6 | Media at rest | Retention per D4; dedicated container (D7); id-based authenticated routes; `Cache-Control: private, no-store` on originals; no directory listing. |
| S7 | Stored script injection from prompt text, model names, filenames | Strict CSP (`default-src 'self'`, no inline script); metadata rendered as text only; JSON APIs require a custom request header. |
| S8 | Replayed or duplicated actions | Outbox until acknowledged; idempotency keys; PC receipts authoritative and shown on the phone. |
| S9 | Lost decisions | Gateway SQLite in WAL mode with `synchronous=FULL`; nothing purged before acknowledgement; the PC acts only on validated records, never on gateway state alone. |
| S10 | Container supply chain | Base image pinned by digest; hash-pinned requirements; bundled front-end assets; reproducible build; minimal dependency set. |
| S11 | Revocation while the PC is offline | Revocation on the gateway itself as well as from the desktop; revoked devices refused within one request. |
| S12 | Experimental work run from the phone without the warning | With N1, the phone summary shows the desktop's warnings and the accepted warning is recorded in provenance. |
| S13 | Forge on the AI worker reached by anything but the PC (RG-145) | Forge bound to `127.0.0.1` inside the container, without `--listen` or insecure extension access; reachable only through the PC's SSH forward as `ai-tunnel`, with that key limited to the Ollama and Forge ports; the gateway container has no route to the worker; Forge receives only compiled NJR stages, never raw phone payloads. |

Existing-code findings this work touches: prompt text is logged at INFO into `logs/stablenew.log.jsonl` (sync logging
must not add prompts or secrets; N11 moves prompt text to DEBUG); `src/app/site_native_review.py` deliberately refuses
Discard (`review_archive_required`), which the new digest-bound phone Discard replaces for the gateway path only; the
hosted relay keeps its Site-wide credential until it is retired (RG-150, owner decision).

## Delivery slices

| Slice | Scope | Depends on | Class / model recommendation |
|---|---|---|---|
| RG-100 | This contract and the sync schema. Docs only. | Owner decisions | Architectural docs; Claude Code Opus 5.5 High; Codex GPT-6 Astra High |
| RG-110 | Gateway MVP in `services/review_gateway/`: container build (pinned), enrollment and sessions, sync API, phone web app (inbox by run, tap/swipe triage, video playback, Keep/Delete/Favorite, tags), SQLite outbox, retention job, hermetic tests with an ASGI test client. | RG-100 | Standard within a known design; Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High |
| RG-120 | StableNew sync worker: publish from the Library index, pull/validate/apply/acknowledge, phone Discard to archive, Favorite flag, desktop pair/revoke/status, tests against a fake gateway. | RG-100; parallel with RG-110 | Architectural (security boundary); Claude Code Opus 5.5 High; Codex GPT-6 Astra High |
| RG-130 | Immich uploader in the gateway: upload on Keep, album per run, favorite flag, checksum dedupe, receipts to the PC. | RG-110, RG-120 | Standard; Sonnet 5.5 High; GPT-6.1 Sol High |
| RG-140 | Phone actions (N4, N8) as outbox requests compiled and admitted on the PC, with a one-screen summary and receipts; phone touch-ups take front-of-queue priority. | RG-120; N1 for warnings | Standard-high; Opus 5.5 High; GPT-6 Astra High |
| RG-145 | Touch-up lane on the AI worker (D8). Changes queue concurrency; needs owner approval of the amended invariant text. | RG-140, N9 | Architectural; Opus 5.5 High; GPT-6 Astra High |
| RG-150 | Eval ratings on the phone (N15); retire the hosted relay once nothing needs it (owner decision). | RG-140 | Standard; Sonnet 5.5 High; GPT-6.1 Sol High |

The sync schema is the contract between RG-110 and RG-120 so they can be built in parallel. A change to it bumps
`schema_version`; both slices must agree before either merges.

## Execution class and model recommendation (RG-100)

- Execution class: Architectural (new deployable, new network boundary), docs only.
- Execution location: Local.
- Model recommendation: Claude Code Opus 5.5 High; Codex GPT-6 Astra High.

## Exact start state and authorities

- Task start: 2026-11-25T21:12:18-05:00. Session `claude:3d36ca46-e1b2-4877-9199-8b5c8b77a76f` (the same session that ran
  the assessment and design review; RG-110 onward start in fresh sessions per `AGENTS.md` section 7).
- Repository `destroyer42/StableNew2`, branch `docs/rg-100-phone-review-gateway` from `origin/main` at `dbdfa2a3`, in an
  isolated worktree.
- Authorities consulted: `AGENTS.md`, `STATUS.md`, `docs/CODEX_MAP.md` (Operator Site row),
  `docs/ARCHITECTURE_v2.6.md` sections 1, 11, 14, `docs/runbooks/stablenew_operator_site.md`,
  `docs/runbooks/ai_assist_preview_activation.md` (the SSH forward), `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`.

## Surface assessment

- RG-100 files: this file, the schema, `docs/ARCHITECTURE_v2.6.md` (one paragraph), `STATUS.md` (one line).
- Controller or coordinator surface touched by later slices: none of the ratcheted controllers should grow. Pairing and
  status UI live in a new `src/app/` service plus a small dialog; composition only in `src/app/runtime_stack.py`.
- Architecture authority changed: yes, as an approved design (section 11 paragraph). The queue-concurrency invariant
  changes only in RG-145, after owner approval of its exact text.

## Acceptance and evidence

Program acceptance (verified at the slice that completes each item):

- S1–S11 implemented with tests where testable; S12 with N1; S13 with RG-145.
- A real batch of at least 100 items reviewed on the phone over Tailscale away from home: first screen of thumbnails under
  1.5 s, an image opens under 1 s, no manual copying.
- Each Keep yields Retain evidence on the PC and an Immich asset in the run's album; Favorite sets Immich's favorite flag.
- Each Delete moves the file into the review archive; Undo on the desktop restores it.
- With the PC off, review continues; decisions apply within one sync interval after it returns.
- A revoked device is refused within one request.
- No phone-originated job reaches the runner except through `JobService.submit_njrs` (test).

RG-100 evidence mode: documentation inspection. The schema parses as JSON and every internal `$ref` resolves. It was not
checked against the JSON Schema 2020-12 meta-schema, because `jsonschema` is not in the application or dev environment;
RG-110 adds a pinned validator and a test that checks the schema and sample payloads. No qualification claim. Not
demonstrated: anything at runtime.

## Token-efficient validation plan

1. Gateway (RG-110): hermetic ASGI-client tests for enrollment, scopes, outbox durability and refusal of sync routes on
   the phone app; schema validation of every sync payload.
2. Sync worker (RG-120): tests against a fake gateway for publish idempotence, forged-record refusal (path, digest,
   unknown action, revoked device), archive semantics and acknowledgement.
3. Existing `tests/app/` Site suites stay green.
4. `python tools/ci/run_pr_gate.py` in an isolated worktree (the live app runs in the main checkout).
5. One owner-run physical acceptance session for the program acceptance list.

## Stop conditions

- Any need to accept inbound connections on the PC.
- Any phone path that would create jobs outside the existing admission services.
- An Immich version that cannot scope its API key.
- The Library index cannot serve as the publish source without reading the job database under its lock.
- RG-145 discovers it needs a second repository, history or cancellation authority.

## Documentation impact

- RG-100: this file, the schema, `docs/ARCHITECTURE_v2.6.md` section 11 paragraph, `STATUS.md` Operator Site line.
- RG-110/RG-120: a living document `docs/Subsystems/ReviewGateway/REVIEW_GATEWAY.md` (listed in
  `docs/Subsystems/README.md`), a runbook for deploy, pairing, revoke, retention and backup, and a `docs/CODEX_MAP.md` row,
  each when the code exists.
- RG-145: the amended queue invariant in `AGENTS.md` section 2 and `docs/ARCHITECTURE_v2.6.md`, after owner approval.
- RG-150: STATUS when the hosted relay retires.

## Completion report (RG-100)

Filled in at closeout in the PR body per `AGENTS.md` section 8.
