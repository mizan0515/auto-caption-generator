param(
    [string]$Root = ".",
    [string]$SessionId,
    [switch]$AllSessions,
    [switch]$RequireDisconfirmation
)

$ErrorActionPreference = "Stop"

function Add-Issue {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Message
    )

    $List.Add($Message) | Out-Null
}

function Test-Regex {
    param(
        [string]$Text,
        [string]$Pattern
    )

    return [regex]::IsMatch($Text, $Pattern, [System.Text.RegularExpressions.RegexOptions]::Multiline)
}

function Get-RegexMatch {
    param(
        [string]$Text,
        [string]$Pattern
    )

    return [regex]::Match($Text, $Pattern, [System.Text.RegularExpressions.RegexOptions]::Multiline)
}

function Get-YamlChildBlock {
    param(
        [string]$Text,
        [string]$Key
    )

    $lines = $Text -split "`r?`n"
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $pattern = '^(?<indent>\s*)' + [regex]::Escape($Key) + ':\s*(?<inline>.*)$'
        $match = [regex]::Match($lines[$i], $pattern)
        if (-not $match.Success) {
            continue
        }

        $baseIndent = $match.Groups["indent"].Value.Length
        $blockLines = New-Object System.Collections.Generic.List[string]

        for ($j = $i + 1; $j -lt $lines.Count; $j++) {
            $line = $lines[$j]
            if ([string]::IsNullOrWhiteSpace($line)) {
                $blockLines.Add($line) | Out-Null
                continue
            }

            $lineIndent = ([regex]::Match($line, '^\s*')).Value.Length
            if ($lineIndent -le $baseIndent) {
                break
            }

            $blockLines.Add($line) | Out-Null
        }

        return [PSCustomObject]@{
            Found = $true
            Indent = $baseIndent
            InlineValue = $match.Groups["inline"].Value.Trim()
            Block = $blockLines -join "`n"
        }
    }

    return [PSCustomObject]@{
        Found = $false
        Indent = 0
        InlineValue = $null
        Block = ""
    }
}

function Get-PacketFiles {
    param(
        [string]$DialogueRoot
    )

    $files = New-Object System.Collections.Generic.List[string]

    $packetsDir = Join-Path $DialogueRoot "packets"
    if (Test-Path $packetsDir) {
        Get-ChildItem -Path $packetsDir -File -Filter "*.yaml" | ForEach-Object {
            $files.Add($_.FullName) | Out-Null
        }
    }

    $sessionsDir = Join-Path $DialogueRoot "sessions"
    if (Test-Path $sessionsDir) {
        Get-ChildItem -Path $sessionsDir -Recurse -File -Filter "turn-*.yaml" | ForEach-Object {
            $files.Add($_.FullName) | Out-Null
        }
    }

    return $files | Sort-Object -Unique
}

function Parse-PacketMetadata {
    param(
        [string]$Path,
        [string]$Text
    )

    $sessionMatch = Get-RegexMatch -Text $Text -Pattern '^session_id:\s*(?<value>[^\r\n]+?)\s*$'
    $turnMatch = Get-RegexMatch -Text $Text -Pattern '^turn:\s*(?<value>\d+)\s*$'
    $fromMatch = Get-RegexMatch -Text $Text -Pattern '^from:\s*(?<value>[^\r\n]+)\s*$'

    $sessionId = $null
    if ($sessionMatch.Success) {
        $sessionId = $sessionMatch.Groups["value"].Value.Trim()
        if ($sessionId.Length -ge 2 -and $sessionId.StartsWith('"') -and $sessionId.EndsWith('"')) {
            $sessionId = $sessionId.Substring(1, $sessionId.Length - 2)
        }
    }

    [PSCustomObject]@{
        Path = $Path
        SessionId = $sessionId
        Turn = if ($turnMatch.Success) { [int]$turnMatch.Groups["value"].Value } else { $null }
        From = if ($fromMatch.Success) { $fromMatch.Groups["value"].Value.Trim() } else { $null }
    }
}

function Get-CheckpointDescriptions {
    param(
        [string]$Text
    )

    $map = @{}
    $matches = [regex]::Matches($Text, '(?ms)^\s*-\s*id:\s*(C\d+)\s*\r?\n\s*description:\s*"([^"]+)"')
    foreach ($match in $matches) {
        $map[$match.Groups[1].Value] = $match.Groups[2].Value
    }

    return $map
}

