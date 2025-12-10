PR-109 – Job History V2 Integration for New Run Path.md

Risk Tier: Medium (Tier 2 – history model + GUI panel)
Baseline: StableNew-snapshot-20251203-071519.zip + repo_inventory.json
Related PRs: PR-103 (run bridge), PR-107 (StageExecutionPlan), PR-108 (payloads)

1. Intent

Give the V2 run path a real, unified job history so:

Every run (DIRECT or QUEUE) leaves a consistent JobRecord.

The Job History Panel V2 reads from that unified history API instead of talking to legacy controllers.

We preserve the user-facing behavior from the old GUI history (ordering, “latest job”, basic fields) using the archived tests as behavioral documentation.

This is primarily a model + GUI integration PR. It does not change how jobs execute; it just records their existence and exposes them to the UI.

2. Scope
In-Scope

src/pipeline/job_history.py (or equivalent module that owns job history)

Define/extend JobRecord.

Expose a JobHistoryStore / JobHistoryService API consumed by controllers + GUI.

src/gui/panels/job_history_panel_v2.py

Wire the panel to the new history API.

Present fields for job id, run_mode, source, prompt origin, timestamp, etc.

archive/legacy_tests/tests_gui_v2_legacy/test_job_history_panel_v2.py

Read only as specification of behavior (sort order, filters, column semantics).

tests/gui_v2/test_job_history_panel_v2.py (new)

Exercise the V2 panel using the new history API.

Out-of-Scope

Any changes to job execution, pipeline runner, executor, or queue logic.

Learning tab integration (that will use history later, but not in this PR).

Forbidden core files (main entrypoints, executor, etc.).

3. Design
3.1 JobRecord and JobHistoryStore

File: src/pipeline/job_history.py

Introduce or refine the history model.

3.1.1 JobRecord

Use a dataclass (or Pydantic equivalent if you already do) to describe one job:

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from datetime import datetime


@dataclass
class JobRecord:
    job_id: str
    run_mode: str       # "direct" | "queue"
    source: str         # "run" | "run_now" | "add_to_queue"
    prompt_source: str  # "manual" | "pack"
    prompt_pack_id: Optional[str] = None

    # summary fields
    stage_count: int = 0
    has_adetailer: bool = False
    has_upscale: bool = False

    # config snapshot fingerprint
    config_hash: Optional[str] = None

    # timestamps
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    # raw-ish metadata (for future learning / debugging)
    meta: Mapping[str, Any] = field(default_factory=dict)


You can adjust field names to match your existing run/job models; important thing is: run_mode, source, prompt source, and timestamps are always present.

3.1.2 JobHistoryStore

A simple in-memory store interface (backed by a list; can grow into persistent storage later):

class JobHistoryStore:
    def __init__(self) -> None:
        self._jobs: list[JobRecord] = []

    def add_job(self, record: JobRecord) -> None:
        self._jobs.append(record)

    def update_job_completion(
        self,
        job_id: str,
        *,
        completed_at: Optional[datetime] = None,
        meta: Optional[Mapping[str, Any]] = None,
    ) -> None:
        for job in reversed(self._jobs):
            if job.job_id == job_id:
                job.completed_at = completed_at or datetime.utcnow()
                if meta is not None:
                    # Shallow merge or overwrite
                    job.meta = {**job.meta, **meta}
                return

    def list_jobs(self) -> list[JobRecord]:
        # Most recent first
        return sorted(self._jobs, key=lambda j: j.started_at, reverse=True)

    def latest_job(self) -> Optional[JobRecord]:
        jobs = self.list_jobs()
        return jobs[0] if jobs else None


You may already have something like this; if so, extend it rather than duplicate.

3.2 Wiring job creation and completion into the new run path

Where: whichever component currently creates and finishes jobs (likely JobService, JobController, or PipelineController).

This PR does not change execution logic, but it must:

On job creation:

Build a JobRecord using:

job_id from the job model.

run_mode and source from the RunConfig/bridge (PR-103).

prompt_source + prompt_pack_id from RunConfig or job metadata.

stage_count and has_adetailer from the StageExecutionPlan (if available).

config_hash from a stable hash of the pipeline config (stringified JSON, etc.).

Call job_history_store.add_job(record).

On job completion:

When a job reaches a terminal state (success or error), call:

job_history_store.update_job_completion(
    job_id,
    completed_at=job.completed_at,
    meta={
        "status": job.status,
        "error": str(job.error) if job.error else None,
        "images_path": job.output_path,
    },
)


