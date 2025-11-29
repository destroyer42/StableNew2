# Archive

This directory stores legacy and prior-work artifacts that are no longer part of the active StableNew codebase but are kept for reference. Nothing in `archive/` should be imported by active modules or executed as part of the default test suite.

### Rules
- Move files here only when they are clearly legacy or unused and have been confirmed as safe to exclude from active execution.
- Do not place V2 work-in-progress or stage card implementations here.
- Keep `ARCHIVE_MAP.md` updated with every move to preserve the original path and reason.

### Layout
- `tests_v1/` — legacy test suites that should not run with the active V2 stack.
- Additional subfolders may be added (e.g., `gui_v1`, `pipeline_v1`, `prior_work`) as other legacy clusters are archived.
