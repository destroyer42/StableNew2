# QUAL-CLOSEOUT-860 - Existing-capability qualification reconciliation (2026-11-05)

Status: dated evidence record. It supports the owner decision at the end; it does not supersede `STATUS.md`, authorize a
physical run or promote anything. Historical PR reports are untouched.

- **Execution class:** Standard, read-only evidence reconciliation plus documentation. No `src/` change, no GPU, Forge, Comfy or
  SVD runtime started, no model download, no restart.
- **Model recommendation:** Claude Code Sonnet 5.5 Medium; Codex GPT-6.1 Sol Medium.
- **Baseline:** `main` = `origin/main` = `a2794072a624ec75572916e403fd1f74afb19fcb`. Work is on branch `docs/qual-closeout-860`
  in a separate worktree; nothing is pushed or merged. The live checkout's `presets/settings.json` change was left alone.
- **Ledger:** `tools/qualification/system840/ledger.v1.json` (built from `d76d1acd`, reconciled here at `a2794072`).
  `python -m tools.qualification.system840 ledger --check --live` is valid before and after.

## 1. What the 50 entries say now

Columns: implemented, operator-reachable, strongest physical evidence, then the three qualification dimensions the ledger
derives status from (resource safety, product quality, integration), then the status. `PQ` partially qualified, `F`
feasible, `INC` inconclusive, `NT` not tested, `H` hold, `NG` no-go, `U` unsupported. Nothing is `QUALIFIED`, and product
quality is `NT` for every capability but one (`INC`): no visual-quality gate has been run anywhere. "Production path via
harness" means the canonical `JobService`/`run_njr` path driven by an acceptance script, never the operator GUI; no entry has
operator-GUI physical evidence, so none can reach QUALIFIED (`ledger.py:272-287`).

