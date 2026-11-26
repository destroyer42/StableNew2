# EVAL-HOME-383 — One canonical home for evaluation plans, opened automatically, with dropdowns instead of file pickers

Hand-off prompt for a fresh Claude Code or Codex session. Discovery is done; read only the files named here.

## Objective

- **Owner request (2026-11-22):** "Make an authoritative place or folder where all proposed evaluation test plans go. They are
  hidden throughout multiple folders with no standardization. Make it a default location, link to it automatically when going
  to look for an evaluation, and let available runs be selected from a dropdown instead of a file picker."
- **Outcome:**
  1. A canonical **Evaluation Plans** root, `<Output>/eval_plans/`, with one subfolder per plan kind and a written convention
     (naming, schema key, README), resolved through one path helper and overridable by one setting.
  2. The Video Workflow eval controls list **plans** and **runs** in read-only dropdowns (with Refresh, Open folder, and an
     "Other file…" escape hatch), defaulting to the canonical folders; no blind file picker on the normal path.
  3. A safe **import** that copies existing scattered suites into the canonical folder without touching the originals.
  4. Qualification CLIs default their plan output into the canonical tree when that is allowed (see design §5).
- **Explicit exclusions:** no schema changes to suites/runs/ratings; no moving or deleting owner files; no change to the
  per-run owner authorization rules; Learning experiment sessions stay where they are (`data/learning/experiments`, its own store
  and Library UI) — list them in the README as "not an eval plan".

## Execution class and model recommendation

- Execution class: **Standard** (path helper + GUI panel rework + small tool; no runtime/queue change).
- Model recommendation: Claude Code **Sonnet 5.5 High**; Codex **GPT-6.1 Sol High**.
- Expected usage: about 10M cache-read, 90k output.

## Exact start state and sequencing

- `origin/main` at hand-off `d8ea1c86`; isolated worktree; main's `.venv` interpreter. Branch `gui/eval-home-383-plans-folder`.
  Record task-start timestamp and session ID.
- **Overlap:** `VID-UX-384` (Video Workflow layout redesign) moves the eval panel inside the tab. This package owns the **internals**
  of `src/gui/views/video_eval_panel_v2.py`; 384 owns where the panel sits. Land this first, or coordinate so they never edit the
  same file concurrently. `VID-CAND-382` (Hunyuan eval) will put its suites into `<Output>/eval_plans/video/` once this lands.

## Research already done

