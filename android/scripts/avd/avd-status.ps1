. (Join-Path $PSScriptRoot "avd-common.ps1")

$sdk = Get-AndroidSdkDirectory
if ($sdk -and (Test-Path -LiteralPath $sdk)) {
    Write-Host "[OK] Android SDK: $sdk"
}
else {
    Write-Host "[WARN] Android SDK nicht gefunden."
}

$tools = @(
    @{ Name = "sdkmanager.bat"; Path = "cmdline-tools\latest\bin\sdkmanager.bat" },
    @{ Name = "avdmanager.bat"; Path = "cmdline-tools\latest\bin\avdmanager.bat" },
    @{ Name = "emulator.exe";   Path = "emulator\emulator.exe" },
    @{ Name = "adb.exe";        Path = "platform-tools\adb.exe" }
)

foreach ($tool in $tools) {
    try {
        $resolved = Get-SdkTool -Name $tool.Name -CandidateRelativePaths @($tool.Path)
        Write-Host "[OK] $($tool.Name): $resolved"
    }
    catch {
        Write-Host "[WARN] $($tool.Name) fehlt."
    }
}

foreach ($api in @(26, 36)) {
    $package = Get-AvdTargetPackage -Api $api
    $name = Get-DefaultAvdName -Api $api

    if (Test-SystemImageInstalled -Api $api) {
        Write-Host "[OK] Systemimage API ${api}: $package"
    }
    else {
        Write-Host "[WARN] Systemimage API ${api} fehlt: $package"
    }

    try {
        if (Test-AvdExists -Name $name) {
            Write-Host "[OK] AVD $name vorhanden."
        }
        else {
            Write-Host "[WARN] AVD $name fehlt."
        }
    }
    catch {
        Write-Host "[WARN] AVD-Prüfung fehlgeschlagen: $($_.Exception.Message)"
    }
}

try {
    $adb = Get-SdkTool -Name "adb.exe" -CandidateRelativePaths @("platform-tools\adb.exe")
    $devices = Invoke-Native -FilePath $adb -Arguments @("devices") -AllowFailure
    Write-Host ""
    Write-Host "adb devices:"
    Write-Host $devices.Output
}
catch {
    Write-Host "[WARN] adb devices konnte nicht ausgeführt werden: $($_.Exception.Message)"
}

Write-Host "avd-status: INFORMATIONEN ANGEZEIGT" -ForegroundColor Green
exit 0
