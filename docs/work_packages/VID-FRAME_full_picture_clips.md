# VID-FRAME: whole-picture A14B clips, smoothed cuts, frame retention

Status: built 2026-11-27 with deterministic tests; no GPU run. Base `origin/main` 88061016, branch `claude/vid-frame`.
Owner decisions (2026-11-27): "Whole source picture at same pixel count"; video frames on disk may be deleted 1 day
after their clip exists; the owner will do a blind rating of the faster attention (CK) profile.

Execution class: Standard. Model recommendation: Claude Code Sonnet 5.5 at high effort, or Codex equivalent.
Controller surface: one source-geometry field on the workflow record in `video_workflow_controller.py`; no ratcheted
controller grows. Validation: focused tests per commit, then `tests/video`, `tests/system`, `tests/tools/test_code_map.py`,
`python tools/ci/run_pr_gate.py` and ratchets; GUI tests alone. No test may need FFmpeg or RIFE. No GPU work.

Not in scope: new engine or model, 2:3 sizes, picker redesign (PRs #461 and #462 change the form and picker, so form
edits here stay minimal).

## a. Sizes: A14B full picture (experimental)

- `wan22_i2v_a14b_4step_full_picture_v1` 1.0.0: the A14B 1.0.0 graph and files, only `source_preparation` differs. It
  is its own workflow id (planned as version 1.4.0) because the picker offers one entry per id; it is listed with **Show
  experimental**. `make_video_default` False; launch profile `baseline`.
- `aspect_targets`: 480x832, 512x768, 544x720, 624x624, 720x544, 768x512, 832x480 (multiples of 16, no more than
  399,360 pixels). The size that crops the source least is chosen. 768x1024 -> 544x720 (0.7 % crop; the exact 3:4
  alternative 528x704 has 7 % fewer pixels). 1024x1024 -> 624x624 (no crop). 832x1216 -> 512x768 (2.6 %).
- A14B workflows have a 5 % crop limit, declared beside the specs so published versions stay byte-identical. Above it,
  an N1 warning (`video_source_cropped`, why and fix) is shown beside Queue, in the multi-image batch preview, and
  frozen in accepted warnings. It never refuses.
- Provenance: `video_workflow.source_crop_fraction` (absent when nothing is cut); the chosen size is already
  `source_preparation.target_dimensions`.
- Eval suite: `docs/runbooks/examples/video_eval_a14b_full_picture.suite.json`.

**GPU test needed before it becomes the default** (none run): for 512x768, 544x720, 624x624, 720x544 and 768x512 at 81
frames on the 12 GB card, cold and warm: peak VRAM, host RAM, wall time, no out-of-memory; 121 frames (the declared
maximum) for 544x720; then an owner-rated motion and identity comparison against A14B 1.0.0 on the same 768x1024 and
1024x1024 sources, prompts and seeds. Readiness floors stay 1.0.0's and are unmeasured at these sizes.

**Result and promotion (2026-11-27).** The size test ran through the eval harness: 18/18 clips at their declared sizes; peak
VRAM 10,320 of 12,282 MiB at 81 frames; the 121-frame 544x720 clip left 3.76 GiB host RAM free. Owner blind rating of the
six pairs against 1.0.0: likeness 6 same, stability 6 same, motion 1 full picture, 1 current, 4 same (one seed per case;
the pairs were trimmed to the 1.0.0 view, so the added picture was not judged). Promoted: full picture `approved` and
`make_video_default`; 1.0.0 stays approved, no longer the default; both spec digests re-pinned, graphs unchanged.

## b. Blind CK rating sitting (prepared, not rated)

Nine pairs from clips that already existed, copied (originals untouched) to
`%USERPROFILE%\Videos\StableNewAcceptance\VID-FRAME\a14b_ck_blind`: six app jobs where 1.0.0 and the CK profile ran the
same source, prompt, seed 123456 and 81 frames, and the three WAN-BENCH-373 run-002 cases. `HOW_TO_RATE.txt` gives the
steps; `pairwise.csv` is the sheet; `pairwise_key.json` and `sources_DO_NOT_OPEN.json` stay closed until it is full.
Score with `python -m tools.qualification.vid_cand382 score-pairwise --sheet pairwise.csv --key pairwise_key.json`.
The prepared 10-job suite (`vid_a14b_ck_bench.suite.json`) was not run: it needs the GPU.

