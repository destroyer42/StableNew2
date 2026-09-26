# PR-VID-183 - Wan2.2-Animate Basic-Retargeting Controlled A/B

Status: **`PR-VID-183 — COMPLETE / ACCEPTED / INTEGRATED — BASIC_RETARGET_APPLIES; REFERENCE_BOUND_LOCOMOTION_NOT_DEMONSTRATED`**.

This qualification-only package tested the upstream basic-retarget applicability gate that PR-VID-182 could not exercise. It adds no production backend, controller, resolver, graph, or workflow registration. The result is evidence for product-owner adjudication, not an Animate capability pass or a DIAG-GPU stability pass.

## Execution profile

- **Execution class:** Standard qualification; Local/Desktop only because the proof requires local source media, the disposable CPU detector environment, managed Comfy, telemetry, and read-only machine-state capture.
- **Model/reasoning recommendation:** GPT-5.6 Luna — Medium for this documentation-only closeout; Local/Desktop execution preserves the existing local evidence and ref-verification boundary.
- **Controller surface assessment:** none. No `src/` production controller, coordinator, resolver, backend, runner, or graph changed; the qualification runner remains outside the product execution path.
- **Token-efficient validation plan:** reuse VID-181 graph/ownership/telemetry evidence; run the new deterministic guards and touched-surface Ruff/formatter checks; use the disposable existing CPU environment for detector work; run exactly the two preauthorized GPU arms; leave the full local gate to GitHub if a prescribed local tool is absent.

## Question and frozen envelope

Question: with a new naturally compliant real-human locomotion source, does pinned upstream basic retargeting make locomotion stay bound to the frozen reference person?

| Arm | `retarget_flag` | `use_flux` |
| --- | --- | --- |
| A | `False` | `False` |
| B | `True` | `False` |

Both arms used the same source frames, detector/checkpoint metadata, reference, 480x832/13f/8fps control shape, accepted Animate graph, prompt/negative/memory policy, sampler (`uni_pc`/`simple`), 20 steps, cfg 1.0, shift 5.0, and seed `1733123036`. `face_video` was absent. No background mitigation, FLUX, SAM2, pose editing, retries, or third submission occurred.

Pinned upstream was `Wan-Video/Wan2.2 @ 1ea34ff48f87168174e12956e200b1d908b1c5ff`; the detector checkpoint revision was `Wan-AI/Wan2.2-Animate-14B @ cb93a225fbaf1ca100f54e79da8f994995b689b3`. Arm B calls that checkout's `retarget_pose.get_retarget_pose` directly with its two edit-pose arguments `None`; the implementation was not recreated locally.

## Source, reference, and CPU-only preprocessing

