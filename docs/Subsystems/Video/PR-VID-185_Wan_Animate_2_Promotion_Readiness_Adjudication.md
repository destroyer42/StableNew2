# PR-VID-185 - Wan-Animate-2 Promotion Gate & Production-Readiness Adjudication

Status: **COMPLETE / TECHNICALLY NOT YET PROMOTION-READY / NO PRODUCTION INTEGRATION**.

This is a documentation-only adjudication of accepted PR-VID-184S evidence. It does not
rewrite PR-VID-184, PR-VID-184R, or PR-VID-184S, and it authorizes no GPU run, model
installation, external-runtime action, or StableNew production change.

## Decision summary

The owner product-value verdict remains **`WAN_ANIMATE_2_OWNER_MOTION_VALUE_PASS`**.
The frozen automated result remains **`motion_curve_correlation` FAIL**: 0.151 in
PR-VID-184R and 0.139/0.151 in PR-VID-184S, against the unchanged 0.30 threshold.

That metric is a useful non-blocking guardrail, not a sufficient hard promotion gate for
the intended product outcome. It measures correlation between global optical-flow
residual motion-energy curves after median global shift removal; it does not measure
skeletal correspondence, identity-bound motion, anatomy, or usefulness. The accepted
PR-VID-181 evidence gives it a meaningful signal (gesture pass 0.419 versus locomotion
failure -0.132, with the PR-VID-180 synthetic range -0.089 to 0.005), but only a small
cross-case calibration set. The 0.30 threshold remains a conservative pre-registered
diagnostic/guardrail threshold, not a validated universal hard blocker against a qualified
owner visual/product verdict.

The metric disagreement is recorded, not averaged away:

| Evidence | Result | Adjudication |
| --- | --- | --- |
| Owner product value | PASS | Preserved as the owner's judgment for the tested case |
| Continuity | PASS, 1.0 | Required product-quality evidence |
| Ghost actor | PASS, 0 frames | Required product-quality evidence |
| Root translation | PASS, 0.623/0.628 and direction-matched | Required product-quality evidence |
| Motion-curve correlation | **FAIL, 0.139-0.151 vs 0.30** | Frozen historical result; future non-blocking guardrail |

This is not a capability-wide PASS. It is a technically eligible direction only if the
future resource/usability evidence below is obtained and the owner separately authorizes
an experimental integration decision.

## Product outcome under adjudication

The tested question is not whether every body pose or video looks ideal. It is whether a
reference-bound human can carry useful driving-source motion on the target workstation
while retaining sufficient identity/continuity, avoiding a persistent ghost actor and
disqualifying visual artifacts, and completing with operationally acceptable resource
behavior. Owner-visible product value, automated proxies, resource feasibility, and the
separate workstation-stability diagnosis are distinct claims. This record does not turn
the owner PASS into a capability-wide or production-readiness PASS.

## Metric validity adjudication

`motion_curve_correlation` is implemented by the reused `vid110` metric code. For each
adjacent pair of decoded frames, it converts the image to grayscale at a normalized width,
computes Farneback optical flow, removes the median flow vector as global/camera shift,
and averages the residual-vector magnitudes into a per-frame local-motion-energy curve.
The driving clip supplies one curve and the generated output supplies the other; each is
linearly resampled to the shorter common length and compared with Pearson correlation.

A high value means the *shape over time* of those global residual-motion energies is
similar. It does not establish that the same limbs moved, that the reference identity
performed the motion, or that spatial pose, amplitude, direction, anatomy, background, or
overall usefulness is acceptable. A low value can arise from genuine non-adherence, but
also from timing/phase shifts, different amplitude envelopes, background or appearance
motion affecting flow, or visually useful motion whose energy is distributed differently.

The frozen 0.30 value was selected before the Animate-2 result from a limited anchor set:
PR-VID-181's accepted gesture transfer was 0.419, its planted-subject locomotion failure
was -0.132, and PR-VID-180 synthetic controls ranged from -0.089 to 0.005. It is therefore
a defensible conservative heuristic for detecting disagreement, not a product-validated
threshold capable of independently vetoing the owner's defined outcome. The observed
0.139-0.151 is above the documented 0.10 non-adherent/noise boundary but below the frozen
0.30 guardrail; it warrants explanation and retention, not historical revision.

