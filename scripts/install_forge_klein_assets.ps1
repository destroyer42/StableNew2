[CmdletBinding()]
param(
    # Directory holding the three exact Klein files (flat). Required unless -CheckOnly.
    [string]$SourceDir = "",
    # Managed Forge install (<root>\neo-<rev8>); assets go to <InstallDir>\data\models\<subdir>.
    [string]$InstallDir = "",
    # Test seam: alternate manifest with the same schema (default config\forge_klein_assets.json).
    [string]$ManifestPath = "",
    # Verify the destinations only; mutate nothing and need no source.
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# PR-IMG-116: copies the three exact FLUX.2 Klein 4B FP8 files into the StableNew-managed Forge data/model tree.
# Performs no network download, never touches the A1111 library, the Forge source or venv, or any running runtime.
# All sources are size+SHA-256 verified and every destination is classified BEFORE the first byte is written; a
# same-name file with a different hash is refused (never overwritten); a correct destination is a no-op; each copy is
# staged beside the destination, hashed, renamed atomically and hashed again at the final name.

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ManifestPath)) { $ManifestPath = Join-Path $RepoRoot "config\forge_klein_assets.json" }
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "StableNew\Forge\neo-d70373eb"
}
$DataModels = Join-Path $InstallDir "data\models"
if (-not (Test-Path -LiteralPath (Join-Path $InstallDir "data") -PathType Container)) {
    throw "Managed Forge data directory not found: '$(Join-Path $InstallDir 'data')'. Build the managed runtime first; this tool never creates it."
}
if (-not $CheckOnly -and [string]::IsNullOrWhiteSpace($SourceDir)) { throw "-SourceDir is required unless -CheckOnly." }

function Get-Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

function Test-Exact([string]$Path, $Asset) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return "missing" }
    if ((Get-Item -LiteralPath $Path).Length -ne [int64]$Asset.size) { return "wrong" }
    if ((Get-Sha256 $Path) -ne ([string]$Asset.sha256).ToLowerInvariant()) { return "wrong" }
    return "correct"
}

$Plan = @()
foreach ($asset in $Manifest.assets) {
    $dest = Join-Path (Join-Path $DataModels $asset.models_subdir) $asset.filename
    $destResolved = [System.IO.Path]::GetFullPath($dest)
    if (-not $destResolved.StartsWith([System.IO.Path]::GetFullPath($DataModels), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Destination escapes the managed Forge model tree: '$destResolved'."
    }
    $state = Test-Exact $destResolved $asset
    $source = ""
    if (-not $CheckOnly) {
        $source = Join-Path $SourceDir $asset.filename
        $sourceState = Test-Exact $source $asset
        if ($sourceState -ne "correct") { throw "Source '$source' is $sourceState (exact size and SHA-256 required): no file was changed." }
    }
    $Plan += [pscustomobject]@{ Role = $asset.role; Filename = $asset.filename; Source = $source; Destination = $destResolved; State = $state; Asset = $asset }
}

$conflicts = @($Plan | Where-Object { $_.State -eq "wrong" })
if ($conflicts.Count -gt 0) {
    $names = ($conflicts | ForEach-Object { $_.Destination }) -join "; "
    throw "Refusing to overwrite a same-name destination with a different hash: $names. No file was changed."
}

$Result = @()
foreach ($item in $Plan) {
    $action = "verified"
    if ($item.State -eq "missing") {
        if ($CheckOnly) { $action = "missing" }
        else {
            $dir = Split-Path -Parent $item.Destination
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $partial = "$($item.Destination).partial-$([guid]::NewGuid().ToString('N'))"
            try {
                Copy-Item -LiteralPath $item.Source -Destination $partial
                if ((Test-Exact $partial $item.Asset) -ne "correct") { throw "Staged copy of '$($item.Filename)' failed verification." }
                Move-Item -LiteralPath $partial -Destination $item.Destination
            }
            finally { if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force } }
            if ((Test-Exact $item.Destination $item.Asset) -ne "correct") { throw "Installed '$($item.Destination)' failed post-copy verification." }
            $action = "installed"
        }
    }
    $Result += [pscustomobject]@{ role = $item.Role; filename = $item.Filename; destination = $item.Destination; action = $action; sha256 = $item.Asset.sha256 }
}

[pscustomobject]@{ check_only = [bool]$CheckOnly; data_models = $DataModels; assets = $Result } | ConvertTo-Json -Depth 5
if ($CheckOnly -and @($Result | Where-Object { $_.action -ne "verified" }).Count -gt 0) { exit 2 }
