#ARCHIVED
> Superseded by CHANGELOG.md in repository root

## Unreleased

- Refactored StableNewGUI layout wiring into AppLayoutV2 helper while preserving V2 panel structure and behavior.
- main_window.py restructured: layout delegated to AppLayoutV2, controller wiring grouped; no user-visible UI changes.
- Added learning execution runner and controller hooks (PR-LEARNING-V2-EXECUTION-001) to orchestrate learning plans without GUI dependencies.
- LearningRecordWriter now appends JSONL records and pipeline runs can emit LearningRecords when learning is enabled (passive L2 path).
- GUI V2 adds a Learning toggle and Review Recent Runs dialog for rating/tagging LearningRecords; learning remains opt-in and off by default.
- Learning adapter/controller now expose recent-record summaries and update-feedback hooks to support the GUI review dialog.
- Queue foundation (PR-#35) adds Job model, thread-safe JobQueue, and SingleNodeJobRunner with accompanying queue tests.
