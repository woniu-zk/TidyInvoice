param(
    [string]$RuntimeDir = "",
    [string]$PolicyPath = "",
    [switch]$DryRun,
    [string]$ReportPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir "..\.."))
$RuntimeSourcesPath = Join-Path $ScriptDir "runtime-sources.json"

function Resolve-RepoPath {
    param([string]$RelativePath)

    if ([System.IO.Path]::IsPathRooted($RelativePath)) {
        return [System.IO.Path]::GetFullPath($RelativePath)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $RelativePath))
}

function Get-PolicyArray {
    param(
        $Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return @()
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return @()
    }
    return @($property.Value)
}

function Get-EntrySizeBytes {
    param([string]$PathValue)

    if (-not (Test-Path -LiteralPath $PathValue)) {
        return [long]0
    }
    $item = Get-Item -LiteralPath $PathValue -Force
    if (-not $item.PSIsContainer) {
        return [long]$item.Length
    }
    $total = (Get-ChildItem -LiteralPath $PathValue -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    if ($null -eq $total) {
        return [long]0
    }
    return [long]$total
}

function Join-RuntimeRelativePath {
    param(
        [string]$RuntimeRoot,
        [string]$RelativePath
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        throw "WebView2 prune policy contains an empty relative path."
    }
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $RuntimeRoot $RelativePath))
    $rootWithSeparator = $RuntimeRoot.TrimEnd("\") + "\"
    if (-not $candidate.StartsWith($rootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to touch a path outside the WebView2 runtime: $RelativePath"
    }
    return $candidate
}

function Remove-PathWithRetry {
    param([string]$PathValue)

    for ($attempt = 1; $attempt -le 5; $attempt++) {
        if (-not (Test-Path -LiteralPath $PathValue)) {
            return
        }
        try {
            Remove-Item -LiteralPath $PathValue -Recurse -Force -ErrorAction Stop
        }
        catch {
            if ($attempt -ge 5) {
                throw
            }
            Start-Sleep -Milliseconds 500
        }
    }
}

function Get-MissingKeepEntries {
    param(
        [string]$RuntimeRoot,
        $Policy
    )

    $keep = if ($null -ne $Policy.PSObject.Properties["keep"]) { $Policy.keep } else { $null }
    $missing = New-Object System.Collections.ArrayList

    foreach ($relative in (Get-PolicyArray $keep "requiredFiles")) {
        $path = Join-RuntimeRelativePath -RuntimeRoot $RuntimeRoot -RelativePath ([string]$relative)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            [void]$missing.Add("file:$relative")
        }
    }
    foreach ($relative in (Get-PolicyArray $keep "requiredNestedFiles")) {
        $path = Join-RuntimeRelativePath -RuntimeRoot $RuntimeRoot -RelativePath ([string]$relative)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            [void]$missing.Add("file:$relative")
        }
    }
    foreach ($relative in (Get-PolicyArray $keep "requiredDirectories")) {
        $path = Join-RuntimeRelativePath -RuntimeRoot $RuntimeRoot -RelativePath ([string]$relative)
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            [void]$missing.Add("directory:$relative")
        }
    }

    return @($missing)
}

# ---------------------------------------------------------------------------
# Load the prune policy.
# ---------------------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($PolicyPath)) {
    $PolicyPath = Join-Path $ScriptDir "webview2-prune-policy.json"
}
$PolicyPath = Resolve-RepoPath $PolicyPath
if (-not (Test-Path -LiteralPath $PolicyPath -PathType Leaf)) {
    throw "WebView2 prune policy not found: $PolicyPath"
}
$policy = Get-Content -Raw -Encoding UTF8 $PolicyPath | ConvertFrom-Json

# ---------------------------------------------------------------------------
# Resolve the fixed WebView2 runtime directory.
# ---------------------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($RuntimeDir)) {
    if (-not (Test-Path -LiteralPath $RuntimeSourcesPath -PathType Leaf)) {
        throw "runtime-sources.json not found: $RuntimeSourcesPath"
    }
    $runtimeManifest = Get-Content -Raw -Encoding UTF8 $RuntimeSourcesPath | ConvertFrom-Json
    $RuntimeDir = [string]$runtimeManifest.webview2.runtime_dir
}
$RuntimeDir = Resolve-RepoPath $RuntimeDir

if (-not (Test-Path -LiteralPath $RuntimeDir -PathType Container)) {
    throw ("WebView2 runtime directory not found: {0}`nRun build\windows\prepare_runtime.ps1 to hydrate it first." -f $RuntimeDir)
}