| Capability | Impl | Reach | Strongest physical evidence | Safety | Quality | Integr. | Status | Review |
|---|---|---|---|---|---|---|---|---|
| IMG-Q0.sdxl-forge-baseline | Y | Y | production path via harness, exact | PQ | NT | PQ | **PQ** | text: harness command lacked `--desktop-driver windows --plan` |
| IMG-Q1.sdxl-family | Y | Y | production path via harness, exact | PQ | NT | PQ | **PQ** | confirmed |
| IMG-Q1.klein-4b-fp8 | Y | Y | production path via harness, exact | PQ | NT | PQ | **PQ** | confirmed |
| IMG-Q1.klein-base-9b | N | N | none | NG | NT | NT | **NG** | confirmed |
| IMG-Q1.zimage-turbo-fp8 | Y | Y | feasibility, exact | INC | NT | NT | **H** | confirmed |
| IMG-Q1.qwen-image | N | N | none | NT | NT | NT | **U** | confirmed |
| IMG-Q1.other-generic-families | Y | N | none | NT | NT | NT | **U** | confirmed |
| IMG-Q2.adetailer-face | Y | Y | production path via harness, exact | PQ | NT | PQ | **PQ** | confirmed |
| IMG-Q2.adetailer-hands | Y | Y | production path via harness, exact | PQ | NT | PQ | **PQ** | confirmed |
| IMG-Q2.upscale | Y | Y | production path via harness, exact | NT | NT | PQ | **PQ** | confirmed |
| IMG-Q2.controlnet-openpose | Y | Y | feasibility, unverified source | NT | NT | NT | **F** | confirmed |
| IMG-Q2.controlnet-canny | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| IMG-Q2.controlnet-depth | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| IMG-Q2.reference-map-creation | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| IMG-Q3.masked-inpaint | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| IMG-Q3.outpaint | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| IMG-Q3.original-pixel-preservation | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| IMG-Q3.regenerate-with-changes | Y | Y | none | NT | NT | NT | **NT** | text: GP832-F3 repaired (`517868d3`) |
| IMG-Q3.compare-with-parent | Y | Y | none | NT | NT | NT | **NT** | text: GP832-F3 repaired |
| IMG-Q3.replay-and-provenance | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| IMG-Q4.forge-vs-comfy-still | N | N | none | NT | NT | NT | **H** | confirmed |
| IMG-Q4.ideogram4-diffusers | N | N | feasibility, exact | F | NT | NT | **F** | confirmed |
| VID-Q0.wan22-ti2v-5b-1.3.0 | Y | Y | production path via harness, unverified source | PQ | NT | PQ | **PQ** | confirmed |
| VID-Q0.wan22-ti2v-5b-1.2.0 | Y | Y | production path via harness, unverified source | PQ | NT | NT | **PQ** | confirmed |
| VID-Q0.wan22-ti2v-5b-legacy-1.0.0-1.1.0 | Y | Y | feasibility, unverified source | NT | NT | NT | **F** | confirmed |
| VID-Q1.svd-xt-native | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| VID-Q1.svd-rife-smoothing | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| VID-Q1.svd-loop-export | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| VID-Q2.motion-library | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| VID-Q2.motion-convert-blender | Y | Y | production path via harness, exact | NT | NT | PQ | **PQ** | **status NT to PQ** (integration): section 2 |
| VID-Q2.fun-control-5b-canny | Y | N | feasibility, exact | F | NT | NT | **F** | confirmed |
| VID-Q3.wan-animate-2 | Y | Y | feasibility, unverified source | PQ | INC | NT | **PQ** | confirmed |
| VID-Q4.wan-a14b-480p | N | N | feasibility, exact | INC | NT | NT | **INC** | confirmed |
| VID-Q5.make-video | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| VID-Q5.prepare-motion-source | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| VID-Q5.playback-and-history | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| VID-Q5.movie-clips-assembly | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| VID-Q5.storyboard-save-reopen | Y | Y | none | NT | NT | NT | **NT** | text: GP832-F4 repaired (`a4954e33`) |
| VID-Q5.eval-kit-and-ratings | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| VID-Q5.two-three-segment-sequence | Y | Y | production path via harness, unverified source | PQ | NT | PQ | **PQ** | confirmed |
| AI-Q0.protected-capture-readiness | Y | N | feasibility, exact | NT | NT | NT | **H** | confirmed |
| AI-Q1.qwen3.5-9b-q4_k_m-unsloth | Y | N | none | NT | NT | NT | **H** | confirmed |
| AI-Q1.qwen3.5-9b-q5_k_m-unsloth | Y | N | none | NT | NT | NT | **H** | confirmed |
| AI-Q1.qwen3.5-4b-q8_0-unsloth | Y | N | none | NT | NT | NT | **H** | confirmed |
| AI-Q1.qwen3.5-4b-q4_k_m-unsloth | Y | N | none | NT | NT | NT | **H** | confirmed |
| AI-Q1.lfm3-1.7b-q4_k_m-liquidai | N | N | none | NT | NT | NT | **H** | confirmed |
| AI-Q1.lfm3-1.7b-q8_0-liquidai | N | N | none | NT | NT | NT | **H** | confirmed |
| AI-Q2.prompt-suggest-integration | Y | N | none | NT | NT | NT | **H** | confirmed |
| AI-Q3.sam21-small | Y | Y | none | NT | NT | NT | **NT** | confirmed |
| AI-Q3.florence2-base-ft | Y | Y | none | NT | NT | NT | **NT** | confirmed |

How "confirmed" was decided: the validator derives each status from the evidence and finds no mismatch; `--live` finds no
drift against the live workflow catalog, governance and AI registry; every cited path exists; and every entry's evidence is
keyed to a model, workflow, runtime or tool identity rather than a source revision. Source did move after the physical
evidence for the image and Wan entries (for example 26 commits touching the IMG-Q0 modules since 2026-10-01), but none changes a
recorded identity, and the ledger already carries `unverified:` exact sources where the executed SHA was never recorded. That
is a confidence limit, not a reclassification. The one status change and the text corrections below are the only edits.

## 2. Corrections made (each with its source)