## Execution profile

- **Execution class:** Difficult bounded qualification/adjudication; Local/Desktop;
  CPU-only evidence and documentation.
- **Model/reasoning recommendation:** Terra High for metric/acceptance-contract analysis;
  Luna High or Terra Medium is sufficient for bounded documentation and CPU-only evidence
  processing. This recommendation optimizes expected total successful-work cost, including
  the cost of rework if the metric-role or promotion contract is misclassified, rather
  than nominal model price.
- **Controller surface assessment:** no controller, coordinator, compiler, NJR, queue,
  repository, runner, backend, GUI, or process-manager code was touched. Any future
  integration must extend the existing `PR-RUNTIME-100` ownership/coexistence policy and
  the canonical `Intent -> Compiler -> NJR -> JobService -> Queue/Repository ->
  PipelineRunner.run_njr` path. It must not create a second scheduler, process authority,
  runner entry point, queue, history, or cancellation authority. External Comfy/A1111
  runtimes remain unadopted; ambiguous dispatched requests remain non-auto-replayed.
- **Token-efficient validation plan:** reuse the exact frozen PR-VID-184S manifests,
  telemetry, hashes, and saved outputs; inspect the scoring implementation and run only
  deterministic CPU/documentation checks; verify the historical records are unchanged;
  run `git diff --check`; defer required Python 3.11/3.12 CI to publication because this
  package has no production or Python-source change.

## Evidence reconciled

PR-VID-184S is accepted evidence for three ordered, matched-state submissions:

- B1 pinned-OFF completed at 52.91% peak Windows commit, 13.99 GB minimum available
  physical RAM, 11,807 MiB peak VRAM, and 163.6 s harness wall time.
- A pinned-ON completed at 73.15% peak commit, 1.94 GB minimum available physical RAM,
  11,732 MiB peak VRAM, and 163.9 s wall time. It did not reproduce the historical GPU
  loss.
- B2 pinned-OFF completed at 52.13% peak commit, 14.27 GB minimum available physical
  RAM, 11,839 MiB peak VRAM, and 163.6 s wall time.
- B1 and B2 decoded pixel-identically. All three outputs were decodable and had zero
  HostBuffer, CUDA, traceback, or GPU-lost counts; teardown left the GPU idle.

The evidence supports these narrower claims:

1. Pinned-OFF is repeatable on this workload under fresh-boot matched-state conditions.
2. Pinned-ON materially increases resource pressure for this workload.
3. Pinned memory is neither proven necessary nor sufficient as the cause of the original
   GPU loss. The original loss remains historical truth for PR-VID-184's tested state.
4. Fresh-boot B1/A/B2 does not establish representative accumulated-state workstation
   stability, and no causality should be inferred from the commit/RAM correlation alone.

## Resource and usability gate for any future experimental promotion

The following is a proposed acceptance contract for a separately authorized future
qualification. It is not a claim that the current evidence has already satisfied the
representative-state requirement.

| Dimension | Evidence required before a future decision |
| --- | --- |
| Configuration | Pinned-OFF is the preferred tested launch policy; any change requires a new owner-authorized comparison |
| Windows commit | Capture peak percentage and minimum headroom for comparison with the accepted B1/B2 and A telemetry; the current evidence does not establish a promotion ceiling |
| Physical RAM | Capture minimum available RAM and machine-responsiveness evidence; B1/B2's roughly 14 GB margin and A's 1.94 GB minimum establish pressure contrast, not an acceptance threshold |
| VRAM | Capture peak/headroom and require no CUDA OOM or device-loss evidence; the current evidence does not establish a general minimum headroom |
| Wall time | Capture completion time against the frozen envelope and documented operator expectation; the current evidence does not establish a product timeout |
| Artifact | Decodable video with the requested geometry/fps/frame count, persisted hash/manifest, and durable artifact/history linkage |
| Teardown | Owned process exits cleanly; GPU returns to idle; no HostBuffer, CUDA, traceback, safety-stop, display-loss, or ambiguous-dispatch evidence |
| Usability | No intervention beyond the documented launch procedure; no severe host-memory pressure, unsafe system state, or unexplained output nondeterminism |

