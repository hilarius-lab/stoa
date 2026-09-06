param(
    [int[]]$Api = @(26, 36),
    [string]$Tasks = "connectedCheck",
    [switch]$Headless,
    [switch]$KeepRunning,
    [int]$BootTimeoutSeconds = 300,
    [string]$PreInstallTask = "",
    [string]$PreInstallApkDirectory = "",
    [switch]$GrantAllPermissions
)

. (Join-Path $PSScriptRoot "avd-common.ps1")
. (Join-Path $PSScriptRoot "avd-device.ps1")

$gradleTasks = @($Tasks -split "\s+")
$failures = [System.Collections.Generic.List[string]]::new()

foreach ($apiLevel in $Api) {
    $name = Get-DefaultAvdName -Api $apiLevel

    try {
        if (-not (Test-AvdExists -Name $name)) {
            Write-Host "AVD $name fehlt und wird durch avd-setup.ps1 vorbereitet."
            $setupScript = Join-Path $PSScriptRoot "avd-setup.ps1"
            $setup = Invoke-Native -FilePath "powershell" -Arguments @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $setupScript, "-Api", "$apiLevel"
            ) -AllowFailure
            if ($setup.ExitCode -ne 0) {
                throw "AVD-Setup fehlgeschlagen: $($setup.Output)"
            }
        }

        $session = Start-Avd -Name $name -Headless:$Headless -BootTimeoutSeconds $BootTimeoutSeconds
        $previousSerial = $env:ANDROID_SERIAL
        $env:ANDROID_SERIAL = $session.Serial

        try {
            if ($GrantAllPermissions) {
                if (-not $PreInstallTask -or -not $PreInstallApkDirectory) {
                    throw "-GrantAllPermissions erfordert -PreInstallTask und -PreInstallApkDirectory."
                }

                $preInstallGradle = Join-Path $script:AvdProjectRoot "gradlew.bat"
                $preInstall = Invoke-Native -FilePath $preInstallGradle -Arguments @($PreInstallTask, "--no-daemon") -AllowFailure
                if ($preInstall.ExitCode -ne 0) {
                    throw "Pre-Install-Build fehlgeschlagen (Exit Code $($preInstall.ExitCode)): $($preInstall.Output)"
                }

                $apkDirectory = Join-Path $script:AvdProjectRoot $PreInstallApkDirectory
                $apk = Get-ChildItem -LiteralPath $apkDirectory -Filter "*.apk" -File -ErrorAction Stop |
                    Select-Object -First 1
                if (-not $apk) {
                    throw "Android-Test-APK nicht gefunden in $PreInstallApkDirectory"
                }

                $adb = Get-SdkTool -Name "adb.exe" -CandidateRelativePaths @("platform-tools\adb.exe")
                $grant = Invoke-Native -FilePath $adb -Arguments @(
                    "-s", $session.Serial, "install", "-r", "-g", $apk.FullName
                ) -AllowFailure
                if ($grant.ExitCode -ne 0 -or $grant.Output -notmatch "Success") {
                    throw "Test-APK-Installation mit Runtime-Permissions fehlgeschlagen: $($grant.Output)"
                }

                Write-Host "[OK] Runtime-Permissions für $name vorinstalliert."
            }

            Write-Host "[INFO] Führe Gradle-Tasks aus: $($gradleTasks -join ' ')"
            $gradle = Join-Path $script:AvdProjectRoot "gradlew.bat"
            $result = Invoke-Native -FilePath $gradle -Arguments ($gradleTasks + @("--no-daemon")) -AllowFailure
            if ($result.ExitCode -ne 0) {
                throw "Gradle-Tasks fehlgeschlagen (Exit Code $($result.ExitCode)): $($result.Output)"
            }

            Write-Host "[OK] Instrumentation für $name - $($gradleTasks -join ' ')"
        }
        finally {
            if ($previousSerial) {
                $env:ANDROID_SERIAL = $previousSerial
            }
            else {
                Remove-Item Env:ANDROID_SERIAL -ErrorAction SilentlyContinue
            }

            if (-not $KeepRunning -and $session.Started) {
                Stop-Avd -Serial $session.Serial
                Write-Host "[OK] Emulator $name gestoppt."
            }
        }
    }
    catch {
        $failures.Add("API ${apiLevel}: $($_.Exception.Message)")
    }
}

if ($failures.Count -eq 0) {
    Write-Host "avd-instrumentation: BESTANDEN" -ForegroundColor Green
    exit 0
}

foreach ($failure in $failures) {
    Write-Host "[FAIL] $failure" -ForegroundColor Red
}
Write-Host "avd-instrumentation: FEHLGESCHLAGEN" -ForegroundColor Red
exit 1