1. **`VID-Q2.motion-convert-blender`: NOT TESTED to PARTIALLY QUALIFIED (integration only).** The 2026-11-04 claim
   "conversion was HOLD, no Blender" is superseded. Journey VID-02 with a supplied Blender 4.5.9 LTS converted two BVH skeletons
   through the Batch Convert dialog under the Windows input driver at the normal, 1280x680 minimum and maximized layouts: each
   result is a 17-frame 480x832 H.264 MP4 whose independent SHA-256 equals the record, whose provenance names the original and
   which the Motion Library kept across a restart. Source: repo `d8e3e9d09e17e334d7f4a21f75e1101389b41703` (no
   `src/video/motion_conversion` change to `a2794072`); sealed archives
   `20261105T130629Z_simulated_d8e3e9d0_normal_acceptance_5da5c5`, `20261105T132035Z_simulated_d8e3e9d0_minimum_acceptance_afbcab`
   and `20261105T133347Z_simulated_d8e3e9d0_maximized_acceptance_00abdb` under `~/StableNewAcceptance/golden-paths`, each re-hashed OK
   on 2026-11-05.
   Limits: BVH skeleton route only (no FBX), quality unjudged. The run is labelled `simulated` because Forge and Comfy are
   loopback fakes; the Blender step is real and observed. The offline GUI-only entries (Motion Library, Make Video, History,
   Storyboard) stay NOT TESTED: no real external tool or model ran for them.
2. **GP832-F3 and GP832-F4 are repaired, not open** (`findings.v1.json` repair block; `517868d3`, `a4954e33`; journeys IMG-03
   and VID-03 PASS at `d8e3e9d0`). Ledger text for `IMG-Q3.regenerate-with-changes`, `IMG-Q3.compare-with-parent` and
   `VID-Q5.storyboard-save-reopen` said "unrepaired".
3. **`IMG-Q0` next-test command was not runnable**: physical mode refuses without `--plan` and `--desktop-driver windows`
   (`tools/operator_journey/golden/modes.py:39-71`).
4. **Device-loss count.** The Windows event log (Kernel-PnP event 1000, NVIDIA device, queried read-only 2026-11-05) holds
   **21** remove-veto markers since 2026-09-07; the last record (`DIAG-GPU-150`) counted 19. The extra two are 2026-10-22 20:10:56
   and 2026-10-30 18:50:44 (ET). No DIAG record in the tree covers either (a local folder `C:\Users\rob\qual\GPU-20261022-2010`
   exists for the first). `STATUS.md` and the ledger hold now say so. Root cause is still unattributed.
5. **Coverage matrix** (`tools/operator_journey/golden/coverage_matrix.v1.json`): two rows still cited failures that no longer
   fail. `GP830-I1` was repaired in 831; the discovered-outputs journey test passes, as do
   `tests/gui_v2/test_photo_optimize_tab_v2.py` and `test_photo_baseline_save_580.py` (17 passed, 2026-11-05, `a2794072` plus
   these edits). Coverage classes are unchanged.
6. **`STATUS.md`**: dated 2026-11-05; "persistent Storyboard authoring" is delivered, not the active outcome; the active
   qualification state and this record are named in place (the file stays at its 150-line cap); loss count above.
   **`tools/qualification/README.md`**: "Physical runs are on HOLD" contradicted `STATUS.md` (hold lifted 2026-10-18); the
   inventory lacked `fun354`, `seq330_*` and `vid324_frames_out_acceptance`, all tracked and tested. **`docs/CODEX_MAP.md`**:
   the qualification row names the golden-path gate.

Reuse: the Windows-driver archives at `d8e3e9d0` stay valid for `a2794072`. The only later source edits are two exception-handler
changes (`src/pipeline/pipeline_runner.py:957`, `src/services/operator_readiness_service.py:415`) from `b986c33c`; the
first now lets an exception from `take_model_sync_failure` propagate instead of being swallowed. Its regression tests
(`tests/pipeline/test_checkpoint_mismatch_operator_reason.py`, `tests/queue/test_webui_running_claim_projection_832.py`) pass (13 passed,
2026-11-05); the helper only swaps an attribute, so no behavior change is expected, but the archives do not cover those two lines. The archives at `88314856` (research branch, before the 833 repairs) show IMG-03/OPS-01 FAIL and VID-02 HOLD;
they predate the repairs and are not evidence for `main`.

## 3. The next qualification: IMG-01 (Forge SDXL), not VID-01

