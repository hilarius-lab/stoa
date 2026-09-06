function Get-RunningAvdSerial {
    param(
        [string]$Adb,
        [string]$AvdName
    )

    $result = Invoke-Native -FilePath $Adb -Arguments @("devices") -AllowFailure
    foreach ($line in ($result.Output -split "`n")) {
        $parts = $line.Trim() -split "\s+"
        if ($parts.Count -lt 2 -or $parts[1] -ne "device") { continue }

        $candidate = $parts[0]
        $current = Invoke-Native -FilePath $Adb -Arguments @("-s", $candidate, "shell", "getprop", "ro.boot.qemu.avd_name") -AllowFailure
        $name = $current.Output.Trim()

        if ([string]::IsNullOrWhiteSpace($name)) {
            $emuName = Invoke-Native -FilePath $Adb -Arguments @("-s", $candidate, "emu", "avd", "name") -AllowFailure
            $name = ($emuName.Output -split "\r?\n" | Where-Object { $_.Trim() } | Select-Object -First 1).Trim()
        }

        if ($name -eq $AvdName) {
            return $candidate
        }
    }

    return $null
}

function Wait-ForAvdBoot {
    param(
        [string]$Adb,
        [string]$AvdName,
        [int]$TimeoutSeconds = 300
    )

    $deadline = [DateTime]::Now.AddSeconds($TimeoutSeconds)
    while ([DateTime]::Now -lt $deadline) {
        $serial = Get-RunningAvdSerial -Adb $Adb -AvdName $AvdName
        if ($serial) {
            $boot = Invoke-Native -FilePath $Adb -Arguments @("-s", $serial, "shell", "getprop", "sys.boot_completed") -AllowFailure
            if ($boot.Output.Trim() -eq "1") {
                return $serial
            }
        }
        Start-Sleep -Seconds 5
    }

    return $null
}

function Start-Avd {
    param(
        [string]$Name,
        [switch]$Headless,
        [int]$BootTimeoutSeconds = 300
    )

    $sdk = Get-AndroidSdkDirectory
    if ($sdk) {
        [System.Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", $sdk, "Process")
    }

    $adb = Get-SdkTool -Name "adb.exe" -CandidateRelativePaths @("platform-tools\adb.exe")
    $existing = Get-RunningAvdSerial -Adb $adb -AvdName $Name

    if ($existing) {
        $serial = Wait-ForAvdBoot -Adb $adb -AvdName $Name -TimeoutSeconds $BootTimeoutSeconds
        if (-not $serial) {
            throw "AVD $Name ist verbunden, aber der Boot wurde innerhalb von $BootTimeoutSeconds Sekunden nicht bestätigt."
        }
        return [pscustomobject]@{
            Serial  = $serial
            Started = $false
        }
    }

    $emulator = Get-SdkTool -Name "emulator.exe" -CandidateRelativePaths @("emulator\emulator.exe")
    $arguments = @("-avd", $Name, "-no-boot-anim", "-no-audio", "-gpu", "auto")
    if ($Headless) {
        $arguments += "-no-window"
    }

    Write-Host "Starte Emulator: $Name"
    $tempDirectory = [System.IO.Path]::GetTempPath()
    $stamp = [DateTime]::Now.ToString("yyyyMMddHHmmss")
    $logFile = Join-Path $tempDirectory "smart-notebook-avd-$Name-$stamp-$PID.out.log"
    $errorFile = Join-Path $tempDirectory "smart-notebook-avd-$Name-$stamp-$PID.err.log"
    Start-Process -FilePath $emulator -ArgumentList $arguments -NoNewWindow -RedirectStandardOutput $logFile -RedirectStandardError $errorFile | Out-Null

    $serial = Wait-ForAvdBoot -Adb $adb -AvdName $Name -TimeoutSeconds $BootTimeoutSeconds
    if (-not $serial) {
        throw "AVD $Name war innerhalb von $BootTimeoutSeconds Sekunden nicht bootet."
    }

    return [pscustomobject]@{
        Serial  = $serial
        Started = $true
    }
}

function Stop-Avd {
    param([string]$Serial)

    if ([string]::IsNullOrWhiteSpace($Serial)) { return }

    $adb = Get-SdkTool -Name "adb.exe" -CandidateRelativePaths @("platform-tools\adb.exe")
    $result = Invoke-Native -FilePath $adb -Arguments @("-s", $Serial, "emu", "kill") -AllowFailure
    if ($result.ExitCode -ne 0) {
        throw "AVD $Serial konnte nicht gestoppt werden: $($result.Output)"
    }
}

function Install-DebugApk {
    param(
        [string]$Serial,
        [string]$ApkPath,
        [switch]$Build
    )

    if ([string]::IsNullOrWhiteSpace($ApkPath)) {
        $ApkPath = Join-Path $script:AvdProjectRoot "app\build\outputs\apk\debug\app-debug.apk"
    }

    if (-not (Test-Path -LiteralPath $ApkPath)) {
        if ($Build) {
            $gradle = Join-Path $script:AvdProjectRoot "gradlew.bat"
            $build = Invoke-Native -FilePath $gradle -Arguments @(":app:assembleDebug") -AllowFailure
            if ($build.ExitCode -ne 0) {
                throw "Debug-Build fehlgeschlagen: $($build.Output)"
            }
        }

        if (-not (Test-Path -LiteralPath $ApkPath)) {
            throw "Debug-APK fehlt. Erst .\gradlew :app:assembleDebug ausführen oder -Build setzen."
        }
    }

    $adb = Get-SdkTool -Name "adb.exe" -CandidateRelativePaths @("platform-tools\adb.exe")
    $result = Invoke-Native -FilePath $adb -Arguments @("-s", $Serial, "install", "-r", $ApkPath) -AllowFailure
    if ($result.ExitCode -ne 0 -or $result.Output -notmatch "Success") {
        throw "APK-Installation fehlgeschlagen: $($result.Output)"
    }
}

function Launch-AppLauncher {
    param(
        [string]$Serial,
        [string]$Package = "com.smartnotebook.app"
    )

    $adb = Get-SdkTool -Name "adb.exe" -CandidateRelativePaths @("platform-tools\adb.exe")
    $installed = Invoke-Native -FilePath $adb -Arguments @("-s", $Serial, "shell", "pm", "list", "packages", $Package) -AllowFailure
    if ($installed.Output -notmatch [regex]::Escape($Package)) {
        throw "App $Package ist nicht installiert."
    }

    $result = Invoke-Native -FilePath $adb -Arguments @("-s", $Serial, "shell", "monkey", "-p", $Package, "-c", "android.intent.category.LAUNCHER", "1") -AllowFailure
    if ($result.ExitCode -ne 0 -or $result.Output -match "No activities found") {
        throw "Launcher-Start fehlgeschlagen: $($result.Output)"
    }
}
