PR-GUI-D26 — Dropdown Normalization.md + Stage Controls + Queue Completion + “WebUI Down” Failure Path (No UI Stall)
Related Canonical Sections

ARCHITECTURE_v2.6: single unified path; no alternate flows; explicit controller event API (no string dispatch). 

ARCHITECTURE_v2.6

Golden Path: Queue transitions must reach COMPLETED/FAILED and move into History (GP1/GP2). 

E2E_Golden_Path_Test_Matrix_v2.6

Intent (what this PR does / does NOT do)
Does

Fix dropdown display + value mapping for Model + VAE (and other WebUI resources) so the UI shows clean names while keeping stable internal IDs.

Restore Pipeline stage checkboxes + ADetailer visibility path so optional stages can be enabled/disabled from Pipeline UI without requiring a PromptPack default.

Fix queue lifecycle completion: jobs must leave Queue on completion/failure and land in History; Queue must not back up. (Matches GP1/GP2 expectations.) 

E2E_Golden_Path_Test_Matrix_v2.6

Convert “WebUI connection refused” during execution into a fast FAIL that:

marks job FAILED

records error in history

continues queue

does not stall UI and does not create empty outputs pretending success

Does NOT

No new architecture, no new job sources, no bypass of NJR-only execution.

No redesign of UI layout/tabs.

No new “manual prompt” fallback (PromptPack-only remains hard invariant). 

ARCHITECTURE_v2.6

Symptoms this PR must resolve (acceptance criteria)

Model/VAE dropdowns show clean names (no hashes/extra metadata blobs).

Stage checkboxes exist and can toggle stages; ADetailer can be enabled from UI (not only via pack defaults).

Queue jobs transition SUBMITTED → QUEUED → RUNNING → COMPLETED/FAILED, then:

disappear from Queue list

appear in History with final status

When WebUI goes down mid-run (e.g., connection refused), the job becomes FAILED quickly, queue continues, UI stays responsive, diagnostics may still trigger as designed (but we do not rely on a stall to recover).

Allowed Files (HARD BOUNDARY)

Codex MUST touch only these files. If any file is missing or paths differ: STOP.

Area	Path	Allowed change
GUI resource display	src/gui/dropdown_loader_v2.py	normalize display labels + value mapping
Pipeline UI controls	src/gui/pipeline_panel_v2.py	ensure stage checkboxes + adetailer toggle wiring
Sidebar integration (if needed)	src/gui/sidebar_panel_v2.py	ensure pipeline panel hooks are reachable
Controller glue (only for wiring)	src/controller/app_controller.py	minimal wiring for stage toggles + dispatcher-safe events
Queue lifecycle	src/queue/job_queue.py and/or src/queue/single_node_runner.py	completion/removal + history handoff
JobService lifecycle	src/controller/job_service.py	ensure completion/failure triggers state transitions + history write
History persistence	src/history/jsonl_job_history_store.py (or your existing history store file)	record final status + error payload
API failure classification	src/api/api_client.py (or equivalent)	treat connection refused as fast job failure

Tests only (new/modified):

tests/gui_v2/test_pipeline_left_column_config_v2.py (only if currently failing / to assert checkboxes exist)

tests/queue/test_single_node_runner_loopback.py

tests/queue/test_queue_njr_path.py

tests/controller/test_app_controller_pipeline_integration.py (if queue/run wiring still flaky)

Add: tests/queue/test_queue_completion_to_history.py (new, small)

If any of these don’t exist exactly: STOP and report (no guessing). Per v2.7.1-X drift rules. 

PR TEMPLATE — v2.7.1-X

Implementation Steps (ORDERED, NON-OPTIONAL)
Step 1 — Dropdown normalization (display label != stored value)

File: src/gui/dropdown_loader_v2.py

Implement a small normalizer per resource type:

Models: display title (or model_name) only; strip trailing [hash] patterns.

