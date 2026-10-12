# PR-BATCH-OPS-201 — Unified batch operations and outcome triage

Status: **implemented and locally verified on `codex/batch-ops-201-unified-management`; not pushed, no PR.** All
validation is CPU / fake-runner only: no WebUI, Comfy, GPU, installed runtime or user SQLite data was touched.

## 1. Execution profile and model recommendation

Standard, cross-file package with bounded concurrency and persistence risk (cancellation races, replay identity,
all-or-none admission, Tk thread affinity). Recommended Codex GPT-6.1 Sol XHigh / Claude Code Sonnet 5.5 XHigh under
`docs/AI_MODEL_SELECTION.md` (difficult bounded lifecycle/persistence/concurrency work); Local/Desktop fits the SQLite
and native-Tk acceptance testing. No Opus/Astra escalation: no ownership or architecture ambiguity surfaced.

Controller surface assessment: `app_controller.py` (7,540), `job_service.py` (1,233), `job_history_service.py` (647) and
`pipeline_controller.py` (1,774) are **unchanged** (ratchet OK, no ceiling raised). The one new controller,
`src/controller/batch_operations_service.py`, is 546 lines (limit 600; output resolution lives in
`batch_output_resolution.py`); the pure logic lives in `src/queue/` and `src/pipeline/`, the Tk view is wired from `PipelineTabFrame`, and no responsibility was added to `AppController`.

## 2. Phase 0 baseline (before any source change)

Base `d2828d93` (= `origin/main`, clean worktree). Reproduced with temporary SQLite and the real Review builder
(`prepare_review_batch`), the real `VideoWorkflowController`, the real `JobService`/`JobQueue`/`JobRepository`:

| Observation at the base | Result |
|---|---|
| Persisted Review identity | `provenance.metadata.review_batch {batch_id, source_count, group_by_model}` plus top-level `batch_id`; no kind, no per-job index |
| Persisted Video identity | `provenance.metadata.batch {schema "stablenew.batch.v1", batch_id, batch_kind "video_workflow", source_index (0-based), source_count}` |
| Recent-20 history | a 25-job batch showed 20 jobs (10-job batches showed all 10); History panel has no batch concept |
| Review `batch_size=4` | 10 sources -> **9 jobs**, 25 sources -> **22 jobs**; `source_count` stays 10/25 (jobs != sources) |
| Replay (`compile_replay_intent`, both History paths) | copied `batch_id`, `review_batch` **and** `batch` into the new job: a replay looked like another original member |
| `JobService.cancel_job` / `JobQueue.remove|clear` | check-then-cancel in separate lock acquisitions; `RUNNING -> CANCELLED` is a legal transition, so a job claimed in between was cancelled |
| Missing features | batch discovery/progress, selected retry, failure triage view, output navigation from History (History->Review did not exist), Cancel Remaining |

## 3. What was built

**Membership (pure, `src/queue/batch_membership.py`).** Identity is the composite `(kind, batch_id)` with kinds
`review`, `video_workflow`, `selected_retry`. A job is `MEMBER`, `UNGROUPED` (no valid identity - an ordinary job;
a bare top-level `batch_id`, unsupported kinds, bad counts), or `AMBIGUOUS` (descriptors/ids contradict - excluded from
every batch and reported). Nothing infers membership from pack names, timestamps, queue position, output folders,
prompts or labels. No migration, no batch table, no persisted batch status.