The new source was [Mixkit #4856](https://mixkit.co/free-stock-video/girl-listens-to-music-and-dances-happily-4856/), recorded under the Mixkit Stock Video Free License. The selected natural window starts at 8.000 s and lasts 1.625 s. Its first processed frame is a single, upright, front-facing full-body person with visible arms, legs, and feet; the uninterrupted window retains alternating walking strides. It is a static fixed crop, not a tracking crop or synthetic/manipulated source.

| Item | SHA-256 / facts |
| --- | --- |
| Raw source | `6ff5a150a3f45988ff390237476b48b205296d16b8fb0aac4b6af9bcf2a7defd`; 1280x720, 29.970 fps, 412 frames |
| Fixed processed driving input | `e4ae310dc51a5c806f71caa687c6c1a55a1ecae799869dbaf57660d5511ed6b7`; 464x832, 29.970 fps, 49 frames |
| Crop | `crop=377:676:450:30,scale=464:832:flags=lanczos`; `tracking=false` |
| Frozen reference | `reports/vid110/inputs/source_fullbody.png`; `362c86cc83876e340b8927dd54a0f55af1c5fb82c1e9c98d624e67044afa71bb` |

Preprocessing ran exactly once per arm in `C:\Users\rob\qual\vid181\venv`, a disposable CPU-only environment outside StableNew, Comfy, and A1111. `CUDA_VISIBLE_DEVICES=-1`, CPUExecutionProvider was the actual provider for detector and pose, and `torch.cuda_available` / `torch.cuda_initialized` were both false. The 13 selected input-frame indices were `0, 4, 7, 11, 15, 19, 22, 26, 30, 34, 37, 41, 45`. The minimum lower-body confidence was 0.866; mean body confidence was 0.892.

| Control | Full-pose SHA-256 | Frozen final 480x832/13f/8fps SHA-256 |
| --- | --- | --- |
| A | `d3a59d774a3dcf84611a412ae50c0481072436e565f9039fbcfc340121dbdfaf` | `ac2e52c476176cfcc023b60552e29f817c10e73ba61ac4b0cc43895d3f43fc82` |
| B | `4ae98745fb89f2898513302b2cecc2d474f9ac7f45a27947ac9d796876bd952d` | `eb4aa6fb701a15dbfcf28fe7d4c7dc70e871a6fd9e052d07ec3e4e67bb2e3dde` |

The CPU pair gate passed: mean corresponding-frame pixel delta was 2.382; A/B temporal motion energy was 2.232/1.912. Thus B was neither a byte-identical no-op nor a temporally static control. The runner refuses submission unless those exact pair-validation hashes and motion guard exist.

## Two and only two Animate generations

The managed-Comfy preflight was free before each submission; dependency and frozen-graph validation were empty. Both outputs are 480x832, 13 frames, and 8 fps.

| Arm | Prompt ID | Wall | Output SHA-256 | VRAM peak | Commit peak / min headroom | Result |
| --- | --- | ---: | --- | ---: | --- | --- |
| A | `5ef2d551-f25e-492d-a9b9-decad2042c8b` | 132.2 s | `103cb0efe7744a6009c6a2c29f083e93b10a0e43789edb7d28d14d1e168524d5` | 11,788 MiB | 79.75% / 12.71 GB | completed |
| B | `2f07b700-df95-4fb4-b1d2-7f0a486b6123` | 128.8 s | `664771f63f75bb2047cf8f9497d1f1f568d2130b27f3cb45c14a46224f20adab` | 11,788 MiB | 79.40% / 12.93 GB | completed |

There was no safety stop, CUDA OOM, display loss, WHEA event, Kernel-Power 41, unexpected shutdown 6008, or display-driver 4101 event in the checked System-log interval. The manager owned and tore down each Comfy process successfully. That is clean-run evidence only; it does not change `XMP-OFF ISOLATION IN PROGRESS / OBSERVATION ONLY` or establish a GPU stability PASS.

## Result

Arm B materially changes the control and output, so the basic-retarget path is applicable for this new compliant source. It does **not** establish acceptable reference-bound locomotion in this small envelope: B starts as a lower-body/cropped rendering of the reference-looking subject and develops an exaggerated split-step/lunge rather than stable, full reference-person locomotion. Arm A retains a more complete reference-looking figure initially but also exhibits later body/background distortion. Neither result contains a clean, useful reference-bound walking transfer.

This does not reinterpret the result as a general Wan/Animate failure, nor does it alter the accepted `BACKGROUND_INSTABILITY_CROSS_CASE` finding from PR-VID-181. It closes only the controlled basic-retarget A/B question at this one source, seed, and short envelope. Product-owner review is required before naming or starting a successor objective.

## Validation and boundaries

- `ruff check tools/qualification/vid183 tests/tools/test_vid183_controlled_retarget.py`: pass.
- `ruff format --check` on those surfaces: pass.
- New deterministic tests: 5 passed in the repository interpreter, with the two OpenCV synthetic video cases skipped because that interpreter lacks OpenCV; the existing qualification environment has OpenCV 5.0.0, NumPy 2.4.6, ONNX Runtime 1.30.0, and CPU-only Torch 2.14.0.
- `py_compile` for the new package and `git diff --check`: pass.
- The local repository interpreter lacks NumPy/OpenCV for inherited VID-181 tests and local mypy is absent; no environment was modified. GitHub Actions run `36213829612` is the canonical integration verdict: required Python 3.11 and 3.12 passed; informational full-suite failures were limited to the known Xvfb broader-suite step.

No production source changed. No controller/coordinator surface was touched. All reports, controls, telemetry, source media, and outputs remain ignored local evidence under `reports/vid183/` or `C:\Users\rob\qual\vid183\`.

## Product-owner acceptance and closeout

The controlled A/B is accepted as valid. Basic retargeting materially changed the conditioning and output, so this is not `ANIMATE_BASIC_RETARGET_NO_EFFECT`; neither arm demonstrated clean stable reference-bound walking, so this is not a reference-bound locomotion success and is not a general Wan/Animate NO-GO. The secondary finding remains `BACKGROUND_INSTABILITY_CROSS_CASE`.

The immediate next objective is not further Wan2.2-Animate locomotion tuning through basic retargeting, `face_video`, or FLUX enhanced-retargeting. The next distinct objective is **PR-VID-184 — Wan-Animate-2 Target-Hardware & Integration Feasibility Research**. No PR-VID-184 implementation is included here.

DIAG-GPU-130 remains **`XMP-OFF ISOLATION IN PROGRESS / OBSERVATION ONLY`**. These two clean ordinary high-load observations are not a stability PASS, fix, or root-cause conclusion. Animate remains unregistered, and this package makes no production controller, resolver, backend, queue, NJR, or runtime-authority change.
