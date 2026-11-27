# RG-170: "To rate" on the phone review gateway

Status: **built, hermetically tested, not deployed.** Owner request 2026-11-27: "bring in the harness evaluations and
movie clip comparisons into Phone review gateway (in another tab or section) … and track all the things that I am
supposed to be rating or giving feedback on." Contract and invariants: [RG-100](RG-100_phone_review_gateway.md).

## Objective and acceptance

The phone shows every open rating or feedback request, lets the owner answer it, and the answers land in the same files
the desktop rating pages write.

1. A "To rate" tab lists tasks with an open count and per-task progress (open, partly done, waiting for the PC, done,
   refused with the reason).
2. Four task kinds: A/B pairs (`pairs`), 1–5 and yes/no scores per clip (`scores`), an N-way ordering (`ranking`) and a
   pick-one question (`choice`). `choice` also covers post-reveal picks and owner decisions (slice 2 of the request).
3. Answers are saved per item as they are given, so a sitting can stop and resume, on any paired phone.
4. Submit is explicit and final. Only then does the PC read the eval's key, write the results, and send the reveal.
5. The PC writes results into the eval's own contract. It never overwrites a different judgment already there.
6. A follow-up pick (for example 8 or 12 steps) is registered only after the reveal.
7. A harness registers a sitting with one call or one JSON file in a known folder. No gateway code per eval.
8. Arm identities do not reach the gateway before submission, including through file names or media metadata.

Exclusions: no queueing or job creation from a rating, no report rebuild or threshold verdict (the eval session's
`verify` command still does that), no change to review decisions, no offline queue (RG-160), no deployment here.

## Design

```
eval harness ──register──▶ %LOCALAPPDATA%\StableNew\review-gateway\rating_tasks\<task_id>.json   (PC only)
PC sync worker ──manifest + stripped renditions──▶ gateway rating store ──▶ phone "To rate"
phone ──answers (saved per item) ──▶ gateway ──submission──▶ PC pulls ──▶ eval CSV / ratings.csv / answer file
PC ──acknowledgement + reveal──▶ gateway ──▶ phone
```

The PC still accepts no inbound connection (RG-100 invariant 1). The gateway stays a projection and outbox
(invariant 2): the registration folder and the eval files on the PC are the only authorities.

### Where the design differs from the proposed shape

- **A separate rating submission queue, not the decision outbox.** An outbox record names one library item by id and
  digest, and its parser and applier are the security-hardened path for Keep, Delete and queueing. A rating names no
  library item. The new queue has the same semantics (pending until the PC acknowledges, idempotent, refusable) and
  leaves `outbox`, `review_gateway_apply.py` and retention of review items untouched.
- **Separate rating media**, in `<media_dir>/rating/`. Review retention therefore needs no change, and a clip that is
  both a library item and a rating clip is stored twice (a few MB per sitting).
- **Rating renditions, not the publisher's phone transcode.** The eval MP4s checked on 2026-11-27 carry the workflow
  description, backend id and a PC manifest path in their container metadata, and the publisher's transcode (CRF 28,
  metadata copied, and skipped for clips under 64 MB) would send that. Every rating clip is re-encoded the same way:
  H.264 CRF 18, at most 1280 px, `-map_metadata -1`. Reference images are re-encoded without metadata.
- **Contract additions are `$defs` in the existing sync schema**, behind the gateway's `rating_tasks` health feature.
  A second schema file would not be extracted by the deployer already installed on the container.

### Payloads (`stablenew.review-gateway-sync.v1`, additive)

| Payload | Direction | Content |
|---|---|---|
| `rating_task` | PC → gateway | task id, title, kind, instructions, criteria, items (opaque ids, text context, optional reference image, clips as SHA-256 media), state (`open`, `done`, `withdrawn`) |
| `rating_submission_page` | gateway → PC | pending submissions: submission id, task id, device id, answers |
| `rating_acknowledgement` | PC → gateway | `applied` or `refused` with a reason code, and the reveal tables |

Bounds: 60 items per task, 6 clips per item, 16 criteria, 2000 characters of context per item, 1000 of notes, 256 KiB
per manifest. A task id's shape (kind, criteria, item ids, clip ids) is fixed once published; a changed shape needs a
new id.

