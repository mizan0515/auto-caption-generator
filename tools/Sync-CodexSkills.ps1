[CmdletBinding()]
param(
    [string]$Root = ".",
    [string]$DestinationRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath $Root).Path
$sourceRoot = Join-Path $repoRoot ".agents\skills"

if (-not (Test-Path -LiteralPath $sourceRoot)) {
    throw "Source skills directory not found: $sourceRoot"
}

if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $DestinationRoot = Join-Path $HOME ".codex\skills"
}

$destinationRootResolved = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DestinationRoot)
$expectedPrefix = Join-Path $HOME ".codex\skills"
if (-not ($destinationRootResolved -like ($expectedPrefix + "*"))) {
    throw "Destination must stay under $expectedPrefix"
}

if (-not (Test-Path -LiteralPath $destinationRootResolved)) {
    New-Item -ItemType Directory -Path $destinationRootResolved | Out-Null
}

$skills = Get-ChildItem -LiteralPath $sourceRoot -Directory | Sort-Object Name

foreach ($skill in $skills) {
    $sourcePath = $skill.FullName
    $targetPath = Join-Path $destinationRootResolved $skill.Name
    $resolvedTargetParent = Split-Path -Path $targetPath -Parent

    if ($resolvedTargetParent -ne $destinationRootResolved) {
        throw "Refusing to sync outside destination root: $targetPath"
    }

    if (Test-Path -LiteralPath $targetPath) {
        Remove-Item -LiteralPath $targetPath -Recurse -Force
    }

    Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Recurse -Force
    Write-Output ("Synced {0} -> {1}" -f $skill.Name, $targetPath)
}

Write-Output ("Synced {0} skill(s) to {1}" -f $skills.Count, $destinationRootResolved)
