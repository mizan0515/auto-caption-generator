<#
.SYNOPSIS
    Detect stale v1 terms that still remain in active DAD v2 documents.

.DESCRIPTION
    After the DAD v2 protocol is introduced, this script scans active system
    documents (.prompts/, .claude/commands/, CLAUDE.md, AGENTS.md,
    DIALOGUE-PROTOCOL.md, etc.) for stale v1-era terms and reports them.
    Archived material such as Document/archive/ is excluded.

.PARAMETER Fix
    Apply only the safe auto-fixes. Terms that still need judgment are reported
    as MANUAL and must be reviewed by hand.

.EXAMPLE
    .\tools\Lint-StaleTerms.ps1
    .\tools\Lint-StaleTerms.ps1 -Fix
#>

param(
    [switch]$Fix
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $root

# --- stale term catalog (pattern -> replacement) ---
$staleTerms = @(
    @{ Pattern = "Proposal Packet";                              Replacement = "Turn Packet or handoff/peer_review field"; AutoFix = $false }
    @{ Pattern = "Result Packet";                                Replacement = "Turn Packet or handoff/peer_review field"; AutoFix = $false }
    @{ Pattern = "Evaluation Packet";                            Replacement = "Turn Packet or peer_review/checkpoint_results"; AutoFix = $false }
    @{ Pattern = "Review Packet";                                Replacement = "Turn Packet or peer_review field"; AutoFix = $false }
    @{ Pattern = "round-(\d+)-(proposal|result|evaluation|review)\.ya?ml"; Replacement = "turn-$1.yaml"; IsRegex = $true; AutoFix = $true }
    @{ Pattern = "round-\*-(proposal|result|evaluation|review)\.ya?ml";     Replacement = "turn-{N}.yaml"; IsRegex = $true; AutoFix = $true }
    @{ Pattern = "type:\s*proposal";                             Replacement = "type: turn"; IsRegex = $true; AutoFix = $true }
    @{ Pattern = "type:\s*result";                               Replacement = "type: turn"; IsRegex = $true; AutoFix = $true }
    @{ Pattern = "type:\s*evaluation";                           Replacement = "type: turn"; IsRegex = $true; AutoFix = $true }
    @{ Pattern = "type:\s*review";                               Replacement = "type: turn"; IsRegex = $true; AutoFix = $true }
    @{ Pattern = "\bphase\s*[:=]";                               Replacement = "current_turn / contract_status / relay_mode"; IsRegex = $true; AutoFix = $false }
    @{ Pattern = "\binitiator\s*[:=]";                           Replacement = "last_agent / from"; IsRegex = $true; AutoFix = $false }
    @{ Pattern = "\bexecutor\s*[:=]";                            Replacement = "from / my_work owner"; IsRegex = $true; AutoFix = $false }
    @{ Pattern = "\breviewer\s*[:=]";                            Replacement = "peer_review author"; IsRegex = $true; AutoFix = $false }
    @{ Pattern = "\bmax_rounds\s*[:=]";                          Replacement = "max_turns"; IsRegex = $true; AutoFix = $false }
)

# --- target files ---
$targetPaths = @(
    "CLAUDE.md"
    "AGENTS.md"
    "DIALOGUE-PROTOCOL.md"
    "PROJECT-RULES.md"
    ".claude/commands"
    ".prompts"
    "Document/dialogue"
)

$excludePattern = "archive", "round-", "state.json", "\sessions\", "/sessions/", "-review.md", "-summary.md"
$legacyContextPattern = "(?i)\b(v1|legacy|migration|archive)\b"

$files = @()
foreach ($tp in $targetPaths) {
    $fullPath = Join-Path $root $tp
    if (Test-Path $fullPath -PathType Leaf) {
        $files += Get-Item $fullPath
    }
    elseif (Test-Path $fullPath -PathType Container) {
        $files += Get-ChildItem -Path $fullPath -Recurse -Include "*.md","*.yaml","*.yml","*.json" -File
    }
}

# exclude archive and session artifacts
$files = $files | Where-Object {
    $path = $_.FullName
    -not ($excludePattern | Where-Object { $path -like "*$_*" })
}

# --- scan ---
$totalHits = 0
$hitFiles = @()

foreach ($file in $files) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    $fileHits = @()

    foreach ($term in $staleTerms) {
        $isRegex = $term.ContainsKey("IsRegex") -and $term.IsRegex

        if ($isRegex) {
            $matches = [regex]::Matches($content, $term.Pattern, "IgnoreCase")
            if ($matches.Count -gt 0) {
                foreach ($m in $matches) {
                    $lineNum = ($content.Substring(0, $m.Index) -split "`n").Count
                    $lineText = ($content -split "`r?`n")[$lineNum - 1]
                    if ($lineText -match $legacyContextPattern) {
                        continue
                    }
                    $fileHits += @{
                        Line        = $lineNum
                        Match       = $m.Value
                        Pattern     = $term.Pattern
                        Replacement = $term.Replacement
                        IsRegex     = $true
                        AutoFix     = ($term.ContainsKey("AutoFix") -and $term.AutoFix)
                    }
                }
                if ($Fix -and ($term.ContainsKey("AutoFix") -and $term.AutoFix)) {
                    $content = [regex]::Replace($content, $term.Pattern, $term.Replacement, "IgnoreCase")
                }
            }
        }
        else {
            $idx = 0
            while (($idx = $content.IndexOf($term.Pattern, $idx, [System.StringComparison]::OrdinalIgnoreCase)) -ge 0) {
                $lineNum = ($content.Substring(0, $idx) -split "`n").Count
                $lineText = ($content -split "`r?`n")[$lineNum - 1]
                if ($lineText -match $legacyContextPattern) {
                    $idx += $term.Pattern.Length
                    continue
                }
                $fileHits += @{
                    Line        = $lineNum
                    Match       = $term.Pattern
                    Pattern     = $term.Pattern
                    Replacement = $term.Replacement
                    IsRegex     = $false
                    AutoFix     = ($term.ContainsKey("AutoFix") -and $term.AutoFix)
                }
                $idx += $term.Pattern.Length
            }
            if ($Fix -and ($term.ContainsKey("AutoFix") -and $term.AutoFix)) {
                $content = $content.Replace($term.Pattern, $term.Replacement)
            }
        }
    }

    if ($fileHits.Count -gt 0) {
        $totalHits += $fileHits.Count
        $relativePath = $file.FullName.Substring($root.Length + 1)
        $hitFiles += $relativePath

        foreach ($hit in $fileHits) {
            if ($Fix -and $hit.AutoFix) {
                $action = "FIXED"
                $color = "Yellow"
            }
            elseif ($Fix -and -not $hit.AutoFix) {
                $action = "MANUAL"
                $color = "Red"
            }
            else {
                $action = "FOUND"
                $color = "Red"
            }
            Write-Host "  [$action] $relativePath`:$($hit.Line) -- '$($hit.Match)' -> '$($hit.Replacement)'" -ForegroundColor $color
        }

        if ($Fix) {
            Set-Content -Path $file.FullName -Value $content -Encoding UTF8 -NoNewline
        }
    }
}

# --- result ---
Write-Host ""
if ($totalHits -eq 0) {
    Write-Host "OK: No stale v1 terms found in active documents." -ForegroundColor Green
    exit 0
}
else {
    if ($Fix) {
        Write-Host "$totalHits stale term(s) detected. Safe replacements were applied where possible; remaining MANUAL hits still need review." -ForegroundColor Yellow
    }
    else {
        Write-Host "$totalHits stale term(s) found in $($hitFiles.Count) file(s)." -ForegroundColor Red
        Write-Host "Run with -Fix to auto-replace safe cases." -ForegroundColor Cyan
    }
    exit 1
}
