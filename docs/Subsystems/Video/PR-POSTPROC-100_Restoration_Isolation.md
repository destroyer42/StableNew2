# PR-POSTPROC-100 — Restoration isolation and modernization

Status: under owner review. Owner of the boundary: `src/video/restoration/`.

## Boundary

Native-SVD postprocessing stays a stage under the existing execution path
(`PipelineRunner.run_njr` → SVD handler → `SVDPostprocessRunner` → helper process
`src.video.svd_postprocess_worker`). No new job type, queue, runner, or history authority.

| Module | Responsibility |
|---|---|
| `src/video/restoration/runtime.py` | Cheap readiness: `find_spec` only; never imports a model library, touches the GPU, reads weights, or downloads |
| `src/video/restoration/model_loader.py` | Spandrel load of a checkpoint, architecture check, device/eval/half |
| `src/video/restoration/upscaler.py` | RRDB/RealESRGAN upscaling: StableNew-owned padding, tiling, colour order, Lanczos `outscale` resize |
| `src/video/restoration/codeformer.py` | CodeFormer: Spandrel network, tensor conversion, per-face inference, no-face pass-through |
| `src/video/restoration/legacy_face_helper.py` | The one retained legacy component (see below); the only module that imports `facelib` |
| `src/video/svd_postprocess_worker.py` | Parse payload, dispatch product method, write outputs, release memory |

Public product methods are unchanged: `CodeFormer`, `GFPGAN`, `RealESRGAN` (plus RIFE and secondary
motion, untouched).

## Dependency profiles

- **Core** (`requirements.txt`, `requirements-svd.txt`): everything native SVD needs. `torchvision`
  is core because transformers' default `CLIPImageProcessor` backend (SVD conditioning) requires
  it; without it transformers silently falls back to a different PIL backend. `opencv-python` stays
  core for Photo Optimize/refinement face detection and quality metrics (not for native SVD).
- **Optional postprocess** (`requirements-postprocess.txt`, bootstrap `-WithPostprocess`):
  `spandrel`, `spandrel-extra-arches` (CodeFormer architecture), `codeformer` (provides the legacy
  `facelib` face helper). Exact pins live in the `# profile: postprocess` section of
  `constraints/windows-py314-cu130.txt`; `tools/runtime/verify_runtime_pins.py` treats it as absent
  by design unless requested or a marker package is installed.

A clean core-only environment contains 57 packages and none of the restoration stack (no
`codeformer`, `lpips`, `facexlib`, `spandrel`, `scipy`, `numba`, `matplotlib`). Missing optional
packages never affect startup, native SVD, or postprocess-disabled jobs; enabling a stage whose
runtime is incomplete fails at admission with an install action.

## Capability classification

| Capability | Result | Notes |
|---|---|---|
| RealESRGAN | MODERNIZED / ACCEPTED | Spandrel `ESRGAN` network + StableNew tiling; bit-identical to legacy |
| CodeFormer network | MODERNIZED / ACCEPTED | Spandrel `CodeFormer`; identical state dict, bit-identical output |
| CodeFormer face helper | LEGACY ISOLATED / RETAINED | `facelib` from the `codeformer` wheel, see below |
| GFPGAN | UNAVAILABLE BEFORE AND AFTER | `gfpgan` was never in a supported profile; the legacy `GFPGANer` loader was retired with its shim and the method fails closed |

## Retained legacy component: the face helper

Reason: upstream `facexlib` 0.3.0's `FaceRestoreHelper` is not behaviour-equivalent to the fork
vendored in the `codeformer` wheel (different detection scale/confidence, no upscale of small
inputs to 512 px, different paste-back and grayscale handling). With identical weights and the same
Spandrel network, swapping in `facexlib` changed CodeFormer output materially on the test inputs
(max per-pixel difference 79–147/255, PSNR 42.5–47.1 dB; differences confined to the face region).
That is a product-quality change, so it was not adopted.

Scope: face detection, landmark alignment, crop, and paste-back for CodeFormer only.

Removal condition: owner adjudication of a modern helper (facexlib or StableNew-owned code) after
visual and objective quality review; then delete `legacy_face_helper.py` and the `codeformer`
package from the profile.

Retired from the old worker: the `torchvision.transforms.functional_tensor` shim (the BasicSR code
vendored in this wheel never needed it), `sys.path` edits, process working-directory changes, and
copying weights into site-packages. The weight directory is passed to `facelib` explicitly for the
duration of construction. A guard test fails if any other production module imports `facelib`, or if
`basicsr`, `facexlib`, `gfpgan`, or the shim reappear.

## Behaviour notes

- Spandrel's CodeFormer takes the fidelity as `weight=` (adain is built in). The legacy `w=` keyword
  would be swallowed by `**kwargs` and silently default to 0.5; a regression test pins the keyword.
- Per-face CodeFormer inference failures keep the legacy behaviour (the face is pasted back
  unrestored) but are now reported: the worker tags the warning (`WORKER_WARNING_PREFIX`) because a
  successful worker's stderr is otherwise discarded, and `SVDPostprocessRunner` logs it and records
  it under `warnings` in the postprocess metadata (absent when there are none). RealESRGAN
  failures, including per-tile failures, propagate instead of producing partial output.

## Equivalence evidence (existing local weights, no new SVD generation)

Pre-registered rules (recorded before any candidate output): identical dimensions/mode and face
count; EXACT, or CPU max |Δ| ≤ 2/255 with PSNR ≥ 50 dB, or CUDA-fp16 upscale max |Δ| ≤ 8/255 with
PSNR ≥ 42 dB; anything else is a material difference.

Inputs: matplotlib's public-domain `grace_hopper.jpg` (512×600, one face), a 1024×576 two-face
composite of it, and a 256×256 synthetic no-face gradient. Weights (SHA-256 prefix): CodeFormer
`1009e537e0c2a07d`, RealESRGAN_x4plus `4fa0d38905f75ac0`, detection `6d1de9c2944f2ccd`, parsing
`3d558d8d0e42c202`.

Final code vs legacy, nine cases (CPU fp32: CodeFormer fidelity 0.7/0.3 on one face, two faces, no
face; RealESRGAN ×2 untiled, ×2 tile 256, ×4; CUDA: CodeFormer two faces, RealESRGAN ×2): all nine
bit-identical (max |Δ| 0). Faces detected: 1, 2, 0 for both helpers. The legacy `x2plus` checkpoint
was not available locally, so the ×2-network path (mod-pad) is covered only by deterministic tests.