Both are covered by the existing harness (`python -m tools.operator_journey --suite golden-paths`, journeys `image` and
`video`; `tools/operator_journey/golden/img01.py`, `vid01.py`, `physical.py`, `plan.py`, `readiness.py`; doc
`docs/Subsystems/Testing/TESTING_AND_CI.md` section 11a). No replacement harness is needed. Nothing has ever run in physical
mode (`coverage_matrix.v1.json` row `physical-gpu-generation-through-the-gui`). "Approved" for Wan 1.3.0 is catalog governance;
no physical run authorization exists for either journey.

Read-only readiness (`--mode readiness`, no runtime started) on 2026-11-05 at `a2794072`:

| | IMG-01 (Forge SDXL, 512x512, 6 steps, 1 job) | VID-01 (Wan2.2 TI2V-5B 1.3.0, 17 frames, 1 job) |
|---|---|---|
| Verdict | HOLD: external Forge not running | NO-GO: 9.1 GB RAM available, 16 GB needed |
| Runtime ownership | Forge is external: the owner starts it, the harness never does | Comfy managed: the product process manager owns and releases it |
| Assets | checkpoint present, SHA-256 equals the accepted baseline | weights present; source image present (hash frozen) |
| Prior envelope | 16.3 s, 8,118 MiB peak (Pair A, `702a4fe8`) | peak 11.2 GiB of 12 GiB, free RAM down to 1.9 GB (cold-load floor 16 GB, `workflow_catalog.py:363`) |
| Why it ranks | The default product path underpins `IMG-Q1`, `IMG-Q2`, `IMG-Q3`; smallest workload; one external prerequisite | The run is near the VRAM ceiling and the host RAM floor; two of its 2026-10-21 acceptance attempts (`reports/vid324*`) stopped at the product's RAM gate (15.7 GB) and at a startup timeout before later runs passed |

IMG-01 is first because it is the smallest workload on the most-depended-on path with a single unmet prerequisite; VID-01
is second and needs RAM freed first. A `PASS` would raise only the integration evidence of `IMG-Q0` from harness-driven to
GUI-driven; quality stays pending operator review.

### 3.1 Immutable plan identity

Plan file (outside Git, unauthorized): `C:\Users\rob\qual\qual860-evidence\plan_img01_UNAUTHORIZED.json`

- digest `74ad40503fda22cd4d51265fcc196b3e7cf84ea00f9297ea8b6f2622d802baaa`; typed launch phrase `RUN 74ad40503fda`
- repo `a2794072a624ec75572916e403fd1f74afb19fcb`, host `Rob-Gaming-Desk`, Windows 11 10.0.26100, Python 3.14.9,
  RTX 4070 Ti 12,282 MiB (driver 621.01, uuid `GPU-7d893fd1-7bcd-2bf9-ee0f-03601830eec3`)
