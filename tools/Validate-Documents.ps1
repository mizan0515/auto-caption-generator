# UTF-8 BOM rationale: Korean-language documents in this template risk being
# misdetected as CP949 (legacy Windows Korean encoding) by editors and tools.
# Enforcing UTF-8 BOM prevents silent mojibake. Cross-platform teams that
# prefer BOM-less UTF-8 may relax this check for non-Document/ files.

param(
    [string]$Root,
    [switch]$Fix,
    [switch]$IncludeRootGuides,
    [switch]$IncludeAgentDocs,
    [switch]$ReportLargeDocs,
    [switch]$ReportLargeRootGuides,
    [switch]$FailOnLargeDocs,
    [int]$LargeDocCharThreshold = 12000
)

$ErrorActionPreference = 'Stop'

$utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
$cp949 = [System.Text.Encoding]::GetEncoding(949)
$defaultRepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = if ($Root) { (Resolve-Path -LiteralPath $Root).Path } else { $defaultRepoRoot }
$normalizedRepoRoot = $repoRoot.Replace('/', '\').TrimEnd('\')

function Get-DocumentFiles {
    $files = @()
    $documentRoot = Join-Path $repoRoot 'Document'

    if (Test-Path -LiteralPath $documentRoot) {
        $files += @(
            Get-ChildItem -Path $documentRoot -Recurse -File -Filter '*.md' | Select-Object -ExpandProperty FullName
        )
    }

    if ($IncludeRootGuides) {
        $files += @(
            Get-ChildItem -Path $repoRoot -File -Filter '*.md' | Select-Object -ExpandProperty FullName
        )
    }

    if ($IncludeAgentDocs) {
        $includeDirectories = @(
            '.agents\skills',
            '.claude\commands',
            '.prompts'
        )

        foreach ($relativeDirectory in $includeDirectories) {
            $directory = Join-Path $repoRoot $relativeDirectory
            if (Test-Path -LiteralPath $directory) {
                $files += @(
                    Get-ChildItem -Path $directory -Recurse -File -Filter '*.md' | Select-Object -ExpandProperty FullName
                )
            }
        }
    }

    $files | Sort-Object -Unique
}

function Test-HasBom([byte[]]$Bytes) {
    return $Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF
}

function Test-RequiresBom([string]$Path) {
    $normalized = (Resolve-Path -LiteralPath $Path).Path.Replace('/', '\')

    if ($normalized -match '\\Document\\') {
        return $true
    }

    $parent = (Split-Path -Path $normalized -Parent).TrimEnd('\')
    if ($parent -eq $normalizedRepoRoot -and $normalized.EndsWith('.md', [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }

    return $normalized -match '\\\.claude\\commands\\' -or
        $normalized -match '\\\.prompts\\'
}

function LooksLikeLocalReference([string]$Reference) {
    if ([string]::IsNullOrWhiteSpace($Reference)) {
        return $false
    }

    $candidate = $Reference.Trim().Trim('<', '>')
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        return $false
    }

    if ($candidate -match '^[a-zA-Z][a-zA-Z0-9+.-]*://') {
        return $false
    }

    if ($candidate.StartsWith('#')) {
        return $false
    }

    if ($candidate -match '\s' -or $candidate -match '[*{}]') {
        return $false
    }

    if ($candidate -match '^[A-Za-z]:\\') {
        return $false
    }

    if ($candidate -match '^/[A-Za-z0-9_-]+$' -or $candidate -match '^\.[A-Za-z0-9]+$') {
        return $false
    }

    return ($candidate -match '[\\/]' -or $candidate -match '\.(md|ps1|sh|json|ya?ml|txt)$')
}

function Normalize-LocalReference([string]$Reference) {
    $candidate = $Reference.Trim().Trim('<', '>')
    $candidate = ($candidate -split '#', 2)[0]
    $candidate = ($candidate -split '\?', 2)[0]

    if ($candidate -match '^(?<path>.+\.(md|ps1|sh|json|ya?ml|txt)):\d+$') {
        $candidate = $matches.path
    }

    $candidate.TrimEnd('.', ',', ';', ':')
}

function Test-IsEphemeralReference([string]$Reference) {
    $normalized = $Reference -replace '\\', '/'

    return $Reference -in @(
        'state.json',
        'summary.md',
        'Document/dialogue/state.json'
    ) -or
    $Reference -match '^Document/dialogue/sessions/' -or
    $Reference -match '^turn-\{N\}\.yaml$' -or
    $normalized -eq 'pipeline_config.json' -or
    $normalized -eq '.claude/settings.local.json' -or
    $normalized -eq '_archive/' -or
    $normalized -like '_archive/*' -or
    $normalized -eq 'output/' -or
    $normalized -like 'output/*' -or
    $normalized -eq 'work/' -or
    $normalized -like 'work/*'
}

function Resolve-LocalReferencePath([string]$Reference, [string]$SourcePath) {
    $sourceDirectory = Split-Path -Path $SourcePath -Parent
    $normalizedReference = $Reference -replace '/', '\'

    if ($Reference.StartsWith('./') -or $Reference.StartsWith('.\') -or $Reference.StartsWith('..\') -or $Reference.StartsWith('../')) {
        return (Join-Path $sourceDirectory $normalizedReference).TrimEnd('\')
    }

    $relativeCandidate = (Join-Path $sourceDirectory $normalizedReference).TrimEnd('\')
    if (Test-Path -LiteralPath $relativeCandidate) {
        return $relativeCandidate
    }

    return (Join-Path $repoRoot $normalizedReference).TrimEnd('\')
}

function Get-LocalReferenceIssues([string]$Path, [string]$Text) {
    $issues = New-Object System.Collections.Generic.List[string]
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $references = New-Object System.Collections.Generic.List[string]

    foreach ($match in [regex]::Matches($Text, '`([^`]+)`')) {
        $references.Add($match.Groups[1].Value)
    }

    foreach ($match in [regex]::Matches($Text, '\[[^\]]+\]\(([^)]+)\)')) {
        $references.Add($match.Groups[1].Value)
    }

    foreach ($rawReference in $references) {
        if (-not (LooksLikeLocalReference -Reference $rawReference)) {
            continue
        }

        $reference = Normalize-LocalReference -Reference $rawReference
        if ([string]::IsNullOrWhiteSpace($reference)) {
            continue
        }

        if (Test-IsEphemeralReference -Reference $reference) {
            continue
        }

        if ($reference -match '[<>\"|?*]') {
            continue
        }

        if (-not $seen.Add($reference)) {
            continue
        }

        $targetPath = Resolve-LocalReferencePath -Reference $reference -SourcePath $Path

        if (-not (Test-Path -LiteralPath $targetPath)) {
            $issues.Add("missing-ref:$reference")
        }
    }

    $issues
}

function Get-Candidate([byte[]]$Bytes, [System.Text.Encoding]$Encoding, [string]$Name) {
    try {
        $text = $Encoding.GetString($Bytes)
        $hangul = ([regex]::Matches($text, '[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]')).Count
        $replacement = ($text.ToCharArray() | Where-Object { $_ -eq [char]0xFFFD } | Measure-Object).Count
        $nul = ($text.ToCharArray() | Where-Object { $_ -eq [char]0 } | Measure-Object).Count
        $control = ($text.ToCharArray() | Where-Object {
            $code = [int][char]$_
            $code -lt 32 -and $code -notin 9, 10, 13
        } | Measure-Object).Count

        [PSCustomObject]@{
            Name = $Name
            Text = $text
            Score = ($hangul * 4) - ($replacement * 100) - ($nul * 1000) - ($control * 300)
            Valid = $true
        }
    }
    catch {
        [PSCustomObject]@{
            Name = $Name
            Text = $null
            Score = -999999
            Valid = $false
        }
    }
}

function Resolve-DocumentText([byte[]]$Bytes, [string]$Path) {
    if (Test-HasBom $Bytes) {
        return [PSCustomObject]@{
            Source = 'utf8-bom'
            Text = $utf8Strict.GetString($Bytes, 3, $Bytes.Length - 3)
        }
    }

    $utf8Candidate = Get-Candidate -Bytes $Bytes -Encoding $utf8Strict -Name 'utf8'
    $cp949Candidate = Get-Candidate -Bytes $Bytes -Encoding $cp949 -Name 'cp949'

    if ($utf8Candidate.Valid -and -not $cp949Candidate.Valid) {
        return [PSCustomObject]@{ Source = 'utf8'; Text = $utf8Candidate.Text }
    }

    if (-not $utf8Candidate.Valid -and $cp949Candidate.Valid) {
        return [PSCustomObject]@{ Source = 'cp949'; Text = $cp949Candidate.Text }
    }

    if (-not $utf8Candidate.Valid -and -not $cp949Candidate.Valid) {
        throw "Unable to decode file as UTF-8 or CP949: $Path"
    }

    if ($cp949Candidate.Score -gt ($utf8Candidate.Score + 20)) {
        return [PSCustomObject]@{ Source = 'cp949'; Text = $cp949Candidate.Text }
    }

    return [PSCustomObject]@{ Source = 'utf8'; Text = $utf8Candidate.Text }
}

function Get-Issues([string]$Path, [string]$Text, [bool]$HasBom, [string]$SourceEncoding) {
    $issues = New-Object System.Collections.Generic.List[string]

    if ((Test-RequiresBom -Path $Path) -and -not $HasBom) {
        $issues.Add('missing-bom')
    }

    if ($SourceEncoding -eq 'cp949') {
        $issues.Add('legacy-cp949')
    }

    if ($Text.Contains([char]0)) {
        $issues.Add('nul-char')
    }

    if ($Text.Contains([char]0xFFFD)) {
        $issues.Add('replacement-char')
    }

    foreach ($ch in $Text.ToCharArray()) {
        $code = [int][char]$ch
        if ($code -lt 32 -and $code -notin 9, 10, 13) {
            $issues.Add('control-char')
            break
        }
    }

    foreach ($referenceIssue in Get-LocalReferenceIssues -Path $Path -Text $Text) {
        $issues.Add($referenceIssue)
    }

    $issues
}

$results = foreach ($file in Get-DocumentFiles) {
    $bytes = [System.IO.File]::ReadAllBytes($file)
    $resolved = Resolve-DocumentText -Bytes $bytes -Path $file

    if ($Fix) {
        $normalized = $resolved.Text.Replace([string][char]0, '')
        [System.IO.File]::WriteAllText($file, $normalized, $utf8Bom)
        $bytes = [System.IO.File]::ReadAllBytes($file)
        $resolved = Resolve-DocumentText -Bytes $bytes -Path $file
    }

    [PSCustomObject]@{
        File = $file
        IsRootGuide = -not ($file -match '\\Document\\')
        TextLength = $resolved.Text.Length
        LineCount = ($resolved.Text -split "`r?`n").Count
        Issues = (Get-Issues -Path $file -Text $resolved.Text -HasBom (Test-HasBom $bytes) -SourceEncoding $resolved.Source) -join ', '
    }
}

$problemFiles = $results | Where-Object { $_.Issues }

if ($problemFiles) {
    $problemFiles | Format-Table -AutoSize
    exit 1
}

$largeDocFiles = $results | Where-Object { -not $_.IsRootGuide -and $_.TextLength -ge $LargeDocCharThreshold } | Sort-Object TextLength -Descending
$largeRootGuideFiles = $results | Where-Object { $_.IsRootGuide -and $_.TextLength -ge $LargeDocCharThreshold } | Sort-Object TextLength -Descending

if ($ReportLargeDocs -and $largeDocFiles) {
    Write-Output ''
    Write-Output "Large document warning report (char heuristic >= $LargeDocCharThreshold):"
    $largeDocFiles | Select-Object File, TextLength, LineCount | Format-Table -AutoSize

    if ($FailOnLargeDocs) {
        exit 2
    }
}

if ($ReportLargeRootGuides -and $largeRootGuideFiles) {
    Write-Output ''
    Write-Output "Large root-guide warning report (char heuristic >= $LargeDocCharThreshold):"
    $largeRootGuideFiles | Select-Object File, TextLength, LineCount | Format-Table -AutoSize

    if ($FailOnLargeDocs) {
        exit 2
    }
}

Write-Output "Document validation passed for $($results.Count) files."
