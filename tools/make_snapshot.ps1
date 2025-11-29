# ===============================================
#  StableNew - Clean Snapshot ZIP Builder
# -----------------------------------------------
#  Creates a pruned ZIP of the repo for ChatGPT:
#    - Excludes large/noisy folders (output, archive, models, venv, etc.)
#    - Adds version + timestamp to filename
#
#  Example output:
#    StableNew_v1.0.1_20251115_214500.zip
#
#  Usage (from PowerShell):
#    pwsh -File tools\make_snapshot.ps1
#
#  Version of this script: 1.1
# ===============================================

# ------------- USER CONFIG ---------------------

# Path to your StableNew repo
$RepoPath = "C:\\Users\\rober\\projects\\StableNew"

# Where to save the ZIPs (folder only)
$ZipOutputFolder = "C:\\Users\\rober\\Desktop"

# Base project name (used in ZIP filename)
$ProjectName = "StableNew"

# Starting version if no version file exists
$DefaultVersion = "1.0.0"

# Enable auto patch bump? (e.g. 1.0.0 -> 1.0.1 each time)
$AutoBumpPatch = $true

# Version file to store the current version between runs
$VersionFilePath = Join-Path $RepoPath ".stableNew_version.txt"

# ------------- END USER CONFIG -----------------

Write-Host "=== StableNew Clean ZIP Builder ===" -ForegroundColor Cyan
Write-Host "Repo:   $RepoPath"
Write-Host "Output: $ZipOutputFolder"
Write-Host ""

# Try PATH first
$sevenZip = Get-Command "7z" -ErrorAction SilentlyContinue

# Fallback to default installation path
if (-not $sevenZip) {
    $default7z = "C:\Program Files\7-Zip\7z.exe"
    if (Test-Path $default7z) {
        $sevenZip = $default7z
    }
}

if (-not $sevenZip) {
    Write-Host "ERROR: 7-Zip is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Expected at: C:\Program Files\7-Zip\7z.exe"
    exit 1
}

# ---------- Ensure Repo Exists ----------
if (-not (Test-Path $RepoPath)) {
    Write-Host "ERROR: Repo path does not exist: $RepoPath" -ForegroundColor Red
    exit 1
}

# ---------- Version Helpers ----------
function Parse-Version {
    param(
        [string]$v
    )
    # Expecting format: major.minor.patch (e.g., 1.2.3)
    $parts = $v.Split('.')
    if ($parts.Count -ne 3) {
        throw "Version '$v' is not in 'major.minor.patch' format."
    }
    return [PSCustomObject]@{
        Major = [int]$parts[0]
        Minor = [int]$parts[1]
        Patch = [int]$parts[2]
    }
}

function Version-ToString {
    param(
        [int]$Major,
        [int]$Minor,
        [int]$Patch
    )
    return "$Major.$Minor.$Patch"
}

# ---------- Load or Initialize Version ----------
if (Test-Path $VersionFilePath) {
    $rawVersion = (Get-Content $VersionFilePath -ErrorAction Stop).Trim()
    try {
        $vObj = Parse-Version $rawVersion
    } catch {
        Write-Host "WARNING: Version file invalid, resetting to default $DefaultVersion" -ForegroundColor Yellow
        $vObj = Parse-Version $DefaultVersion
    }
} else {
    Write-Host "No version file found. Initializing version to $DefaultVersion" -ForegroundColor Yellow
    $vObj = Parse-Version $DefaultVersion
}

# Optionally bump patch version
if ($AutoBumpPatch) {
    $vObj.Patch += 1
}

$currentVersion = Version-ToString -Major $vObj.Major -Minor $vObj.Minor -Patch $vObj.Patch

# Save updated version back to file
$currentVersion | Out-File -FilePath $VersionFilePath -Encoding utf8 -Force

Write-Host "Using version: v$currentVersion" -ForegroundColor Green

# ---------- Build Timestamped Filename ----------
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$zipFileName = "{0}_v{1}_{2}.zip" -f $ProjectName, $currentVersion, $timestamp
$ZipOutputPath = Join-Path $ZipOutputFolder $zipFileName

Write-Host "Final ZIP name: $zipFileName"
Write-Host ""

# ---------- Run 7-Zip with Exclusions ----------
Write-Host "Running 7-Zip with exclusions..." -ForegroundColor Yellow

& $sevenZip a `
    $ZipOutputPath `
    "$RepoPath\*" `
    "-tzip" `
    "-xr!output\*" `
    "-xr!archive\*" `
    "-xr!venv\*" `
    "-xr!__pycache__\*" `
    "-xr!.pytest_cache\*" `
    "-xr!models\*" `
    "-xr!.git\*" `
    "-xr!dist\*" `
    "-xr!build\*" `
    "-xr!*.log"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ ZIP successfully created!" -ForegroundColor Green
    Write-Host "Location: $ZipOutputPath"
    Write-Host "Version file updated to v$currentVersion at: $VersionFilePath"
} else {
    Write-Host ""
    Write-Host "❌ ZIP creation failed (7-Zip returned exit code $LASTEXITCODE)" -ForegroundColor Red
}
