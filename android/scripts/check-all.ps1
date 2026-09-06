param(
    [string]$Tasks = ":app:assembleDebug :app:assembleRelease test detekt ktlintCheck lint :core:network:verifyWireDtos architectureTest uiTextCheck"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $projectRoot
$failures = [System.Collections.Generic.List[string]]::new()

function Invoke-GateStep {
    param(
        [string]$Label,
        [string[]]$Command
    )

    Write-Host ""
    Write-Host "== $Label =="
    & $Command[0] @($Command[1..($Command.Length - 1)])
    if ($LASTEXITCODE -ne 0) {
        throw "$Label fehlgeschlagen (Exit Code $LASTEXITCODE)"
    }
}

try {
    Invoke-GateStep -Label "1/5 bootstrap-check" -Command @("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "bootstrap-check.ps1"))

    Invoke-GateStep -Label "2/5 docs-check" -Command @("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "docs-check.ps1"))

    $pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe)) { $pythonExe = "python" }
    Invoke-GateStep -Label "3/5 portability-check" -Command @($pythonExe, (Join-Path $repoRoot "scripts\portability-check.py"), "--root", $repoRoot)

    Set-Location $projectRoot
    $gradle = Join-Path $projectRoot "gradlew.bat"
    Invoke-GateStep -Label "4/5 build-logic tests" -Command @($gradle, "-p", "build-logic", "test", "--no-daemon")

    $gradleArgs = @($Tasks -split "\s+") + @("--no-daemon")
    $gradleCommand = @($gradle) + $gradleArgs
    Invoke-GateStep -Label "5/5 Gradle ($Tasks)" -Command $gradleCommand

    Write-Host ""
    Write-Host "check-all: BESTANDEN" -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ""
    Write-Host "$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "check-all: FEHLGESCHLAGEN" -ForegroundColor Red
    exit 1
}
