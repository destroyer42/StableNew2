PR-GUI-D26A — Dropdown NormalizationV2.md + Stage Controls + ADetailer Enable Path
Related Canonical Sections

ARCHITECTURE_v2.6: single unified path; explicit controller event API; no alternate flows.

Intent
Does

Normalize Model + VAE dropdown display labels (clean names) while preserving stable internal values.

Restore Pipeline stage checkboxes and ensure ADetailer can be enabled from UI (not only via PromptPack defaults).

Does NOT

No queue lifecycle changes.

No runner changes.

No API client changes.

No new execution path; no manual prompt fallback; no architectural drift.

Acceptance Criteria (binary)

Model dropdown shows clean model names (no hashes/extra metadata blobs).

VAE dropdown shows clean VAE names.

Stage checkboxes are visible and toggling them updates AppState/controller.

ADetailer UI becomes reachable when enabled (checkbox → ADetailer panel visible/expandable).

Allowed Files (HARD BOUNDARY)

Codex MUST touch only these files. If any path differs or file missing: STOP.

Area	Path	Allowed change
GUI resource display	src/gui/dropdown_loader_v2.py	normalize display labels + value mapping
Pipeline UI controls	src/gui/pipeline_panel_v2.py	ensure stage checkboxes + adetailer toggle wiring
Sidebar integration (if needed)	src/gui/sidebar_panel_v2.py	ensure stage controls are reachable/visible
Controller glue (only if required)	src/controller/app_controller.py	minimal wiring entrypoints for stage toggles (dispatcher-safe)

Tests only (new/modified):

tests/gui_v2/test_pipeline_left_column_config_v2.py (only if failing; assert checkboxes/panel present)

tests/gui_v2/test_pipeline_stage_checkbox_order_v2.py

tests/gui_v2/test_pipeline_config_panel_lora_runtime.py (only if your changes touch panel init kwargs)

Implementation Steps (ORDERED, NON-OPTIONAL)
Step 1 — Dropdown normalization (display label != stored value)

File: src/gui/dropdown_loader_v2.py

Add/adjust helpers:

normalize_model_label(raw: str) -> str

normalize_vae_label(raw: str) -> str

Implement rules:

Model: display only the human name; strip trailing [hash] and any extra metadata suffixes.

VAE: display base filename / friendly name, not full metadata blob.

Ensure combobox values:

displayed list uses normalized labels

underlying selected value maps back to the stable key used by controller (raw id / raw name — whatever is current canonical in the app)

Must prove: selecting an item results in the same internal config keys as before (no behavior change besides display).

Step 2 — Restore stage checkboxes + ADetailer enable path

File: src/gui/pipeline_panel_v2.py

Ensure stage checkbox controls exist and are visible:

txt2img (always enabled / may be disabled UI)

refiner

hires

upscale

adetailer

Ensure checkbox events:

write state into AppState OR call explicit controller entrypoints

no string-dispatch, no reflection.

Ensure ADetailer panel:

becomes visible/expandable when enabled from UI

doesn’t require loading a pack that already contains ADetailer config

Step 3 — Sidebar / layout integration only if necessary

File: src/gui/sidebar_panel_v2.py (only if tests indicate stage controls are not reachable)

Ensure pipeline panel (or its stage section) is actually attached to the visible layout of the Pipeline tab.

Step 4 — Minimal controller glue only if required

File: src/controller/app_controller.py (only if missing explicit entrypoints)

Add minimal explicit methods to accept stage toggle state updates.

Must only mutate AppState; must not create any new run/queue path.

Test Plan (MANDATORY)
python -m pytest -q tests/gui_v2/test_pipeline_stage_checkbox_order_v2.py
python -m pytest -q tests/gui_v2/test_pipeline_left_column_config_v2.py
python -m pytest -q tests/gui_v2


If failures occur in:

test_pipeline_config_panel_lora_runtime.py due to widget kwargs leaks, fix those in the allowed files (don’t touch Tkinter base).

Evidence Commands (MANDATORY)
git diff
git diff --stat
git status --short
git grep -n "PipelineConfig" src/

Manual Proof (required)

python -m src.main

Confirm dropdown labels are clean.

Confirm stage checkboxes visible and ADetailer can be enabled from UI.