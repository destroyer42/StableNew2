# Windows native-SVD runtime bootstrap

This is the canonical setup procedure for a Windows StableNew environment
that will run the native Stable Video Diffusion (SVD) XT backend. It supports
official standard-GIL Python 3.14, an NVIDIA CUDA runtime, and FFmpeg/ffprobe.

## Prerequisites

Install an official 64-bit standard-GIL Python 3.14 (not the free-threaded
`3.14t` build; the experimental JIT stays off). A per-user, side-by-side
installation is enough: no PATH or file-association change is required. A Python
launcher that resolves `py -3.14` is preferred; an explicit executable can also be passed to the helper. The
machine must have a working NVIDIA driver and an NVIDIA GPU suitable for the
accepted SVD profile.

Install FFmpeg so both `ffmpeg.exe` and its sibling `ffprobe.exe` execute from
the same installation or are available on `PATH`. StableNew resolves these
through its existing production resolver; the repository does not bundle or
install FFmpeg.

## Bootstrap

From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1
```

The default target is the repository `.venv`. To select a particular Python
or an isolated environment, use explicit paths:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 `
  -PythonPath "C:\Path\to\python.exe" `
  -VenvPath "$env:TEMP\StableNew-svd-verify"
```

An existing valid venv is reused. `-Recreate` is an explicit opt-in for a
dedicated venv path; do not use it against an environment containing unrelated
work. `-CheckOnly` validates an existing venv without installing or changing
packages:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 `
  -VenvPath .\.venv -CheckOnly
```

## What the helper does

The supported runtime is reproducible from repository-owned authority:

- `requirements.txt` / `requirements-svd.txt` stay the human-readable direct
  dependencies of the **core** profile (StableNew and native SVD).
  `requirements-postprocess.txt` is the **optional** profile: local face
  restoration and upscaling (Spandrel model loading, plus the `codeformer`
  wheel that provides CodeFormer's face helper). Core SVD, including
  postprocess-disabled jobs, never requires it.
- `constraints/windows-py314-cu130.txt` is the single exact-version authority
  for the supported Windows / CPython 3.14 / CUDA 13.0 environment, including
  the resolver itself (`pip`). It has a core section and a
  `# profile: postprocess` section. Every install the helper performs is
  constrained by it, so a rebuild resolves the same packages instead of
  whatever is newest. It is Windows-specific; Linux/GitHub CI does not use it.
- Changing any pin is its own reviewed, qualified change. Do not regenerate the
  file with `pip freeze` from a developer environment.

The helper installs exactly the pinned pip (never `--upgrade`), installs
`torch` and `torchvision` (the latter backs transformers' default image
processor used by SVD conditioning) at their pinned `+cu130` builds from the
official PyTorch CUDA index (default `https://download.pytorch.org/whl/cu130`;
PyPI is an extra index only for their ordinary dependencies), and then installs
`requirements.txt` followed by `requirements-svd.txt`. Pass `-WithPostprocess`
to also install `requirements-postprocess.txt`. A CPU-only Torch cannot satisfy
or replace the pinned CUDA build. It then runs `pip check` and
`tools/runtime/verify_runtime_pins.py` (a stdlib comparison of installed
distributions against the constraints, which ignores unpinned extras) in both
bootstrap and `-CheckOnly` modes. The core profile is always required; the
optional profile is required only with `-WithPostprocess` (or when its
`spandrel` markers are installed), is reported as absent-by-design otherwise,
and any installed pinned package that has drifted fails either way. It also verifies
Python, CUDA-enabled Torch, the detected GPU, Diffusers and
`StableVideoDiffusionPipeline`, Transformers, Accelerate, imageio-ffmpeg,
and executable FFmpeg/ffprobe.

The helper never downloads a model. It checks the production default
per-user Hugging Face cache through StableNew's existing cache/model helpers.
If the accepted plain XT model is absent, it exits with an actionable model
acquisition message. Acquire the model deliberately through the approved
operator process, then rerun the helper; model acquisition is not an
import-time, bootstrap, or inference side effect.

Stable Diffusion WebUI/A1111 remains a separate externally managed runtime.
Its environment is not replaced by StableNew's `.venv`, and this helper does
not start, stop, adopt, or configure it.

## Migrating an existing environment to Python 3.14

An existing Python 3.12 `.venv` keeps working for the old interpreter but is no
longer the supported runtime. Migrate without losing the rollback:

1. Install the official standard (GIL) Python 3.14 per-user and side by side
   (no PATH or file-association change needed).
2. Keep the current environment as the rollback: rename `.venv` to
   `.venv-py312` (do not delete it).
3. Build the new environment from merged `main` with a short path if Windows
   long paths are not enabled, for example
   `.\scripts\bootstrap_windows.ps1 -PythonPath <Python314\python.exe>`
   (add `-WithPostprocess` if local face restoration/upscaling is wanted).
4. Verify with `.\scripts\bootstrap_windows.ps1 -CheckOnly` (pin verifier,
   `pip check`, CUDA, SVD pipeline, cached model, FFmpeg).
5. Only after the new environment passes, retire `.venv-py312`.

A1111, Forge and ComfyUI keep their own interpreters and are not touched.

## Common failures

- **Unsupported Python:** install official 3.14 (3.12, 3.13, 3.15+ and the
  free-threaded build are rejected), or pass `-PythonPath` to a standard
  3.14 executable.
- **Runtime drift reported:** a pinned package is missing or at a different
  version. Rebuild with the helper (`-Recreate` only on a dedicated venv path)
  rather than editing packages by hand.
- **Path too long during install:** Windows can fail while unpacking deeply
  nested package files (for example setuptools). Use a short `-VenvPath`
  (such as `C:\sn-venv`) unless Windows long paths are enabled.
- **CPU-only Torch or CUDA unavailable:** rerun with the official CUDA index
  using `-CudaIndexUrl` if the validated index has changed; do not accept a
  CPU-only environment for native SVD.
- **FFmpeg/ffprobe missing:** install both executables and place them on
  `PATH`, or configure the existing StableNew FFmpeg resolver authority.
- **Model acquisition required:** the production per-user Hugging Face cache
  does not contain a complete accepted plain XT snapshot. The helper does not
  download it.
- **Access denied:** use an elevated/local Windows shell for the target
  environment, or pass a disposable venv under `%TEMP%` for validation.

Successful bootstrap proves runtime prerequisites and local-only model/cache
readiness. It does not submit an NJR, load a model, run portrait inference,
or constitute the broader MVP-080 release proof.
