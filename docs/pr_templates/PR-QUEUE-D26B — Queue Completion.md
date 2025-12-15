PR-QUEUE-D26B — Queue Completion.md → History + WebUI-Down Fast FAIL (No Empty Success Outputs)
Related Canonical Sections

Golden Path: Queue transitions must reach COMPLETED/FAILED and move to History (GP1/GP2).

ARCHITECTURE_v2.6: single unified path; no alternate execution flows.

Intent
Does

Ensure queue jobs complete/fail and leave queue, and always write a final record into History.

Convert WebUI “connection refused / max retries” into fast FAIL with:

Job marked FAILED

Error recorded in history

Queue continues

No fake empty “success” output folders

Does NOT

No GUI changes except those required for tests (but this PR should not touch GUI at all).

No new execution paths; no NJR bypass.

Acceptance Criteria (binary)

Jobs transition SUBMITTED → QUEUED → RUNNING → COMPLETED/FAILED

Completed/failed jobs disappear from queue and appear in History with final status.

When WebUI is down mid-run, job is FAILED quickly, queue continues, UI remains responsive (by virtue of no blocking in queue thread).

Allowed Files (HARD BOUNDARY)

Codex MUST touch only these files. If any path differs or file missing: STOP.

Area	Path	Allowed change
Queue lifecycle	src/queue/job_queue.py and/or src/queue/single_node_runner.py	completion/removal + history handoff
JobService lifecycle	src/controller/job_service.py	ensure completion/failure triggers state transitions + history write
History persistence	src/history/jsonl_job_history_store.py (or actual history store used)	record final status + error payload
API failure classification	src/api/api_client.py (or equivalent)	raise typed exception on connection refused / max retries

Tests only (new/modified):

tests/queue/test_single_node_runner_loopback.py

tests/queue/test_queue_njr_path.py

Add: tests/queue/test_queue_completion_to_history.py (new)

Implementation Steps (ORDERED, NON-OPTIONAL)
Step 1 — Queue completion → remove from queue → write to history

Files: src/queue/single_node_runner.py, src/queue/job_queue.py, src/controller/job_service.py, history store file

On success:

mark job COMPLETED

persist history entry (include summary + result metadata)

remove job from queue data structures

persist queue_state_v2

On failure:

mark job FAILED + error envelope

persist history entry (error included)

remove job from queue

continue loop to next job

Must comply with GP1/GP2 behavior.

Step 2 — WebUI down → fast FAIL (typed exception)

File: src/api/api_client.py (or actual API layer used for POST)

When POST retries exhaust due to connection refused:

raise a typed exception (e.g., WebUIUnavailableError) that carries endpoint + error detail.

Runner/job_service must translate it into:

FAILED job

history write

queue continues

Ensure no “success-looking” output folder is committed as final output unless at least one image artifact exists.

Step 3 — Add new test: completion goes to history

File: tests/queue/test_queue_completion_to_history.py (new)

Test cases:

Success: submit job → runner executes stub success → job not in queue; history contains COMPLETED.

Failure: submit job → runner stub raises typed WebUI error → job not in queue; history contains FAILED + error message.

Test Plan (MANDATORY)
python -m pytest -q tests/queue/test_single_node_runner_loopback.py
python -m pytest -q tests/queue/test_queue_njr_path.py
python -m pytest -q tests/queue/test_queue_completion_to_history.py
python -m pytest -q tests/queue

Evidence Commands (MANDATORY)
git diff
git diff --stat
git status --short
git grep -n "PipelineConfig" src/

Manual Proof (required)

Start StableNew

Enqueue 2 jobs

Observe:

first RUNNING then COMPLETED/FAILED

it leaves queue and appears in history

second proceeds

Stop WebUI and enqueue:

job becomes FAILED quickly

queue continues