function Test-RequiresDisconfirmation {
    param(
        [string]$Description
    )

    if ([string]::IsNullOrWhiteSpace($Description)) {
        return $false
    }

    $keywords = @(
        '정합', '일관', '동기화', '문서', 'wireframe', 'alignment', 'align',
        'consistent', 'consistency', 'density', '밀도', '같은', 'shared', 'sync',
        'match', 'same', 'category', 'wording', '용어'
    )

    foreach ($keyword in $keywords) {
        if ($Description -match [regex]::Escape($keyword)) {
            return $true
        }
    }

    return $false
}

function Validate-PacketFile {
    param(
        [string]$Path
    )

    $issues = New-Object System.Collections.Generic.List[string]
    $text = Get-Content -Path $Path -Raw -Encoding UTF8
    $descriptions = Get-CheckpointDescriptions -Text $text

    $requiredTopLevel = @(
        '^type:\s*turn\s*$',
        '^from:\s*.+$',
        '^turn:\s*\d+\s*$',
        '^session_id:\s*.+$',
        '^contract:\s*$',
        '^peer_review:\s*$',
        '^my_work:\s*$',
        '^handoff:\s*$'
    )

    foreach ($pattern in $requiredTopLevel) {
        if (-not (Test-Regex -Text $text -Pattern $pattern)) {
            Add-Issue -List $issues -Message "Missing required field/section matching pattern: $pattern"
        }
    }

    if (Test-Regex -Text $text -Pattern '^\s*self_work:\s*$') {
        Add-Issue -List $issues -Message "Found forbidden section 'self_work'. Use 'my_work'."
    }

    if (Test-Regex -Text $text -Pattern '^suggest_done:\s*(true|false)\s*$') {
        Add-Issue -List $issues -Message "Found forbidden root-level 'suggest_done'. Move it under handoff."
    }

    if (Test-Regex -Text $text -Pattern '^done_reason:\s*') {
        Add-Issue -List $issues -Message "Found forbidden root-level 'done_reason'. Move it under handoff."
    }

    $allowedStatuses = 'PASS|FAIL|FAIL-then-FIXED|FAIL-then-PASS'
    $checkpointResults = Get-YamlChildBlock -Text $text -Key 'checkpoint_results'
    $statusMatches = @()
    if ($checkpointResults.Found -and $checkpointResults.InlineValue -ne '{}') {
        $statusMatches = [regex]::Matches($checkpointResults.Block, '^\s+status:\s*(?<value>[A-Za-z-]+)\s*$', [System.Text.RegularExpressions.RegexOptions]::Multiline)
    }
    foreach ($match in $statusMatches) {
        $value = $match.Groups["value"].Value
        if ($value -notmatch "^($allowedStatuses)$") {
            Add-Issue -List $issues -Message "Unsupported checkpoint status '$value'."
        }
    }

    $handoffSuggest = Get-RegexMatch -Text $text -Pattern '^\s+suggest_done:\s*(?<value>true|false)\s*$'
    if ($handoffSuggest.Success -and $handoffSuggest.Groups["value"].Value -eq "true") {
        if (-not (Test-Regex -Text $text -Pattern '^\s+ready_for_peer_verification:\s*true\s*$')) {
            Add-Issue -List $issues -Message "handoff.suggest_done=true requires handoff.ready_for_peer_verification=true."
        }

        if (-not (Test-Regex -Text $text -Pattern '^\s+done_reason:\s*\S+')) {
            Add-Issue -List $issues -Message "handoff.suggest_done=true requires handoff.done_reason."
        }
    }

    $hasPassCheckpoint = $checkpointResults.Found -and [regex]::IsMatch($checkpointResults.Block, '^\s+status:\s*PASS\s*$', [System.Text.RegularExpressions.RegexOptions]::Multiline)
    if ($hasPassCheckpoint -and -not (Test-Regex -Text $text -Pattern '^\s+evidence:\s*$|^\s+evidence:\s*\S+')) {
        Add-Issue -List $issues -Message "PASS checkpoint exists without visible evidence block."
    }

    foreach ($checkpointId in $descriptions.Keys) {
        $statusPattern = '(?ms)^\s+' + [regex]::Escape($checkpointId) + ':\s*\r?\n(.*?)(?=^\s+C\d+:|^\s{1,2}\w|\Z)'
        $blockMatch = [regex]::Match($text, $statusPattern)
        if (-not $blockMatch.Success) {
            continue
        }

        $block = $blockMatch.Groups[1].Value
        $statusMatch = [regex]::Match($block, '(?m)^\s+status:\s*([A-Za-z-]+)\s*$')
        if (-not $statusMatch.Success) {
            continue
        }

        $status = $statusMatch.Groups[1].Value
        if ($status -ne 'PASS') {
            continue
        }

        if ($RequireDisconfirmation -and (Test-RequiresDisconfirmation -Description $descriptions[$checkpointId])) {
            $hasDisconfirmation = [regex]::IsMatch($block, '(?m)^\s+disconfirmation:\s*$') -and
                [regex]::IsMatch($block, '(?m)^\s+attempted:\s*true\s*$')
            if (-not $hasDisconfirmation) {
                Add-Issue -List $issues -Message "PASS checkpoint '$checkpointId' requires disconfirmation evidence based on its description."
            }
        }
    }

    return [PSCustomObject]@{
        Meta = Parse-PacketMetadata -Path $Path -Text $text
        Issues = $issues
    }
}

