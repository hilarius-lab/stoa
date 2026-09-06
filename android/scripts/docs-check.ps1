param(
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

$requiredDocs = @(
    "README.md",
    "docs\ARCHITECTURE.md",
    "docs\SETUP_WIZARD.md",
    "docs\API_INTEGRATION.md",
    "docs\AUDIO_PIPELINE.md",
    "docs\OFFLINE_SYNC.md",
    "docs\SERVER_DRIVEN_UI.md",
    "docs\SECURITY_AND_PRIVACY.md",
    "docs\TESTING.md",
    "docs\OPERATIONS.md",
    "docs\DEPENDENCIES.md",
    "CHANGELOG.md"
)

Write-Host "== Pflichtdokumente (S14) =="
foreach ($doc in $requiredDocs) {
    $path = Join-Path $projectRoot $doc
    if (Test-Path $path) {
        Write-Host "[OK]   $doc"
    } elseif ($Strict) {
        Write-Host "[FAIL] $doc fehlt"
        $failures.Add("Pflichtdokument fehlt: $doc")
    } else {
        Write-Host "[WARN] $doc fehlt (erst mit -Strict hartes Gate)"
        $warnings.Add("Pflichtdokument fehlt: $doc")
    }
}

if (-not (Test-Path (Join-Path $projectRoot "docs\adr"))) {
    $message = "ADR-Verzeichnis fehlt: docs\adr"
    if ($Strict) {
        Write-Host "[FAIL] $message"
        $failures.Add($message)
    } else {
        Write-Host "[WARN] $message"
        $warnings.Add($message)
    }
} else {
    Write-Host "[OK]   docs\adr"
}

Write-Host ""
Write-Host "== Relative Markdown-Links =="

$markdownFiles = Get-ChildItem -Path (Join-Path $projectRoot "docs") -Recurse -Filter "*.md"
$markdownFiles += Get-Item (Join-Path $projectRoot "README.md") -ErrorAction SilentlyContinue

$brokenLinks = 0
foreach ($file in $markdownFiles) {
    if ($null -eq $file -or -not (Test-Path $file.FullName)) { continue }
    $dir = Split-Path -Parent $file.FullName
    $content = Get-Content $file.FullName -Raw
    $matches = [regex]::Matches($content, '\[[^\]]*\]\(([^)]+)\)')
    foreach ($match in $matches) {
        $target = $match.Groups[1].Value.Trim()
        if ($target -match '^(https?:)?//' -or $target.StartsWith('#') -or $target.StartsWith('mailto:')) {
            continue
        }
        $hashIndex = $target.IndexOf('#')
        if ($hashIndex -ge 0) { $target = $target.Substring(0, $hashIndex) }
        if ($target -eq '' -or $target.StartsWith('#')) { continue }
        $resolved = Join-Path $dir $target
        if (-not (Test-Path $resolved)) {
            Write-Host "[FAIL] $($file.FullName.Replace($projectRoot, '')) -> $target"
            $brokenLinks++
        }
    }
}

if ($brokenLinks -eq 0) {
    Write-Host "[OK]   keine gebrochenen relativen Links"
} else {
    $failures.Add("$brokenLinks gebrochene relative Markdown-Links")
}

Write-Host ""
foreach ($warning in $warnings) {
    Write-Host "[WARN] $warning" -ForegroundColor Yellow
}

if ($failures.Count -eq 0) {
    Write-Host "Docs-Check: BESTANDEN" -ForegroundColor Green
    exit 0
} else {
    foreach ($failure in $failures) {
        Write-Host "[FAIL] $failure" -ForegroundColor Red
    }
    Write-Host "Docs-Check: FEHLGESCHLAGEN" -ForegroundColor Red
    exit 1
}
