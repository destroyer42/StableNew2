# ARCH-DESIGN-950 structural inventory

Supporting evidence for
[the 2026-11-10 assessment](../../2026-11-10_arch_design_950_coordination_hotspot_decomposition.md). Everything here was
measured at `origin/main` `fdd900a93dd966a5f26c6453aac495447c69bd81` by static analysis only. Line numbers are valid
for that SHA; a later session must re-run the script before acting on them.

Notation: `name@line:size` is a method, the line of its `def`, and its length in physical lines.

## 1. Unreferenced symbols (tier A)

Definition: the method name occurs in no tracked `.py` file other than the defining file (`git grep -w`), is not named
by a string literal or attribute access in any referenced method of its class, and is not referenced by module-level
code in its file. 59 methods, 1,559 lines.

`src/pipeline/executor.py`, class `Pipeline` — 14 methods, 904 lines:

- `_log_run_efficiency_metrics@363:17`, `_resolve_negative_prompt@843:26`, `_discover_current_model_if_needed@988:10`,
  `_log_pipeline_cancellation@2987:6`
- `run_upscale@2994:20`, `_run_upscale_impl@3015:44`, `_normalize_config_for_pipeline@3060:61`
- `_annotate_active_variant@3202:16`, `_tag_variant_metadata@3220:14`, `_build_variant_suffix@3236:11`,
  `_extract_name_prefix@3302:20`
- `run_img2img@3323:19`, `_run_img2img_impl@3343:186`, `run_pack_pipeline@4320:454`

`src/pipeline/pipeline_runner.py`, class `PipelineRunner` — 4 methods, 235 lines:

- `_call_stage@1752:79`, `_apply_stage_metadata@1832:34`, `_build_executor_config@1867:47`,
  `_build_stage_payload@1915:75`
- `_build_stage_payload` is named once outside its file, in the stale comment at `executor.py:4815`; it has no caller.

`src/controller/app_controller.py`, class `AppController` — 23 methods, 235 lines:

- `on_add_to_queue_clicked@321:16`, `_submit_jobs_async@338:6` (the only code that touches `_draft_job_bundle`; it
  calls `job_service.submit_queued` directly)
- `on_add_to_job@1350:3`, `on_update_preview@1354:6`, `_read_pack_prompts@1472:9`
- `on_open_advanced_editor@3091:13`, `on_advanced_prompt_applied@3105:30`
- `_set_lifecycle_threadsafe@3153:13`, `_append_log_threadsafe@3251:11`, `get_process_auto_scanner@3343:2`,
  `_capture_error_envelope@3400:8`
- `run_pipeline@4104:12`, `_execute_pipeline_via_runner@4117:12`, `_coerce_bool@4167:9`, `_ensure_webui_api@4177:4`
- `_set_profile_default@4301:13`, `_apply_base_generation_overrides@4679:21`,
  `_get_gui_overrides_for_pipeline@4904:30`, `build_pipeline_config_v2@4944:9`
- `on_matrix_base_prompt_changed@5068:2`, `on_matrix_slots_changed@5072:2`, `on_request_preview_refresh@5080:2`,
  `_apply_webui_resources@5107:2`

`src/gui/controllers/learning_controller.py`, class `LearningController` — 5 methods, 105 lines:

- `export_grid_contact_sheet@833:11`, `_build_stage_flags_for_experiment@1785:12`, `_build_variant_overrides@1798:37`,
  `_apply_overrides_to_config@1836:42`, `prune_missing_discovered_outputs@3184:3`

`src/controller/pipeline_controller.py`, class `PipelineController` — 13 methods, 80 lines:

- `get_webui_connection_state@172:4`, `_get_batch_runs@735:4`, `_get_learning_runner@769:6`,
  `get_learning_runner_for_tests@793:4`, `is_learning_enabled@832:4`, `set_learning_queue_cap@837:7`,
  `get_last_run_config_for_tests@919:2`, `get_last_stage_events_for_tests@922:4`, `_get_draft_part_count@1209:7`,
  `_log_add_to_queue_event@1217:9`, `remove_pack_from_draft@1417:9`, `_infer_job_stage@1498:18`,
  `_hydrate_history_record@1627:2`