$beforeBytes = Get-EntrySizeBytes -PathValue $RuntimeDir
$keep = if ($null -ne $policy.PSObject.Properties["keep"]) { $policy.keep } else { $null }
$prune = if ($null -ne $policy.PSObject.Properties["prune"]) { $policy.prune } else { $null }
$localeKeepFiles = @(Get-PolicyArray $keep "localeFiles")

# Never prune in a runtime that is already missing startup-critical entries: a
# partial hydration must fail loudly instead of producing a broken package.
$missingBefore = @(Get-MissingKeepEntries -RuntimeRoot $RuntimeDir -Policy $policy)
if ($missingBefore.Count -gt 0) {
    throw ("WebView2 runtime is missing startup-critical entries before pruning: {0}`nRe-run build\windows\prepare_runtime.ps1 -Force to re-hydrate the fixed runtime." -f ($missingBefore -join ", "))
}

# ---------------------------------------------------------------------------
# Build the conservative prune target list. Only explicit policy entries and
# non-kept locale files are candidates; unknown entries are always kept.
# ---------------------------------------------------------------------------
$requiredRelativePaths = New-Object System.Collections.ArrayList
foreach ($relative in (Get-PolicyArray $keep "requiredFiles")) { [void]$requiredRelativePaths.Add([string]$relative) }
foreach ($relative in (Get-PolicyArray $keep "requiredNestedFiles")) { [void]$requiredRelativePaths.Add([string]$relative) }

$targets = New-Object System.Collections.ArrayList

