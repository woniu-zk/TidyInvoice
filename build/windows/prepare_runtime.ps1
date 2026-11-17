param(
    [string]$PythonExe = ".\\.venv\\Scripts\\python.exe",
    [ValidateSet("fixed", "evergreen", "both")]
    [string]$WebView2Mode = "fixed",
    [switch]$SkipPlaywright,
    [switch]$SkipWebView2,
    [switch]$SkipWebView2Prune,
    [switch]$PruneDryRun,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir "..\\.."))
$RuntimeManifestPath = Join-Path $ScriptDir "runtime-sources.json"
$RuntimeManifest = Get-Content -Raw -Encoding UTF8 $RuntimeManifestPath | ConvertFrom-Json

function Resolve-RepoPath {
    param([string]$RelativePath)
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $RelativePath))
}

function Assert-LeafPathExists {
    param(
        [string]$PathValue,
        [string]$Label
    )

    if (-not (Test-Path $PathValue -PathType Leaf)) {
        throw "$Label not found: $PathValue"
    }
}

function Remove-PathIfExists {
    param([string]$PathValue)

    if (Test-Path $PathValue) {
        Remove-Item -LiteralPath $PathValue -Recurse -Force
    }
}

function New-CleanDirectory {
    param([string]$PathValue)

    Remove-PathIfExists -PathValue $PathValue
    New-Item -ItemType Directory -Force -Path $PathValue | Out-Null
}

function Assert-Hash {
    param(
        [string]$PathValue,
        [string]$ExpectedSha256
    )

    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $PathValue).Hash
    if ($actual -ne $ExpectedSha256) {
        throw "SHA256 mismatch for $PathValue. Expected $ExpectedSha256, got $actual"
    }
}

function Install-PlaywrightRuntime {
    param([string]$PythonExecutable)

    $playwrightRuntimeDir = Resolve-RepoPath $RuntimeManifest.playwright.runtime_dir
    $expectedEntries = @($RuntimeManifest.playwright.expected_entries)
    $needsInstall = $Force

    if (-not $needsInstall) {
        foreach ($entry in $expectedEntries) {
            if (-not (Test-Path (Join-Path $playwrightRuntimeDir $entry))) {
                $needsInstall = $true
                break
            }
        }
    }

    if (-not $needsInstall) {
        Write-Host "Playwright runtime already hydrated: $playwrightRuntimeDir"
        return
    }

    New-Item -ItemType Directory -Force -Path $playwrightRuntimeDir | Out-Null
    $env:PLAYWRIGHT_BROWSERS_PATH = $playwrightRuntimeDir
    & $PythonExecutable -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright runtime install failed with exit code $LASTEXITCODE"
    }
}

function Install-WebView2Runtime {
    $runtimeDir = Resolve-RepoPath $RuntimeManifest.webview2.runtime_dir
    $archivePath = Resolve-RepoPath $RuntimeManifest.webview2.archive_path
    $downloadUrl = [string]$RuntimeManifest.webview2.download_url
    $requiredFiles = @($RuntimeManifest.webview2.required_files)

    $needsInstall = $Force
    if (-not $needsInstall) {
        foreach ($entry in $requiredFiles) {
            if (-not (Test-Path (Join-Path $runtimeDir $entry))) {
                $needsInstall = $true
                break
            }
        }
    }

    if (-not $needsInstall) {
        Write-Host "WebView2 runtime already hydrated: $runtimeDir"
        return
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $archivePath) | Out-Null
    if ($Force -or -not (Test-Path $archivePath -PathType Leaf)) {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath
    }

    Assert-LeafPathExists -PathValue $archivePath -Label "WebView2 runtime archive"
    Assert-Hash -PathValue $archivePath -ExpectedSha256 ([string]$RuntimeManifest.webview2.archive_sha256)

    $extractDir = Join-Path (Split-Path -Parent $archivePath) "_webview2_extract"
    New-CleanDirectory -PathValue $extractDir
    New-CleanDirectory -PathValue $runtimeDir

    & expand.exe $archivePath -F:* $extractDir | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to extract WebView2 runtime archive"
    }

    $payloadRoot = $extractDir
    $topLevelEntries = @(Get-ChildItem -LiteralPath $extractDir -Force)
    if ($topLevelEntries.Count -eq 1 -and $topLevelEntries[0].PSIsContainer) {
        $payloadRoot = $topLevelEntries[0].FullName
    }
    foreach ($entry in Get-ChildItem -LiteralPath $payloadRoot -Force) {
        Copy-Item -LiteralPath $entry.FullName -Destination $runtimeDir -Recurse -Force
    }
    Remove-PathIfExists -PathValue $extractDir

    foreach ($entry in $requiredFiles) {
        if (-not (Test-Path (Join-Path $runtimeDir $entry))) {
            throw "Hydrated WebView2 runtime is missing required entry: $entry"
        }
    }
}

