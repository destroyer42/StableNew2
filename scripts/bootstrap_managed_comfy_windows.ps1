[CmdletBinding()]
param(
    # Official standard-GIL CPython matching config/managed_comfy_runtime.json (python.minor).
    [string]$PythonPath = "",
    # StableNew-owned root for managed installs; each install is <root>\<release>-py<minor>\{source,venv}.
    [string]$InstallRoot = "",
    # Qualification overrides: build another stable release for comparison. Normal use omits all three
    # and installs exactly the release/revision/constraints pinned by the manifest.
    [string]$Release = "",
    [string]$Revision = "",
    [string]$ConstraintsPath = "",
    [string]$CudaIndexUrl = "",
    [string]$PackageIndexUrl = "https://pypi.org/simple",
    [switch]$CheckOnly,
    [switch]$Recreate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# This installs the StableNew-MANAGED ComfyUI runtime only. It never touches an external/desktop
# ComfyUI, A1111, Forge or the StableNew application environment; it downloads no model, installs
# no custom node, and never tracks an upstream branch (only an exact tag whose commit is verified).

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ManifestPath = Join-Path $RepoRoot "config\managed_comfy_runtime.json"
$Verifier = Join-Path $RepoRoot "tools\runtime\verify_managed_comfy.py"
$MarkerName = ".stablenew-managed-comfy.json"

$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$IsOverride = (-not [string]::IsNullOrWhiteSpace($Release)) -or (-not [string]::IsNullOrWhiteSpace($Revision)) -or (-not [string]::IsNullOrWhiteSpace($ConstraintsPath))
if ([string]::IsNullOrWhiteSpace($Release)) { $Release = $Manifest.upstream.release }
if ([string]::IsNullOrWhiteSpace($Revision)) {
    if ($Release -ne $Manifest.upstream.release) { throw "-Revision is required for a release other than the manifest's $($Manifest.upstream.release)." }
    $Revision = $Manifest.upstream.revision
}
if ([string]::IsNullOrWhiteSpace($ConstraintsPath)) {
    if ($Release -ne $Manifest.upstream.release) { throw "-ConstraintsPath is required for a release other than the manifest's $($Manifest.upstream.release)." }
    $ConstraintsPath = Join-Path $RepoRoot $Manifest.constraints
}
if ($Release -notmatch '^v\d+\.\d+\.\d+$') { throw "-Release must be an exact stable tag such as v0.38.0 (never a branch)." }
if ($Revision -notmatch '^[0-9a-f]{40}$') { throw "-Revision must be a full 40-hex commit SHA." }
if (-not (Test-Path -LiteralPath $ConstraintsPath -PathType Leaf)) { throw "Constraints file not found: '$ConstraintsPath'." }
if ([string]::IsNullOrWhiteSpace($CudaIndexUrl)) { $CudaIndexUrl = $Manifest.torch.index_url }
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = [Environment]::ExpandEnvironmentVariables($Manifest.install.default_root).Replace("/", "\")
}
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$pythonMinor = [string]$Manifest.python.minor
$InstallDir = Join-Path $InstallRoot ("{0}-py{1}" -f $Release, $pythonMinor.Replace(".", ""))
$SourceDir = Join-Path $InstallDir "source"
$VenvDir = Join-Path $InstallDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments, [string]$FailureMessage)
    # Native stderr (pip/git notices) must not become a terminating error; the exit code decides.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Executable @Arguments 2>&1
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage`n$(($output | Out-String).Trim())"
    }
    return $output
}

function Get-PythonFacts {
    param([string]$Executable)
    $code = "import sys, sysconfig, os; print(sys.version_info.major, sys.version_info.minor, int(bool(sysconfig.get_config_var('Py_GIL_DISABLED'))), os.environ.get('PYTHON_JIT', '0'))"
    $line = (Invoke-Checked -Executable $Executable -Arguments @("-c", $code) -FailureMessage "Unable to execute Python at '$Executable'.") | Select-Object -Last 1
    $parts = ($line.ToString().Trim()) -split " "
    return @{ Minor = "$($parts[0]).$($parts[1])"; FreeThreaded = ($parts[2] -ne "0"); Jit = $parts[3] }
}

function Assert-SupportedPython {
    param([string]$Executable)
    $facts = Get-PythonFacts -Executable $Executable
    if ($facts.Minor -ne $pythonMinor) { throw "Python $pythonMinor is required for the managed ComfyUI runtime; '$Executable' reports $($facts.Minor). Install official Python $pythonMinor or pass -PythonPath." }
    if ($facts.FreeThreaded) { throw "'$Executable' is a free-threaded Python build, which the managed ComfyUI runtime does not support." }
    if ($facts.Jit -notin @("", "0")) { throw "'$Executable' runs with PYTHON_JIT=$($facts.Jit); the experimental JIT is not supported. Unset PYTHON_JIT." }
}

function Assert-OwnedInstallDir {
    # Anything destructive may only happen inside the explicit install root, on a directory this
    # tooling created (marker file), never on a drive root, the repository, or someone else's install.
    $root = [IO.Path]::GetPathRoot($InstallRoot).TrimEnd("\")
    if (($InstallRoot.TrimEnd("\") -eq $root) -or ($InstallRoot.TrimEnd("\") -eq $RepoRoot.TrimEnd("\"))) {
        throw "Refusing to use a drive root or the repository root as -InstallRoot."
    }
    if (-not $InstallDir.StartsWith($InstallRoot.TrimEnd("\") + "\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Install directory '$InstallDir' is outside -InstallRoot."
    }
}

function Get-ConstraintPin {
    param([string]$Name)
    $match = Select-String -LiteralPath $ConstraintsPath -Pattern ("^{0}==(\S+)\s*$" -f [regex]::Escape($Name)) | Select-Object -First 1
    if ($null -eq $match) { return $null }
    return $match.Matches[0].Groups[1].Value
}

function Invoke-Verifier {
    $arguments = @($Verifier, "--install-dir", $InstallDir, "--constraints", $ConstraintsPath)
    if ($IsOverride) { $arguments += @("--release", $Release, "--revision", $Revision) }
    Invoke-Checked -Executable $VenvPython -Arguments $arguments -FailureMessage "The managed ComfyUI runtime at '$InstallDir' does not match its contract." | ForEach-Object { Write-Host $_ }
}

if ($CheckOnly -and $Recreate) { throw "-CheckOnly and -Recreate cannot be used together." }
Assert-OwnedInstallDir

if ($CheckOnly) {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { throw "No managed ComfyUI venv at '$VenvPython'. Run this script without -CheckOnly first." }
    Assert-SupportedPython -Executable $VenvPython
    Invoke-Verifier
    Write-Host "Managed ComfyUI check-only verification passed: $InstallDir"
    return
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) { throw "-PythonPath is required (an official standard-GIL CPython $pythonMinor)." }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
Assert-SupportedPython -Executable $PythonPath

if (Test-Path -LiteralPath $InstallDir) {
    if (-not $Recreate) {
        if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { throw "'$InstallDir' exists but is incomplete. Pass -Recreate to rebuild this StableNew-managed install." }
    } else {
        if (-not (Test-Path -LiteralPath (Join-Path $InstallDir $MarkerName) -PathType Leaf)) {
            throw "Refusing to delete '$InstallDir': it was not created by this tooling (no $MarkerName)."
        }
        Remove-Item -LiteralPath $InstallDir -Recurse -Force
    }
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $SourceDir "main.py") -PathType Leaf)) {
    Invoke-Checked -Executable "git" -Arguments @("clone", "--quiet", "--depth", "1", "--branch", $Release, $Manifest.upstream.repository, $SourceDir) -FailureMessage "Could not clone ComfyUI $Release." | Out-Null
}
$head = (Invoke-Checked -Executable "git" -Arguments @("-C", $SourceDir, "rev-parse", "HEAD") -FailureMessage "Could not read the ComfyUI source revision.") | Select-Object -Last 1
if ($head.ToString().Trim() -ne $Revision) { throw "ComfyUI $Release resolved to $head, not the pinned $Revision. Refusing to install." }

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Invoke-Checked -Executable $PythonPath -Arguments @("-m", "venv", $VenvDir) -FailureMessage "Could not create the venv at '$VenvDir'." | Out-Null
}
Assert-SupportedPython -Executable $VenvPython   # a reused venv keeps the interpreter it was created with

$pipPin = Get-ConstraintPin -Name "pip"
if ($null -eq $pipPin) { throw "'pip' is not pinned in '$ConstraintsPath'." }
Invoke-Checked -Executable $VenvPython -Arguments @("-m", "pip", "install", "pip==$pipPin") -FailureMessage "Could not install the pinned pip $pipPin." | Out-Null

# The Torch family comes from the CUDA index at exact +cu130 pins (a CPU build cannot satisfy them);
# PyPI is an extra index only for their ordinary dependencies.
$torchFamily = @("torch", "torchvision", "torchaudio") | Where-Object { $null -ne (Get-ConstraintPin -Name $_) }
if ($torchFamily -notcontains "torch") { throw "'torch' is not pinned in '$ConstraintsPath'." }
Invoke-Checked -Executable $VenvPython -Arguments (@("-m", "pip", "install", "-c", $ConstraintsPath, "--index-url", $CudaIndexUrl, "--extra-index-url", $PackageIndexUrl) + $torchFamily) -FailureMessage "Could not install CUDA-enabled Torch from '$CudaIndexUrl'." | Out-Null

# Exactly what the pinned ComfyUI release declares, under the exact constraints.
Invoke-Checked -Executable $VenvPython -Arguments @("-m", "pip", "install", "-c", $ConstraintsPath, "-r", (Join-Path $SourceDir "requirements.txt")) -FailureMessage "Could not install ComfyUI's declared requirements under '$ConstraintsPath'." | Out-Null

@{ release = $Release; revision = $Revision; python = $pythonMinor; constraints = (Split-Path -Leaf $ConstraintsPath); created_by = "bootstrap_managed_comfy_windows.ps1" } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallDir $MarkerName) -Encoding utf8

Invoke-Checked -Executable $VenvPython -Arguments @("-m", "pip", "check") -FailureMessage "pip check found inconsistent dependencies in '$VenvDir'." | Out-Null
Invoke-Verifier
Write-Host "Managed ComfyUI bootstrap verification passed: $InstallDir"