**Projection (pure, `src/queue/batch_projection.py`).** Per-job views and per-batch summaries derived from
canonical `JobStatus` rows: five counts, a display-only aggregate state (Active / Waiting / Completed / Completed with
failures / Completed with cancellations / Failed / Cancelled), job count and declared source count kept separate
(`covered_source_count` is informational), first-job-created time (labelled as such; there is no batch submission
record), WebUI-held annotation read from the **live** `JobQueue` at refresh time (never a status, never remembered),
artifact references from the canonical result, stage checkpoints and failure `completed_output_paths` (so a FAILED
job's partial outputs stay discoverable), retry parent/children (children are never counted as members), integrity
notes (duplicate positions, differing declared counts => `conflicting`, operations refused; missing declared members).

**Failure triage (pure, `src/queue/failure_triage.py`).** Typed evidence only: the persisted
`failure_evidence` block (reusing `assess_evidence`), the restart-recovery marker, and exact exception *types* in the
persisted envelope. Categories: backend unavailable before dispatch; readiness/runtime-identity refusal; dispatched
outcome unknown (outcome-unknown, request-may-have-executed, timeout, restart interruption); definitive HTTP
rejection; invalid model/configuration/unsupported operation; resource exhaustion (`SVDOutOfMemoryError`,
`ResourceLimitError`); other/unclassified. Message text is shown (first line, <=240 chars) but **never** keyword
matched; untyped historical failures stay `Other / unclassified` and are never called safe to replay. Known limit: a
WebUI CUDA OOM is not currently persisted as typed evidence, so it classifies as an HTTP rejection or Other.

**Bounded repository reads (`JobRepository`).** `read_batch_candidate_page(before_cursor, window)` is one read-only
window (newest rowids first) of jobs whose snapshot mentions `"batch_id"`; the window bounds the rowids *examined*
(default 2,000), so the repository lock is held for a bounded time however sparse batch jobs are. The cursor is the
SQLite `rowid` (`queue_order` is renumbered by reordering and cannot page). `list_replay_child_rows(parent_ids)` finds
history-replay children. No schema change. The service streams windows straight into the projection (only derived
per-job views are retained, never every snapshot/result), independent of the recent-20 History list. The *listing* is
capped (20,000 candidates, newest kept, explicit `truncated` notice); *operations* always scan a batch whole.

**Guarded cancel (`JobQueue.cancel_if_queued` / `cancel_queued_jobs`).** The QUEUED check and the existing
`QUEUED -> CANCELLED` transition run under the same queue lock that makes `claim_next_job`'s `QUEUED -> RUNNING`
atomic, and `JobRepository.transition_job(expected_status=QUEUED)` re-checks the durable status inside the same
transaction (`JobStatusChanged`, no write). A member that started first is *skipped*, never cancelled; running work, its
cancellation token and processes are never touched; ordinary status callbacks, persistence and heap cleanup apply. No
raw bulk `UPDATE`. The unguarded `transition_job`/`cancel_job` behavior is unchanged.

**Replay lineage (`compile_replay_intent`).** A replay no longer inherits active membership. The parent's
`batch`/`review_batch`/`batch_id` are archived verbatim and inert under
`metadata.replay_origin {schema "stablenew.replay-origin.v1", parent_job_id, ...}`; this covers the ordinary single-job
History Replay as well. `ReplayIntent.batch` can attach a *new* `stablenew.batch.v1` descriptor with
`batch_kind = "selected_retry"` (`source_index`/`source_count` over the retry selection).

**Selected retry (`BatchOperationsService`).** User-initiated only. `preflight_retry` assesses *every* selected job
(ineligible ones listed with reasons, never dropped): FAILED status, reconstructable stored NJR, no existing
queued/running/completed retry child, today's submission validation and image operation admission
(`require_njr_operation`), the video backend's own workflow governance gate run now (unknown, disabled, un-opted-in or
unpinned workflow), and frozen inputs present and unchanged (`replay_input_verification`: recorded SHA-256 for the
Review source artifact - also through retry-of-retry chains, via the inherited metadata digest - the prepared video
source and driving video; presence for anchors/depth). Non-blocking notices flag an untyped failure ("not known
whether the earlier request ran") and already-recorded outputs. `submit_retry`
refuses during shutdown, re-runs the whole preflight against current repository truth, requires an explicit
acknowledgement per unknown-outcome job (judged against both the reviewed and the current evidence), compiles each job with `compile_replay_intent` (new id, parent lineage; >= 2 jobs share a new `selected_retry`
batch, a single job is an ordinary replay child), and crosses `JobService.submit_njrs` **once**. Plans are single-use and
one submission runs at a time. A post-admission follow-up error or a runner that is not running is reported as
*admitted with a note* (durability is judged against the identities that existed before the call); pause, auto-run and
the WebUI hold are respected by the existing queue. No batch-specific runner exists.

**Content visibility (SFW mode).** The view applies the same `ContentVisibilityResolver` policy as History, driven by
`AppState.content_visibility_mode` (re-derived immediately when the mode toggles). Counts, statuses and structure are
never falsified. A job the policy would hide shows `[Hidden in SFW mode]` for source/model/outputs, its detail shows only
id, status, priority, times, the generic failure category and lineage (no message, paths or outputs), and its outputs are
never resolved, opened in Review/Movie Clips or revealed in a folder. Every displayed free-text field (source, model,
failure message, output names/paths, operator messages) is also redacted whole when it contains explicit terms, and the
retry review shows hidden jobs' labels and reasons redacted while eligibility and tokens stay unchanged. Covered by
`tests/gui_v2/test_batch_operations_visibility_201.py`.

**Outputs.** `resolve_outputs` returns existing files in selection order then artifact order; missing/moved/unreadable
files are reported (`PIL` header verify for images), never silently handed off. Review: `route_images_to_review`
(beside the Video/Movie Clips routes) -> `ReviewTabFrame.load_selected_images`, a thin public wrapper over the existing
`_set_selected_images` (it drops a stale staged-curation hand-off; stage toggles are untouched). Video jobs: output
folder, Movie Clips bundle from recorded video paths, and a thumbnail only as an image; an MP4 is never sent to Review.
No quality scoring, curation database or automatic exclusion/deletion.

**View.** `PipelineTabFrame` row 4: a collapsed "Batches" `DisclosureSection` under History (existing History/Queue
panels and their controls are unchanged). Toolkit-neutral `BatchOperationsSession`
(`src/gui/view_contracts/batch_operations_contract.py`) owns state, filters, selection, truthful action gating and the
stale-completion rules; `BatchOperationsPanelV2` renders batch list, progress summary, filter boxes, a selectable job
table (status/failure first, remaining columns scroll at the ~400 px column width), a read-only detail pane (failure
triage, checkpoints, outputs with availability, lineage), Cancel Remaining, Retry Selected Failed, Open Output Folder,
Open in Review and Movie Clips. Every repository read and operation runs off Tk through the existing
`BackgroundWorkRunner` (`ThreadRegistry` + `TkUiDispatcher`); completions are latest-wins, single-delivery, and dropped
after close. Auto-refresh is debounced (2 s) and only while the view is open and mapped. Selection in the job table
follows table order.

## 4. Race handling

| Race | Behavior |
|---|---|
| Job starts while Cancel Remaining is confirmed | skipped (guarded, durable re-check), reported |
| Job completes while refreshing | each page is a consistent row read; the next refresh converges |
| Selected FAILED job replayed elsewhere before the click | admission-time preflight sees the child and refuses |
| Sources change between preflight and admission | admission re-verifies hashes/presence and refuses with zero admitted |
| WebUI hold changes while loading | hold is read from the live queue at refresh; next refresh corrects it |
| Two retry clicks overlap | single-use token + in-flight refusal; two separate plans: the second sees the first's child |
| Widget destroyed with a worker outstanding | session closed on `<Destroy>`; late completion is ignored |
| Admission commits but runner start fails | reported as admitted with a note; jobs stay QUEUED |

## 5. Acceptance matrix (all deterministic; temporary SQLite, synthetic NJRs, fake runner/backends)

Files: `tests/queue/test_batch_membership_201.py` (M), `test_batch_catalog_201.py` (C), `test_batch_cancel_201.py` (X),
`tests/controller/test_batch_operations_service_201.py` (S), `tests/gui_v2/test_batch_operations_session_201.py` (N),
`test_batch_operations_view_201.py` (V), `test_batch_operations_review_handoff_201.py` (H).

| # | Criterion | Evidence |
|---|---|---|
| 1 | Review and Video provenance normalize | C `real_review_and_video_builders_normalize_to_their_batches`; M `review_shape…`, `video_shape…` |
| 2 | Kind + ID prevents collisions | M `composite_identity…`; C `batch_kind_plus_id_prevents_collisions…` |
| 3 | Legacy/unknown stay ungrouped | M `records_without_a_valid_identity…`; C (same test, legacy records) |
| 4 | Reopened SQLite reconstructs the batch | C `reopened_sqlite_reconstructs_the_same_batch` |
| 5 | Recent-20 does not truncate 25 jobs | C `recent_twenty_history_never_truncates…`, `pagination…` |
| 6 | Review multi-source jobs counted accurately | C `real_review_and_video_builders…` (`batch_size=4`: 9 jobs / 10 sources) |
| 7 | Job 7 of 25 fails, others continue | C `job_seven_of_twenty_five_fails…` (real `SingleNodeJobRunner`, fake backend) |
| 8 | Every canonical status counted | C `every_canonical_status_is_counted_exactly`; M aggregate-state table |
| 9 | Held WebUI images stay QUEUED; video progresses | C `webui_held_images_stay_queued…` |
| 10 | Partial artifacts on failed jobs | C `partial_artifacts_stay_discoverable…` |
| 11 | Only selected-batch QUEUED cancelled | X `only_queued_members_of_the_selected_batch…` |
| 12 | Concurrent claim skipped | X `member_claimed_after_confirmation…`, `repository_transition_is_conditional…`, `stale_queue_view…`, `concurrent_dispatch…` |
| 13 | Other batches/running work unchanged | X `only_queued_members…` (no cleanup, no token, no callbacks for others) |
| 14 | Idempotent repeat, accurate partial report | X `repeating_cancel…`, `confirmed_members_that_left…`, `repository_error_is_reported_per_job…` |
| 15 | Status and queue order consistent after restart | X `status_and_queue_order_remain_consistent_after_restart` |
| 16 | Three failures -> three new identities, parents | S `three_selected_failures…` |
| 17 | One all-or-none `submit_njrs` | S `three_selected_failures…` (call spy) |
| 18 | Later admission failure -> zero admitted | S `later_item_admission_failure…` |
| 19 | Old membership not inherited; origin kept | M `replay_never_inherits…`, `selected_retry_descriptor…`; S `multi_job_retry_is_a_new_versioned_batch…` |
| 20 | Single Replay cannot contaminate | M replay tests; S `ordinary_single_replay_cannot_contaminate…` |
| 21 | Unknown outcome needs acknowledgement | M triage; S `unknown_outcome_needs_explicit…`; V `retry_dialog_lists_everything…` |
| 22 | No automatic replay / restart bypass | S `nothing_is_replayed_automatically…` |
| 23 | Stale/unavailable inputs fail preflight | S `missing_and_changed_sources…`, `sources_that_change_between…`, `video_failures_retry…` |
| 24 | Double click / stale callbacks cannot duplicate | S `same_plan…`, `overlapping_clicks…`, `two_separately_reviewed_plans…`; N `duplicate_completion_delivery…` |
| 25 | Retry children found after restart | S `retry_children_are_found_after_restart…` |
| 26 | Progress and filters follow persisted state | N `progress_rows_and_summary…`, `…filters…`; V `…lists_batches…`, `filters_drive…` |
| 27 | Selection preserved across refresh | N `selection_survives_refresh…`; V `selected_jobs_and_batch_remain_selected…` |
| 28 | Review receives intended image paths | N `open_in_review_receives…`; H `batch_view_open_in_review_selects_exactly…`, `route_images_to_review…` |
| 29 | Video outputs use existing artifact paths | S `video_outputs_use_existing_artifact_paths…`; N `video_outputs_use_folder_and_movie_clips…` |
| 30 | Missing outputs / absent evidence actionable | S `review_outputs_resolve…`, `absent_evidence…`; N `missing_outputs_are_reported…` |
| 31 | Worker / Tk thread affinity | N `reads_run_off_the_ui_thread_and_completions_land_on_it` |
| 32 | Destroyed widget / stale worker harmless | N `completions_after_close…`, `stale_refresh…`; V `destroying_the_view_with_a_worker_outstanding…` |
| 33 | Existing Queue/History controls unchanged | V `real_pipeline_tab_mounts…`; existing Queue/History/Pipeline tab suites unchanged and green |
| 34 | Review-200 / Video-200 remain valid | `tests/gui_v2/test_review_batch_200.py`, `tests/video/test_pr_vid_batch_200_multisource.py` unchanged and green |
| 35 | PR-171/172 unaffected | `tests/queue/test_webui_outage_containment_171.py`, `test_dead_forge_cascade_172.py` unchanged and green |
| 36 | No live process / GPU / user data | fake runner (`tests/helpers/batch_ops_201.py`), one real runner with a fake callable, temporary SQLite only |

## 5b. Independent aggregate review (read-only, fresh context) and dispositions

One HIGH, four MEDIUM and several LOW findings, no BLOCKER; the cancel-versus-claim race, lock ordering and every other
replay copier were checked and found correct (30 trials x 150 members against a real claiming thread: 0 errors, no
claimed job cancelled). Dispositions (each with a regression test that fails without its fix):

| Finding | Disposition |
|---|---|
| H1 Replays recorded before this change copy batch markers and were counted as members (inflated counts, `conflicting`, Cancel Remaining would cancel the user's replay) | **Fixed**: a `history_replay` job is a member only of a `selected_retry` batch; any other copied marker makes it a retry child (`catalog.legacy_replay_job_ids`). `test_replays_recorded_before_the_fix_are_retry_children_never_members` |
| M1 Capped scan dropped the newest batches and operations ignored truncation | **Fixed**: newest-first listing; operations scan whole (`cap=None`). `test_windowed_reads_cover_every_member_and_a_capped_listing_keeps_the_newest` |
| M2 Scan scaled with history (lock hold, retained rows, refresh superseding) | **Fixed**: rowid-windowed reads, streamed projection, single in-flight refresh with one coalesced follow-up. `test_repository_windows_bound_the_rows_examined…`, `test_refresh_requests_while_loading_coalesce…`. Residual: rehydration cost still grows with batch-member count (~0.2 ms per member job) |
| M3 Retry-of-retry lost the SHA-256 integrity check | **Fixed**: digest read from the inherited metadata. `test_a_retry_of_a_retry_still_verifies_the_original_source_digest` |
| M4 Video retry not revalidated under workflow governance | **Fixed**: registry gate run at preflight/admission. `test_video_retry_is_revalidated_against_current_workflow_governance` |
| LOW `_queue_notes` could raise after commit; plan token burned by a pure pre-admission failure; acknowledgement judged only on the reviewed plan; stuck `busy`/`loading` when a worker cannot start; Tk module read private controller attributes | **Fixed** (observation failure is a note; token released when nothing became durable; acknowledgement also judged on fresh evidence; start failure resets state; factory moved to the controller layer using public accessors) |
| LOW Retry bypasses `QueueSubmissionService` | **Partly addressed**: shutdown is refused; model-order sorting is not applied (retries keep selection order) |
| LOW `replay_origin` in chains | **Documented**: it names the batch member whose batch was archived; a retry of a retry-batch member records the retry batch as origin and the older origin stays reachable through lineage |
| LOW Typed `timeout` flag is keyword-derived upstream (`webui_failure_evidence.py`) | **Documented** (outside this change); a timeout is treated as outcome-unknown, i.e. the conservative direction |

### Final aggregate review (read-only, at `3eb4fbb`) and dispositions

Cancellation/dispatch races, replay lineage and Tk thread safety: no findings (race stress and lock order re-verified;
every `compile_replay_intent` caller checked). SFW visibility: three reproduced leaks, all fixed with regression tests that
fail on the pre-fix source:

| Finding | Disposition |
|---|---|
| S1 (blocker) status line kept pre-toggle text after switching to SFW | **Fixed**: the message is stored raw and redacted at read time against the current mode and hidden jobs |
| S2 (blocker) retry refusal/error text embedded a hidden job's label and paths (innocuous file name, hidden by prompt) | **Fixed**: any message naming a hidden job's source, file, path or folder is redacted whole in SFW mode |
| S3 (high) an outputs completion landing after switching to SFW still handed images to Review | **Fixed**: the hand-off re-checks visibility when it completes and opens nothing if a requested job became hidden |
| S4 (low) classification ignored directory names | **Fixed**: job classification includes source/output paths; a job under a hidden directory is hidden |
| Hardening (low) | experimental opt-in must be exactly `true`; any registry refusal is a preflight problem; mid-anchor files are presence-checked |

Accepted/documented (LOW): video preflight is weaker than the backend on accepted-control, backend-id, frame-count and
launch-flag checks (a retry that fails there fails again and is classified, never silently replayed); Review jobs with
several inputs, anchors and depth maps are presence-checked only (no recorded digest, or no single parent digest); a
Folder hand-off opens a directory that may also hold hidden jobs' files; the mode defaults to NSFW when no app state is
attached (same as History); `parent_job_id` has no index (about 12 ms per 400-id chunk at 6k jobs) and a full refresh of
6,000 member jobs takes about 2.3 s off the Tk thread (about 8 s at the 20,000 cap); the job table inserts all rows of the
selected batch.

## 5a. Scale evidence

Synthetic repository of 4,000 jobs (3,000 ordinary plus 40 batches of 25, half Review and half Video): one full
`BatchOperationsService.refresh()` (paged scan, projection, live hold read) took about 240 ms, and 160 ms with a selected
batch's retry-children and file-availability detail, on a loaded CI-class VM, entirely off the Tk thread.

## 6. Debt and limits

- Membership is only as good as the frozen descriptors: batches created before PR-REVIEW/VID-BATCH-200 have none and
  stay ordinary jobs (by design). A Review batch has no per-job position, so rows show `-`.
- A scan reads every job whose snapshot mentions `batch_id` (windowed, so no long lock hold); very large histories
  (>20,000 candidates) show a truncation notice for the listing only. There is still no index; a dedicated column would
  need an approved schema change.
- `selected_retry` is not offered as a Review/Video *submission* path and has no recurring/automatic form.
- Admission is serialized per process; a History Replay click racing a Retry click in the same millisecond is bounded
  by the child check, not by a shared lock (the legacy `JobExecutionController.replay` path still bypasses
  `JobService.submit_njrs`; it is untouched here).
- WebUI CUDA OOM is not typed in persisted evidence (see §3 triage).
- Content visibility reuses the shared `ContentVisibilityResolver` heuristic (explicit-term matching plus recorded
  rating), so it inherits its limits; this view additionally classifies a separator-normalized copy of file
  names/paths (`nude_study.png`), which the shared word-boundary match misses (History has that gap too; the shared
  resolver is untouched).
- Hosted Python 3.14 CI has not run for this branch; nothing was pushed.