### Inventory (where plans live today)
| Plan type | Schema key | Current location(s) | Loader | Picker today |
|---|---|---|---|---|
| Video eval suite | `"schema": "stablenew.video-eval-suite.v1"` (`src/video/video_eval_suite.py:22`) | examples `docs/runbooks/examples/video_eval_three_engines.suite.json`, `video_eval_a14b_speed_arms.suite.json`; real ones in `C:\Users\rob\qual\clip371\*.suite.json` (stage0/1/2 + variants) | `load_eval_suite` (`video_eval_suite.py:183`; image paths resolve **relative to the suite file**, L202) | `video_eval_panel_v2.py:69-83` `on_queue_suite`, `askopenfilename`, **no initialdir** |
| Video eval run | `stablenew.video-eval-run.v1` (`src/video/video_eval_run.py:28-30`: `RUN_SCHEMA`, `RUN_MANIFEST_NAME`, `EVAL_OUTPUT_FOLDER="video_eval"`) | `<Output>/video_eval/<YYYYmmdd_HHMMSS>_<suite_id>_<hex8>/run.json` (+ `metrics.json`, `ratings.csv`, `index.html` after a report) | `load_run_manifest` (`src/video/video_eval_report.py:181`) | `video_eval_panel_v2.py:122-139` `on_build_report`, `askdirectory`, initialdir `<Output>/video_eval` if it exists |
| Fun Control qualification plan | `stablenew.fun-control-qualification-plan.v1` (`tools/qualification/fun354/plan.py:21`) | any path **outside the repo** (`_outside_repo`, `fun354/__main__.py:34`) | `fun354/__main__.py:63` | CLI |
| SYSTEM-840 plan / auth | `PLAN_SCHEMA = 1`, `AUTH_SCHEMA = 1` (`tools/qualification/system840/plan.py:43-44`) | outside repo (`cli.py:46`); evidence `%USERPROFILE%\Videos\StableNewAcceptance\QUAL-840\` (`STABLENEW_QUAL840_ROOT`, `evidence.py:29,48-50`) | `plan.py:559 load_json` | CLI |
| AI visual sets | `stablenew.vl220.cases/1|2`, `labels/1|2`; vl242 plan with `plan_sha256`; vl240 `stablenew.vl240.image_manifest/1` | `D:\StableNew-Assets\offline-ai\visual-evaluation\…` (refuses Git folders; `docs/runbooks/ai_visual_real_set.md:136-137`, `ai_visual_evaluation.md:35`) | vl220/vl240/vl242 modules | CLI |
| ai111 / wan321f frozen plans | `stablenew.ai111.v1`, `ai111.final.v2`, `stablenew.wan321f.v1` | `reports/ai111/*freeze*/plan.json`, `reports/wan321f/offline-freeze-*/plan.json` | their `plan.py` | CLI |
| Golden journey plan | `PLAN_SCHEMA = 1` (`tools/operator_journey/golden/plan.py:21`) | `reports/operator_journeys/<ts>_golden-paths_<mode>/plan.json`; baselines `~/StableNewAcceptance` (`STABLENEW_ACCEPTANCE_ROOT`) | `golden/plan.py:140` | CLI |
| Learning proposed experiment (not an eval plan) | session JSON | `data/learning/experiments/<id>/session.json` via `WorkspacePaths.learning_experiments_root()` | `experiment_store.py:185` | Learning Library (Treeview) + `learning_tab_frame_v2.py:1644` |

Runbook `docs/runbooks/video_eval_kit.md` §6 tells the operator to "copy the file next to your own images" — that is why suites scatter.

### Path and settings conventions
- `src/state/workspace_paths.py::WorkspacePaths` (singleton `workspace_paths`, L108; test temp-root support) — has
  `learning_experiments_root()`, `photo_optimize_root(output_root=...)` (precedent for a folder under Output). Add `eval_plans_root(output_root=...)`.
- `src/state/output_routing.py:9-31` route constants (`OUTPUT_ROUTE_*`, `KNOWN_OUTPUT_ROUTE_DIRS`, `get_output_route_root()`).
  `video_eval` is defined separately in `video_eval_run.py`.
- Settings: `src/utils/config.py::ConfigManager` → `presets/settings.json` (`_load_settings` L222, `get_setting` L705, `save_settings` L766);
  only folder key is `"output_dir": "output"` (`_apply_application_defaults` L455). No eval key exists. Add `eval_plans_dir` (empty =
  default `<output_dir>/eval_plans`). Never hand-edit the owner's `presets/settings.json` (locally modified in the main checkout).
- Gitignored: `output/`, `data/learning/`, `/reports/`, `tmp/`, `/state/`.
- Operator Site shares the configured Output folder (`src/app/site_output_catalog.py`); its `list_runs` matches only
  `_RUN_ID = \d{8}_\d{6}_...` (L38) so an `eval_plans/` folder will not confuse it.

### Run discovery to reuse
- `SiteOutputCatalog.list_runs(include_unbuilt=False)` (`src/app/site_output_catalog.py:137-161`): newest first, `_MAX_RUNS = 100`,
  built = `run.json` + `metrics.json`; `include_unbuilt=True` accepts `run.json` alone; `eval_manifest(run_id)` (L163) checks schema + id.
  It lives in `src/app` (Site) — **do not import `src/app` from `src/gui`**: extract the pure listing into `src/video/video_eval_catalog.py`
  and have the Site call it (keep Site behavior and tests identical).

### GUI wiring and patterns
- Panel `src/gui/views/video_eval_panel_v2.py` (209 lines, `VideoEvalPanel`, LabelFrame "Eval suite"; buttons L54-60; injected
  `ask_open`/`ask_directory`, default `filedialog`, L33). Wired in `src/gui/views/video_workflow_tab_frame_v2.py:898-906` with
  `output_dir=lambda: str(getattr(self.app_controller, "output_dir", "") or "output")`.
- Consumers: `src/controller/video_eval_controller.py` (`VideoEvalControllerMixin.preview_eval_run` L54 → `load_eval_suite`;
  `submit_eval_run` L59; `build_eval_report` L65 → `video_eval_report.py:319`).
- Dropdown patterns: readonly Combobox `src/gui/sidebar_panel_v2.py:1176` (`_set_pack_list_values`, disabled when empty);
  glob-by-mtime + Open folder + refresh `src/gui/panels_v2/debug_hub_panel_v2.py:548` (`_open_path`); filter Combobox + Treeview
  `learning_tab_frame_v2.py:1464-1532`; `DARK_COMBOBOX_STYLE` (`adetailer_stage_card_v2.py:1432`).
- Style: `docs/Subsystems/GUI/GUI_STYLE_GUIDE.md` (TOKENS, one Primary per surface, inline `SubmissionNotice`, checks in
  `tests/gui_v2/test_design_foundation_400.py`). Other pickers that could later default to the canonical root (out of scope unless
  trivial): `model_evidence_window.py:1940` `_import`, `job_history_panel_v2.py:828` `_pick_sequence_ledger`.

### Tests that change or pin paths
- `tests/gui_v2/test_video_eval_panel_320.py` (injects `ask_open`/`ask_directory` L57-58; tests L65-127) — rework for dropdowns.
- `tests/video/test_pr_vid_eval_320_run.py`, `test_pr_vid_eval_320_report.py`, `test_pr_vid_quality_351_identity.py`.
- Example-suite path pins: `tests/video/test_vid_clip_370_candidate_specs.py:57`, `tests/video/test_vid_a14b_374_speed_arms.py:57` —
  keep the `docs/runbooks/examples/` files (they are documentation examples); seed them into the canonical folder as templates instead.
- `tests/controller/test_site_output_catalog.py:81`, `test_site_phone_admission.py`; `tests/gui_v2/test_pr_vid_ux_360_task_first.py:439`.

## Design

1. **Folder convention** (write `docs/runbooks/eval_plans.md` and drop a generated `README.md` into the root on first creation):
   ```
   <Output>/eval_plans/
     video/          *.suite.json          stablenew.video-eval-suite.v1   (GUI: Queue eval suite)
     image/          *.plan.json           image comparison plans (IMG-COMFY-381 will use this)
     qualification/  <tool>/<plan>.json    frozen qualification plans (see §5)
     templates/      copies of docs/runbooks/examples/*.suite.json (read-only starting points)
     _imported/      provenance log of imports (imports.jsonl)
   ```
   Naming: `<YYYYmmdd>_<slug>.suite.json`; the schema key is the authority, not the extension. Runs stay where they are
   (`<Output>/video_eval/<run_id>/`) — "plans" and "runs" are different things; the README links both.
2. **Path helper:** `WorkspacePaths.eval_plans_root(output_root)` + `eval_plans_dir(kind)`; honors setting `eval_plans_dir`; creates
   folders lazily (not at import); one constant set in `src/video/video_eval_run.py` or a tiny `src/state/eval_plans_paths.py`.
3. **Catalog:** `src/video/video_eval_catalog.py` (pure, no Tk): `list_plans(kind="video")` → entries (path, suite_id, cases, arms,
   jobs, experimental flag, mtime, valid/error string) validated with `load_eval_suite`; `list_runs(include_unbuilt=True)` extracted
   from the Site (label fields: created_at, suite_id, job count, built?, ratings filled `n/m`).
4. **Panel rework (`VideoEvalPanel`):**
   - Row "Plan": readonly Combobox (label `suite_id — 8 cases × 3 arms (24 jobs) · experimental`), invalid plans shown disabled with
     the error in a tooltip/status line; buttons **Queue…** (keeps the existing preview/confirm flow), **Refresh**, **Open folder**,
     **Other file…** (the old picker, initialdir = canonical folder, offers to import the chosen file).
   - Row "Run": readonly Combobox newest first (`2026-11-18 04:00 · clip371-stage2 · 16 jobs · report built · rated 16/16`); buttons
     **Build report**, **Open report** (enabled when `index.html` exists), **Open folder**.
   - Empty states: "No plans in <path> — Open folder or Import…" (inline, not modal). After a successful Queue, select the new run.
   - Refresh on panel show and after admission; no filesystem polling loop; listing off the Tk thread if it can exceed ~50 ms
     (marshal results back to the GUI thread).
   - Keep attribute names that tests and VID-UX-384 rely on (`eval_panel`, the button attributes); add new ones rather than renaming.
5. **Qualification plans:** fun354/system840/etc. refuse in-repo paths on purpose, and the default Output (`output`) is **inside** the
   repo. Default `--out` to `<eval_plans>/qualification/<tool>/` **only when that path is outside the repo**; otherwise keep today's
   behavior and print the canonical-folder recommendation. Do **not** relax `_outside_repo` (safety rule) — if the owner wants that,
   it is a separate decision. Document each tool's location in `docs/runbooks/eval_plans.md`.
6. **Import tool:** `tools/eval_plans_import.py --from C:\Users\rob\qual\clip371 [--apply]` — dry-run by default; copies
   `*.suite.json` into `video/`, rewrites relative image paths to **absolute** paths (so moved suites still resolve; verify with
   `image_sha256` when present), never copies `*.private.json` contents into a shared location without flagging them, appends to
   `_imported/imports.jsonl`. Originals untouched. Also seeds `templates/` from `docs/runbooks/examples/`.
7. **Docs:** `docs/runbooks/video_eval_kit.md` §6 ("put suites in `<Output>/eval_plans/video/`"), new `docs/runbooks/eval_plans.md`,
   `docs/Subsystems/Video/VIDEO_PIPELINE.md` eval paragraph, `docs/CODEX_MAP.md` Comfy row (catalog module), `STATUS.md` video eval
   sentence (edit, don't add).

## Acceptance criteria

1. With an empty Output, opening the eval controls creates nothing until needed and shows the empty state with the canonical path.
2. Plans in `<Output>/eval_plans/video/` appear in the dropdown with correct labels; invalid ones are listed disabled with reasons;
   Queue admits exactly as before (same `run.json`, same single `submit_njrs` call).
3. Runs dropdown lists `<Output>/video_eval/*` newest first incl. unbuilt; Build report / Open report work; Site behavior unchanged.
4. "Other file…" still works and opens in the canonical folder.
5. Import dry-run lists actions; `--apply` copies with absolute image paths; originals unchanged (hash before/after in a test).
6. No `src/gui` → `src/app` import; no controller line-ceiling increase (`AppController` is exactly at 4,775).

## Token-efficient validation plan

1. Focused: `tests/gui_v2/test_video_eval_panel_320.py` (reworked), new `tests/video/test_video_eval_catalog.py`,
   `tests/controller/test_site_output_catalog.py`, `tests/video/test_pr_vid_eval_320_run.py`, `tests/tools/test_eval_plans_import.py`,
   `tests/gui_v2/test_design_foundation_400.py`.
2. `python tools/ci/run_pr_gate.py` from the isolated worktree; `python -m pytest tests/tools -q` (new tool; memory: gate misses tools census).
3. `git diff --check`. Optional manual check in the app at 1366x768 (owner's live app runs from main; use a worktree launch).

## Stop conditions

- Making qualification CLIs write in-repo would require relaxing `_outside_repo` → stop for owner.
- Extracting `list_runs` changes Site responses → stop and keep the Site's copy.

## Completion report

`AGENTS.md` §8. `Model / usage` line. Feature-branch commits; publish only with owner authorization. Tell the owner the one command
to import the CLIP-371 suites (dry-run first).
