param(
    [Parameter(Mandatory = $true)]
    [string]$SessionId,
    [Parameter(Mandatory = $true)]
    [string]$TaskSummary,
    [ValidateSet('small', 'medium', 'large')]
    [string]$Scope = 'medium',
    [ValidateSet('autonomous', 'hybrid', 'supervised')]
    [string]$Mode = 'hybrid',
    [string]$Root = ".",
    [int]$MaxTurns = 0,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if ($MaxTurns -le 0) {
    switch ($Scope) {
        'small' { $MaxTurns = 2 }
        'medium' { $MaxTurns = 5 }
        'large' { $MaxTurns = 10 }
    }
}

$resolvedRoot = (Resolve-Path $Root).Path
$dialogueRoot = Join-Path $resolvedRoot "Document\dialogue"
$sessionsRoot = Join-Path $dialogueRoot "sessions"
$targetDir = Join-Path $sessionsRoot $SessionId
$statePath = Join-Path $dialogueRoot "state.json"
$sessionStatePath = Join-Path $targetDir "state.json"

if ((Test-Path $targetDir) -and -not $Force) {
    throw "Session directory already exists: $targetDir"
}

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

$state = [ordered]@{
    protocol_version = "dad-v2"
    session_id = $SessionId
    session_status = "active"
    superseded_by = $null
    closed_reason = $null
    relay_mode = "user-bridged"
    mode = $Mode
    scope = $Scope
    current_turn = 0
    max_turns = $MaxTurns
    last_agent = $null
    task_summary = $TaskSummary
    contract_status = "proposed"
    contract_checkpoints = [ordered]@{}
    packets = @()
    decisions = @()
    meta_improvements = @()
}

$json = $state | ConvertTo-Json -Depth 20
$enc = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($statePath, $json, $enc)
[System.IO.File]::WriteAllText($sessionStatePath, $json, $enc)

Write-Output "Created DAD session '$SessionId'."
Write-Output "Session dir: $targetDir"
Write-Output "State: $statePath"