- `_get_batch_runs` is held out of ARCH-951: `STATUS.md` open owner decision 4 is about this control.

## 2. Module reachable only through tier A (tier B)

- `src/pipeline/payload_builder.py` (458 lines). Importers: `pipeline_runner.py:35` (used only at line 1940 inside
  `_build_stage_payload`) and `tests/api/test_sdxl_payloads.py:20`.

## 3. Referenced only by tests (tier C, not in ARCH-951)

40 methods, 843 lines. Each needs a judgment about the test that names it.

- `Pipeline`: `reset_stage_events@1891:4`, `get_stage_events@1896:4`
- `PipelineRunner`: `_is_image_producing_stage_type@1652:7`, `_validate_stage_plan@1660:78`,
  `_emit_learning_record@1991:48`
- `AppController`: `on_run_job_now_v2@1612:20`, `on_submit_image_edits@1959:98`, `on_optimize_photo_assets@2090:14`,
  `_run_pipeline_via_runner_only@4130:16`, `_get_pipeline_tab_upscale_params@4147:9`,
  `_get_pipeline_tab_prompt@4157:9`, `_get_active_prompt_text@4804:27`, `update_config@4870:33`,
  `_build_pipeline_config@4954:61`, `_resolve_prompt_from_pack@5016:12`, `_update_gui_dropdowns@5186:18`,
  `_lora_settings_payload@5375:8`, `_build_job_from_draft@5384:13`, `_job_payload_from_draft@5398:13`,
  `on_add_job_to_queue@6105:12`, `on_run_job_now@6118:3`, `on_run_queue_now_clicked@6122:7`, `on_pause_queue@6138:6`,
  `on_resume_queue@6145:6`
- `LearningController`: `_submit_variant_job@1102:77`, `_admission_unresolved@1181:10`,
  `_on_variant_job_completed@1937:4`, `_apply_single_recommendation@3001:37`
- `PipelineController`: `_build_job@119:52`, `build_pipeline_config_with_profiles@544:70`,
  `handle_learning_record@798:18`, `get_learning_record_handler@817:4`, `get_last_learning_record@822:4`,
  `get_last_run_result@902:4`, `get_last_stage_execution_plan_for_tests@914:4`, `add_packs_to_draft@1408:8`,
  `reconstruct_jobs_from_snapshot@1618:8`, `_hydrate_njr_from_snapshot@1630:4`,
  `get_job_execution_controller@1666:3`, `replace_queue_runner@1674:10`

## 4. Class metrics

| Class | Methods | Public | Attributes set on `self` | `__init__` lines / parameters | Methods of 100+ lines (lines) | `.get(` | `getattr(` | `except Exception` |
|---|---|---|---|---|---|---|---|---|
| `AppController` | 339 | 154 | 97 | 327 / 15 | 6 (1,088) | 465 | 374 | 168 |
| `Pipeline` | 92 | 14 | 34 | 56 / 3 | 13 (4,213) | 567 | 29 | 74 |
| `PipelineRunner` | 47 | 3 | 18 | 40 / 14 | 3 (514) | 136 | 78 | 23 |
| `LearningController` | 155 | 89 | 27 | 58 / 9 | 7 (920) | 289 | 134 | 40 |
| `ExperimentDesignPanel` | 106 | 11 | 101 | 55 / 4 | 6 (899) | 201 | 94 | 8 |
| `ModelEvidenceWindow` | 57 | 2 | 53 | 177 / 1 | 1 (177) | 69 | 28 | 5 |
| `PipelineController` | 107 | 59 | 28 | 91 / 8 | 1 (162) | 33 | 90 | 52 |

The `.get(`, `getattr(` and `except Exception` columns are whole-file counts.

Largest methods: `Pipeline.run_adetailer` 789, `run_txt2img_stage` 740, `run_upscale_stage` 539, `run_pack_pipeline`
454 (unreferenced), `_poll_progress_loop` 385, `run_img2img_stage` 329; `AppController.__init__` 327,
`_build_stage_overrides_from_current_config` 217, `_build_reprocess_config` 156, `_build_svd_history_record` 144;
`ExperimentDesignPanel._build_ui` 376; `PipelineRunner._execute_video_stage` 201, `_run_train_lora_njr` 177,
`run_njr` 136; `LearningController._build_variant_njr` 176.