Make sure this call happens for both DIRECT (run-now) and QUEUE jobs.

Note: if you have a JobService singleton, it’s an ideal place to own a single JobHistoryStore instance and expose it to controllers GUI.

3.3 Job History Panel V2

File: src/gui/panels/job_history_panel_v2.py

The panel should:

Depend on a job_history or job_service that exposes list_jobs() / latest_job().

Fill its table using only JobRecord data; no direct poking at controllers and no old V1 glue.

3.3.1 Data source

Constructor or setter should receive a JobHistoryStore (or adapter):

class JobHistoryPanelV2(ttk.Frame):
    def __init__(self, master, *, job_history: JobHistoryStore, theme: Any = None, **kwargs):
        super().__init__(master, **kwargs)
        self.job_history = job_history
        self.theme = theme
        ...


If existing code passes something like app_controller, add a small adapter property that returns app_controller.job_history.

3.3.2 Rendering rows

Define a method that converts a JobRecord into a row tuple (or dict):

    def _job_to_row(self, job: JobRecord) -> tuple[str, ...]:
        return (
            job.job_id,
            job.run_mode,
            job.source,
            job.prompt_source,
            job.prompt_pack_id or "",
            str(job.stage_count),
            "yes" if job.has_upscale else "no",
            "yes" if job.has_adetailer else "no",
            job.started_at.isoformat(timespec="seconds"),
            job.completed_at.isoformat(timespec="seconds") if job.completed_at else "",
        )


Then refresh() can:

    def refresh(self) -> None:
        # clear table
        self._clear_rows()
        for job in self.job_history.list_jobs():
            self._insert_row(self._job_to_row(job))


Sort order and filtering should mirror behavior from the legacy tests:

Latest job at top.

Filters (if present) by prompt pack vs manual can use job.prompt_source.

4. Legacy test parity

File: archive/legacy_tests/tests_gui_v2_legacy/test_job_history_panel_v2.py

Use this file as documentation:

Match expectations for:

What columns exist.

Which job is considered “latest.”

Basic filter/sorting behavior (if there were tests for that).

You don’t change this file; you just mirror the behavioral expectations in the new V2 tests.

5. New GUI Tests

File: tests/gui_v2/test_job_history_panel_v2.py (new)

These tests should:

Instantiate JobHistoryStore.

Insert a few JobRecords directly.

Construct JobHistoryPanelV2 with this store.

Trigger refresh() and then query the underlying widget model (list/tree adapter) to assert row content.

No Tk mainloop or full GUI boot necessary; tests should stay focused on panel behavior, not window management.

5.1 Sample tests

Latest job appears first

Create two JobRecords with different started_at.

Add them to history_store.

Call panel.refresh().

Assert first row corresponds to the job with the later started_at.

run_mode and source visible

Create a DIRECT/RUN job and QUEUE/RUN_NOW job.

Assert that the rows include run_mode and source strings in the expected columns.

Prompt source and pack id

Create:

One manual job (prompt_source="manual").

One pack job (prompt_source="pack", prompt_pack_id="pack-123").

Assert rows show "manual" vs "pack" and pack-123 in the right column.

Stage_count / flags

Insert a job with stage_count=4, has_upscale=True, has_adetailer=True.

Assert the row shows 4, and columns for upscale/adetailer show “yes”.

6. Validation & Acceptance Criteria

Commands:

pytest tests/gui_v2/test_job_history_panel_v2.py
pytest tests/gui_v2
pytest tests/pipeline  # to ensure history hooks didn’t break pipeline tests


Acceptance:

 JobRecord and JobHistoryStore (or equivalent) exist and are used to record every job, direct or queued.

 On job creation, a JobRecord is created and added to the store with:

job_id, run_mode, source, prompt_source, prompt_pack_id.

stage_count, has_upscale, has_adetailer.

config_hash and started_at.

 On job completion, JobHistoryStore.update_job_completion(...) is used to fill completed_at and final meta fields.

 JobHistoryPanelV2 pulls its data exclusively from the history store and renders:

Latest job first.

run_mode, source, prompt_source, prompt_pack_id in proper columns.

 New tests in tests/gui_v2/test_job_history_panel_v2.py:

Cover ordering, basic columns, and run_mode visibility.

 Legacy job history tests in archive/legacy_tests/... are left unchanged and their expectations are met.