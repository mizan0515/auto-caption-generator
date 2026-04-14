param(
    [Parameter(Mandatory = $true)]
    [string]$SessionId,
    [string]$Root = ".",
    [switch]$UpdateState,
    [switch]$CopyOnly,
    [string]$SessionStatus,
    [ValidateSet('autonomous', 'hybrid', 'supervised')]
    [string]$Mode,
    [ValidateSet('small', 'medium', 'large')]
    [string]$Scope,
    [int]$MaxTurns = 0,
    [string]$ClosedReason,
    [string]$SupersededBy
)

$ErrorActionPreference = "Stop"

function Set-StateField {
    param(
        [object]$Object,
        [string]$Name,
        $Value
    )

    if ($Object.PSObject.Properties.Match($Name).Count -gt 0) {
        $Object.$Name = $Value
    }
    else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

$resolvedRoot = (Resolve-Path $Root).Path
$dialogueRoot = Join-Path $resolvedRoot "Document\dialogue"
$packetsRoot = Join-Path $dialogueRoot "packets"
$sessionsRoot = Join-Path $dialogueRoot "sessions"
$targetDir = Join-Path $sessionsRoot $SessionId
$statePath = Join-Path $dialogueRoot "state.json"

if (-not (Test-Path $statePath)) {
    throw "state.json not found: $statePath"
}

if (-not (Test-Path $packetsRoot)) {
    throw "Legacy packets directory not found: $packetsRoot"
}

$state = Get-Content -Path $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
$sessionPattern = '(?m)^session_id:\s*"?' + [regex]::Escape($SessionId) + '"?\s*$'
$packetFiles = Get-ChildItem -Path $packetsRoot -File -Filter "*.yaml" | Where-Object {
    $text = Get-Content -Path $_.FullName -Raw -Encoding UTF8
    [regex]::IsMatch($text, $sessionPattern)
}

if (-not $packetFiles) {
    throw "No legacy packet files found for session '$SessionId'."
}

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

$migratedPacketRefs = New-Object System.Collections.Generic.List[string]
$packetMeta = New-Object System.Collections.Generic.List[object]

foreach ($packet in $packetFiles | Sort-Object Name) {
    $text = Get-Content -Path $packet.FullName -Raw -Encoding UTF8
    $dest = Join-Path $targetDir $packet.Name
    Copy-Item -LiteralPath $packet.FullName -Destination $dest -Force

    if (-not $CopyOnly) {
        Remove-Item -LiteralPath $packet.FullName -Force
    }

    $relative = $dest.Substring($resolvedRoot.Length + 1).Replace('\', '/')
    $migratedPacketRefs.Add($relative) | Out-Null

    $turnMatch = [regex]::Match($text, '(?m)^turn:\s*(\d+)\s*$')
    $fromMatch = [regex]::Match($text, '(?m)^from:\s*([^\r\n]+)\s*$')
    $contractMatch = [regex]::Match($text, '(?ms)^contract:\s*\r?\n\s*status:\s*"?([^"\r\n]+)"?')
    $doneMatch = [regex]::Match($text, '(?m)^\s+suggest_done:\s*(true|false)\s*$')
    $doneReasonMatch = [regex]::Match($text, '(?m)^\s+done_reason:\s*(.+)$')

    $checkpointMap = [ordered]@{}
    $checkpointMatches = [regex]::Matches($text, '(?ms)^\s+(C\d+):\s*\r?\n\s+status:\s*([A-Za-z-]+)\s*$')
    foreach ($m in $checkpointMatches) {
        $checkpointMap[$m.Groups[1].Value] = $m.Groups[2].Value
    }

    $packetMeta.Add([PSCustomObject]@{
        Name = $packet.Name
        Turn = if ($turnMatch.Success) { [int]$turnMatch.Groups[1].Value } else { $null }
        From = if ($fromMatch.Success) { $fromMatch.Groups[1].Value.Trim() } else { $null }
        ContractStatus = if ($contractMatch.Success) { $contractMatch.Groups[1].Value.Trim() } else { $null }
        SuggestDone = if ($doneMatch.Success) { $doneMatch.Groups[1].Value -eq 'true' } else { $false }
        DoneReason = if ($doneReasonMatch.Success) { $doneReasonMatch.Groups[1].Value.Trim() } else { $null }
        Checkpoints = $checkpointMap
    }) | Out-Null
}

$packetMeta = $packetMeta | Sort-Object Turn, Name
$latestPacket = $packetMeta[-1]
$doneTrueCount = ($packetMeta | Where-Object { $_.SuggestDone }).Count

if (-not $SessionStatus) {
    if ($doneTrueCount -ge 2) {
        $SessionStatus = "converged"
    }
    else {
        $SessionStatus = "active"
    }
}

if (-not $ClosedReason -and $SessionStatus -ne "active") {
    if ($latestPacket.DoneReason) {
        $ClosedReason = $latestPacket.DoneReason
    }
    elseif ($SessionStatus -eq "converged") {
        $ClosedReason = "Inferred convergence from session packets: latest packet marked suggest_done and at least two packets requested closure."
    }
}

if (-not $Scope) {
    if ($state.scope) {
        $Scope = [string]$state.scope
    }
    else {
        $Scope = "medium"
    }
}

if (-not $Mode) {
    if ($state.mode) {
        $Mode = [string]$state.mode
    }
    else {
        $Mode = "hybrid"
    }
}

if ($MaxTurns -le 0) {
    if ($state.max_turns) {
        $MaxTurns = [int]$state.max_turns
    }
    else {
        switch ($Scope) {
            "small" { $MaxTurns = 2 }
            "medium" { $MaxTurns = 5 }
            "large" { $MaxTurns = 10 }
        }
    }
}

$summaryCandidates = Get-ChildItem -Path $sessionsRoot -File -Filter "*$SessionId*summary.md" -ErrorAction SilentlyContinue
foreach ($summary in $summaryCandidates) {
    Copy-Item -LiteralPath $summary.FullName -Destination (Join-Path $targetDir $summary.Name) -Force
    Copy-Item -LiteralPath $summary.FullName -Destination (Join-Path $targetDir "summary.md") -Force
}

if ($UpdateState -or $state.session_id -eq $SessionId) {
    Set-StateField -Object $state -Name "protocol_version" -Value "dad-v2"
    Set-StateField -Object $state -Name "session_id" -Value $SessionId
    Set-StateField -Object $state -Name "session_status" -Value $SessionStatus
    Set-StateField -Object $state -Name "superseded_by" -Value $(if ($SupersededBy) { $SupersededBy } else { $null })
    Set-StateField -Object $state -Name "closed_reason" -Value $ClosedReason
    Set-StateField -Object $state -Name "relay_mode" -Value "user-bridged"
    Set-StateField -Object $state -Name "mode" -Value $Mode
    Set-StateField -Object $state -Name "scope" -Value $Scope
    Set-StateField -Object $state -Name "current_turn" -Value $latestPacket.Turn
    Set-StateField -Object $state -Name "max_turns" -Value $MaxTurns
    Set-StateField -Object $state -Name "last_agent" -Value $latestPacket.From
    Set-StateField -Object $state -Name "contract_status" -Value $latestPacket.ContractStatus
    Set-StateField -Object $state -Name "contract_checkpoints" -Value $latestPacket.Checkpoints
    Set-StateField -Object $state -Name "packets" -Value @($migratedPacketRefs)
    $updatedJson = $state | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText($statePath, $updatedJson, (New-Object System.Text.UTF8Encoding($true)))
}

$sessionStatePath = Join-Path $targetDir "state.json"
$sessionState = [ordered]@{
    protocol_version = "dad-v2"
    session_id = $SessionId
    session_status = $SessionStatus
    superseded_by = if ($SupersededBy) { $SupersededBy } else { $null }
    closed_reason = $ClosedReason
    relay_mode = "user-bridged"
    mode = $Mode
    scope = $Scope
    current_turn = $latestPacket.Turn
    max_turns = $MaxTurns
    last_agent = $latestPacket.From
    contract_status = $latestPacket.ContractStatus
    contract_checkpoints = $latestPacket.Checkpoints
    packets = @($migratedPacketRefs)
    inferred_from_packets = $true
}
$sessionStateJson = $sessionState | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($sessionStatePath, $sessionStateJson, (New-Object System.Text.UTF8Encoding($true)))

Write-Output "Migrated session '$SessionId' to '$targetDir'."
if ($UpdateState -or $state.session_id -eq $SessionId) {
    Write-Output "Updated state.json packet references to session-scoped paths."
}
