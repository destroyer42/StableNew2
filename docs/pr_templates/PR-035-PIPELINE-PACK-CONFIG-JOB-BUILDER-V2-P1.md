PR-035-PIPELINE-PACK-CONFIG-JOB-BUILDER-V2-P1

Pack selector becomes a job/config tool, not a prompt editor

1. Title

PR-035-PIPELINE-PACK-CONFIG-JOB-BUILDER-V2-P1 — Re-scope Pipeline Pack Selector into Config + Job Builder

2. Summary

This PR makes the Pipeline tab pack selector do what you actually need:

Treat each prompt pack as a runnable unit with its own config.

Let you:

Load a pack’s config into the stage cards (“Load current config”).

Apply the current stage config back onto one or more packs (“Apply config to pack(s)”).

Add the selected pack(s) into a Job draft with their bound configs (“Add to Job”).

Keep prompt editing strictly in the Prompt tab:

Pipeline pack selector stays read-only for prompt text; it only uses that preview for context.

We also add the missing semantics around presets vs pack configs, and lay the groundwork for randomization-at-job-creation without implementing the full queue system yet.

3. Problem Statement

Right now:

The Pipeline tab still has:

A single preset dropdown.

A single pack selector with a text preview field under it (first prompt of the pack).

But the pack selector behavior is fuzzy:

It still smells like “Prompt editor” instead of “Job builder”.

There’s no clear way to:

Load a pack’s config into the stage cards.

Push the current config back into the pack.

Apply presets to one or more packs.

Build a Job from selected packs + configs.

Randomization logic conceptually belongs at job creation (per pack, per run), but today:

Randomization config isn’t clearly attached to a pack at job creation.

The “randomization module” is pipeline-centric, not job-centric.

We need the Pipeline pack selector to be the bridge between:

Packs (from Prompt world), and

Jobs (what the pipeline actually runs), including:

Config binding,

Preset apply,

Randomization config snapshot.

4. Goals
G1 — Re-scope Pipeline pack selector to job/config semantics

The pack list in Pipeline tab must:

Support multi-select.

Stay read-only for text (no editing here).

Provide buttons/actions for:

Load current config — read the selected pack’s config into the stage cards.

Apply config to pack(s) — write current stage config (including randomization config) into one or more selected packs.

Add to Job — add one or more packs to the current job draft, along with their bound configs.

G2 — Clarify Preset <–> Pack Config relationship

The existing Pipeline preset combobox should:

Represent pipeline config presets (People, Landscapes, Night, etc.).

Gain the following actions:

Apply to default

Set the “global default run config” from this preset.

Apply to selected pack(s)

Copy preset values into the configs of all selected packs.

Load to stages

Load the preset values into the stage cards (for further tweaking).

Save

Save the current stage config (including randomizer parameters) as a preset.

Delete

Remove an existing preset (with confirmation).

All of these operate on configs only, not prompt text.

G3 — Introduce a minimal Job draft model in state

Add a small JobDraft representation to AppStateV2, something like:

class JobDraft:
    packs: list[PackSelection]  # pack_id + config snapshot (+ randomizer config)
    # Future: flags for randomization, batch runs, etc.


Add to Job in Pipeline tab:

Appends selected pack(s) + their configs to JobDraft.

Triggers a simple update in the right-hand Job Preview panel (just a summary list for now).

G4 — Respect randomization at job creation (no full queue yet)

When a pack is added to a job:

The randomization-related part of the config (whatever fields exist today in RunConfig) should be snapshotted into the job’s pack entry.

No complex scheduling logic yet; just a clear place where randomizer config attaches to a job.

5. Non-goals

Implementing the full job queue or history UI/logic (that’s future PRs).

Implementing advanced randomization strategies beyond using the existing RunConfig/randomizer flags.

Changing how prompts are edited, saved, or managed in the Prompt tab.

Changing how the pipeline actually executes jobs beyond reading a future job structure.

6. Allowed Files

State & controller (light-touch)

src/gui/app_state_v2.py

Introduce a JobDraft structure and fields for job preview state.

src/controller/app_controller.py

Add handlers for:

Pack config load/apply.

Preset → default/pack/stage operations.

“Add to Job”.

GUI / views (Pipeline tab & associated panels)

src/gui/views/pipeline_tab_frame_v2.py

src/gui/panels_v2/sidebar_panel_v2.py
(pack list, preset combobox, and new buttons)

src/gui/panels_v2/pipeline_config_panel_v2.py
(stage config read/write, randomization config exposure as part of config)

src/gui/panels_v2/preview_panel_v2.py

Only to render a Job preview summary from JobDraft.

Tests

tests/controller/test_pipeline_pack_config_job_builder_v2.py

tests/gui_v2/test_pipeline_pack_selector_job_actions_v2.py

7. Forbidden Files

Do not modify:

src/pipeline/pipeline_runner.py

src/pipeline/stage_sequencer.py