function Get-SessionPackets {
    param(
        [string]$SessionId,
        [System.Collections.Generic.List[object]]$PacketResults
    )

    return @(
        $PacketResults |
            Where-Object { $_.Meta.SessionId -eq $SessionId -and $_.Meta.Turn -ne $null } |
            Sort-Object { $_.Meta.Turn }, { $_.Meta.Path }
    )
}

function Validate-StateObject {
    param(
        [object]$State,
        [string]$Label,
        [System.Collections.Generic.List[object]]$PacketResults,
        [string]$ResolvedRoot,
        [string]$DialogueRoot,
        [switch]$SkipSummaryCheck
    )

    $issues = New-Object System.Collections.Generic.List[string]

    if (-not $State.protocol_version -or $State.protocol_version -ne "dad-v2") {
        Add-Issue -List $issues -Message "$Label protocol_version must be 'dad-v2'."
    }

    if ([string]::IsNullOrWhiteSpace([string]$State.session_id)) {
        Add-Issue -List $issues -Message "$Label is missing session_id."
        return $issues
    }

    $allowedSessionStatus = @("active", "converged", "superseded", "abandoned")
    if (-not $State.session_status -or $allowedSessionStatus -notcontains [string]$State.session_status) {
        Add-Issue -List $issues -Message "$Label session_status must be one of: $($allowedSessionStatus -join ', ')."
    }

    if ([string]::IsNullOrWhiteSpace([string]$State.relay_mode)) {
        Add-Issue -List $issues -Message "$Label is missing relay_mode."
    }
    elseif ([string]$State.relay_mode -ne "user-bridged") {
        Add-Issue -List $issues -Message "$Label relay_mode must be 'user-bridged'."
    }

    $allowedContractStatuses = @("proposed", "accepted", "amended")
    if ([string]::IsNullOrWhiteSpace([string]$State.contract_status)) {
        Add-Issue -List $issues -Message "$Label is missing contract_status."
    }
    elseif ($allowedContractStatuses -notcontains [string]$State.contract_status) {
        Add-Issue -List $issues -Message "$Label contract_status '$($State.contract_status)' must be one of: $($allowedContractStatuses -join ', ')."
    }

    $allowedModes = @("autonomous", "hybrid", "supervised")
    if ([string]::IsNullOrWhiteSpace([string]$State.mode)) {
        Add-Issue -List $issues -Message "$Label is missing mode."
    }
    elseif ($allowedModes -notcontains [string]$State.mode) {
        Add-Issue -List $issues -Message "$Label mode '$($State.mode)' must be one of: $($allowedModes -join ', ')."
    }

    $allowedScopes = @("small", "medium", "large")
    if ([string]::IsNullOrWhiteSpace([string]$State.scope)) {
        Add-Issue -List $issues -Message "$Label is missing scope."
    }
    elseif ($allowedScopes -notcontains [string]$State.scope) {
        Add-Issue -List $issues -Message "$Label scope '$($State.scope)' must be one of: $($allowedScopes -join ', ')."
    }

    if ($null -eq $State.current_turn) {
        Add-Issue -List $issues -Message "$Label is missing current_turn."
    }
    elseif ([int]$State.current_turn -lt 0) {
        Add-Issue -List $issues -Message "$Label current_turn must be >= 0."
    }

    if ($null -eq $State.max_turns) {
        Add-Issue -List $issues -Message "$Label is missing max_turns."
    }
    elseif ([int]$State.max_turns -le 0) {
        Add-Issue -List $issues -Message "$Label max_turns must be > 0."
    }

    if ($State.last_agent -and @("codex", "claude-code") -notcontains [string]$State.last_agent) {
        Add-Issue -List $issues -Message "$Label last_agent '$($State.last_agent)' must be one of: codex, claude-code."
    }

    if ($null -eq $State.packets) {
        Add-Issue -List $issues -Message "$Label is missing packets."
    }
    else {
        foreach ($packetRef in @($State.packets)) {
            $resolvedPacketPath = Join-Path $ResolvedRoot $packetRef
            if (-not (Test-Path $resolvedPacketPath)) {
                Add-Issue -List $issues -Message "$Label references missing packet path: $packetRef"
            }
        }
    }

    $sessionPackets = @(Get-SessionPackets -SessionId ([string]$State.session_id) -PacketResults $PacketResults)
    if ($sessionPackets.Count -gt 0) {
        $latestPacket = $sessionPackets[-1].Meta

        if ([int]$State.current_turn -ne $latestPacket.Turn) {
            Add-Issue -List $issues -Message "$Label current_turn=$($State.current_turn) does not match latest packet turn=$($latestPacket.Turn) for session '$($State.session_id)'."
        }

        if ([string]$State.last_agent -ne $latestPacket.From) {
            Add-Issue -List $issues -Message "$Label last_agent='$($State.last_agent)' does not match latest packet from='$($latestPacket.From)'."
        }
    }
    elseif (([int]$State.current_turn -gt 0) -or ($State.packets -and @($State.packets).Count -gt 0)) {
        Add-Issue -List $issues -Message "$Label has no packets for target session '$($State.session_id)'."
    }

    if ($State.session_status -ne "active" -and [string]::IsNullOrWhiteSpace([string]$State.closed_reason)) {
        Add-Issue -List $issues -Message "$Label closed_reason is required when session_status is '$($State.session_status)'."
    }

    if ($State.session_status -eq "superseded" -and [string]::IsNullOrWhiteSpace([string]$State.superseded_by)) {
        Add-Issue -List $issues -Message "$Label superseded_by is required when session_status='superseded'."
    }

    if (-not $SkipSummaryCheck -and $State.session_status -ne "active") {
        $sessionDir = Join-Path (Join-Path $DialogueRoot "sessions") ([string]$State.session_id)
        if (-not (Test-Path $sessionDir)) {
            Add-Issue -List $issues -Message "$Label session directory not found: $sessionDir"
        }
        else {
            if (-not (Test-Path (Join-Path $sessionDir "summary.md"))) {
                Add-Issue -List $issues -Message "$Label is missing session summary.md."
            }

            $namedSummaries = Get-ChildItem -Path $sessionDir -File -Filter "*-$($State.session_id)-summary.md" -ErrorAction SilentlyContinue
            if (-not $namedSummaries) {
                Add-Issue -List $issues -Message "$Label is missing named closed-session summary (*-$($State.session_id)-summary.md)."
            }
        }
    }

    return $issues
}

