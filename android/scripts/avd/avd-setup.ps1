param(
    [int[]]$Api = @(26, 36),
    [string]$Device = "pixel",
    [string]$Tag = "google_apis",
    [string]$Abi = "x86_64",
    [switch]$SkipImageInstall,
    [switch]$Recreate,
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot "avd-common.ps1")

$failures = [System.Collections.Generic.List[string]]::new()

foreach ($apiLevel in $Api) {
    $name = Get-DefaultAvdName -Api $apiLevel
    $package = Get-AvdTargetPackage -Api $apiLevel -Tag $Tag -Abi $Abi

    try {
        if (-not $SkipImageInstall) {
            $installed = Install-SystemImage -Api $apiLevel -Tag $Tag -Abi $Abi -DryRun:$DryRun
            if (-not $installed) {
                throw "Systemimage ist nach der Installation nicht verfügbar: $package"
            }
        }
        elseif (-not (Test-SystemImageInstalled -Api $apiLevel -Tag $Tag -Abi $Abi)) {
            Write-Host "[WARN] Systemimage fehlt: $package"
        }

        if ($Recreate -and (Test-AvdExists -Name $name)) {
            Remove-Avd -Name $name
        }

        if (Test-AvdExists -Name $name) {
            $target = Get-AvdTarget -Name $name
            if ($target -and -not (Test-AvdTargetMatches -Target $target -Api $apiLevel -Tag $Tag)) {
                Write-Host "[WARN] AVD $name existiert mit Target '$target'; erwartet wird $Tag/android_$apiLevel. Bei Bedarf -Recreate verwenden."
            }
            Write-Host "[OK] AVD $name wiederverwendet."
        }
        else {
            New-Avd -Name $name -Package $package -Device $Device -DryRun:$DryRun
            Write-Host "[OK] AVD $name erstellt."
        }
    }
    catch {
        $failures.Add("API ${apiLevel}: $($_.Exception.Message)")
    }
}

if ($failures.Count -eq 0) {
    Write-Host "avd-setup: BESTANDEN" -ForegroundColor Green
    exit 0
}

foreach ($failure in $failures) {
    Write-Host "[FAIL] $failure" -ForegroundColor Red
}
Write-Host "avd-setup: FEHLGESCHLAGEN" -ForegroundColor Red
exit 1
