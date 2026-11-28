# NAME-INFO: descriptive output names and "More info" in review

Status: in progress (2026-11-27). Not deployed or qualified until the living documents say so.

## Problem

The owner asked (2026-11-27) for names that say which path made a file (txt2img, ADetailer, upscale, img2img, clip,
storyboard), which model (in short form), which prompt pack and prompt number, and when; or at least for that to be
shown in review behind "More info".

Today: run folders truncate pack and model to `000-Style-photoMomenW_v20-none`, file names have no model or date,
Reprocess and clip folders say `unknown-none`, and a clip is a workflow id plus a 32-character job id.

## Execution class and models

- Execution class: Standard (additive contract and schema changes; one new naming module; no new authority).
- Model recommendation: Claude Code Sonnet 5.5 High; Codex GPT-6.1 Sol High.
- Controller surface: none. `src/pipeline/`, `src/review/`, `src/app/` services, the separate gateway, one Review
  panel in `src/gui/`.
- Validation: focused tests per slice, then `tests/app`, `tests/pipeline`, `tests/video`, `tests/gui_v2`,
  `tests/system`, `tests/tools`, the gateway tests, `tools/ci/run_pr_gate.py --parity`, the ruff ratchets and the
  code-map check.

## Constraints

- Existing files are never renamed: History, the Output Library index, the phone ledger and Immich refer to them.
- No PC path leaves the PC (RG-100 invariant 3). Names are allowed.
- One naming authority: `src/pipeline/output_naming.py`. Every stage writer, the video backends and both "More info"
  surfaces use it.
- The NJR stays immutable and unchanged. Names are derived from the frozen NJR, the input image's own metadata and
  the run's start time.

## Slice 1: "More info" everywhere

- One derivation, `src/review/output_info.py`, reads (read-only, bounded) the output's embedded metadata, its run
  manifest and the job's immutable NJR snapshot, and returns: stage path, short and full model or workflow name,
  source model of a clip, prompt pack, prompt number, variant, date and time, seed and batch name. A reprocess or
  clip job takes pack and prompt from the job of its input image, at most four hops back.
- The PC sends it as the manifest's optional `info` object, only to a gateway whose health lists `item_info`.
  Closed field list, bounded text, paths reduced to their last part.
- The gateway stores it and returns it with each item and with each compare side.
- Phone: a "More info" button on every item; a compare shows both sides. Code in `static/moreinfo.js`; the hook in
  `app.js` is `infoPanel(item, other)`.
- Desktop Review: the same fields for the selected image, and for both sides of Compare with Parent.
- Old items: items without `info` show what the item already has (batch, model, workflow, seed, date). Items
  published before this slice are not published again for it.

Acceptance: a txt2img image, an ADetailer reprocess and an A14B clip each show a correct stage path, model, pack,
prompt number, date and seed in manifest, phone payload and Review; an item without `info` still renders; nothing
path-shaped is in any manifest; an older gateway receives no `info`.

## Slice 2: descriptive names, new files only

File: `{YYYYMMDD-HHMM}_{stage path}_{model}_{pack}_p{NN}v{NN}_{short id}.{ext}`

- `20261127-1648_txt2img+adetailer_photoMomentum_000-Style_p01v02_8f87e4a2.png`
- `20261127-1457_clip-A14B_from-photoMomentum_000-Style_p01v01_969e487e.mp4`

Folder: `{YYYYMMDD_HHMMSS}_{pack}_{model}`.

Rules:

- Unknown parts are left out; there is no `unknown`, `none` or `workspace-P00`.
- Short id: the first eight characters of the job id (a hash of it when it is not hexadecimal). It links a file to
  its job in History. Batch images keep the existing `_batchN` / `_sNN` suffix; a second input of one reprocess job
  gets `_iNN`.
- Model short name: from the checkpoint stem (N12), dropping version, precision, `SDXL`/`XL` and `NSFW` markers; a
  workflow uses the short map. Both maps are in `config/output_model_names.json`. A local
  `config/output_model_names.local.json` (ignored by Git) overrides it, because editing a tracked file makes the
  checkout dirty and the Update button refuses.
- Only `A-Z a-z 0-9 . _ + -` and spaces turned into `-`; each part capped, whole name at most 140 characters.
- Folders: pack jobs of one pack and model still share a folder as before. Jobs without a pack of their own (video,
  reprocess) keep one folder per job and carry the short id, so sequence ledgers cannot collide.
- Learning uses the same scheme, with the experiment's variable and value in the file name; its folder label is
  unchanged.
- Immich: the PC sends the file name (name only) when it follows this scheme, and the gateway uploads under it.
  Older files keep today's Immich name.

## Finding: `OutputPlan.filename_template`

The NJR stores it (`{seed}`), Learning reads a setting into it, and no writer has ever read it: stage handlers build
names themselves. This package does not add a template language. The resolver is the authority, called by the runner
and the writers; `OutputPlan` is unchanged, so stored NJRs replay and hash as before.

## Out of scope

Renaming existing files; re-publishing old phone items to add `info`; a per-user template; names of Movie Clips
assembly outputs the operator names; eval-run folder names.

## Owner questions

None blocking. Defaults taken, each easy to change:

1. A pack-less job (video, reprocess) puts the short id at the end of its folder name.
2. The VAE leaves the folder name (it stays in "More info" through the model's metadata and in the manifests).
3. Date and time in names are the PC's local time, as folders are today.