VAE: display base filename (or model_name), not full metadata blob.

Ensure Combobox values store an internal stable key (preferably the raw API identifier), but displayed text is clean.

Add/adjust a helper like:

normalize_model_label(raw: str) -> str

normalize_vae_label(raw: str) -> str

Ensure this does not change any job-building semantics; it is display/value mapping only.

Must prove: selecting an item produces the same internal config keys as before (just prettier display).

Step 2 — Restore stage checkboxes + ADetailer enable path

File: src/gui/pipeline_panel_v2.py

Confirm stage controls exist in the panel class (or re-add them if removed):

txt2img (always on / not hideable)

refiner

hires

upscale

adetailer

Ensure toggles update AppState / controller through the explicit controller entrypoints (no reflection / string dispatch). 

ARCHITECTURE_v2.6

Ensure ADetailer UI becomes reachable when enabled:

either show panel section immediately when checkbox is enabled

or show a collapsed section that can be expanded once enabled

Add a GUI test assertion (or fix existing) verifying the checkbox widgets exist.

Step 3 — Queue completion → remove from queue → write to history

Files: src/queue/single_node_runner.py, src/queue/job_queue.py, src/controller/job_service.py, history store file

On job completion:

mark job status COMPLETED

persist history entry (including summary + result metadata)

remove job from in-memory queue structure

persist queue_state_v2

On job failure:

mark FAILED with error details

persist history entry including error envelope

remove job from queue

continue runner loop to next job

Confirm Golden Path expectation: Queue shows progress and empties as jobs finish (GP1/GP2). 

E2E_Golden_Path_Test_Matrix_v2.6

New test (required): tests/queue/test_queue_completion_to_history.py

submit job

runner executes stub success → job ends in history and not in queue

submit job

runner executes stub failure → job ends FAILED in history and not in queue

Step 4 — “Connection refused” becomes fast FAIL (no hang, no empty outputs)

File: API client file (e.g., src/api/api_client.py)

Detect connection refused / max retries for POST /options or /txt2img:

raise a typed exception that the runner/job_service translates into job FAILED

Ensure failure path:

does not block UI thread

does not stall queue runner

does not create “success-looking” empty output folders

Ensure the error message is recorded in history.

Step 5 — Minimal controller wiring only if required

File: src/controller/app_controller.py

Only if Step 2 requires controller hooks for stage toggles:

add minimal explicit entrypoints (or use existing) to write stage flags into AppState.

do not add new alternate execution flows.

keep NJR-only execution invariant intact.

Test Plan (MANDATORY — exact commands + output)
Required unit/system lanes
python -m pytest -q tests/queue
python -m pytest -q tests/controller/test_app_controller_pipeline_integration.py
python -m pytest -q tests/gui_v2/test_pipeline_left_column_config_v2.py
python -m pytest -q tests/gui_v2/test_pipeline_stage_checkbox_order_v2.py

Required “core lanes” (your standard)
python -m pytest -q tests/controller tests/queue tests/gui_v2

New test file
python -m pytest -q tests/queue/test_queue_completion_to_history.py


If any fail: fix immediately (no skipping). This matches v2.7.1-X proof rules. 

PR TEMPLATE — v2.7.1-X

Evidence Commands (MANDATORY)
git diff
git diff --stat
git status --short
git grep -n "PipelineConfig" src/            # ensure no regression vs invariants mindset
git grep -n "after(" -n src/ | findstr /i "queue job_service"   # show UI marshaling not reintroduced incorrectly (Windows)

Manual proof (required)

Start app:

python -m src.main


Confirm dropdowns: model + vae show clean names.

In Pipeline tab: enable ADetailer + one optional stage.

Add to Queue twice; confirm:

Queue shows RUNNING for first, second waits

first completes → leaves Queue → appears in History

Stop WebUI (or point URL wrong) and enqueue a job:

job becomes FAILED quickly

queue continues

UI stays responsive