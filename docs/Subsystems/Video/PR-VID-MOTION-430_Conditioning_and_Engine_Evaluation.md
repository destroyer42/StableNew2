# PR-VID-MOTION-430: alternative conditioning, engine evaluation and qualification readiness

Status: **implemented on a feature branch; offline only** (Phase 4 of `docs/Subsystems/Video/CONTROLLED_MOTION_ROADMAP.md`). This is a per-PR record: the code and
the living docs (`VIDEO_PIPELINE.md`, `MOTION_LIBRARY.md`, `docs/runbooks/motion_conditioning_and_engine_evaluation.md`, `docs/runbooks/video_eval_kit.md` section 12) win where they differ. No physical
generation, qualification run, model download, dependency or custom-node installation, workflow promotion or ledger change was made.

Execution class: Standard, difficult bounded cross-file. **Model recommendation:** Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh (`docs/AI_MODEL_SELECTION.md`).

## 1. Baseline and prerequisites (verified, not assumed)

| Fact | Evidence |
|---|---|
| Start state | `origin/main` `7885a184` (PR #419); feature worktree `qual/StableNew-vid-motion-430`, branch `feature/pr-vid-motion-430-conditioning-engine-eval` |
| Phase 1 (400), Phase 2 (410), Phase 3 (420) are integrated | PR #399 `c0a837fe`, PR #405 `e421db70` (plus closeout #409), PR #413 `3c4c4d6a`; each branch tip is an ancestor of `origin/main` |
| Fun Control 1.1.0 trial is the registered current version | `workflow_catalog_fun_control.py`: same graph as 1.0.0, `trial_unqualified`, 10,000 MiB VRAM floor and 16 GB RAM advisory (provisional), per-job opt-in; 1.0.0 still refuses |
| Applicable physical evidence | 410: 15-job Stage A/B pilot and 11-job revised Stage C, motion ratings blank. 420: 2-job pilot, 8-job diagnostic and 2-job re-run, **unrated**; the 16-job stage has not run. VID-MOTION-354 run 3: 14/14 Fun Control cases feasible on 1.0.0's graph (RTX 4070 Ti 12 GB) |

**Limitation reported, not hidden:** the roadmap says Phase 4 depends on applicable evaluation evidence. The Phase 2 and 3 evidence that exists is mostly *unrated*, so
this package could not refine case selection from accepted rated results (Workstream H) or establish an alignment baseline from accepted Phase 3 evidence (F.3).
It built the offline capability the owner asked for, kept alignment an explicit declared variable and left every physical stage unauthorized. Stage design must be revisited
once the 410/420 results are rated.

## 2. What was verified in the pinned runtime (ComfyUI v0.38.0, `6b747c04`)

Read from the installed source, not from names or older docs. These are `runtime_source` facts, not measurements.

| Workflow | Order of operations on the driving clip |
|---|---|
| Fun Control (`Wan22FunControlToVideo`) | `LoadVideo` -> `GetVideoComponents` -> **`Canny` at the frame's own size** (kornia, fixed 0.1 / 0.6) -> the node takes the first `length` frames, **centre-crops to the aspect and resizes bilinearly** to width x height -> VAE-encode. The edge image is one channel repeated to three |
| Wan-Animate-2 (`WanAnimate2ToVideo`) | `LoadVideo` -> `GetVideoComponents` -> `ResizeImageMaskNode` (area, centre crop) -> in the node: first `length` frames, **a clip shorter than `length` is padded by holding its last frame**, VAE-encode; the first frame is also CLIP-vision encoded as extra context |

The 354 preview cropped *before* detecting edges and used a 1-4-6-4-1 Gaussian. Both differed from the graph: it now runs Canny first, then crop and bilinear resize, with the
exact sigma-1 kernel and replicate-padded Sobel. Four deterministic synthetic vectors, generated with the pinned venv's kornia 0.8.3 on the CPU (no ComfyUI process, no GPU), match the NumPy
implementation bit for bit (`tests/video/canny_vectors_430.py`, `test_pr_vid_motion_430_conditioning_preview.py`). The label stays **approximate**: real-clip parity, the full-size analysis and the model's float32 path are not
verified, and exact parity would need the separately authorized physical runtime.

## 3. What was delivered (implementation)

| Workstream | Delivered | Where |
|---|---|---|
| A. Conditioning contract | A pure projection derived from each registered graph: representation vocabulary, mechanism, ordered stages, geometry, lengths, preparation, controls, governance, resource policy, limitations (each with a basis). Precomputed edge maps and pose maps are refused; shared envelope (17-49 frames at 24 FPS) and engine-change problems | `src/video/workflow_conditioning.py` |
| B. Representation variants | `movement_key` (every conversion choice except the profile) recorded additively on `DerivationRecord`; catalog grouping and detail lines; re-verification against the conversion record; suite binding carries a validated `representation` claim | `motion_conversion/representation.py`, `motion_library/variants.py`, `models.py`, `library_bridge.py`, `snapshot.py`, `video_eval_authoring.py` |
| C. Effective-conditioning inspection | Graph-order preview, exact kernel, labelled fidelity, structured advisories with a basis, effective prepared/aligned driver selection, stale-preparation reporting | `conditioning_preview.py`, `conditioning_advisories.py`, `conditioning_inspection.py`, controller delegate, Follow-a-driving-clip window |
| D. Engine selection | Readiness details show how the selected engine uses the clip and what it does with each representation; engine rows; an engine change blocks a preparation made for another workflow, version or length (existing session, now tested) | `workflow_motion_guidance.motion_readiness_projection`, `video_motion_readiness_contract.py`, `conditioning_inspection.engine_rows` |
| E. Fun Control trial and qualification readiness | The 1.0.0 plan and its digests are unchanged; a separate 1.1.0 plan pins graph, assets, resource-policy identity and trial telemetry; Q0 re-checks the policy; decimal GPU temperatures no longer end sampling in the older monitors | `tools/qualification/fun354/`, `vid160c/telemetry.py`, `vid110/monitor.py`, `vid110/inventory.py` |
| F/G. Evidence | `MULTI_ENGINE` and `REPRESENTATION` comparison kinds; engine disclosures; a case's motion prompt is sent only to an engine that declares the control; representation-group integrity; five new summary levels | `video_eval_integrity.py`, `video_eval_assessment.py`, `video_eval_transfer.py`, `video_eval_motion.py`, `video_eval_run.py`, `video_eval_motion_html.py` |
| H. Campaign | Four unexecuted staged templates (2 / 12 / 12 / 4 jobs, 30 before reuse) | `docs/runbooks/examples/video_eval_conditioning_stage*.suite.json` |
| I. Assessment | Three candidate approaches, all conditional | `docs/assessments/2026-11-25_vid_motion_430_alternative_conditioning_candidates.md` |

A found gap closed on the way: a motion suite injected the case's motion prompt into every arm, so a Fun Control arm was refused ("does not accept workflow controls"). Engine
comparison was impossible until the prompt became engine-specific; the pair is now disclosed, not refused, and two different prompts or a missing prompt on the *same* engine stay incomparable.

## 4. Supported representation matrix

| Driving representation | Wan-Animate-2 1.2.0 | Fun Control 1.1.0 (trial) |
|---|---|---|
| RGB footage | accepted; appearance and background visible to the model | accepted; Canny keeps outline, clothing texture and background edges |
| Rendered character | accepted; its appearance is visible | accepted; outline plus texture edges |
| Rendered silhouette | accepted as RGB; no edge step; **not tested** as an Animate-2 driver here | accepted as silhouette-derived RGB, then Canny; not an externally computed edge tensor |
| Rendered skeleton | accepted as RGB; effect untested | accepted; Canny of the drawn lines; head orientation only as present as the bones |
| Precomputed edge map | refused (no edge path) | refused (it would be Canny-ed again; no direct-edge mode) |
| Explicit pose map | refused (no registered graph) | refused (no registered graph) |

Capability is declared by the registered graph; a new direct-edge or pose pathway needs its own verified, versioned workflow.

## 5. Fun Control: trial, qualification proposal and evidence boundaries

* **Not changed:** 1.0.0's graph and blocking policy, 1.1.0's trial policy, every stop condition, authorization semantics and the immutable catalog. Nothing was promoted or written to a ledger.
* **Proposal (offline):** `python -m tools.qualification.fun354 propose --workflow-version 1.1.0 ...`. With no inputs pinned the structural digest is
  `54a33e11d36d163d3128cfd7b639ebfb3410c23f03e30417f8046b98f23254d8` (graph `42a6f0b6cd3c...`, resource-policy digest `bceb4df94244...`, runtime commit `6b747c04...`);
  an authorizable plan exists only once the owner pins real prepared clips, which mints a new digest. The unpinned file was written to the operator evidence folder outside the repository.
  Q1 is one 17-frame case; Q2 is two 49-frame seeds and a cancel/release case. The plan records GPU temperature and the minimum VRAM headroom; it does **not** capture separate cold-start/generation durations or allocator state.
* **Evidence categories, kept apart:** historical technical feasibility (354 run 3, 1.0.0's graph); experimental trial admission (owner decision 2026-11-24); current runtime readiness (the standard policy at preview, queue and dispatch);
  standardized motion-quality evaluation (the 410 rubric, unrated so far); formal hardware qualification (none); production promotion (none). The 14-case result does not qualify 1.1.0.
* **Oversized drivers:** Prepare Motion Source scales an input longer than 832 px to an 832-pixel long edge for Fun Control (`fun-control-canny-max-832`), and the app refuses older oversized prepared records. The advisories point to the prepared derivative; no new
  hard threshold was imposed. The 4K failures happened before that scaling existed.
* **Older-monitor defect:** `vid160c` sampling called `int()` on `nvidia-smi` temperature, so a decimal value ("83.9") raised and silently ended telemetry; `vid110`'s parser had the same defect. Both now keep decimals. The `img110r` parser has the same pattern; it is an image harness outside this package and was left alone.

## 6. Documentation reconciled

`STATUS.md` still described Fun Control as having "Queue refusal"; `VIDEO_PIPELINE.md` listed only 1.0.0; `motion_conversion.md` said Queue stays blocked and the preview "stays approximate until tested against known vectors".
They now state the version-specific truth (1.0.0 refuses; 1.1.0 is a trial) and the vector evidence. Historical version records were not rewritten.

## 7. Known limitations and owner decisions

* No physical evidence was produced; every campaign stage and the qualification plan await exact-digest owner authorization.
* Phase 2/3 results are unrated; revisit the stage designs after they are rated. Whether the sampled evidence changes Phase 4 priorities is unknown.
* The preview is approximate; limb definition is not measured (only faint or sparse outlines are flagged); "multiple subjects" is a coarse column-profile heuristic.
* Silhouette and skeleton drivers for Animate-2 are untested here; skeleton head turns are expected to be poor.
* Provisional Fun Control floors are unchanged; changing them needs measured evidence and an owner decision.
* Candidate assessment recommendations (pose/depth control on the pinned Fun Control weights; SCAIL-2 gated by a resource check; VACE deferred) are conditional and unverified on this GPU.
* Not implemented: automated recommendations, recipes (VID-MOTION-440), segmentation or pose-estimation dependencies, new graph variants.

## 8. Acceptance (summary)

AC-01..AC-23 are met by deterministic tests or documentation inspection, as above. AC-20 (qualification proposal) is met as an *unpinned structural proposal*. AC-24: no physical generation, install, promotion or runtime change occurred. AC-25 is recorded in the PR body (gate and review).
