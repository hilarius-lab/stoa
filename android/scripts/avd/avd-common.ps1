$ErrorActionPreference = "Stop"

$script:AvdProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

function Get-AndroidSdkDirectory {
    if ($env:ANDROID_HOME) { return $env:ANDROID_HOME }
    if ($env:ANDROID_SDK_ROOT) { return $env:ANDROID_SDK_ROOT }

    $localProps = Join-Path $script:AvdProjectRoot "local.properties"
    if (Test-Path -LiteralPath $localProps) {
        $line = Get-Content -LiteralPath $localProps |
            Where-Object { $_ -match "^sdk\.dir=" } |
            Select-Object -First 1
        if ($line) {
            return (($line -split "=", 2)[1]).Trim().Trim('"')
        }
    }

    return $null
}

function Get-SdkTool {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string[]]$CandidateRelativePaths = @()
    )

    $sdk = Get-AndroidSdkDirectory
    if (-not $sdk -or -not (Test-Path -LiteralPath $sdk)) {
        throw "Android SDK nicht gefunden. ANDROID_HOME, ANDROID_SDK_ROOT oder sdk.dir in local.properties setzen."
    }

    foreach ($candidate in $CandidateRelativePaths) {
        $path = Join-Path $sdk $candidate
        if (Test-Path -LiteralPath $path) { return $path }
    }

    $cmdlineTools = Join-Path $sdk "cmdline-tools"
    if (Test-Path -LiteralPath $cmdlineTools) {
        $found = Get-ChildItem -LiteralPath $cmdlineTools -Recurse -Filter $Name -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    throw "Android-Werkzeug nicht gefunden: $Name"
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$AllowFailure
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $FilePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previous

    $text = if ($null -eq $output) { "" } else { ($output | Out-String).Trim() }

    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "$FilePath beendet mit Exit Code ${exitCode}: $text"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = $text
    }
}

function Invoke-NativeCommandLine {
    param(
        [Parameter(Mandatory = $true)][string]$CommandLine,
        [switch]$AllowFailure
    )

    return Invoke-Native -FilePath $env:ComSpec -Arguments @("/c", $CommandLine) -AllowFailure:$AllowFailure
}

function Get-AvdTargetPackage {
    param(
        [int]$Api,
        [string]$Tag = "google_apis",
        [string]$Abi = "x86_64"
    )

    return "system-images;android-$Api;$Tag;$Abi"
}

function Test-SystemImageInstalled {
    param(
        [int]$Api,
        [string]$Tag = "google_apis",
        [string]$Abi = "x86_64"
    )

    $sdk = Get-AndroidSdkDirectory
    if (-not $sdk) { return $false }

    $image = Join-Path $sdk "system-images\android-$Api\$Tag\$Abi\system.img"
    return (Test-Path -LiteralPath $image)
}

function Install-SystemImage {
    param(
        [int]$Api,
        [string]$Tag = "google_apis",
        [string]$Abi = "x86_64",
        [switch]$DryRun
    )

    $package = Get-AvdTargetPackage -Api $Api -Tag $Tag -Abi $Abi
    if (Test-SystemImageInstalled -Api $Api -Tag $Tag -Abi $Abi) {
        return $true
    }

    if ($DryRun) {
        Write-Host "[DRY-RUN] sdkmanager --install $package"
        return $true
    }

    $sdkmanager = Get-SdkTool -Name "sdkmanager.bat" -CandidateRelativePaths @("cmdline-tools\latest\bin\sdkmanager.bat")
    Write-Host "Installiere Systemimage: $package"
    $commandLine = "`"$sdkmanager`" --install `"$package`""
    $result = Invoke-NativeCommandLine -CommandLine $commandLine -AllowFailure

    if (Test-SystemImageInstalled -Api $Api -Tag $Tag -Abi $Abi) {
        return $true
    }

    if ($result.ExitCode -ne 0) {
        throw "Installation von $package fehlgeschlagen: $($result.Output)"
    }

    throw "Systemimage ist nach der Installation nicht verfügbar: $package"
}

function Get-DefaultAvdName {
    param([int]$Api)
    return "SmartNotebookApi$Api"
}

function Test-AvdExists {
    param([string]$Name)

    if ($env:USERPROFILE) {
        $config = Join-Path $env:USERPROFILE ".android\avd\$Name.avd\config.ini"
        if (Test-Path -LiteralPath $config) { return $true }
    }

    $avdmanager = Get-SdkTool -Name "avdmanager.bat" -CandidateRelativePaths @("cmdline-tools\latest\bin\avdmanager.bat")
    $result = Invoke-Native -FilePath $avdmanager -Arguments @("list", "avd") -AllowFailure
    return ($result.Output -match "Avd Name: $([regex]::Escape($Name))\b")
}

function Get-AvdTarget {
    param([string]$Name)

    if (-not $env:USERPROFILE) { return $null }

    $config = Join-Path $env:USERPROFILE ".android\avd\$Name.avd\config.ini"
    if (-not (Test-Path -LiteralPath $config)) { return $null }

    $line = Get-Content -LiteralPath $config |
        Where-Object { $_ -match "^target=" } |
        Select-Object -First 1

    if (-not $line) { return $null }
    return (($line -split "=", 2)[1]).Trim()
}

function Test-AvdTargetMatches {
    param(
        [string]$Target,
        [int]$Api,
        [string]$Tag = "google_apis"
    )

    if ([string]::IsNullOrWhiteSpace($Target)) { return $false }
    return (($Target -eq "$Tag;android_$Api") -or ($Target -like "*$Tag*" -and $Target -like "*android_$Api*"))
}

function Remove-Avd {
    param([string]$Name)

    $avdmanager = Get-SdkTool -Name "avdmanager.bat" -CandidateRelativePaths @("cmdline-tools\latest\bin\avdmanager.bat")
    $result = Invoke-Native -FilePath $avdmanager -Arguments @("delete", "avd", "-n", $Name, "--force") -AllowFailure
    if ($result.ExitCode -ne 0) {
        throw "AVD $Name konnte nicht entfernt werden: $($result.Output)"
    }
}

function New-Avd {
    param(
        [string]$Name,
        [string]$Package,
        [string]$Device,
        [switch]$DryRun
    )

    if ($DryRun) {
        Write-Host "[DRY-RUN] avdmanager create avd -n $Name -k $Package -d $Device"
        return
    }

    $avdmanager = Get-SdkTool -Name "avdmanager.bat" -CandidateRelativePaths @("cmdline-tools\latest\bin\avdmanager.bat")
    $commandLine = "`"$avdmanager`" create avd -n `"$Name`" -k `"$Package`" -d `"$Device`""
    $result = Invoke-NativeCommandLine -CommandLine $commandLine -AllowFailure
    if ($result.ExitCode -ne 0) {
        throw "AVD $Name konnte nicht erstellt werden: $($result.Output)"
    }
}
