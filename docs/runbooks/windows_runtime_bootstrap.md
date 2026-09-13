# Windows native-SVD runtime bootstrap

This is the canonical setup procedure for a Windows StableNew environment
that will run the native Stable Video Diffusion (SVD) XT backend. It supports
official Python 3.11 or 3.12, an NVIDIA CUDA runtime, and FFmpeg/ffprobe.

## Prerequisites

Install an official 64-bit Python 3.11 or 3.12. A supported Python launcher
is preferred; an explicit executable can also be passed to the helper. The
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

The helper upgrades pip, installs `torch` from the official PyTorch CUDA
index (default `https://download.pytorch.org/whl/cu130`), and then installs
`requirements.txt` followed by `requirements-svd.txt`. Those requirement
files and `pyproject.toml` remain the package authorities; the helper only
defines the CUDA-specific Torch installation ordering. It verifies Python,
CUDA-enabled Torch, the detected GPU, Diffusers and
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

## Common failures

- **Unsupported Python:** install official 3.11 or 3.12, or pass
  `-PythonPath` to that executable.
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
