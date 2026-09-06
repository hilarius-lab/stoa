param(
    [int]$Api = 36,
    [string]$ApkPath = "",
    [switch]$Build,
    [switch]$Launch,
    [switch]$Headless,
    [switch]$StopWhenDone,
    [int]$BootTimeoutSeconds = 300,
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot "avd-common.ps1")
. (Join-Path $PSScriptRoot "avd-device.ps1")

$name = Get-DefaultAvdName -Api $Api

if ($DryRun) {
    Write-Host "[DRY-RUN] AVD $name starten, Debug-APK installieren"
    if ($Launch) {
        Write-Host "[DRY-RUN] Launcher für com.smartnotebook.app öffnen"
    }
    exit 0
}

if (-not (Test-AvdExists -Name $name)) {
    throw "AVD $name fehlt. Zuerst avd-setup.ps1 -Api $Api ausführen."
}

$session = Start-Avd -Name $name -Headless:$Headless -BootTimeoutSeconds $BootTimeoutSeconds

try {
    Install-DebugApk -Serial $session.Serial -ApkPath $ApkPath -Build:$Build
    Write-Host "[OK] Debug-APK auf $($session.Serial) installiert."

    if ($Launch) {
        Launch-AppLauncher -Serial $session.Serial
        Write-Host "[OK] Launcher für com.smartnotebook.app gestartet."
    }
}
finally {
    if ($StopWhenDone -and $session.Started) {
        Stop-Avd -Serial $session.Serial
        Write-Host "[OK] Emulator $name gestoppt."
    }
}

exit 0