$resolvedRoot = (Resolve-Path $Root).Path
$dialogueRoot = Join-Path $resolvedRoot "Document\dialogue"
$rootStatePath = Join-Path $dialogueRoot "state.json"
$packetFiles = Get-PacketFiles -DialogueRoot $dialogueRoot
$sessionStateFiles = @(Get-ChildItem -Path (Join-Path $dialogueRoot "sessions") -Recurse -File -Filter "state.json" -ErrorAction SilentlyContinue)

if (-not (Test-Path $rootStatePath)) {
    if (($packetFiles.Count -eq 0) -and ($sessionStateFiles.Count -eq 0)) {
        Write-Host "No live DAD sessions found under Document/dialogue. Packet validation skipped."
        return
    }

    throw "state.json not found: $rootStatePath"
}

$statePath = $rootStatePath
$state = Get-Content -Path $rootStatePath -Raw -Encoding UTF8 | ConvertFrom-Json

# F3: valid intermediate state -- session created but no turns yet.
# Skip unless -SessionId targets a specific (potentially older) session,
# or packet files exist elsewhere (e.g., historical sessions under sessions/).
if ($state.session_status -eq "active" -and $state.current_turn -eq 0 -and (-not $state.packets -or @($state.packets).Count -eq 0)) {
    if ((-not $SessionId) -and ($packetFiles.Count -eq 0)) {
        Write-Host "Session initialized but no turns yet. Validation skipped."
        return
    }
}

