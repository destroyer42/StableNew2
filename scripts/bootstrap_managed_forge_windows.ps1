[CmdletBinding()]
param(
    # Official standard-GIL CPython matching config/managed_forge_runtime.json (python.minor).
    [string]$PythonPath = "",
    # StableNew-owned root for managed installs; each install is <root>\neo-<rev8>\{source,venv,data,runtime} (keep the root short).
    [string]$InstallRoot = "",
    # Existing A1111 home whose models Forge REFERENCES (--forge-ref-a1111-home). Never copied or modified.
    [string]$ModelReferenceHome = "",
    # A directory that already holds the two accepted YOLO detectors (face_yolov8n.pt, hand_yolov8n.pt).
    # They are hash-validated and COPIED into the managed data dir; the source is never modified or deleted.
    [string]$DetectorSourceDir = "",
    [string]$CudaIndexUrl = "",
    [string]$PackageIndexUrl = "https://pypi.org/simple",
    [switch]$SkipModelHashes,
    [switch]$CheckOnly,
    [switch]$Recreate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# This installs the StableNew-MANAGED Forge Neo runtime only. It never starts, stops, adopts or kills any
# runtime (WebUIProcessManager is the sole lifecycle authority) and never touches an external Forge, A1111,
# Comfy or the StableNew application environment. It downloads no model or detector, installs no MediaPipe,
# runs no uncontrolled extension installer and never tracks a mutable branch: it fetches two exact commits
# and installs the complete accepted package set without re-resolving it.

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ManifestPath = Join-Path $RepoRoot "config\managed_forge_runtime.json"
$Verifier = Join-Path $RepoRoot "tools\runtime\verify_managed_forge.py"
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$MarkerName = [string]$Manifest.install.marker
$ConstraintsPath = Join-Path $RepoRoot $Manifest.constraints
$ForgeRevision = [string]$Manifest.upstream.revision
$AdetailerRevision = [string]$Manifest.adetailer_neo.revision
if ($ForgeRevision -notmatch '^[0-9a-f]{40}$' -or $AdetailerRevision -notmatch '^[0-9a-f]{40}$') { throw "The manifest must pin full 40-hex revisions (never a branch)." }
if (-not (Test-Path -LiteralPath $ConstraintsPath -PathType Leaf)) { throw "Constraints file not found: '$ConstraintsPath'." }
if ([string]::IsNullOrWhiteSpace($CudaIndexUrl)) { $CudaIndexUrl = $Manifest.torch.index_url }
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = [Environment]::ExpandEnvironmentVariables($Manifest.install.default_root).Replace("/", "\")
}
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$pythonMinor = [string]$Manifest.python.minor
$InstallDir = Join-Path $InstallRoot ("neo-{0}" -f $ForgeRevision.Substring(0, 8))
$SourceDir = Join-Path $InstallDir "source"
$DataDir = Join-Path $InstallDir ([string]$Manifest.runtime_dirs.data)
$VenvDir = Join-Path $InstallDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

# Windows long paths are off by default and torch ships a very deep licenses tree: refuse a too-long root up
# front (read-only) instead of failing deep into the install.
$worstPath = $VenvDir.Length + [int]$Manifest.install.path_budget.max_venv_relative_path
if ($worstPath -gt [int]$Manifest.install.path_budget.windows_path_limit) {
    throw "Install path is too long: the deepest package file would be $worstPath characters (limit $($Manifest.install.path_budget.windows_path_limit)). Use a shorter -InstallRoot."
}

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
    if ($facts.Minor -ne $pythonMinor) { throw "Python $pythonMinor is required for the managed Forge runtime; '$Executable' reports $($facts.Minor). Install official Python $pythonMinor or pass -PythonPath." }
    if ($facts.FreeThreaded) { throw "'$Executable' is a free-threaded Python build, which the managed Forge runtime does not support." }
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

function Write-InstallMarker {
    # The ownership marker: written the moment this run creates the install directory (status
    # "installing"), and updated to "verified" only after the finished runtime passes its checks.
    param([string]$Status)
    @{ revision = $ForgeRevision; adetailer_neo = $AdetailerRevision; python = $pythonMinor; constraints = (Split-Path -Leaf $ConstraintsPath); created_by = "bootstrap_managed_forge_windows.ps1"; status = $Status } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallDir $MarkerName) -Encoding utf8
}

