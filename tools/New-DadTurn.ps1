param(
    [string]$SessionId,
    [ValidateSet('codex', 'claude-code')]
    [string]$From = 'codex',
    [int]$Turn = 0,
    [string]$Root = ".",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$resolvedRoot = (Resolve-Path $Root).Path
$dialogueRoot = Join-Path $resolvedRoot "Document\dialogue"
$statePath = Join-Path $dialogueRoot "state.json"

if (-not (Test-Path $statePath)) {
    throw "state.json not found: $statePath"
}

$state = Get-Content -Path $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $SessionId) {
    $SessionId = $state.session_id
}

$targetDir = Join-Path (Join-Path $dialogueRoot "sessions") $SessionId
if (-not (Test-Path $targetDir)) {
    throw "Session directory not found: $targetDir"
}

$sessionStatePath = Join-Path $targetDir "state.json"
if (-not (Test-Path $sessionStatePath)) {
    throw "Session state not found: $sessionStatePath"
}

$sessionState = Get-Content -Path $sessionStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sessionState.session_id -ne $SessionId) {
    throw "Session state mismatch in '$sessionStatePath'. Expected session_id '$SessionId', found '$($sessionState.session_id)'."
}

if ($Turn -le 0) {
    $existing = Get-ChildItem -Path $targetDir -File -Filter "turn-*.yaml" | ForEach-Object {
        if ($_.BaseName -match '^turn-(\d+)') { [int]$Matches[1] }
    } | Sort-Object
    $Turn = if ($existing) { $existing[-1] + 1 } else { 1 }
}

$fileName = ('turn-{0:00}.yaml' -f $Turn)
$targetPath = Join-Path $targetDir $fileName

if ((Test-Path $targetPath) -and -not $Force) {
    throw "Turn file already exists: $targetPath"
}

$yaml = @"
type: turn
from: $From
turn: $Turn
session_id: "$SessionId"

contract:
  status: proposed
  checkpoints: []
  amendments: []

peer_review:
  # project_analysis: ""          # Turn 1 only
  # task_model_review:            # Turn 2+
  #   status: aligned             # aligned | amended | superseded
  #   coverage_gaps: []
  #   scope_creep: []
  #   risk_followups: []
  #   amendments: []
  checkpoint_results: {}
  issues_found: []
  fixes_applied: []

my_work:
  # task_model: {}                # recommended for large scope
  plan: ""
  changes:
    files_modified: []
    files_created: []
    summary: ""
  self_iterations: 0
  evidence:
    commands: []
    artifacts: []
  verification: ""
  open_risks: []
  confidence: medium

handoff:
  next_task: ""
  context: ""
  questions: []
  ready_for_peer_verification: true
  suggest_done: false
  done_reason: ""
"@

$enc = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($targetPath, $yaml, $enc)

$relative = $targetPath.Substring($resolvedRoot.Length + 1).Replace('\', '/')
$packets = @()
if ($sessionState.packets) {
    $packets += @($sessionState.packets)
}
if ($packets -notcontains $relative) {
    $packets += $relative
}
[void]($sessionState.PSObject.Properties.Remove('packets'))
[void]($sessionState.PSObject.Properties.Remove('current_turn'))
[void]($sessionState.PSObject.Properties.Remove('last_agent'))
[void]($sessionState.PSObject.Properties.Remove('session_id'))
$sessionState | Add-Member -NotePropertyName packets -NotePropertyValue @($packets)
$sessionState | Add-Member -NotePropertyName current_turn -NotePropertyValue $Turn
$sessionState | Add-Member -NotePropertyName last_agent -NotePropertyValue $From
$sessionState | Add-Member -NotePropertyName session_id -NotePropertyValue $SessionId

$updatedJson = $sessionState | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($statePath, $updatedJson, $enc)
[System.IO.File]::WriteAllText($sessionStatePath, $updatedJson, $enc)

Write-Output "Created turn file: $targetPath"
