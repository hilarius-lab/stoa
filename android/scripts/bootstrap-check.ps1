$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

function Test-Requirement {
    param(
        [string]$Name,
        [scriptblock]$Test,
        [string]$Detail
    )
    $ok = & $Test
    if ($ok) {
        Write-Host "[PASS] $Name"
    } else {
        Write-Host "[FAIL] ${Name}: $Detail"
        $script:failures.Add($Name)
    }
}

function Test-OptionalRequirement {
    param(
        [string]$Name,
        [scriptblock]$Test,
        [string]$Detail
    )
    $ok = & $Test
    if ($ok) {
        Write-Host "[PASS] $Name (optional)"
    } else {
        Write-Host "[WARN] ${Name} fehlt: $Detail"
        $script:warnings.Add($Name)
    }
}

$javaExe = $null
if ($env:JAVA_HOME) {
    $candidate = Join-Path $env:JAVA_HOME "bin\java.exe"
    if (Test-Path $candidate) { $javaExe = $candidate }
}

$javaVersion = ""
if ($javaExe) {
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $javaVersion = (& $javaExe -version 2>&1 | Out-String)
    $ErrorActionPreference = $previousEap
}

Test-Requirement "JDK 21 (JAVA_HOME)" { $javaVersion -match 'version "21\.' } "JAVA_HOME zeigt nicht auf eine JDK 21 (aktuell: $javaVersion)"

$sdkDir = $null
if ($env:ANDROID_HOME) { $sdkDir = $env:ANDROID_HOME }
$localProps = Join-Path $projectRoot "local.properties"
if (-not $sdkDir -and (Test-Path $localProps)) {
    $line = Get-Content $localProps | Where-Object { $_ -match "^sdk\.dir=" } | Select-Object -First 1
    if ($line) { $sdkDir = ($line -split "=", 2)[1].Trim().Trim('"') }
}

Test-Requirement "Android SDK-Pfad" { -not [string]::IsNullOrWhiteSpace($sdkDir) -and (Test-Path $sdkDir) } "Weder ANDROID_HOME noch sdk.dir in local.properties gesetzt oder Pfad existiert nicht"

if ($sdkDir) {
    Test-Requirement "Platform android-36" { Test-Path (Join-Path $sdkDir "platforms\android-36") } 'Installation: sdkmanager "platforms;android-36"'
    Test-Requirement "Platform android-37.1 (compileSdk)" { Test-Path (Join-Path $sdkDir "platforms\android-37.1") } 'Installation: sdkmanager "platforms;android-37.1"'
    $buildTools36 = Get-ChildItem -Path (Join-Path $sdkDir "build-tools") -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "^36\." }
    Test-Requirement "Build-Tools 36.x" { $null -ne $buildTools36 } 'Installation: sdkmanager "build-tools;36.1.0"'
    Test-OptionalRequirement "platform-tools" { Test-Path (Join-Path $sdkDir "platform-tools\adb.exe") } 'Installation: sdkmanager "platform-tools"'
    Test-Requirement "SDK-Lizenzen" { (Get-ChildItem -Path (Join-Path $sdkDir "licenses") -Filter "android-sdk*" -ErrorAction SilentlyContinue) -ne $null } "Ausführen: sdkmanager --licenses"
    Test-OptionalRequirement "Emulator" { Test-Path (Join-Path $sdkDir "emulator\emulator.exe") } 'Installation: sdkmanager "emulator"'
    Test-OptionalRequirement "Systemimage API 26 (google_apis/x86_64)" {
        Test-Path (Join-Path $sdkDir "system-images\android-26\google_apis\x86_64\system.img")
    } 'Installation: scripts\avd\avd-setup.ps1 -Api 26'
    Test-OptionalRequirement "Systemimage API 36 (google_apis/x86_64)" {
        Test-Path (Join-Path $sdkDir "system-images\android-36\google_apis\x86_64\system.img")
    } 'Installation: scripts\avd\avd-setup.ps1 -Api 36'
    Test-OptionalRequirement "AVD SmartNotebookApi26" {
        Test-Path (Join-Path $env:USERPROFILE ".android\avd\SmartNotebookApi26.avd\config.ini")
    } 'Erstellung: scripts\avd\avd-setup.ps1 -Api 26'
    Test-OptionalRequirement "AVD SmartNotebookApi36" {
        Test-Path (Join-Path $env:USERPROFILE ".android\avd\SmartNotebookApi36.avd\config.ini")
    } 'Erstellung: scripts\avd\avd-setup.ps1 -Api 36'
}

Test-Requirement "Gradle Wrapper" { (Test-Path (Join-Path $projectRoot "gradlew.bat")) -and (Test-Path (Join-Path $projectRoot "gradle\wrapper\gradle-wrapper.jar")) } "Ausführen: gradle wrapper --gradle-version 9.7.1"

Write-Host ""
foreach ($warning in $warnings) {
    Write-Host "[WARN] $warning ist optional für JVM-Prüfungen, aber für Emulator- oder Instrumentationstests erforderlich." -ForegroundColor Yellow
}

if ($failures.Count -eq 0) {
    Write-Host "Bootstrap-Check: ALLE PRUEFUNGEN BESTANDEN" -ForegroundColor Green
    exit 0
} else {
    Write-Host "Bootstrap-Check: $($failures.Count) FEHLGESCHLAGENE PRUEFUNGEN: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}