- Forge external at `http://127.0.0.1:7860`, identity `forge_webui@d70373ebcf1a`
- model `cyberrealisticXL_v90-16fp.safetensors`, SHA-256 `4f2dc6418c8d93737e2d0a5f022707977c783851e79ccd23aed1fda8397ac10e`
  (hashed on the host, equals `PR-IMG-FORGE-100`), path `C:\Users\rob\stable-diffusion-webui\models\Stable-diffusion\`
- 512x512, 6 steps, seed 424242, prompt `golden path image, a lighthouse at dusk, oil painting`, negative `blurry, low quality`,
  pack `golden_img01`, ADetailer and upscale off, 1 job, 1 artifact
- limits: timeout 300 s, VRAM <= 10,500 MiB, available RAM >= 6 GB, commit <= 40 GB, free disk >= 10 GB (proposed by this
  record; the owner approves them by approving the digest)

The digest covers the repository SHA. Merging any commit, including this documentation branch, changes `main`'s HEAD and
requires re-freezing (`--build-plan`, one command, read-only) and a new authorization. Run it before the branch merges, or
re-freeze after.

### 3.2 Command, evidence and stops

```text
python -m tools.operator_journey --suite golden-paths --journey image --mode physical --desktop-driver windows --plan <authorized plan>
```

Gates in order (`physical.py:261-300`): plan readable and intact, authorization names this digest and `image` with a future
`expires_at` (`plan.py:183-208`), environment equals the frozen one, readiness PASS, then the operator types the phrase at an
interactive terminal. Any miss is HOLD and starts nothing.

Evidence: a run folder under `reports/operator_journeys/` (`plan.json`, `evidence.json`, `summary.md`, `actions.jsonl`,
screenshots, `artifacts.json` with the image path, SHA-256 and decoded geometry, `resource_telemetry.jsonl` every 2 s) and a
sealed archive under `~/StableNewAcceptance/golden-paths/` (`MANIFEST.json`, `COMPLETE`; check with `--verify-archive`).
Three independent outcomes are reported: functional, resource/runtime safety, and visual quality, which stays
`PENDING_OPERATOR_REVIEW`.

Stop conditions (all NO-GO, never retried, a generation POST is never replayed): device loss, CUDA/OOM error text, 300 s timeout,
any retry or return-to-queue (ambiguous dispatch), GPU or host telemetry loss, VRAM or commit over the plan, RAM under the
floor, environment drift mid-run, an NJR that disagrees with the plan or a second job (`PlanGate`, `frozen.py:138-167`).
Any new device loss also stops the campaign (`HOLD-GPU-DEVICE-LOSS`).

### 3.3 Owner authorization required (none has been given)

1. Decide whether a GPU run is acceptable given 21 loss markers, the newest on 2026-10-30, and whether the PCIe Gen3 variable
   from `DIAG-GPU-150` was applied. The last five documented losses came 4-11 s into Forge txt2img jobs, which is what IMG-01 does.
   Optional: start `tools/diagnostics/gpu_hang_recorder.py` first.
2. Start the pinned managed Forge Neo (`d70373eb`) yourself, idle on `127.0.0.1:7860`, with no other StableNew instance
   running. The harness will not start, stop, adopt or restart it.
3. Add the authorization block to a copy of the plan (the harness never writes it): `"authorization": {"state": "approved",
   "approved_by": "<name>", "plan_digest": "<full digest above>", "journeys": ["image"], "expires_at": "<ISO time>"}`. It is
   not part of the digest.
4. Sit at the desktop with other windows closed and hands off the mouse and keyboard while the Windows driver runs, then type
   `RUN 74ad40503fda`.

## 4. Unresolved implementation defects (evidence-proven only)

- `GP833-F1` (minor, UNREPAIRED): a claimed job waiting on an unreachable backend is RUNNING with no "preparing" state; the
  registry says it needs an owner decision. `GP833-O2` (Motion Library tree and Review canvas capture the mouse wheel) and
  `GP833-O3` (Review Edit Mask and Extend Canvas below the fold at the minimum window) are minor and UNREPAIRED. None blocks the
  candidate. No source-change PR is recommended here.
- Not defects, but unverified: Smart Review edits record no parent (a safe default); the two newest device-loss markers have
  no analysis.

## 5. Checks run (all non-GPU)

- `ledger --check --live`: valid, 50 capabilities, before and after the edits.
- `tests/tools/test_qual840_*.py` (four files): 98 passed. `--check-registries`: OK. The 17-test group in section 2.5: passed.
- `--verify-archive` on the six archives cited: OK.
- Readiness for both journeys with unauthorized plans; the VID-01 plan is an analysis artifact, not a candidate.
- Not run: the full census or any gate beyond these, because no executable source changed.

## 6. Next owner decision

Authorize the IMG-01 plan above (or decline it, or ask for a re-freeze after the documentation branch merges). Independent
of that, the documentation branch needs a decision to publish: it is committed locally and not pushed.

### 6.1 Update, 2026-11-06 (this record's decision was taken)

The owner authorized the IMG-01 plan and it was run under `QUAL-IMGQ0-FAILFAST_Closeout.md`: four GUI-driven physical attempts (one NO-GO on
the 6 GB host-RAM floor, then three functional and safety PASSes under an owner-accepted 2 GB floor). IMG-Q0 stays PARTIALLY QUALIFIED
(quality NOT TESTED); no ledger entry is QUALIFIED. The sections above are the 2026-11-05 evidence as written; sections 3.3 and 6 are
superseded by that closeout record. The documentation branch is published together with the fail-fast repair.
