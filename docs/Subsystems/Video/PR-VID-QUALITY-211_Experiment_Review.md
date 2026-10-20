# PR-VID-QUALITY-211 — Video Experiment Comparison, Review and Durable Quality Evidence

Status: **implemented and locally verified (CPU only).** Validation used pure unit tests, a real temporary SQLite repository, real FFmpeg on KB-sized synthetic clips and a real Tk window. No physical generation was run, no runtime was started or restarted, and nothing here shows that any workflow produces better motion. No NJR field, queue, runner, compiler, process manager, Comfy graph, model policy, seed or generated artifact changed; Wan-Animate-2 and Wan2.2 stay experimental and native SVD XT stays the accepted production backend.

Execution class: Standard (cross-file, no new execution contract, no schema change; see section 8). **Model recommendation:** Claude Code Sonnet 5.5 XHigh (`docs/AI_MODEL_SELECTION.md` row "difficult bounded lifecycle/persistence/concurrency/cross-file PR"); Codex GPT-6.1 Sol XHigh as the alternative; stay in one local session.

## 1. What it is

A post-execution consumer. An operator who queued a one-variable Video Workflow experiment (PR-VID-194) can open **Review Experiment** from the Video Workflow tab (after queueing, or empty to type a job id) or from Job History (a selected arm's **Review Experiment** button or context-menu entry), including after restarting StableNew. The window rebuilds the study from persisted jobs, lists every arm A to D with its own state, shows two arms side by side with one comparison clock, and records a quality assessment per clip as durable Learning evidence. Nothing it does queues, retries, repairs or scores a job, and it never picks a winner.

**A high motion magnitude does not establish that the requested movement succeeded.** The rubric therefore records *whether the requested action happened* separately from *how good the clip looks*.

## 2. Identity: the group is recovered, never guessed

`src/video/video_review_group.py` (`build_review_group`) starts from any one job id:

1. `repository.get_job` must return a job whose NJR is a `video_workflow` source, video workload, carries a `LearningJobContext` and a `video_workflow` stage block. Otherwise there is no group (single Video Workflow jobs, native SVD jobs, replays and image jobs are refused with an explanation).
2. `JobRepository.list_experiment_sibling_entries(job_id, experiment_id)` returns candidates. It is read-only SQL over the existing `jobs` table (no schema, index, cache or lifecycle effect) and examines only `2 * EXPERIMENT_SIBLING_WINDOW + 1` rowids around the selected job, because an experiment is admitted by one `record_job_submissions` transaction and its arms are adjacent. A bounded miss means "not found"; it never widens into a table scan.
3. Each candidate is accepted only when its **own NJR** carries the same `experiment_id` as a `video_workflow` source. Replay descendants (`history_replay`) and other kinds that merely mention the id are listed in `excluded_job_ids`, never merged.
4. Duplicate or out-of-range arm indices are refused; with two or more arms the PR-VID-194 `assert_one_variable` gate is re-run over the stored NJRs, so arms that differ outside the tested control (a different seed, workflow, prompt) are refused with the gate's own message. A single found arm is a group of one (nothing to compare).
5. Arms are ordered by `variant_index` and labelled from `ARM_LABELS`, whatever order they completed in.

An arm is **playable** only when the repository says `completed` and the recorded video bundle (`video_bundle`, or the runner's `metadata.video_primary_artifact`, read by `video_bundle_from_result` in `src/video/video_artifact_helpers.py`) names a supported container (`.mp4 .webm .mov .mkv .avi .gif`) that exists as a file. No directory is ever scanned. The other states (`pending`, `running`, `failed`, `cancelled`, `interrupted`, `no_output`, `missing`, `unsupported`) stay visible with their own text.

## 3. The review window

`src/gui/views/video_experiment_review_window.py` (Tk) over `src/gui/view_contracts/video_review_contract.py` (`VideoReviewSession`, `ComparisonClock`; no Tk). All repository, file-hash, FFmpeg and evidence I/O runs through the existing `BackgroundWorkRunner` on a `ThreadRegistry` worker; results return through `TkUiDispatcher` and the session drops any result that went stale (window closed, review reloaded, selection changed). Closing the window cancels every load and decode and frees all frame memory.

* **Overview:** experiment id/name, tested control, workflow id/version/backend, shared seed, frame count and fps, prompt and negative prompt, fixed controls, source image, driving video (path, hash) and prepared motion source (derived path, hash) when present, and a per-arm table (job id, tested value, state). Prompts, text-valued controls and tested values pass through `ContentVisibilityResolver` for the current visibility mode, so SFW mode shows `[Hidden in SFW mode]`.
* **Comparison:** pick any two playable arms; synchronized Play/Pause, Restart, scrub, step by frame, timestamp and per-clip frame position, **Open original** per side (only while the recorded file still exists).
* **Clock honesty:** position is a step on a grid of `1 / max(fps)`, so stepping never skips a frame of either clip. A lower-rate clip repeats frames, a shorter clip is **held on its final frame**, real-time playback is never retimed, and every such difference is printed under the clip.
* **Previews are review previews:** `src/video/review_preview.py` decodes at most `MAX_PREVIEW_FRAMES` (120) frames, downscaled inside FFmpeg to at most `MAX_PREVIEW_EDGE` (256) px, as raw RGB over a stdout pipe capped at `MAX_PREVIEW_BYTES` (24 MiB) per clip, through the contained `run_bounded` primitive (60 s timeout, cooperative cancel, `file` protocol only, nothing written, nothing re-encoded). The window says so and offers the original. A clip with more frames than the cap shows "first N of M frames". No GPU, model, network, Comfy or WebUI process is involved.
* **Failure:** missing FFmpeg, a corrupt or unreadable file, a timeout or a cancel yields a message in place of frames; the metadata, ratings and the original-file action stay available.

## 4. The rubric and the evidence

Every saved clip review has a required overall rating (1 to 5), a required requested-action outcome (`achieved`, `partially_achieved`, `not_achieved`, `cannot_assess`), optional 1 to 5 dimensions (directed-motion fidelity, temporal continuity, character/subject consistency, anatomy/object integrity, scene/background stability; higher is better) and notes (at most 2000 characters, control characters removed). A positive overall rating never implies achieved motion; both combinations are stored and distinguishable. An operator may also mark a **manual preference** (one arm or none, with a reason of at most 1000 characters): a recorded human choice, not a computed winner or a recommendation.

`src/learning/video_quality_review.py` writes through the canonical `LearningRecordWriter` to the canonical `learning_records.jsonl`:

* Record kind `video_workflow_quality_rating`; every video field sits in `metadata.video_quality_review` (schema `stablenew.video-quality-review.v1`, `entry_type` `clip_review` or `manual_preference`). The record carries **none** of `user_rating`, `image_path`, `experiment_id`, `experiment_name`, `learning_context`, `variant_value` or `variable_under_test` at the metadata top level, so `RecommendationEngine` (unknown kind), `LearningAnalytics` and the `LearningRecordWriter` per-experiment readers cannot see it. Tests run the real readers against 5-star video records.
* A clip review is identified by `(job_id, artifact_sha256)`, never by path. It records the experiment, job, arm, tested value, workflow identity, artifact path and SHA-256, the NJR fingerprint, seed, source and driving-video identities, ratings, notes and a UTC timestamp. No bytes, snapshots, graphs or previews are stored (a record is about 1 KB).
* Append-only revisions: an edit appends `revision + 1`; reading resolves the latest **valid** revision (records that break the rubric, use another schema version or are torn are skipped, so an earlier valid revision still wins). A replaced file hashes differently and therefore inherits nothing, while the earlier evidence stays on disk attached to its own bytes. Saving re-hashes the file and refuses when it changed under an open window.
* Concurrent saves are safe: every append stages through its own temp file and appends under a process-wide per-path lock (`evidence_file_lock`), and `VideoReviewStore` holds that same lock across resolving the latest revision and appending, so any number of independently opened windows get distinct, ordered revisions and never interleave, lose or duplicate a record. The lock is process-local; a second StableNew process writing the same file is out of scope.
* A successful save acknowledges only the values that were submitted: edits typed while the worker was running stay dirty and the message says so.
* An unchanged save appends nothing. A failed write raises `ReviewSaveError` (writer returned `False`, raised, or the line could not be read back from the file tail); the session then shows `Save FAILED, your edits are kept`, leaves the form dirty and never says "Saved".
* A saved preference applies on reopen only while it names the same artifact bytes.

`src/learning/video_review_service.py` (`VideoReviewService`) composes the group, the hashing (bounded to 2 GiB, cancellable) and the store. It holds no state between calls; a restarted application recovers everything from the repository file and the evidence file.

## 5. Limits and traps

* The sibling lookup depends on adjacency. If a repository were ever compacted so an experiment's rows were no longer adjacent, siblings outside `EXPERIMENT_SIBLING_WINDOW` would not be found (the review would show fewer arms, never wrong ones). The window is generous (16 each side for at most 4 arms).
* An experiment's declared arm count is not stored in the NJR, so a group missing an arm that was never persisted cannot be told from a smaller experiment.
* Frame positions use the container's reported frame rate; a clip that reports none is timed at 24 fps and flagged. Variable-frame-rate clips are decoded frame-exact but timed at the reported rate.
* The preview is downscaled and ignores sample aspect ratio; judge fine detail in the original.
* The evidence file is scanned from the start on open and on each save (a cheap substring prefilter avoids parsing image records). Moving review evidence to an indexed store would be a separate, owner-approved change.
* Records written by this feature are ignored by older builds' recommendation engine only because the kind is unknown to them; they are never migrated.

## 6. Tests

| Area | Tests |
|---|---|
| Group identity, retrieval, states, bounded query | `tests/video/test_pr_vid_quality_211_group.py` |
| Bounded preview decode (fake runner and real FFmpeg) | `tests/video/test_pr_vid_quality_211_preview.py` |
| Rubric, append-only evidence, isolation from image Learning | `tests/learning/test_video_quality_review_211.py` |
| Service: hashing, reopen, rebuilt-service recovery, replaced artifacts | `tests/learning/test_video_review_service_211.py` |
| Session, clock, stale work, save/failure behaviour, redaction | `tests/gui_v2/test_video_review_contract_211.py` |
| Real Tk window, entry points, worker threads | `tests/gui_v2/test_video_experiment_review_window_211.py`, `tests/gui_v2/test_video_workflow_experiment_ui.py` |
| Acceptance path with real FFmpeg | `tests/integration/test_video_quality_211_acceptance.py` |
| Post-execution-consumer guards | `tests/safety/test_video_review_211_architecture.py` |

Shared harness: `tests/helpers/video_review_211.py` (real experiment from the production controller preview, real temporary `JobRepository`, synthetic `testsrc` clips).

## 7. Explicit exclusions (unchanged by this work)

No new generation workflow or model, no Wan or SVD qualification or promotion, no automated motion scoring or optical flow, no winner selection or next-parameter recommendation, no multi-variable experiments, no arbitrary external-video comparison, no editing, trimming or Movie Clips change, no deletion of clips or prepared sources, no Learning migration, no new media dependency (the existing FFmpeg and Tk/Pillow stack is sufficient for the bounded contract).

## 8. Architecture effect

None to the canonical path. Added: one read-only repository query, a video-bundle reader, five new modules and one Tk window. Changed: the Video Workflow experiment panel and tab (a button and one delegate) and the Job History panel (a button and menu entry). `VideoWorkflowController`, `AppController`, `JobHistoryService`, `JobService`, `PipelineController` and `LearningController` are untouched; no controller ceiling changed.