Sync routes: `POST /sync/v1/rating-tasks`, `PUT|HEAD /sync/v1/rating-media/{sha256}`,
`GET /sync/v1/rating-submissions`, `POST /sync/v1/rating-acknowledgements`.
Phone routes: `GET /api/rating/tasks`, `GET /api/rating/tasks/{id}`, `POST …/answers`, `POST …/submit`,
`GET /rating-media/{id}/{sha256}`. Every phone route needs an enrolled device with the `review` scope (S1); a
submission from a device the PC has revoked is refused on the PC too.

### Registration and result adapters

`src/video/video_eval_rating_task.py` owns the registration file (`stablenew.rating-set.v1`: id, title, kind,
criteria, items with media paths under `root`, `result`, optional `follow_up`) and `register_rating_task()`.
`python -m tools.review_gateway_rating` builds one from the folders the evals already produce.

| `result.adapter` | Writes | Reveal |
|---|---|---|
| `pairwise_csv` | the `<criterion>_better` and `notes` cells of `pairwise.csv`, as the desktop page does | wins per arm from `pairwise_key.json` |
| `ratings_csv` | the run's `ratings.csv` through `video_eval_ratings_store` | per-arm means and counts from `rating_key.json` |
| `ranking_csv` | `ranking.csv` (`<criterion>_order`, for example `B>A>C`) | mean place per arm |
| `answer_file` | the chosen value (`.txt`) or all answers (`.json`) | none |

Writes are all or nothing: any filled cell that disagrees refuses the whole submission (`already_rated`) and writes
nothing; the phone shows the reason and the task opens again. A `ratings.csv` row bound to another clip digest, or a
clip file that no longer matches the key's digest, is refused (`clip_changed`). A task whose sheet was completed at
the desk is published as done.

### Owner-visible decisions (defaults built; change on request)

| # | Question | Default |
|---|---|---|
| Q1 | Send each case's prompt and source picture to the phone? Needed to judge "did the action happen" and "looks like the source". | Yes. Same private gateway that already holds prompt excerpts and review media. |
| Q2 | Submit once, final, with the arm reveal shown on the phone afterwards? | Yes. |
| Q3 | A value already filled in at the desk differs from the phone's answer. | Refuse the whole submission, keep the desk value. |
| Q4 | Eval run clips are ordinary video outputs, so the review tab may already show them with their model and workflow, which weakens blinding. | Leave as is; say so in each sitting's instructions. Hiding them from review is a separate change. |

### Files

New: `services/review_gateway/review_gateway/rating_store.py`, `rating_routes.py`, `static/rating.js`,
`static/rating.css`; `src/video/video_eval_rating_task.py`; `src/app/review_gateway_ratings.py`;
`tools/review_gateway_rating.py`; tests. Hooks only in `app.py`, `phone_app.py`, `sync_app.py`, `contract.py`,
`static/app.js`, `static/index.html`, `review_gateway_client.py`, `review_gateway_sync.py`, `runtime_stack.py` and the
sync schema.

PHONE-FAST and RG-160 overlap: both edit `app.js`, `phone_app.py`, `review_gateway_sync.py` and `runtime_stack.py`.
The hooks here are a few lines each; whoever merges second resolves them.

## Execution class and model recommendation

- Execution class: Standard (new feature inside the approved RG-100 design; new authenticated phone routes).
- Execution location: Local.
- Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High.
- Controller Surface Assessment: no controller or coordinator file changes; composition only in
  `src/app/runtime_stack.py`.

## Validation (token-efficient)

Hermetic gateway tests with the ASGI client, PC tests against the real gateway app in process with a stubbed
transcoder (Linux CI has no FFmpeg), adapter tests on temporary folders, then `tools/ci/run_pr_gate.py` and the
`tests/app`, `tests/video`, `tests/gui_v2`, `tests/system` and `tests/tools` suites. No app, backend or GPU run.

## Deploy and rollout (after merge, owner-authorized)

1. Deploy the gateway (`review-gateway-deploy`); no new settings, no new schema file, new tables only.
2. Update the PC. The sync worker publishes registered tasks once the gateway lists `rating_tasks`.
3. Physical acceptance, not done here: rate one sitting on the phone and check the CSV it wrote.

## Documentation impact

`docs/Subsystems/ReviewGateway/REVIEW_GATEWAY.md` (section for ratings), the `docs/CODEX_MAP.md` gateway row and the
generated `docs/CODE_MAP.md`.