The accepted telemetry supports a configuration preference and the evidence collection
above; it does not support new numerical promotion ceilings. Any numeric commit, RAM,
VRAM, wall-time, or responsiveness threshold beyond the frozen safety-stop rules would
be a new product/operational decision for the owner. This is not a universal GPU scheduler
or hardware guarantee. Pinned-OFF remains preferred because it reproduced with materially
more host-memory margin; pinned-ON completion does not make it preferred.

Before promotion, a separate owner-authorized qualification must obtain the same evidence
after representative ordinary workstation use rather than immediately after boot. The
smallest useful closure is at least one clean pinned-OFF run in that accumulated-state
condition; if pinned-ON is to be allowed, it needs its own representative-state run under
the same telemetry and artifact contract. This package does not run either option.

## Precommitted promotion consequences

- Owner product-value **FAIL**: no promotion, regardless of automated metrics or resource
  results.
- Owner product-value **PASS** plus a valid hard-gate **FAIL**: promotion remains blocked.
- Owner product-value **PASS** plus the frozen motion-correlation **FAIL**: preserve the
  historical FAIL, raise a guardrail/disagreement requiring review, but do not block solely
  on this proxy when continuity, ghost, root-translation, visual rubric, and resource /
  usability gates support the product outcome.
- Representative-state resource/usability evidence missing: not promotion-ready, even
  though the fresh-boot B1/A/B2 evidence is accepted.
- All valid product and resource gates pass: technically eligible for a separate,
  explicitly owner-authorized experimental integration decision. Technical eligibility is
  not owner authorization and does not promote or register Wan-Animate-2.

The motion-correlation guardrail should remain reported for every future candidate. A
future value near the documented noise floor should trigger investigation of non-adherence;
the 0.30 result should remain visible as a disagreement signal until a larger,
cross-candidate calibration set justifies changing its role. No threshold is changed by
this record.

## Production-readiness boundary

If the owner later authorizes the smallest integration package after valid evidence, it
must be a separate package that registers only an experimental, explicit-opt-in
`backend_id=comfy` workflow through the existing neutral video execution contract and
canonical queue/NJR/runner path. It must extend `PR-RUNTIME-100` for owned runtime
coexistence and preserve external-runtime immutability. No production backend, workflow,
GUI exposure, compiler, controller, scheduler, process manager, or runner change is part
of PR-VID-185.

Qualification remains evidence-specific. No universal resource framework is justified;
common infrastructure should wait until another candidate demonstrates a genuinely shared
need.

## Validation and independent review

- Historical PR-VID-184, PR-VID-184R, and PR-VID-184S records remain unchanged.
- Frozen scoring code and contract remain unchanged, including contract hash
  `30608f7a3595d5db000946fbb4941918fdf6dd09cdf8fa1387a7953ed706543c`.
- No `src/` production integration, GPU/model/runtime action, or hardware/platform change
  occurred.
- The metric review traced `motion_curve_correlation` to the reused Farneback optical-flow
  residual-motion and Pearson-correlation implementation and classified it as a useful
  non-blocking guardrail.
- Independent verification checked the historical-result preservation, pinned-memory
  causality limits, representative-state gap, promotion consequences, and architecture
  boundary; no unresolved contradiction remains.
- `git diff --check` is required before handoff. Applicable documentation checks are the
  only local validation scope; required Python 3.11/3.12 CI remains the publication verdict
  if the documentation PR is published.

## Final adjudication

Wan-Animate-2 is **not technically promotion-ready on the current evidence** because
representative-state resource/usability evidence is missing. The owner product-value PASS
stands, the automated motion-correlation FAIL stands, and the latter is demoted to a
non-blocking guardrail for future adjudication rather than erased or treated as a hard
blocker. A future owner decision is required before any experimental integration or new
GPU evidence.
