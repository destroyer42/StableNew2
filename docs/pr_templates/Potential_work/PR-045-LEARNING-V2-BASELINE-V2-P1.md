PR-045-LEARNING-V2-BASELINE-V2-P1

“Passive Learning Log + Job History Ratings (No ML Yet)”

1. Title

PR-045 – Learning V2 Baseline: Passive Job Logging + Rating Hooks (V2-P1)

2. Summary

This PR introduces the foundational Learning V2 layer:

A structured Learning Log (learning_log_v2.jsonl) written after each completed Job, storing:

Pack(s) used

Full RunConfigV2 snapshot

Randomization plan snapshot

ADetailer/txt2img/img2img/upscale configs

Detected LoRAs/embeddings

Output file paths, count

Timing metrics

Job metadata (job_id, variant index, variant_total, timestamp)

A persistent rating store (learning_ratings_v2.jsonl) where the user can assign a 0–5 star rating to a Job from the Job History panel.

A V2 Job History Panel integration:

Shows each completed job in a scrollable list with:

Timestamp

Packs used

Outputs

A star-rating widget (5 clickable icons or a slider)

When rating is changed:

Store writes a LearningRatingRecord.

Controller glue that:

Receives on_job_completed(job) events

Writes LearningLog entries

Updates JobHistory store

Ensures GUI refreshes

Targeted tests to ensure LearningLog writes correctly and Rating store persists updates.

This baseline is intentionally lightweight, safe, and forward-compatible with the full Learning System in later PRs (PR-060+).

No ML modeling, no analysis, no recommendations — this is data collection + UX stubs only.

3. Problem Statement

The system currently runs pipelines and stores output images, but has:

No structured job-level telemetry, so the Learning System is blind.

No per-job rating mechanism, so the user cannot teach the system which configs produced desirable results.

No durable job history, making it impossible to review past runs at a glance.

No clear lifecycle hook to capture job completion.

To build future features (adaptive config generation, recommended models/samplers/steps, LoRA weighting, pack-specific intelligence, etc.), the system must first persist data about every pipeline run in a structured way.

Thus, PR-045 provides:
“The black box flight recorder + cockpit switches” before any actual Learning occurs.

4. Goals
✔️ Logging Goals

Add a LearningLogV2Writer writing JSONL entries for each completed job.

Ensure log entries contain enough metadata for future Learning phases.

Avoid massive payloads; store structured, consistent, compressed metadata.

✔️ Job History Goals

Create a JobHistoryStoreV2 that persists a rolling record of recent Jobs.

Expose it in the Job History right panel (GUI V2).

✔️ Rating Goals

Add a simple rating control (0–5 stars or numeric slider) in each history entry.

Persist changes in a LearningRatingsV2Store JSONL file.

Wire controller → learning store → GUI refresh.

✔️ Safety

Zero ML, zero inference, zero recommendation logic.

No heavy compute.

No changes to pipeline execution logic or core executor.

✔️ Architecture

Clean separation of concerns:

Logging: src/learning/learning_log_v2.py

Ratings: src/learning/ratings_store_v2.py

Lifecycle wiring: app_controller.py

Rendering: job_history_panel_v2.py

5. Non-goals

Not in this PR:

No interactive comparison tools

No “similar jobs” clustering

No prompt analysis

No pipeline optimization

No statistical modeling

No automation that touches controls or configs

No rewriting of JobQueue, executor, or WebUI logic

No storage compression or archival/indexing (future PR)

Everything here is Phase-1 passive, required to enable Phase-2+ learning.

6. Allowed Files
✔ Learning subsystem

New files:

src/learning/learning_log_v2.py

src/learning/ratings_store_v2.py

src/learning/__init__.py (if missing)

✔ GUI / JobHistory panel

src/gui/panels_v2/job_history_panel_v2.py

src/gui/views/pipeline_tab_frame_v2.py (only to expose/update the panel)

src/gui/theme_v2.py (only for icon/toggle styling; no color changes)

✔ Controller

src/controller/app_controller.py

Only adding job_completed hook

Only adding rating_changed hook

✔ AppState

src/gui/app_state_v2.py

Adding job_history list

Adding accessor/update helpers

✔ Tests

New tests:

tests/learning/test_learning_log_v2.py

tests/learning/test_ratings_store_v2.py

tests/gui_v2/test_job_history_panel_v2.py

tests/controller/test_learning_hooks_v2.py

7. Forbidden Files

No changes to:

src/main.py

src/pipeline/executor.py or executor_v2.py

src/pipeline/job_queue_v2.py

src/pipeline/stage_sequencer_v2.py

src/api/webui_process_manager.py

src/api/healthcheck.py

Any V1 file or compatibility shim

Any theme changes beyond style tokens (PR-041 governs design)

If any of these need work, split into a separate PR.

8. Step-by-step Implementation
A. Create LearningLogV2Writer

New file: src/learning/learning_log_v2.py

Define record schema:

