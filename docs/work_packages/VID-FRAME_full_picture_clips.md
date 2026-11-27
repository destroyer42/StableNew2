# VID-FRAME: whole-picture A14B clips, smoothed cuts, frame retention

Status: design written 2026-11-26; **no code yet**. Base `origin/main` 88061016, branch `claude/vid-frame`.
Owner decisions (2026-11-27): "Whole source picture at same pixel count"; video frames on disk may be deleted 1 day
after their clip exists; the owner will do a blind rating of the faster attention (CK) profile.

Execution class: Standard. Model recommendation: Claude Code Sonnet 5.5 at high effort, or Codex equivalent.
Controller surface: one source-geometry field on the workflow record in `video_workflow_controller.py`; no ratcheted
controller grows. Validation: focused tests per commit, then `tests/video`, `tests/system`, `tests/tools/test_code_map.py`,
`python tools/ci/run_pr_gate.py` and ratchets; GUI tests alone. No test may need FFmpeg or RIFE. No GPU work.

Not in scope: new engine or model, 2:3 sizes, picker redesign (PRs #461 and #462 change the form and picker, so form
edits here stay minimal).

## a. Sizes: A14B 1.4.0 (experimental)

- New version `1.4.0` of `wan22_i2v_a14b_4step_v1`: the 1.0.0 graph and files, only `source_preparation` differs.
  `make_video_default` False. `a14b_launch_attention` must return `baseline` for it, as for 1.0.0.
- Policy gains optional `aspect_targets`: 480x832, 544x720, 624x624, 720x544, 832x480 (multiples of 16, at or just
  under 399,360 pixels). The size that crops the source least is chosen. 768x1024 -> 544x720 (0.7 % crop; the exact
  3:4 alternative 528x704 has 7 % fewer pixels). 1024x1024 -> 624x624 (no crop).
- All A14B specs declare `max_crop_fraction` 0.05. Above it, an N1 warning (`video_source_cropped`, why and fix) is
  shown beside Queue, in the multi-image batch preview, and frozen in accepted warnings. It never refuses.
- Provenance: `source_preparation` gains `crop_fraction`; the chosen size is already `target_dimensions`.
- Touch points: `workflow_source_preparation.resolve_declared_target`, `workflow_warnings`, `policy_warnings`,
  `video_workflow_njr_builder`, `video_workflow_batch.assess` (its `warnings` list), `list_workflow_specs`,
  `video_workflow_tab_frame_v2._experimental_warning_text` plus a source-change trace to `_refresh_queue_gate`.
- Tests that list versions must change: `test_vid_a14b_374_speed_arms.py`, `test_pr_vid_gov_316_ti2v_governance.py`.
- Add eval suite `docs/runbooks/examples/video_eval_a14b_full_picture.suite.json` (1.0.0 vs 1.4.0).
- Reachability: the picker offers only the approved version of a workflow id, and phone video lists runnable
  (approved) specs only, so until promotion 1.4.0 runs through the Video Eval panel.

**GPU test needed before 1.4.0 becomes the default** (none run): for 544x720, 624x624 and 720x544 at 81 frames on the
12 GB card, cold and warm: peak VRAM, host RAM, wall time, no out-of-memory; 121 frames (the declared maximum) for
544x720; then an owner-rated motion and identity comparison against 1.0.0 on the same 768x1024 and 1024x1024 sources,
prompts and seeds. Readiness floors stay 1.0.0's and are unmeasured at these sizes.

## b. Blind CK rating sitting

Prepare, from existing clips only, a blind pairwise comparison of `wan22_i2v_a14b_4step_ck_v1` against the A14B 1.0.0
default using the existing video eval kit. No GPU jobs. Sources named in the evidence note
(`04_video_as_built.md` findings 4 and 6: 63 CK jobs in the job database, and a prepared 10-job blind suite recorded in
memory `animate-job-time-breakdown.md` that has not run). Not yet investigated.

## c. Animate 1.3.0

Rebase local `feature/pr-vid-animate-ck-warm` (d499ea2d, worktree `C:\Users\rob\qual\StableNew-vid-animate-ck-warm`)
onto main as its own branch; report conflicts, do not force. A branch `claude/vid-animate-ck-warm` (a06a0ea4, worktree
`C:\stn-tmp\vf\wt-animate`) already exists on this machine and was **not inspected**: check it first.

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

Setting `video_frame_cleanup_enabled` (default on, per the owner decision), a checkbox in Engine Settings. The sweep
runs only while no job is queued or running, off the GUI thread. Deletion cannot be undone; turning the setting off
only stops further deletion.

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

## Owner questions

1. 3:4 size: 544x720 (0.7 % crop, same pixel count) or 528x704 (no crop, 7 % fewer pixels)?
2. Should 1.4.0 be selectable on the desktop before it is promoted?
3. 2:3 sources (for example 832x1216) still crop about 9.5 % and will warn. Add a 2:3 size?
