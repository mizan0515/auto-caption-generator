[CmdletBinding()]
param(
    [string]$Root = "."
)

$ErrorActionPreference = "Stop"

function Test-Ascii {
    param([string]$Value)

    if ($null -eq $Value) {
        return $false
    }

    return [System.Text.Encoding]::UTF8.GetByteCount($Value) -eq $Value.Length
}

$repoRoot = (Resolve-Path -LiteralPath $Root).Path
$skillsRoot = Join-Path $repoRoot ".agents\skills"

if (-not (Test-Path -LiteralPath $skillsRoot)) {
    throw "Skills directory not found: $skillsRoot"
}

$failures = New-Object System.Collections.Generic.List[string]
$skills = Get-ChildItem -LiteralPath $skillsRoot -Directory | Sort-Object Name

foreach ($skill in $skills) {
    $skillMdPath = Join-Path $skill.FullName "SKILL.md"
    $openAiYamlPath = Join-Path $skill.FullName "agents\openai.yaml"

    if (-not (Test-Path -LiteralPath $skillMdPath)) {
        $failures.Add("[$($skill.Name)] missing SKILL.md")
        continue
    }

    if (-not (Test-Path -LiteralPath $openAiYamlPath)) {
        $failures.Add("[$($skill.Name)] missing agents/openai.yaml")
        continue
    }

    $skillMdContent = Get-Content -LiteralPath $skillMdPath -Raw -Encoding UTF8
    if ($skillMdContent -notmatch '(?s)^---\s*\r?\n(.*?)\r?\n---') {
        $failures.Add("[$($skill.Name)] invalid SKILL.md frontmatter")
        continue
    }

    $frontmatter = $Matches[1]
    $nameMatch = [regex]::Match($frontmatter, '(?m)^name:\s*(.+)\s*$')
    $descriptionMatch = [regex]::Match($frontmatter, '(?m)^description:\s*"([^"]+)"\s*$')

    if (-not $nameMatch.Success) {
        $failures.Add("[$($skill.Name)] missing frontmatter name")
    } else {
        $frontmatterName = $nameMatch.Groups[1].Value.Trim()
        if ($frontmatterName -ne $skill.Name) {
            $failures.Add("[$($skill.Name)] folder name and frontmatter name differ: folder=$($skill.Name), name=$frontmatterName")
        }
        if (-not (Test-Ascii $frontmatterName)) {
            $failures.Add("[$($skill.Name)] frontmatter name must stay ASCII for reliable Codex Desktop indexing")
        }
    }

    if (-not $descriptionMatch.Success) {
        $failures.Add("[$($skill.Name)] missing quoted frontmatter description")
    } elseif (-not (Test-Ascii $descriptionMatch.Groups[1].Value)) {
        $failures.Add("[$($skill.Name)] frontmatter description must stay ASCII for reliable Codex Desktop indexing")
    }

    $yamlContent = Get-Content -LiteralPath $openAiYamlPath -Raw -Encoding UTF8
    foreach ($field in @("display_name", "short_description", "default_prompt")) {
        $pattern = '(?m)^\s*{0}:\s*"([^"]+)"\s*$' -f [regex]::Escape($field)
        $match = [regex]::Match($yamlContent, $pattern)
        if (-not $match.Success) {
            $failures.Add("[$($skill.Name)] missing quoted $field in agents/openai.yaml")
            continue
        }
        if (-not (Test-Ascii $match.Groups[1].Value)) {
            $failures.Add("[$($skill.Name)] $field must stay ASCII for reliable Codex Desktop indexing")
        }
    }
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output ("Validated {0} skill(s): PASS" -f $skills.Count)
