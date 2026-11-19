# PR-VID-CLIP-371: Three-Engine Human-Motion Evaluation (evidence record)

Status: evidence and owner decision only. Nothing is promoted by this change;
no code, spec, schema or setting changed. Raters: the owner, by hand-edited
`ratings.csv`. Suites, source images, prompts, clips and contact sheets are
private and not in the repository.

## Identities

| Item | Value |
|---|---|
| Plan digests | v1 `be71c7ee…31c5`, v5 `b400b079…9d5d`, v6 `d2ec5595…4204` (SHA-256 of canonical JSON; v6 authorized by the owner) |
| Stage 0 run | `20261116_013842_clip371-stage0_c9b8ea34`: 16 jobs, TI2V-5B 1.3.0 480p, terse vs structured prompts, seed 371 |
| Stage 1 run | `20261116_134153_clip371-stage1_c947ec0a`: 48 jobs, 3 arms x 8 cases x 2 prompt styles, seed 371, suite sha `03281df3…a9ed6` |
| Stage 2 run | `20261118_040044_clip371-stage2_b060db61`: 16 jobs, A14B vs TI2V-720p, 8 full-body cases, seed 372, suite sha `39e19991…e511b` |
| Runtime | managed ComfyUI 0.38.0, PyTorch 2.14.0+cu130, on every completed clip |

Budget 80 generations (owner-raised from 56). Suite sha, seed, workflow
version, geometry, prompt and negative prompt matched the frozen plan on every
completed clip (0 mismatches).

## Results

Completion: Stage 1 44/48 (3 failed health checks or timeouts on 720p, 1 cold-start health check on 480p); Stage 2 15/16
(1 cold-start health check on 720p, no retry). Wall time per clip, Stage 1/2:
TI2V-480p 32-132 s; A14B-480p 140-176 s; TI2V-720p 47-622 s (mean 399 s in
Stage 1, 314 s in Stage 2; two Stage 1 clips hit the 600 s history timeout).

Mean owner ratings (1-5); fidelity and stability saturated at 5 on all arms.

| Arm | Action achieved or partial | Identity breaks | Fidelity / stability |
|---|---|---|---|
| A14B 4-step 480p, Stage 1 terse | 8/8 | 0 | 5 / 5 |
| A14B 4-step 480p, Stage 1 structured | 8/8 | 0 | 5 / 5 |
| A14B 4-step 480p, Stage 2 full-body | 8/8 (all achieved) | 0 | 5 / 5 |
| TI2V-5B 720p, Stage 1 terse (5 rated) | 4/5 | 0 | 5 / 5 |
| TI2V-5B 720p, Stage 1 structured | 5/8 | 0 | 5 / 5 |
| TI2V-5B 720p, Stage 2 (7 of 8 clips) | 5 achieved, 2 cannot assess | 0 | 5 / 5 |
| TI2V-5B 480p baseline, Stage 1 terse (7 rated) | 3/7 | 0 | 5 / 5 |
| TI2V-5B 480p baseline, Stage 1 structured | 4/8 | 0 | 5 / 5 |

Structured prompting: no lift on Stage 0 (baseline engine); in Stage 1 it
matched A14B terse and added one action on 720p and baseline. By the rule
(>= 1 point on mean action or stability) it did not qualify as helping, partly
because stability could not rise above 5.

## Verdicts against the accepted thresholds

- **A14B 4-step 480p: not NO-GO.** 8/8 action in Stage 1 and Stage 2, 0
  identity breaks, means 5. This is a pass on the stated thresholds, not
  QUALIFIED status.
- **TI2V-5B 720p: NO-GO under the written thresholds.** One clip took 622 s,
  over the 10-minute limit, and the +1 stability gain over baseline is
  unreachable on a saturated scale. Stage 2 is INSUFFICIENT EVIDENCE (one case
  has no clip, so no verified fully reviewed comparison).
- **TI2V-5B 480p: stays fast draft.** With A14B passing, it is NO-GO as primary
  human-motion engine.

## Not demonstrated

No host-commit telemetry (the 0.95 rule is unobserved, no allocation failure was
seen); ratings saturate so stability differences are hidden; Stage 1 and 2 images
and prompts were authored by the evaluator rather than the owner's own; the
owner judged 720p visually superior, which the thresholds do not capture; 5 failed
jobs have no clip.

## Owner decision (2026-11-18, recorded, not implemented here)

After reviewing the clips the owner decided, overriding the written 720p
thresholds on visual quality: both experimental workflows are a GO and treated
as qualified by the owner. A14B 4-step 480p is the promoted engine and the
intended Make Video default. TI2V-5B 720p is an alternate. TI2V-5B 480p stays
available but is not the default. This record changes no code, spec or
setting; implementing the decision is a separate package.

Implementation (VID-CLIP-372): A14B 1.0.0 is approved and the Make Video default, the 720p history timeout is
1200 s (per spec), an owned ComfyUI gets a 180 s cold-start readiness window, the A14B launch flag is applied or
Queue is blocked, and an approved workflow on a ComfyUI other than 0.38.0 warns (`VIDEO_PIPELINE.md` sections 1.1
and 4.4). **Held for an owner decision:** approving TI2V-5B 1.4.0 (720p) while keeping 1.3.0 (480p) selectable, because
the picker offers one entry per workflow id and the newest approved version would hide 1.3.0.

## Recommended next actions (each a new package)

1. Promotion package: move `wan22_i2v_a14b_4step_v1` 1.0.0 from experimental to
   approved and make it the Make Video default; keep `wan22_ti2v_5b_i2v_v1`
   1.4.0 (720p) as an approved alternate and 1.3.0 (480p) selectable, not
   default. Update the catalog, STATUS Holds and VIDEO_PIPELINE.
2. Runtime and timeouts: the 600 s history timeout fails valid 720p clips (two
   Stage 1 timeouts); raise or make it per workflow. Cold-start health checks
   failed three times at 30 s; lengthen or retry readiness on first launch.
3. Make the A14B `--disable-pinned-memory` requirement part of managed runtime
   configuration, and warn when an approved workflow runs on a runtime it was
   not qualified on (0.38.0).
4. Add host-commit telemetry so the 0.95 stop rule is observable.
5. Add an eval rating screen (ratings are a hand-edited CSV today) and a wider
   rating scale or anchors, since fidelity and stability saturate at 5.
6. Optional: a video LoRA input; RAM 32 to 64 GB; re-run `cannot_assess` and
   the failed fb3 720p case after the timeout work.
