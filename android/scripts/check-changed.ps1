param(
    [Alias("Modules")]
    [string[]]$SelectedModules = @(),
    [string[]]$Paths = @(),
    [switch]$Full,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$androidRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $androidRoot
$separator = [System.IO.Path]::DirectorySeparatorChar
$settingsPath = Join-Path $androidRoot "settings.gradle.kts"
$settingsContent = Get-Content -LiteralPath $settingsPath -Raw
$modules = [regex]::Matches($settingsContent, 'include\("([^"]+)"\)') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique

function ConvertTo-ModuleDirectory {
    param([string]$Module)
    return $Module.TrimStart(":").Replace(":", $separator)
}

function ConvertTo-GradleModule {
    param([string]$Path)
    return ":" + $Path.Replace($separator, ":")
}

function Test-KnownModule {
    param([string]$Module)
    $normalized = if ($Module.StartsWith(":")) { $Module } else { ":" + $Module }
    return $modules -contains $normalized
}

function Get-ModuleBuildFile {
    param([string]$Module)
    return Join-Path $androidRoot (Join-Path (ConvertTo-ModuleDirectory $Module) "build.gradle.kts")
}

function Get-ModuleDependencies {
    param([string]$Module)
    $buildFile = Get-ModuleBuildFile $Module
    if (-not (Test-Path -LiteralPath $buildFile)) { return @() }
    $content = Get-Content -LiteralPath $buildFile -Raw
    return [regex]::Matches($content, 'project\("([^"]+)"\)') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
}

$dependents = @{}
foreach ($module in $modules) { $dependents[$module] = @() }
foreach ($module in $modules) {
    foreach ($dependency in (Get-ModuleDependencies $module)) {
        if ($dependents.ContainsKey($dependency)) {
            $dependents[$dependency] += $module
        }
    }
}

function Get-AffectedModules {
    param([string[]]$Seeds)
    $affected = [System.Collections.Generic.HashSet[string]]::new()
    $queue = [System.Collections.Generic.Queue[string]]::new()
    foreach ($seed in $Seeds) {
        if (-not $affected.Contains($seed)) {
            $affected.Add($seed) | Out-Null
            $queue.Enqueue($seed)
        }
    }
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        foreach ($dependent in $dependents[$current]) {
            if (-not $affected.Contains($dependent)) {
                $affected.Add($dependent) | Out-Null
                $queue.Enqueue($dependent)
            }
        }
    }
    return @($affected | Sort-Object)
}

function ConvertTo-SeedModules {
    param([string[]]$InputPaths)
    $seeds = [System.Collections.Generic.List[string]]::new()
    $moduleDirs = $modules | ForEach-Object { ConvertTo-ModuleDirectory $_ } | Sort-Object { $_.Length } -Descending

    foreach ($rawPath in $InputPaths) {
        $path = $rawPath.Trim().Trim('"')
        if ($path -eq "") { continue }
        $normalized = $path.Replace("/", $separator).Replace("\", $separator)
        if ($normalized -like "*$separator.git*" -or $normalized -like "*$separator.work*") { continue }

        $relative = $normalized
        if ($relative.StartsWith($repoRoot)) {
            $relative = $relative.Substring($repoRoot.Length).TrimStart($separator)
        }
        if ($relative.StartsWith("android$separator")) {
            $relative = $relative.Substring(("android$separator").Length)
        }

        if (
            $relative.StartsWith("build-logic$separator") -or
            $relative -eq "settings.gradle.kts" -or
            $relative -eq "build.gradle.kts" -or
            $relative -eq "gradle.properties" -or
            $relative.StartsWith("gradle$separator")
        ) {
            $seeds.Clear()
            $seeds.AddRange($modules)
            return @($seeds)
        }

        if ($relative.StartsWith("contracts$separator")) {
            if (-not $seeds.Contains(":core:network")) { $seeds.Add(":core:network") }
            if (-not $seeds.Contains(":data")) { $seeds.Add(":data") }
            continue
        }

        foreach ($moduleDir in $moduleDirs) {
            if ($relative -eq $moduleDir -or $relative.StartsWith("$moduleDir$separator")) {
                $module = ConvertTo-GradleModule $moduleDir
                if (-not $seeds.Contains($module)) { $seeds.Add($module) }
                break
            }
        }
    }

    return @($seeds)
}

function Get-ChangedPaths {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot ".git"))) { return $null }
    if ($null -eq (Get-Command git -ErrorAction SilentlyContinue)) { return $null }

    $changed = [System.Collections.Generic.List[string]]::new()
    $porcelain = & git -C $repoRoot status --porcelain 2>$null
    if ($LASTEXITCODE -eq 0) {
        foreach ($line in $porcelain) {
            if ($line.Length -ge 3) { $changed.Add($line.Substring(3).Trim('"')) }
        }
    }
    $diff = & git -C $repoRoot diff --name-only HEAD 2>$null
    if ($LASTEXITCODE -eq 0) {
        foreach ($line in $diff) { if ($line.Trim() -ne "") { $changed.Add($line.Trim()) } }
    }
    return @($changed | Sort-Object -Unique)
}

$seeds = @()
if ($Full) {
    $seeds = @($modules)
} elseif ($SelectedModules.Count -gt 0) {
    foreach ($module in $SelectedModules) {
        $normalized = if ($module.StartsWith(":")) { $module } else { ":" + $module }
        if (-not (Test-KnownModule $normalized)) {
            Write-Host "Unbekanntes Modul: $normalized" -ForegroundColor Red
            exit 1
        }
        if (-not $seeds.Contains($normalized)) { $seeds += $normalized }
    }
} elseif ($Paths.Count -gt 0) {
    $seeds = ConvertTo-SeedModules -InputPaths $Paths
} else {
    $changed = Get-ChangedPaths
    if ($null -eq $changed) {
        Write-Warning "Kein Git-Repository gefunden; check-changed faellt auf das vollstaendige Modul-Set zurueck."
        $seeds = @($modules)
    } else {
        $seeds = ConvertTo-SeedModules -InputPaths $changed
    }
}

$affected = Get-AffectedModules -Seeds $seeds
if ($affected.Count -eq 0) {
    Write-Host "Keine Android-Module betroffen." -ForegroundColor Green
    exit 0
}

$tasks = @("architectureTest", "uiTextCheck")
foreach ($module in $affected) {
    $tasks += "${module}:assembleDebug"
    $tasks += "${module}:test"
    $tasks += "${module}:detekt"
    $tasks += "${module}:ktlintCheck"
    $tasks += "${module}:lint"
}

$gradle = Join-Path $androidRoot "gradlew.bat"
$cacheDir = Join-Path $androidRoot (".work" + $separator + "check-changed")
$command = @($gradle) + $tasks + @("--project-cache-dir", $cacheDir, "--no-daemon")

Write-Host "check-changed: betroffene Module: $($affected -join ', ')"
if ($DryRun) {
    $command | ForEach-Object { Write-Host $_ }
    exit 0
}

& $command[0] @($command[1..($command.Length - 1)])
exit $LASTEXITCODE
