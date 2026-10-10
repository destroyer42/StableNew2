# PR-GUI-111 — Thumbnail Recovery and Operator Tooltip Correctness

Status: COMPLETE / ACCEPTED / INTEGRATED (PR #76; hosted `required` and GUI `affected` lanes passed).

Narrow corrective follow-up to PR-GUI-110 (`PR-GUI-110_Focused_Operator_Workspace.md`). Presentation only: no generation,
queue admission, NJR, runtime or controller behavior changed. Execution profile: Narrow, known root cause; Claude Code
Sonnet 5.5 / Codex GPT-6.1 Sol, Medium. Controller Surface Assessment: no controller touched.

## Durable contracts

**Thumbnail request recovery** (`src/gui/widgets/thumbnail_widget_v2.py`). A request is "in flight" only while a worker
exists that will complete it. If the worker cannot be started, only that request's in-flight marker is released (a newer
selection keeps its own), the widget shows a neutral "Preview unavailable" state, the selected/openable source path is kept,
and the same path can be retried. An unexpected exception inside the decode worker still completes the request (as the same
recoverable failure) instead of leaving it permanently active. Failures are logged by exception type only (no local paths).
Unchanged: latest-request-wins, one active decode per path, no re-decode on resize, no stale or post-destroy result.

**Combobox tooltips** (`src/gui/tooltip.py`). Pointer hover keeps the ordinary help tooltip for every combobox. Keyboard
focus schedules a tooltip only when the selected value is truncated at its rendered width/font, and then shows the complete
value together with any existing help text. Focus-out, pointer-leave, click and selection change still dismiss it;
`install_full_value_tooltips` stays idempotent (no duplicate handlers) and never changes the value or focus.

**Experimental opt-in** (Video Workflow). Covered by regression tests, no production change was needed: the per-job
authorization is cleared whenever the selected workflow identity changes (experimental -> ordinary -> experimental,
experimental A -> experimental B), survives ordinary edits within an unchanged workflow, and each submission serializes the
explicit current value through the one existing callback.

## Tests

`tests/gui_v2/test_thumbnail_tooltip_recovery_111.py`. Before the repair, the worker-start failure, the superseded-request
start failure, the unexpected decode failure and the fitting-value focus tooltip tests failed for the intended reason; the
remaining coverage (stale/duplicate/destroy guards, truncated focus tooltip, hover help, idempotence, opt-in transitions)
guards behavior that already held.

## Deferred (not repaired)

One-pixel Review canvas edge; speculative duplicate-tooltip cleanup when a later `attach_tooltip` replaces a tooltip; Review
preview height redesign.
