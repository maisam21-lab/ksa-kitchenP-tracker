param(
    [string]$Label = "app-stable",
    [string]$Remote = "origin",
    [switch]$NoPush
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Slugify([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return "snapshot" }
    $s = $text.ToLowerInvariant()
    $s = [regex]::Replace($s, "[^a-z0-9]+", "-")
    $s = $s.Trim("-")
    if ([string]::IsNullOrWhiteSpace($s)) { return "snapshot" }
    return $s
}

try {
    git rev-parse --is-inside-work-tree *> $null
} catch {
    Write-Error "Not inside a git repository."
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$slug = Slugify $Label
$branch = "snapshot/$timestamp-$slug"
$tag = "snapshot-$timestamp-$slug"
$head = (git rev-parse --short HEAD).Trim()

$dirty = (git status --porcelain)
if ($dirty) {
    Write-Warning "Working tree has uncommitted changes. Snapshot points to commit $head only (not uncommitted files)."
}

if (((git branch --list $branch | Out-String).Trim())) {
    Write-Error "Branch already exists: $branch"
    exit 1
}
if (((git tag --list $tag | Out-String).Trim())) {
    Write-Error "Tag already exists: $tag"
    exit 1
}

$message = "Pre-change snapshot [$Label] at commit $head ($timestamp)"

git branch $branch | Out-Null
git tag -a $tag -m $message | Out-Null

if (-not $NoPush) {
    git push $Remote $branch
    git push $Remote $tag
}

Write-Host ""
Write-Host "Snapshot created:"
Write-Host "  Commit : $head"
Write-Host "  Branch : $branch"
Write-Host "  Tag    : $tag"
if ($NoPush) {
    Write-Host "  Push   : skipped (--NoPush)"
} else {
    Write-Host "  Push   : completed to $Remote"
}
Write-Host ""
Write-Host "Restore commands:"
Write-Host "  git checkout $branch"
Write-Host "  git checkout $tag"