function Initialize-OwnedInstallDir {
    # Leaves $InstallDir a StableNew-owned, marked directory, or throws. A directory that already
    # exists is touched only if THIS tooling created it earlier (marker present): one without the
    # marker is someone else's and is never modified, adopted, recreated or deleted, with or without
    # -Recreate. A directory this run creates is marked before the first fallible step (fetch, venv, pip),
    # so a failed partial build can always be rebuilt with -Recreate.
    $marker = Join-Path $InstallDir $MarkerName
    if (Test-Path -LiteralPath $InstallDir) {
        if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
            throw "'$InstallDir' already exists and was not created by this tooling (no $MarkerName); refusing to modify or delete it. Move it aside or choose another -InstallRoot."
        }
        if (-not $Recreate) {
            if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { throw "'$InstallDir' is an incomplete StableNew-managed install. Pass -Recreate to rebuild it." }
            return
        }
        Remove-Item -LiteralPath $InstallDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $InstallDir | Out-Null   # no -Force: an existing directory must never be adopted here
    try {
        Write-InstallMarker -Status "installing"
    } catch {
        # The directory is empty and was created by this run; leave no markerless remnant behind.
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Get-ConstraintPin {
    param([string]$Name)
    $match = Select-String -LiteralPath $ConstraintsPath -Pattern ("^{0}==(\S+)\s*(#.*)?$" -f [regex]::Escape($Name)) | Select-Object -First 1
    if ($null -eq $match) { return $null }
    return $match.Matches[0].Groups[1].Value
}

function Install-PinnedSource {
    # Fetch exactly one commit (no branch, no pull) into a fresh repository and require HEAD to equal it.
    param([string]$Repository, [string]$Revision, [string]$Destination)
    if (-not (Test-Path -LiteralPath (Join-Path $Destination ".git"))) {
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        Invoke-Checked -Executable "git" -Arguments @("-C", $Destination, "init", "--quiet") -FailureMessage "Could not initialise '$Destination'." | Out-Null
        Invoke-Checked -Executable "git" -Arguments @("-C", $Destination, "remote", "add", "origin", $Repository) -FailureMessage "Could not add the origin '$Repository'." | Out-Null
        Invoke-Checked -Executable "git" -Arguments @("-C", $Destination, "fetch", "--quiet", "--depth", "1", "origin", $Revision) -FailureMessage "Could not fetch revision $Revision from $Repository." | Out-Null
        Invoke-Checked -Executable "git" -Arguments @("-C", $Destination, "checkout", "--quiet", "--detach", "FETCH_HEAD") -FailureMessage "Could not check out $Revision." | Out-Null
    }
    $head = (Invoke-Checked -Executable "git" -Arguments @("-C", $Destination, "rev-parse", "HEAD") -FailureMessage "Could not read the source revision of '$Destination'.") | Select-Object -Last 1
    if ($head.ToString().Trim() -ne $Revision) { throw "'$Destination' is at $head, not the pinned $Revision. Refusing to continue." }
}

function Install-Detectors {
    # Only the two authorised local YOLO files, validated by sha256 first, copied (never downloaded).
    $target = Join-Path $DataDir "models\adetailer"
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    foreach ($property in $Manifest.detectors.files.PSObject.Properties) {
        $source = Join-Path $DetectorSourceDir $property.Name
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Detector '$($property.Name)' not found in -DetectorSourceDir '$DetectorSourceDir'. Nothing is downloaded." }
        $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $property.Value) { throw "Detector '$($property.Name)' sha256 $hash does not match the accepted $($property.Value)." }
        Copy-Item -LiteralPath $source -Destination (Join-Path $target $property.Name)
    }
}

function Write-ForgeConfig {
    # The declared Forge settings, as BOM-less UTF-8 JSON (Forge reads it with plain utf-8).
    $settings = [ordered]@{}
    foreach ($property in $Manifest.config.required_settings.PSObject.Properties) { $settings[$property.Name] = $property.Value }
    $json = $settings | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $InstallDir ([string]$Manifest.config.file)), $json, (New-Object Text.UTF8Encoding($false)))
}

