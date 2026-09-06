param(
    [int]$Api = 36,
    [switch]$Headless,
    [switch]$StopWhenDone,
    [int]$BootTimeoutSeconds = 300,
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot "avd-common.ps1")
. (Join-Path $PSScriptRoot "avd-device.ps1")

$name = Get-DefaultAvdName -Api $Api

if ($DryRun) {
    Write-Host "[DRY-RUN] AVD $name starten und Launcher für com.smartnotebook.app öffnen"
    exit 0
}

if (-not (Test-AvdExists -Name $name)) {
    throw "AVD $name fehlt. Zuerst avd-setup.ps1 -Api $Api ausführen."
}

$session = Start-Avd -Name $name -Headless:$Headless -BootTimeoutSeconds $BootTimeoutSeconds

try {
    Launch-AppLauncher -Serial $session.Serial
    Write-Host "[OK] Launcher für com.smartnotebook.app auf $($session.Serial) gestartet."
}
finally {
    if ($StopWhenDone -and $session.Started) {
        Stop-Avd -Serial $session.Serial
        Write-Host "[OK] Emulator $name gestoppt."
    }
}

exit 0