if ($SessionId) {
    $sessionStatePath = Join-Path $dialogueRoot ("sessions\" + $SessionId + "\state.json")
    if (Test-Path $sessionStatePath) {
        $statePath = $sessionStatePath
        $state = Get-Content -Path $sessionStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
}
$allIssues = New-Object System.Collections.Generic.List[string]
$packetResults = New-Object System.Collections.Generic.List[object]

if (-not $packetFiles -or $packetFiles.Count -eq 0) {
    Add-Issue -List $allIssues -Message "No packet files found under Document/dialogue."
}

foreach ($packet in $packetFiles) {
    $result = Validate-PacketFile -Path $packet
    $target = if ($SessionId) { $SessionId } elseif ($AllSessions) { $null } else { $state.session_id }
    if ($target -and $result.Meta.SessionId -ne $target) {
        continue
    }

    $packetResults.Add($result) | Out-Null

    foreach ($issue in $result.Issues) {
        Add-Issue -List $allIssues -Message "$($result.Meta.Path): $issue"
    }
}

$stateTargets = New-Object System.Collections.Generic.List[object]

if ($AllSessions) {
    $stateTargets.Add([PSCustomObject]@{
        Label = "root state.json"
        State = $state
        SkipSummaryCheck = $true
    }) | Out-Null

    foreach ($sessionStateFile in $sessionStateFiles | Sort-Object FullName) {
        $sessionState = Get-Content -Path $sessionStateFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $relativeLabel = $sessionStateFile.FullName.Substring($resolvedRoot.Length + 1).Replace('\', '/')
        $stateTargets.Add([PSCustomObject]@{
            Label = $relativeLabel
            State = $sessionState
            SkipSummaryCheck = $false
        }) | Out-Null
    }
}
elseif ($SessionId) {
    $sessionStatePath = Join-Path $dialogueRoot ("sessions\" + $SessionId + "\state.json")
    if (Test-Path $sessionStatePath) {
        $sessionState = Get-Content -Path $sessionStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $stateTargets.Add([PSCustomObject]@{
            Label = "sessions/$SessionId/state.json"
            State = $sessionState
            SkipSummaryCheck = $false
        }) | Out-Null
    }
    else {
        $stateTargets.Add([PSCustomObject]@{
            Label = "root state.json"
            State = $state
            SkipSummaryCheck = $false
        }) | Out-Null
    }
}
else {
    $stateTargets.Add([PSCustomObject]@{
        Label = "root state.json"
        State = $state
        SkipSummaryCheck = $false
    }) | Out-Null

    if (-not [string]::IsNullOrWhiteSpace([string]$state.session_id)) {
        $currentSessionStatePath = Join-Path $dialogueRoot ("sessions\" + $state.session_id + "\state.json")
        if (Test-Path $currentSessionStatePath) {
            $sessionState = Get-Content -Path $currentSessionStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $stateTargets.Add([PSCustomObject]@{
                Label = "sessions/$($state.session_id)/state.json"
                State = $sessionState
                SkipSummaryCheck = $false
            }) | Out-Null
        }
    }
}

foreach ($stateTarget in $stateTargets) {
    $stateIssues = Validate-StateObject `
        -State $stateTarget.State `
        -Label $stateTarget.Label `
        -PacketResults $packetResults `
        -ResolvedRoot $resolvedRoot `
        -DialogueRoot $dialogueRoot `
        -SkipSummaryCheck:([bool]$stateTarget.SkipSummaryCheck)

    foreach ($issue in $stateIssues) {
        Add-Issue -List $allIssues -Message $issue
    }
}

if ($allIssues.Count -gt 0) {
    Write-Output "DAD packet/state validation failed:"
    foreach ($issue in $allIssues) {
        Write-Output "- $issue"
    }
    exit 1
}

if ($AllSessions) {
    Write-Output "DAD packet/state validation passed for all scanned sessions."
}
else {
    $targetSessionId = if ($SessionId) { $SessionId } else { $state.session_id }
    Write-Output "DAD packet/state validation passed for session '$targetSessionId'."
}