function Invoke-Verifier {
    $arguments = @($Verifier, "--install-dir", $InstallDir, "--model-reference-home", $ModelReferenceHome)
    if ($SkipModelHashes) { $arguments += "--skip-model-hashes" }
    Invoke-Checked -Executable $VenvPython -Arguments $arguments -FailureMessage "The managed Forge runtime at '$InstallDir' does not match its contract." | ForEach-Object { Write-Host $_ }
}

if ($CheckOnly -and $Recreate) { throw "-CheckOnly and -Recreate cannot be used together." }
if ([string]::IsNullOrWhiteSpace($ModelReferenceHome)) { throw "-ModelReferenceHome is required (the existing A1111 home whose models Forge references)." }
Assert-OwnedInstallDir

if ($CheckOnly) {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { throw "No managed Forge venv at '$VenvPython'. Run this script without -CheckOnly first." }
    Assert-SupportedPython -Executable $VenvPython
    Invoke-Verifier
    Write-Host "Managed Forge check-only verification passed: $InstallDir"
    return
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) { throw "-PythonPath is required (an official standard-GIL CPython $pythonMinor)." }
if ([string]::IsNullOrWhiteSpace($DetectorSourceDir)) { throw "-DetectorSourceDir is required (a local directory holding the two accepted YOLO detectors)." }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
Assert-SupportedPython -Executable $PythonPath

Initialize-OwnedInstallDir

Install-PinnedSource -Repository $Manifest.upstream.repository -Revision $ForgeRevision -Destination $SourceDir
Install-PinnedSource -Repository $Manifest.adetailer_neo.repository -Revision $AdetailerRevision -Destination (Join-Path $DataDir "extensions\adetailer-neo")

foreach ($relative in $Manifest.runtime_dirs.PSObject.Properties.Value) { New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir $relative) | Out-Null }

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Invoke-Checked -Executable $PythonPath -Arguments @("-m", "venv", $VenvDir) -FailureMessage "Could not create the venv at '$VenvDir'." | Out-Null
}
Assert-SupportedPython -Executable $VenvPython   # a reused venv keeps the interpreter it was created with

$pipPin = Get-ConstraintPin -Name "pip"
if ($null -eq $pipPin) { throw "'pip' is not pinned in '$ConstraintsPath'." }
Invoke-Checked -Executable $VenvPython -Arguments @("-m", "pip", "install", "pip==$pipPin") -FailureMessage "Could not install the pinned pip $pipPin." | Out-Null

# The Torch family comes from the CUDA index at the exact accepted +cu130 builds (a CPU build cannot satisfy
# them); their ordinary dependencies are in the lock, so nothing is resolved here.
$torchPin = Get-ConstraintPin -Name "torch"
$visionPin = Get-ConstraintPin -Name "torchvision"
if ($torchPin -ne [string]$Manifest.torch.torch -or $visionPin -ne [string]$Manifest.torch.torchvision) { throw "The lock's torch/torchvision pins differ from the contract." }
Invoke-Checked -Executable $VenvPython -Arguments @("-m", "pip", "install", "--no-deps", "--index-url", $CudaIndexUrl, "--extra-index-url", $PackageIndexUrl, "torch==$torchPin", "torchvision==$visionPin") -FailureMessage "Could not install CUDA-enabled Torch from '$CudaIndexUrl'." | Out-Null

# The complete accepted set, exactly, WITHOUT re-resolving it: the accepted upstream dependency graph is
# internally inconsistent (gradio 4.40.0 vs pillow 12.3.0) and is reproduced as it is, not repaired.
Invoke-Checked -Executable $VenvPython -Arguments @("-m", "pip", "install", "--no-deps", "-r", $ConstraintsPath) -FailureMessage "Could not install the accepted package set from '$ConstraintsPath'." | Out-Null

Install-Detectors
Write-ForgeConfig

Invoke-Verifier
Write-InstallMarker -Status "verified"
Write-Host "Managed Forge bootstrap verification passed: $InstallDir"
