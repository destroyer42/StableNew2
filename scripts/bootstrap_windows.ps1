[CmdletBinding()]
param(
    [string]$PythonPath = "",
    [string]$VenvPath = "",
    [string]$CudaIndexUrl = "https://download.pytorch.org/whl/cu130",
    [switch]$CheckOnly,
    [switch]$Recreate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($VenvPath)) {
    $VenvPath = Join-Path $RepoRoot ".venv"
} elseif (-not [IO.Path]::IsPathRooted($VenvPath)) {
    $VenvPath = Join-Path $RepoRoot $VenvPath
}
$VenvPath = [IO.Path]::GetFullPath($VenvPath)

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    try {
        $output = & $Executable @Arguments 2>&1
    } catch {
        throw "$FailureMessage`n$($_.Exception.Message)"
    }
    if ($null -ne $output) {
        $output | ForEach-Object { Write-Host $_ }
    }
    if ($LASTEXITCODE -ne 0) {
        $details = if ($null -eq $output) { "" } else { $output -join [Environment]::NewLine }
        throw "$FailureMessage`n$details"
    }
    return $output
}

function Get-PythonVersion {
    param([Parameter(Mandatory = $true)][string]$Executable)

    $output = Invoke-CheckedProcess `
        -Executable $Executable `
        -Arguments @("-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))") `
        -FailureMessage "Unable to execute Python at '$Executable'."
    if ($null -eq $output) {
        throw "Python at '$Executable' returned no version."
    }
    $version = (($output | Select-Object -Last 1).ToString()).Trim()
    if ($version -notmatch '^3\.(11|12)\.') {
        throw "Python 3.11 or 3.12 is required; '$Executable' reports '$version'. Install a supported official Python or pass -PythonPath."
    }
    return $version
}

function Resolve-SupportedPython {
    if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
        $resolved = (Resolve-Path -LiteralPath $PythonPath -ErrorAction Stop).Path
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "-PythonPath must name a Python executable: '$PythonPath'."
        }
        return $resolved
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        foreach ($requested in @("3.12", "3.11")) {
            try {
                $probe = & $launcher.Source "-$requested" "-c" "import sys; print(sys.executable)" 2>$null
                if (($LASTEXITCODE -eq 0) -and ($null -ne $probe)) {
                    $candidate = (($probe | Select-Object -Last 1).ToString()).Trim()
                    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                        return $candidate
                    }
                }
            } catch {
                # Try the next supported launcher target.
            }
        }
    }

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        return $pythonCommand.Source
    }
    throw "No Python executable was found. Install official Python 3.11 or 3.12, or pass -PythonPath."
}

function Assert-SafeVenvPath {
    $root = [IO.Path]::GetPathRoot($VenvPath)
    $normalizedVenv = $VenvPath.TrimEnd('\')
    $normalizedRoot = $root.TrimEnd('\')
    $normalizedRepo = $RepoRoot.TrimEnd('\')
    if (($normalizedVenv -eq $normalizedRoot) -or ($normalizedVenv -eq $normalizedRepo)) {
        throw "Refusing to use a drive root or the repository root as the venv path. Pass a dedicated -VenvPath."
    }
}

function Assert-CudaTorch {
    $output = Invoke-CheckedProcess `
        -Executable $VenvPython `
        -Arguments @("-c", "import torch; print(torch.version.cuda or '')") `
        -FailureMessage "Torch could not be imported from '$VenvPython'."
    $cudaVersion = if ($null -eq $output) { "" } else { (($output | Select-Object -Last 1).ToString()).Trim() }
    if ([string]::IsNullOrWhiteSpace($cudaVersion)) {
        throw "CUDA-enabled Torch is not active in '$VenvPath'. The environment resolved CPU-only Torch; stop and inspect the CUDA index installation."
    }
}

if ($CheckOnly -and $Recreate) {
    throw "-CheckOnly and -Recreate cannot be used together."
}

$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$pythonVersion = $null

