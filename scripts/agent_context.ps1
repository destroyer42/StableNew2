[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$root = git rev-parse --show-toplevel 2>$null
if (-not $root) {
    throw "Not inside a Git repository."
}

Push-Location $root
try {
    $branch = git branch --show-current
    $head = git rev-parse HEAD
    $originMain = git rev-parse origin/main 2>$null
    $status = git status --short
    $last = git log -1 --pretty=format:"%h %cI %s"
    $changed = @()
    if ($originMain) {
        $changed = git diff --name-only origin/main...HEAD
    }

    Write-Output "REPO=$root"
    Write-Output "BRANCH=$branch"
    Write-Output "HEAD=$head"
    if ($originMain) { Write-Output "ORIGIN_MAIN=$originMain" }
    Write-Output "LAST_COMMIT=$last"

    Write-Output "WORKTREE_STATUS_BEGIN"
    if ($status) { $status } else { Write-Output "(clean)" }
    Write-Output "WORKTREE_STATUS_END"

    Write-Output "BRANCH_CHANGED_FILES_BEGIN"
    if ($changed) { $changed } else { Write-Output "(none)" }
    Write-Output "BRANCH_CHANGED_FILES_END"
}
finally {
    Pop-Location
}