@dataclass
class LearningLogRecordV2:
    job_id: str
    variant_index: int
    variant_total: int
    packs: list[str]
    run_config: dict
    randomization_plan: dict
    outputs: list[str]
    num_outputs: int
    started_at: float
    completed_at: float
    duration_sec: float


Implement append logic:

Write newline-delimited JSON (“JSONL”) into:

logs/learning/learning_log_v2.jsonl

Ensure directory creation if missing.

Prevent blocking:

Writes are synchronous but small.

No threading or async complexity.

B. Create RatingsStoreV2

New file: src/learning/ratings_store_v2.py

Define:

@dataclass
class LearningRatingRecordV2:
    job_id: str
    rating: int   # 0–5
    timestamp: float


Simple append-to-file JSONL store:

File: logs/learning/learning_ratings_v2.jsonl.

Provide helpers:

set_rating(job_id, rating)

get_ratings_dict() -> dict[job_id, int]

C. Integrate into AppController

Modify app_controller.py minimally:

Add attributes:

self._learning_log = LearningLogV2Writer()
self._ratings_store = RatingsStoreV2()


Add hook called by JobService when a job completes:

def on_job_completed(self, job: JobResult):
    self._learning_log.append(self._build_learning_record(job))
    self._app_state.job_history.append(job.to_summary())
    self._job_history_panel.refresh(self._app_state.job_history)


Add rating callback:

def on_rating_changed(self, job_id: str, rating: int):
    self._ratings_store.set_rating(job_id, rating)

D. Implement Job History Panel Enhancements

File: src/gui/panels_v2/job_history_panel_v2.py

For each job entry (scrollable):

Show:

Timestamp

Pack names

Output count + preview icon (if available later)

Variant index / total

Rating control

Rating control:

Five-star widget (unicode ★/☆) styled with theme tokens
or

A numeric slider (0–5) if easier

On rating change:

Call controller:

self._controller.on_rating_changed(job_id, rating)


Should remain fast and not leak memory:

Destroy and recreate grid items on refresh

No live image previews yet (future PR)

E. AppStateV2 Updates

File: src/gui/app_state_v2.py

Add job history tracking:

job_history: list[JobSummaryV2] = field(default_factory=list)


Add helper methods:

add_job_history_entry(job_summary)

get_job_history()

clear_job_history() (future use)

F. Tests
1. test_learning_log_v2.py

Build fake job object with:

run_config dict

randomization_plan dict

output list

Log it

Read JSONL file

Assert fields match

Assert duration recorded

2. test_ratings_store_v2.py

Call set_rating("job123", 4)

Re-read file

Assert rating persisted

3. test_job_history_panel_v2.py

Mock controller

Instantiate panel

Add fake job

Ensure row appears

Simulate rating click

Assert controller callback fired

4. test_learning_hooks_v2.py

Mock JobResult

Call controller.on_job_completed(job)

Assert:

Learning log writer called

AppState job history updated

JobHistoryPanel refresh triggered

9. Required Tests (Failing First)

Before implementation the following tests should fail (or not exist):

tests/learning/test_learning_log_v2.py

tests/learning/test_ratings_store_v2.py

tests/gui_v2/test_job_history_panel_v2.py

tests/controller/test_learning_hooks_v2.py

After implementation all must pass.

10. Acceptance Criteria

PR-045 is complete when:

✔ Learning Log

learning_log_v2.jsonl is written for every job.

Contains:

job_id

run_config

randomization plan

outputs

duration

timestamps

✔ Job History Panel

Shows each completed job in a scrollable list.

Displays:

timestamp

pack names

output count

variant information

Has a rating widget.

✔ Ratings

Changing a rating:

Updates the UI

Writes to learning_ratings_v2.jsonl

Is read back on next boot

✔ Controller

on_job_completed writes LearningLog + updates JobHistory.

on_rating_changed writes to rating store.

✔ No forbidden file changes

Executor / main / WebUI code untouched.

✔ Manual validation

After running a job, user can open Job History and:

See the entry

Click rating

Restart app

Rating persists

11. Rollback Plan

To revert PR-045:

Delete:

src/learning/learning_log_v2.py

src/learning/ratings_store_v2.py

Tests under tests/learning/

Remove controller hooks

Remove job history panel enhancements

Delete learning log / ratings JSONL files

App returns to pre-learning state with no impact on pipeline execution.

12. Codex Execution Constraints

No threading

No async

No executor modification

No heavy IO loops — append-only JSONL only

Design must use theme_v2 styling rules (PR-041) for the rating UI

No database, no pandas, no external libs

Learning V2 stays passive, minimal, predictable.

13. Smoke Test Checklist

After implementation:

python -m pytest tests/learning/test_learning_log_v2.py -q

Run a small pipeline job

Check logs/learning/learning_log_v2.jsonl

Open GUI → Pipeline → Job History

Verify job appears

Click rating

Check learning_ratings_v2.jsonl updated

Restart app → rating persists

If all of that works → PR-045 is ready.