#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Bump the Wan2GP REST API plugin version in every source file at once.

.DESCRIPTION
    The plugin version is duplicated in three files that must never drift:
      - pyproject.toml   (version = "X.Y.Z")
      - plugin.py        (self.version = "X.Y.Z")
      - rest_server.py   (FastAPI version="X.Y.Z")
    This script reads the current version from pyproject.toml and rewrites all
    three to a new value. Pass an explicit X.Y.Z, or a bump keyword
    (major | minor | patch) to auto-increment.

.PARAMETER Version
    Target version: an explicit "X.Y.Z", or one of: major, minor, patch.

.EXAMPLE
    ./version_up.ps1 1.1.1
.EXAMPLE
    ./version_up.ps1 patch
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# Each file + the regex bracketing its version (named groups p=prefix, s=suffix).
$targets = @(
    @{ Path = 'pyproject.toml'; Pattern = '(?m)(?<p>^version = ")\d+\.\d+\.\d+(?<s>")' },
    @{ Path = 'plugin.py';      Pattern = '(?<p>self\.version = ")\d+\.\d+\.\d+(?<s>")' },
    @{ Path = 'rest_server.py'; Pattern = '(?<p>version=")\d+\.\d+\.\d+(?<s>")' }
)

# Current version = source of truth from pyproject.toml.
$pyproj = Join-Path $root 'pyproject.toml'
if (-not (Test-Path $pyproj)) { throw "pyproject.toml not found next to the script." }
$pyText = [System.IO.File]::ReadAllText($pyproj)
if ($pyText -notmatch '(?m)^version = "(?<v>\d+\.\d+\.\d+)"') {
    throw "Could not read current version from pyproject.toml."
}
$current = $Matches.v

# Resolve target version.
switch -Regex ($Version.Trim().ToLower()) {
    '^(major|minor|patch)$' {
        $parts = $current.Split('.') | ForEach-Object { [int]$_ }
        switch ($Matches[1]) {
            'major' { $new = "$($parts[0] + 1).0.0" }
            'minor' { $new = "$($parts[0]).$($parts[1] + 1).0" }
            'patch' { $new = "$($parts[0]).$($parts[1]).$($parts[2] + 1)" }
        }
    }
    '^\d+\.\d+\.\d+$' { $new = $Version.Trim() }
    default { throw "Invalid version '$Version'. Use X.Y.Z or one of: major, minor, patch." }
}

if ($new -eq $current) {
    Write-Host "Version already $current - nothing to do."
    return
}

# Rewrite every target (byte-faithful: preserves LF line endings, no BOM).
$replacement = '${p}' + $new + '${s}'
foreach ($t in $targets) {
    $path = Join-Path $root $t.Path
    if (-not (Test-Path $path)) { throw "Missing file: $($t.Path)" }
    $text = [System.IO.File]::ReadAllText($path)
    if ($text -notmatch $t.Pattern) { throw "Version string not found in $($t.Path)." }
    $updated = [regex]::Replace($text, $t.Pattern, $replacement)
    [System.IO.File]::WriteAllText($path, $updated)
    Write-Host "  updated $($t.Path)"
}

Write-Host "Version bumped: $current -> $new" -ForegroundColor Green
Write-Host "Next: review 'git diff', then commit (e.g. 'chore: bump version to $new')."