foreach ($relative in (Get-PolicyArray $prune "topLevelEntries")) {
    if ([string]::IsNullOrWhiteSpace([string]$relative)) {
        continue
    }
    $relativeText = ([string]$relative).Replace("/", "\")
    $targetPath = Join-RuntimeRelativePath -RuntimeRoot $RuntimeDir -RelativePath $relativeText
    if (Test-Path -LiteralPath $targetPath) {
        [void]$targets.Add([PSCustomObject]@{
                Path         = $targetPath
                RelativePath = $relativeText
                Kind         = "top-level"
                SizeBytes    = Get-EntrySizeBytes -PathValue $targetPath
            })
    }
}

foreach ($relative in (Get-PolicyArray $prune "nestedPaths")) {
    if ([string]::IsNullOrWhiteSpace([string]$relative)) {
        continue
    }
    $relativeText = ([string]$relative).Replace("/", "\")
    $targetPath = Join-RuntimeRelativePath -RuntimeRoot $RuntimeDir -RelativePath $relativeText
    if (Test-Path -LiteralPath $targetPath) {
        [void]$targets.Add([PSCustomObject]@{
                Path         = $targetPath
                RelativePath = $relativeText
                Kind         = "nested"
                SizeBytes    = Get-EntrySizeBytes -PathValue $targetPath
            })
    }
}

$localesDir = Join-Path $RuntimeDir "Locales"
if (Test-Path -LiteralPath $localesDir -PathType Container) {
    foreach ($localeFile in @(Get-ChildItem -LiteralPath $localesDir -File -Force)) {
        if ($localeKeepFiles -contains $localeFile.Name) {
            continue
        }
        [void]$targets.Add([PSCustomObject]@{
                Path         = $localeFile.FullName
                RelativePath = ("Locales\" + $localeFile.Name)
                Kind         = "locale"
                SizeBytes    = [long]$localeFile.Length
            })
    }
    foreach ($subDirectory in @(Get-ChildItem -LiteralPath $localesDir -Directory -Force)) {
        Write-Warning "Unexpected subdirectory inside Locales is kept untouched: $($subDirectory.Name)"
    }
}

# Defense in depth: a prune entry must never collide with a required keep entry.
foreach ($target in $targets) {
    if ($requiredRelativePaths -contains $target.RelativePath) {
        throw "WebView2 prune policy lists a required entry for deletion: $($target.RelativePath)"
    }
}

$candidateBytes = [long]0
foreach ($target in $targets) {
    $candidateBytes += [long]$target.SizeBytes
}
$localeTargets = @($targets | Where-Object { $_.Kind -eq "locale" })
$structuralTargets = @($targets | Where-Object { $_.Kind -ne "locale" })

Write-Host ("[prune] WebView2 runtime: {0}" -f $RuntimeDir)
Write-Host ("[prune] Current size: {0:N2} MB" -f ($beforeBytes / 1MB))
Write-Host ("[prune] Policy: {0}" -f $PolicyPath)
Write-Host ("[prune] Kept locale files: {0}" -f (($localeKeepFiles) -join ", "))

foreach ($target in $structuralTargets) {
    $verb = if ($DryRun) { "would remove" } else { "removing" }
    Write-Host ("[prune] {0} {1} ({2:N2} MB)" -f $verb, $target.RelativePath, ($target.SizeBytes / 1MB))
}
if ($localeTargets.Count -gt 0) {
    $verb = if ($DryRun) { "would remove" } else { "removing" }
    $localeBytes = [long]0
    foreach ($target in $localeTargets) { $localeBytes += [long]$target.SizeBytes }
    Write-Host ("[prune] {0} {1} non-kept locale file(s) ({2:N2} MB)" -f $verb, $localeTargets.Count, ($localeBytes / 1MB))
}

$removedCount = 0
if (-not $DryRun) {
    foreach ($target in $targets) {
        Remove-PathWithRetry -PathValue $target.Path
        if (Test-Path -LiteralPath $target.Path) {
            throw "Failed to prune WebView2 entry: $($target.Path)"
        }
        $removedCount += 1
    }
}

# ---------------------------------------------------------------------------
# Post-prune validation: startup-critical entries must still be present and the
# step must be idempotent (a second run finds nothing left to delete).
# ---------------------------------------------------------------------------
$missingAfter = @(Get-MissingKeepEntries -RuntimeRoot $RuntimeDir -Policy $policy)
if ($missingAfter.Count -gt 0) {
    throw ("WebView2 pruning removed startup-critical entries: {0}" -f ($missingAfter -join ", "))
}

if (-not $DryRun) {
    $leftover = @($targets | Where-Object { Test-Path -LiteralPath $_.Path })
    if ($leftover.Count -gt 0) {
        throw ("WebView2 pruning left {0} target(s) behind: {1}" -f $leftover.Count, (($leftover | ForEach-Object { $_.RelativePath }) -join ", "))
    }
}

$afterBytes = Get-EntrySizeBytes -PathValue $RuntimeDir
$summary = [ordered]@{
    schemaVersion           = 1
    dryRun                  = $DryRun.IsPresent
    runtimeDir              = $RuntimeDir
    policyPath              = $PolicyPath
    candidateCount          = $targets.Count
    candidateBytes          = $candidateBytes
    candidateMegabytes      = [math]::Round($candidateBytes / 1MB, 2)
    localeCandidateCount    = $localeTargets.Count
    structuralCandidateCount = $structuralTargets.Count
    removedCount            = $removedCount
    keptLocaleFiles         = @($localeKeepFiles)
    requiredEntriesVerified = $true
    beforeBytes             = $beforeBytes
    beforeMegabytes         = [math]::Round($beforeBytes / 1MB, 2)
    afterBytes              = $afterBytes
    afterMegabytes          = [math]::Round($afterBytes / 1MB, 2)
}

$expected = if ($null -ne $policy.PSObject.Properties["expected"]) { $policy.expected } else { $null }
if ($null -ne $expected -and $candidateBytes -gt 0) {
    $minBytes = [long]$expected.minBytesFreed
    if ($candidateBytes -lt $minBytes) {
        Write-Warning ("WebView2 prune step freed {0:N2} MB, below the expected minimum of {1:N2} MB. Re-check webview2-prune-policy.json against the current runtime payload." -f ($candidateBytes / 1MB), ($minBytes / 1MB))
    }
}

if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    $reportFullPath = Resolve-RepoPath $ReportPath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $reportFullPath) | Out-Null
    [System.IO.File]::WriteAllText(
        $reportFullPath,
        ($summary | ConvertTo-Json -Depth 6),
        (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Host ("[prune] Report: {0}" -f $reportFullPath)
}

if ($DryRun) {
    Write-Host ("[prune][dry-run] Would free {0:N2} MB across {1} entr(ies); no files were deleted." -f ($candidateBytes / 1MB), $targets.Count)
}
elseif ($targets.Count -eq 0) {
    Write-Host "[prune] WebView2 runtime is already pruned; nothing to remove (idempotent)."
}
else {
    Write-Host ("[prune] Removed {0} entr(ies), freed {1:N2} MB. Runtime is now {2:N2} MB." -f $removedCount, ($candidateBytes / 1MB), ($afterBytes / 1MB))
}
