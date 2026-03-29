# PR-CTRL-272 - Content Visibility Resolver and Selector Wiring

Status: Completed 2026-03-27

## Summary

This PR added the shared content-visibility resolver and routed non-execution
selection paths through it so SFW filtering and redaction decisions come from
one place instead of being duplicated per view.

## Delivered

- added `src/controller/content_visibility_resolver.py` as the shared resolver
  for allow/block/redact decisions
- wired prompt-pack discovery in `src/controller/app_controller.py` through the
  resolver so pack selection follows the active mode
- wired `src/controller/job_history_service.py` to filter and redact history
  payloads consistently
- added prompt-redaction helpers in `src/gui/prompt_workspace_state.py`
- routed `src/gui/widgets/lora_picker_panel.py` through resolver-backed
  filtering
- normalized visibility metadata in
  `src/learning/output_scanner.py` and
  `src/learning/discovered_review_store.py` for discovered-review paths
- added deterministic regression coverage for resolver decisions, history
  redaction, pack filtering, prompt redaction, output-scan classification,
  store normalization, and LoRA filtering

## Key Files

- `src/controller/content_visibility_resolver.py`
- `src/controller/app_controller.py`
- `src/controller/job_history_service.py`
- `src/gui/prompt_workspace_state.py`
- `src/gui/widgets/lora_picker_panel.py`
- `src/learning/output_scanner.py`
- `src/learning/discovered_review_store.py`
- `tests/controller/test_content_visibility_resolver.py`

## Tests

Focused verification passed:

- `pytest -q tests/controller/test_content_visibility_resolver.py`
- `pytest -q tests/controller/test_job_history_service.py tests/controller/test_app_controller_packs.py tests/gui_v2/test_prompt_workspace_state_negative.py tests/gui_v2/test_lora_picker_panel_v2.py`
- `python -m compileall src/controller/content_visibility_resolver.py src/controller/app_controller.py src/controller/job_history_service.py src/gui/prompt_workspace_state.py src/gui/widgets/lora_picker_panel.py src/learning/output_scanner.py src/learning/discovered_review_store.py tests/controller/test_content_visibility_resolver.py`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/PR-CTRL-272-Content-Visibility-Resolver-and-Selector-Wiring.md`

## Notes

Execution behavior did not change in this PR. It only centralized selector and
redaction policy for controller, prompt, history, and discovered-review
surfaces.