src/api/* (WebUI/HTTP/API clients)

Any legacy/V1 GUI components.

Learning/queue/cluster modules (job queue/history will be future PRs).

If it looks like something in these areas must change to complete this PR, stop and report instead of editing.

8. Step-by-step Implementation
Step 1 — Define JobDraft in AppStateV2

In app_state_v2.py:

Add a simple job draft structure:

@dataclass
class PackJobEntry:
    pack_id: str
    pack_name: str
    config_snapshot: dict[str, Any]  # includes randomization-related fields

@dataclass
class JobDraft:
    packs: list[PackJobEntry] = field(default_factory=list)


Add to AppStateV2:

self.job_draft: JobDraft = JobDraft()


Add helper methods:

add_packs_to_job_draft(entries: list[PackJobEntry])

clear_job_draft()

Possibly a simple subscriber mechanism (if consistent with existing pattern) so the preview panel can update when the job changes.

Step 2 — Wire Pipeline pack selector as job/config tool

In sidebar_panel_v2.py:

Ensure the pack list:

Supports multi-select (selectmode="extended").

Leaves the existing read-only prompt preview (text field below) intact.

Add buttons:

Load current config

Apply config to pack(s)

Add to Job

Wire events:

Load current config:

If exactly one pack selected:

Call controller.on_pipeline_pack_load_config(pack_id).

If none/multiple selected:

Show a gentle message/tooltip or silently ignore.

Apply config to pack(s):

For all selected packs:

Call controller.on_pipeline_pack_apply_config(pack_ids: list[str]).

Add to Job:

For all selected packs:

Call controller.on_pipeline_add_packs_to_job(pack_ids: list[str]).

Step 3 — Controller logic for configs & presets

In app_controller.py:

Implement:

def on_pipeline_pack_load_config(self, pack_id: str) -> None:
    # 1. Load pack’s config via ConfigManager/pack metadata.
    # 2. Update RunConfig / stage cards with those values.

def on_pipeline_pack_apply_config(self, pack_ids: list[str]) -> None:
    # 1. Read current RunConfig from AppStateV2/stage panel.
    # 2. Save config into each pack’s metadata.

def on_pipeline_add_packs_to_job(self, pack_ids: list[str]) -> None:
    # 1. For each pack, build PackJobEntry with:
    #    - pack_id, pack_name
    #    - config_snapshot (including randomization flags from RunConfig)
    # 2. Call app_state.add_packs_to_job_draft(entries).


Preset actions on the existing preset combobox:

Apply to default

Apply to selected pack(s)

Load to stages

Save

Delete

These can be implemented as methods like:

def on_pipeline_preset_apply_to_default(self, preset_name: str) -> None: ...
def on_pipeline_preset_apply_to_packs(self, preset_name: str, pack_ids: list[str]) -> None: ...
def on_pipeline_preset_load_to_stages(self, preset_name: str) -> None: ...
def on_pipeline_preset_save_from_stages(self, preset_name: str) -> None: ...
def on_pipeline_preset_delete(self, preset_name: str) -> None: ...


Using ConfigManager as the single source for preset serialization.

Step 4 — Keep randomizer config attached to job creation

When building config_snapshot for PackJobEntry:

Include the randomization parameters currently defined in RunConfig (whatever exists today).

No new randomizer logic yet; just ensure these values are present in the snapshot so later queue/runner stages can use them.

Step 5 — Job Preview summary panel

In preview_panel_v2.py:

Add a minimal method:

def update_from_job_draft(self, job_draft: JobDraft) -> None:
    # Render a simple summary:
    # - number of packs
    # - list of pack names
    # - indicator if randomizer is enabled in their config_snapshot
    # - maybe shown as multi-line text or simple list


Hook this up from AppStateV2/Controller:

After add_packs_to_job_draft, call preview_panel.update_from_job_draft.

(We’re not implementing queue/history yet; just the “current job draft” view.)

9. Required Tests (Failing first)

tests/controller/test_pipeline_pack_config_job_builder_v2.py

Fails initially because:

on_pipeline_pack_load_config, on_pipeline_pack_apply_config, on_pipeline_add_packs_to_job don’t exist.

JobDraft doesn’t exist on AppStateV2.

tests/gui_v2/test_pipeline_pack_selector_job_actions_v2.py

Fails because:

New buttons are not present.

Pack list is not multi-select.

Job preview panel doesn’t update when “Add to Job” is clicked.

10. Acceptance Criteria

Pipeline tab left column:

One pack selector listbox, multi-select enabled.

Existing prompt preview text area under the list remains and shows first prompt.

Buttons:

Load current config

Apply config to pack(s)

Add to Job

Single preset combobox with the 5 actions (apply default, apply to packs, load to stages, save, delete).

JobDraft:

Lives in AppStateV2.

Accumulates pack+config entries when “Add to Job” is invoked.

Contains randomization parameters from current config.

Right-hand preview:

Shows a simple textual summary of the Job draft:

List of packs added.

Whether randomizer is enabled for their configs (basic indicator).

No prompt editing possible from Pipeline tab.

All tests in this PR pass and no existing tests break.

11. Rollback Plan

Revert all changes to:

app_state_v2.py

app_controller.py

sidebar_panel_v2.py

pipeline_tab_frame_v2.py

pipeline_config_panel_v2.py

preview_panel_v2.py

tests/controller/test_pipeline_pack_config_job_builder_v2.py

tests/gui_v2/test_pipeline_pack_selector_job_actions_v2.py

This returns Pipeline tab pack selector to its current (less scoped) behavior and removes the JobDraft model.

12. Codex Execution Constraints

Do not modify pipeline execution logic, only config + job draft wiring.

No new external dependencies.

Keep changes local: avoid refactors; add focused methods instead.

Treat randomization fields as opaque; just copy them into snapshots.

13. Smoke Test Checklist

python -m src.main

Open Pipeline tab:

Confirm:

Single pack list.

Prompt preview under pack list still works.

New buttons appear.

Select one pack:

Click Load current config – stage cards change (or at least logs show handler firing).

Click Apply config to pack(s) – no error; logs show config write.

Click Add to Job – right preview shows the pack in the job summary.

Select multiple packs:

Click Apply config to pack(s) and Add to Job – preview shows all selected packs.

Try preset actions:

Apply preset to default / pack(s) / load to stages – no errors in logs.