## 5. Cluster cohesion

"Exclusive state" is an attribute used only by the cluster and `__init__`. "Calls out" are other methods of the same
class the cluster uses.

| Class | Cluster (line range) | Methods | Lines | Exclusive state | Shared state | Calls out |
|---|---|---|---|---|---|---|
| `AppController` | History media projection (6498-6816) | 10 | 307 | 0 | `app_state` | 0 |
| `AppController` | Diagnostics and job explanation (3268-4100) | 37 | 794 | 10 | 18 attributes | 4 |
| `AppController` | Video, SVD, training hand-offs (6177-6497) | 26 | 298 | 3 | 3 | 9 |
| `AppController` | Reprocess, Review, Photo Optimize (1797-2374) | 18 | 559 | 0 | 6 | 5 |
| `AppController` | Pack config and stage overrides (5453-6063) | 10 | 601 | 0 | 8 | 20 |
| `AppController` | UI dispatch and runtime status (748-1160) | 19 | 393 | 12 | 7 | 2 |
| `AppController` | Shutdown (4427-4675) | 9 | 239 | 4 | 10 | 5 |
| `Pipeline` | Prompt optimisation (381-555) | 5 | 170 | 1 | 0 | 0 |
| `Pipeline` | Manifest and metadata (556-869) | 16 | 297 | 2 | 2 | 2 |
| `Pipeline` | Model and VAE sync (962-1089) | 6 | 118 | 6 | 2 | 2 |
| `Pipeline` | Runtime pressure and admission (1090-1839) | 15 | 734 | 0 | 3 | 2 |
| `Pipeline` | WebUI recovery and health (1923-2243) | 6 | 315 | 1 | 2 | 1 |
| `Pipeline` | Generation, recovery, progress (2244-2986) | 6 | 737 | 3 | 8 | 6 |
| `LearningController` | Staged curation (3204-3897) | 25 | 666 | 2 | 4 | 12 |
| `LearningController` | Discovered inbox and scan (3118-3200, 3908-4123) | 19 | 276 | 1 | 4 | 0 |
| `LearningController` | Variant NJR and baseline (1102-1935) | 26 | 803 | 0 | 5 | 4 |
| `LearningController` | Design and plan (233-860) | 16 | 614 | 3 | 6 | 7 |
| `LearningController` | Ratings and feedback (863-980, 2265-2873) | 30 | 698 | 1 | 13 | 5 |
| `LearningController` | Workflow and resume state (1937-2258) | 15 | 307 | 3 | 6 | 7 |

No method outside the staged-curation range calls into it. The diagnostics cluster's four calls out are `_append_log`,
`_get_history_entry_by_job_id`, `_get_latest_runtime_status` and `_spawn_tracked_thread`.

Executor stage methods call the shared steps as follows (call sites per method):

| Helper | `run_txt2img_stage` | `run_img2img_stage` | `run_adetailer` | `run_upscale_stage` |
|---|---|---|---|---|
| `_ensure_runtime_admissible` | 1 | 0 | 1 | 3 |
| `_ensure_model_and_vae` | 1 | 1 | 1 | 0 |
| `_check_model_drift` | 1 | 0 | 2 | 3 |
| `_build_image_metadata_builder` | 1 | 1 | 2 | 1 |
| `_write_manifest_file` | 1 | 1 | 1 | 1 |
| `_run_prompt_optimizer` | 1 | 1 | 1 | 0 |
| `_apply_prompt_stage_policy` | 1 | 1 | 1 | 1 |
| `.get(` in the method | 108 | 44 | 110 | 54 |

## 6. Test coupling