$resolvedPythonExe = if ([System.IO.Path]::IsPathRooted($PythonExe)) { $PythonExe } else { Resolve-RepoPath $PythonExe }
Assert-LeafPathExists -PathValue $resolvedPythonExe -Label "Python interpreter"

function Invoke-WebView2Prune {
    $pruneScriptPath = Join-Path $ScriptDir "prune_webview2_runtime.ps1"
    Assert-LeafPathExists -PathValue $pruneScriptPath -Label "WebView2 prune script"

    $policyRelative = [string]$RuntimeManifest.webview2.prune_policy
    if ([string]::IsNullOrWhiteSpace($policyRelative)) {
        $policyRelative = "build/windows/webview2-prune-policy.json"
    }
    $policyPath = Resolve-RepoPath $policyRelative
    Assert-LeafPathExists -PathValue $policyPath -Label "WebView2 prune policy"

    $runtimeDir = Resolve-RepoPath $RuntimeManifest.webview2.runtime_dir
    # Hashtable splatting keeps the parameters named; array splatting would pass
    # "-DryRun" as a positional value instead of binding the switch.
    $pruneArguments = @{
        RuntimeDir = $runtimeDir
        PolicyPath = $policyPath
    }
    if ($PruneDryRun) {
        $pruneArguments["DryRun"] = $true
        Write-Warning "WebView2 pruning is running in dry-run mode; no runtime files will be deleted."
    }

    & $pruneScriptPath @pruneArguments
}

function Install-WebView2Bootstrapper {
    # Evergreen builds rely on the machine-wide WebView2 runtime. Ship the small
    # Microsoft bootstrapper so a machine without WebView2 can install it on first
    # start instead of downloading the full fixed runtime into the installer.
    $relativePath = [string]$RuntimeManifest.webview2.bootstrapper.path
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        $relativePath = "build/runtime/MicrosoftEdgeWebView2Setup.exe"
    }
    $targetPath = Resolve-RepoPath $relativePath
    if (Test-Path $targetPath -PathType Leaf) {
        Write-Host "WebView2 bootstrapper already present: $targetPath"
        return
    }

    $downloadUrl = [string]$RuntimeManifest.webview2.bootstrapper.download_url
    if ([string]::IsNullOrWhiteSpace($downloadUrl)) {
        Write-Warning "WebView2 bootstrapper download URL is not configured; evergreen builds will rely on the system runtime."
        return
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetPath) | Out-Null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $downloadUrl -OutFile $targetPath -UseBasicParsing -TimeoutSec 120
        Write-Host "Downloaded WebView2 bootstrapper: $targetPath"
    }
    catch {
        Remove-Item -LiteralPath $targetPath -Force -ErrorAction SilentlyContinue
        Write-Warning "Could not download the WebView2 bootstrapper ($downloadUrl). Evergreen builds will rely on the system runtime. Error: $($_.Exception.Message)"
    }
}

if (-not $SkipPlaywright) {
    Install-PlaywrightRuntime -PythonExecutable $resolvedPythonExe
}

if (-not $SkipWebView2 -and ($WebView2Mode -eq "fixed" -or $WebView2Mode -eq "both")) {
    Install-WebView2Runtime
}

if (-not $SkipWebView2 -and ($WebView2Mode -eq "evergreen" -or $WebView2Mode -eq "both")) {
    Install-WebView2Bootstrapper
}

if (-not $SkipWebView2 -and $WebView2Mode -ne "evergreen" -and -not $SkipWebView2Prune) {
    Invoke-WebView2Prune
}

Write-Host "Runtime hydration completed (WebView2 mode: $WebView2Mode)."