if ($CheckOnly) {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw "No existing venv Python was found at '$VenvPython'. Run the bootstrap first or pass a valid -VenvPath."
    }
    $pythonVersion = Get-PythonVersion -Executable $VenvPython
} else {
    $pythonExe = Resolve-SupportedPython
    $pythonVersion = Get-PythonVersion -Executable $pythonExe

    if (Test-Path -LiteralPath $VenvPath) {
        if ($Recreate) {
            Assert-SafeVenvPath
            Remove-Item -LiteralPath $VenvPath -Recurse -Force
        } elseif (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
            $existingEntries = @(Get-ChildItem -LiteralPath $VenvPath -Force)
            if ($existingEntries.Count -gt 0) {
                throw "The existing venv path '$VenvPath' is incomplete. Pass -Recreate only for this dedicated venv path."
            }
        }
    }
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Assert-SafeVenvPath
        Invoke-CheckedProcess `
            -Executable $pythonExe `
            -Arguments @("-m", "venv", $VenvPath) `
            -FailureMessage "Could not create the venv at '$VenvPath'." | Out-Null
    }

    $requirements = Join-Path $RepoRoot "requirements.txt"
    $svdRequirements = Join-Path $RepoRoot "requirements-svd.txt"
    foreach ($requirementsFile in @($requirements, $svdRequirements)) {
        if (-not (Test-Path -LiteralPath $requirementsFile -PathType Leaf)) {
            throw "Required package authority file is missing: '$requirementsFile'."
        }
    }

    Invoke-CheckedProcess `
        -Executable $VenvPython `
        -Arguments @("-m", "pip", "install", "--upgrade", "pip") `
        -FailureMessage "Could not upgrade pip in '$VenvPath'." | Out-Null

    # Torch is the one deliberate package-level exception: install it from the
    # official CUDA index before the repository requirement files are applied.
    Invoke-CheckedProcess `
        -Executable $VenvPython `
        -Arguments @("-m", "pip", "install", "--index-url", $CudaIndexUrl, "torch") `
        -FailureMessage "Could not install CUDA-enabled Torch from '$CudaIndexUrl'." | Out-Null

    Invoke-CheckedProcess `
        -Executable $VenvPython `
        -Arguments @("-m", "pip", "install", "-r", $requirements) `
        -FailureMessage "Could not install the base requirements from '$requirements'." | Out-Null
    Invoke-CheckedProcess `
        -Executable $VenvPython `
        -Arguments @("-m", "pip", "install", "-r", $svdRequirements) `
        -FailureMessage "Could not install the SVD requirements from '$svdRequirements'." | Out-Null

    # Keep CUDA Torch installation first so requirements resolution cannot select
    # a CPU-only build, then probe after its declared runtime dependencies exist.
    Assert-CudaTorch
}

$verificationCode = @'
import json
import os
import subprocess
import sys
from pathlib import Path

# The verification payload is materialized in a temporary file, so restore the
# repository import root that `python -c` would otherwise provide implicitly.
repository_root = Path.cwd()
if str(repository_root) not in sys.path:
    sys.path.insert(0, str(repository_root))

import accelerate
import diffusers
import imageio_ffmpeg
import torch
import transformers
from diffusers import StableVideoDiffusionPipeline

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.svd_models import (
    get_default_svd_cache_dir,
    get_default_svd_model_id,
    is_svd_model_cached,
)

if not torch.cuda.is_available():
    raise SystemExit("CUDA is unavailable in this environment; the native-SVD runtime requires CUDA-enabled Torch.")

ffmpeg = resolve_ffmpeg_executable()
if ffmpeg is None:
    raise SystemExit("FFmpeg was not found. Install FFmpeg with sibling ffprobe and make it available on PATH, or use the supported STABLENEW_FFMPEG_PATH setting.")
ffmpeg = Path(ffmpeg)
ffprobe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
for executable in (ffmpeg, ffprobe):
    if not executable.is_file():
        raise SystemExit(f"Required executable is missing: {executable.name}. Install FFmpeg with ffprobe available beside it or on PATH.")
    result = subprocess.run([str(executable), "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        raise SystemExit(f"{executable.name} could not execute. Repair the FFmpeg installation and retry.")

cache_dir = Path(get_default_svd_cache_dir())
model_id = get_default_svd_model_id()
model_cached = bool(is_svd_model_cached(model_id, cache_dir=cache_dir))
if not model_cached:
    raise SystemExit(
        f"Model acquisition required: complete local cache for {model_id} was not found under the production default cache authority ({cache_dir})."
    )

print(json.dumps({
    "python": sys.version.split()[0],
    "python_executable": sys.executable,
    "torch": torch.__version__,
    "torch_cuda": torch.version.cuda,
    "cuda_available": bool(torch.cuda.is_available()),
    "gpu": torch.cuda.get_device_name(0),
    "diffusers": diffusers.__version__,
    "svd_pipeline": StableVideoDiffusionPipeline.__name__,
    "transformers": transformers.__version__,
    "accelerate": accelerate.__version__,
    "imageio_ffmpeg": imageio_ffmpeg.__version__,
    "ffmpeg": str(ffmpeg),
    "ffprobe": str(ffprobe),
    "model": model_id,
    "model_cached": model_cached,
    "cache_authority": str(cache_dir),
}, indent=2))
'@

$verificationScript = [IO.Path]::ChangeExtension([IO.Path]::GetTempFileName(), ".py")
[IO.File]::WriteAllText(
    $verificationScript,
    $verificationCode,
    [Text.UTF8Encoding]::new($false)
)

Push-Location $RepoRoot
try {
    Invoke-CheckedProcess `
        -Executable $VenvPython `
        -Arguments @($verificationScript) `
        -FailureMessage "Native-SVD runtime verification failed. Resolve the reported prerequisite and retry." | Out-Null
} finally {
    Pop-Location
    Remove-Item -LiteralPath $verificationScript -Force -ErrorAction SilentlyContinue
}

Write-Host "Windows native-SVD bootstrap verification passed."
Write-Host "Venv: $VenvPath"
Write-Host "Mode: $(if ($CheckOnly) { 'check-only' } else { 'bootstrap' })"
