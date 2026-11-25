# Evaluation Plans

Open **Video Workflow → Evaluate** to find video plans and runs. The Plan dropdown reads
`<Output>/eval_plans/video/` when the panel opens. **Refresh** looks for changes, and **Open folder**
creates the Evaluation Plans folders and README on first use. **Create / Edit Suite…** opens the selected
plan for editing. From the editor you can also start a blank suite, open the bundled **Three-engine
template**, or choose **Open JSON / template…** to edit a suite from any local folder. The editor shows
every case even when its source image is missing. **Save as New Version** adds an independent plan and
selects it. **Save & Preview…** also displays the compiled job matrix and any refusals. **Queue All Jobs**
in that preview is the explicit confirmation.

For a **driving-motion** evaluation, choose **Add Driving Motion** on a case, bind a local video or a verified Motion Library
clip, state the intended action, motion prompt and expected outcome, and **Duplicate Case for Another Source…** to test the
same movement on another image. Such a suite is saved as `stablenew.video-eval-suite.v2`; existing v1 plans open and save
unchanged (a new version file is always written) and cannot carry a driver. The arms pick a driving-video workflow and its
controls; the driver and motion prompt come from the cases, and a workflow that takes no driving video refuses the case.
**Review Motion…** appears for a built driving-motion run. See `docs/runbooks/video_eval_kit.md` section 9. To test a spatial
alignment, a case declares `motion.alignment` and two arms differ only in `form.motion_alignment` (`none` or `case`); the
three campaign templates `templates/video_eval_motion_alignment_{pilot,diagnostic,full}.suite.json` (2, 8 and 16 jobs) are
authored the same way, with each case's numbers taken from the alignment you accepted in Align Motion for that exact pair
(`docs/runbooks/video_eval_kit.md` section 10, `docs/runbooks/motion_alignment.md`).

Use **Other file…** for direct preview or the existing copy/import flow when no edits are needed.
Invalid plans show the loader's reason and disable **Queue…**. They can still be opened in the editor
when their JSON structure can be read.

The Run dropdown reads `<Output>/video_eval/<run_id>/run.json`, newest first, including runs that
have yet to produce a report. Use **Build report**, **Open report**, or **Open folder** for the
selected run. The rating count is the number of run jobs with filled review fields in
`ratings.csv`. The report checks whether those ratings still match the clips.

## Folders and naming

Set `eval_plans_dir` in StableNew's `presets/settings.json` to override the plan root. An empty setting
uses `<Output>/eval_plans`; relative settings paths start at the StableNew checkout. Runs use the
configured Output folder even with a plan-root override.

| Folder | Files | Schema or purpose |
|---|---|---|
| `video/` | `YYYYmmdd_slug_vNNN.suite.json` | `schema: "stablenew.video-eval-suite.v1"`, or `.v2` when a case binds a driving-motion reference (v2 is a superset). The schema identifies the suite. |
| `image/` | `YYYYmmdd_slug.plan.json` | Image comparison plans use the schema of the consuming tool. |
| `qualification/<tool>/` | One dated directory per default CLI invocation | Frozen qualification plans with each tool's existing schema. |
| `templates/` | Copies of runbook example suites | Open in the suite editor and bind local source images (and, for the controlled-motion campaign templates, driving videos) before saving. |
| `_imported/` | `imports.jsonl` | Source path, source SHA-256, destination and timestamp for each import. |

Use absolute image paths or paths relative to the suite file. Pin `image_sha256` when you need to
freeze the exact source bytes. The editor saves absolute case-image references with a verified SHA-256 for every case and leaves the source files in place. Learning experiments remain in the Learning Library and
`data/learning/experiments/`.

## Import existing suites

Run from the checkout whose settings you want to use.

```powershell
python -m tools.eval_plans_import --from C:\Users\rob\qual\clip371
python -m tools.eval_plans_import --from C:\Users\rob\qual\clip371 --apply
```

The first command previews copies, collisions, skipped private sidecars and bundled templates. The
second copies valid suites, converts image references to absolute paths, verifies existing image
pins, records provenance and seeds the templates. Existing suites and destination files are
preserved. Files ending in `.private.json` are skipped. Imported suites retain their prompts and
reference their original images, so use a private plan root for sensitive suites and keep the images
in place.

## Qualification CLI output

When the canonical plan root and destination resolve outside the repository, the following
plan-producing commands accept an omitted `--out`.

| Command | Canonical destination | Existing plan schema |
|---|---|---|
| `tools.qualification.fun354 propose` | `qualification/fun354/<dated-id>/plan.json` | `stablenew.fun-control-qualification-plan.v1` |
| `tools.qualification.system840 plan` | `qualification/system840/<dated-id>/plan.json` | `1` |
| `tools.qualification.ai111` and `tools.qualification.ai111.final_plan` | `qualification/ai111/<dated-id>/plan.json` and its offline companion files | `stablenew.ai111.v1` / `ai111.final.v2` |
| `tools.qualification.wan321f` | `qualification/wan321f/<dated-id>/plan.json` and its offline companion files | `stablenew.wan321f.v1` |

With the in-repository default Output, pass `--out` as before or configure an external
`eval_plans_dir`. Fun Control and SYSTEM-840 continue to require plans outside the repository.
Their readiness, authorization and evidence commands retain their existing destinations and gates.
Visual AI sets stay in their isolated asset/evidence folders (see the visual evaluation and real-set
runbooks). The VL242 plan summary still goes to stdout. Golden journey run plans remain with their
run evidence under `reports/operator_journeys/` or the operator's evidence root. The plan-only
`--build-plan` action takes an explicit destination.

A plan copy or freeze does not authorize execution or establish a qualification verdict.