| Class | Private methods | Named in tests | Test files naming them | Patch sites naming the class |
|---|---|---|---|---|
| `AppController` | 184 | 76 | 78 | 8 |
| `Pipeline` | 77 | 28 | 34 | 65 |
| `PipelineRunner` | 43 | 8 | 11 | 5 |
| `LearningController` | 65 | 19 | 38 | 0 |
| `ExperimentDesignPanel` | 94 | 26 | 14 | 0 |
| `ModelEvidenceWindow` | 54 | 24 | 8 | 0 |

`AppController.__new__(AppController)` (construction without `__init__`) occurs 62 times in 35 test files.

## 7. View composition

Methods classified by whether they call `tk`/`ttk`/dialog APIs directly, touch a widget or Tk variable, or neither.

| View | Builds widgets | Touches widgets | No widget access |
|---|---|---|---|
| `ExperimentDesignPanel` | 23 methods, 1,249 lines | 43 methods, 695 lines | 40 methods, 423 lines |
| `ModelEvidenceWindow` | 11 methods, 512 lines | 28 methods, 817 lines | 18 methods, 309 lines |

`model_evidence_window.py` also holds toolkit-neutral module functions: `assess_row@150:109`,
`compare_with_history@261:20`.

## 8. Reproduction

Run from the repository root at the locked SHA. The scripts read files and call `git`; they write nothing.

Reachability (sections 1 and 3), `python reach.py <file> <Class>`:

```python
import ast, collections, subprocess, sys

path, cls = sys.argv[1], sys.argv[2]
tree = ast.parse(open(path, encoding="utf-8").read())
klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
methods = {m.name: m for m in klass.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
size = {n: m.end_lineno - m.lineno + 1 for n, m in methods.items()}


def words(paths):
    out = subprocess.run(
        ["git", "grep", "-h", "-o", "-w", "-E", "[A-Za-z_][A-Za-z0-9_]*", "--", *paths],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    return set(out.split())


prod = words(["src", f":!{path}"]) | words(["tools", "scripts", "*.py", ":!src", ":!tests"])
tests = words(["tests"])
same_file = set()
for node in tree.body:
    if node is klass:
        continue
    for x in ast.walk(node):
        if isinstance(x, ast.Attribute):
            same_file.add(x.attr)
        if isinstance(x, ast.Constant) and isinstance(x.value, str):
            same_file.add(x.value)

edges = collections.defaultdict(set)
for name, m in methods.items():
    for x in ast.walk(m):
        if isinstance(x, ast.Attribute) and x.attr in methods:
            edges[name].add(x.attr)
        if isinstance(x, ast.Constant) and isinstance(x.value, str) and x.value in methods:
            edges[name].add(x.value)
    edges[name].discard(name)


def closure(roots):
    seen, stack = set(roots), list(roots)
    while stack:
        for y in edges[stack.pop()]:
            if y not in seen:
                seen.add(y)
                stack.append(y)
    return seen


dunder = {n for n in methods if n.startswith("__")}
prod_roots = {n for n in methods if n in prod or n in same_file} | dunder
live_prod = closure(prod_roots)
live_any = closure(prod_roots | {n for n in methods if n in tests})
for label, names in (("unreferenced", set(methods) - live_any), ("test-only", live_any - live_prod)):
    ordered = sorted(names, key=lambda n: methods[n].lineno)
    print(label, len(ordered), sum(size[n] for n in ordered))
    print(" ".join(f"{n}@{methods[n].lineno}:{size[n]}" for n in ordered))
```

The rule is conservative: a name shared with any other class, or mentioned in a comment or string anywhere in `src`,
keeps a method alive. Cross-check for each reported name:

```bash
git grep -l -w "<name>" -- '*.py'
```

The result must be the defining file only.

Other measurements:

- Churn: `git log --since "90 days ago" --no-merges --name-only --format=@%H -- src` (and `30 days ago`), counted per
  file; fix-like commits match `fix|repair|regress|bug|correct|restore` in the subject.
- Import fan-in and fan-out: every `import src...` and `from src... import` found by `ast.walk`, including imports
  inside functions.
- Test files naming a module: word match of the dotted module path over `tests/**/*.py`.
- Cluster cohesion: for the methods whose `def` falls in the line range, attribute reads and writes on `self`
  (including `getattr(self, "<literal>")`), split into method calls and state.