## c. Animate 1.3.0 (rebased, separate branch)

`claude/vid-animate-ck-warm` (a06a0ea4) already held the rebase of `feature/pr-vid-animate-ck-warm` onto 88061016; its
third commit (launch-flag proof) is already on main. Verified here: changed non-GUI tests plus the code-map test (189
passed, 2 skipped), the two changed GUI test files (52 passed), PR gate OK. Both branches add a catalog version, so
whichever merges second must add one to the two counts in `test_pr_vid_gov_316_ti2v_governance.py`.

## d1. Smooth Storyboard takes and sequences

- Segments, hand-offs and cut manifests stay at native frames. Only the assembled movie is smoothed.
- Frozen in a separate stage-config key (`cut_interpolation`), so a segment's backend never smooths its own clip.
  Replay and resume keep it. Remove the refusals in `sequence_job_build` and `storyboard_readiness`, and suggest
  smoothing on for the sequence task (`workflow_tasks.REASON_SMOOTH_SEQUENCE`). Storyboard takes default to on when RIFE
  is found (injected check, so tests do not depend on the host).
- `video_interpolation` is capped at 400 frames and holds them in memory; a cut can exceed 972. Interpolate in chunks
  with a one-frame overlap to disk, then encode once.
- The smoothed movie is primary; the native movie is `retained_source` (container metadata and `retained_paths`), so
  only one reaches Review, phone and Immich.

## d2. Frame retention

Changed 2026-11-28 by KEEP-SPACE (`KEEP-SPACE_storage.md` section 1): 7 days instead of 1, and to the Recycle Bin
instead of a permanent delete. The rest of this section is the original design.

Setting `video_frame_cleanup_enabled` (default on, per the owner decision), a checkbox in Engine Settings. Deletion
cannot be undone, so **the first sweep needs the operator**: a dry run counts the frames and size and a non-modal window
shows them, with what is kept, and offers **Delete now**, **Not now** (asked again at the next start) and **Turn off**.
Delete now records `video_frame_cleanup_confirmed`; later sweeps then run on schedule without asking. Passes run only
while no job is queued or running, off the GUI thread, five minutes after start and every six hours. A read-only dry run
on 2026-11-27 found 100,268 removable frames (64.6 GB, 1,232 clip folders; 14 sequence runs skipped, 1,691 protected
names) in about 3.5 minutes.

Delete only PNGs listed in a backend manifest's `frames_out` block, inside that run folder, under the output root, and
only when that clip exists, is non-empty and is more than 24 hours old. Never delete:
- a clip, GIF, or any path in the artifact's `primary_path`, `output_paths` or `video_paths`;
- the first frame (thumbnail) or the last frame (exact hand-off);
- a frame referenced by any cut manifest (`root_cut.json`, `storyboard_cut.json`, lead-in manifests, and those named by
  Storyboard tree files);
- anything in a run folder with `sequence_state.json`, or under `video_eval`, the archive or `.stablenew-library`.

An unreadable cut manifest or tree stops the whole sweep. Each swept run gets a marker listing what was removed.

Two readers must be fixed in the same commit:
- `storyboard_root._frames_out_root` raises when frames are missing. With the marker, decode the unsmoothed clip instead
  (basis `decoded`), so Continue in Storyboard still works on older clips.
- `movie_clips_contract.extract_source_paths_from_bundle` prefers `frame_paths`; fall back to the video when any is gone.

Observation, not verified and not part of this package: the Output Library indexes every PNG, and Comfy frames carry no
`output_role`, so it treats them as primary and the phone publisher may be able to publish them. Retention here treats
"authoritative" as what the job's artifact record names.

## Owner questions (defaults built, 2026-11-27)

1. 3:4 size: 544x720 (built; 0.7 % crop) or 528x704 (no crop, 7 % fewer pixels)?
2. Selectable on the desktop before promotion? Built: yes, with Show experimental.
3. A 2:3 size? Built: 512x768 and 768x512.
