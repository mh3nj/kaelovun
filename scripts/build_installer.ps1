param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (-not $Version) {
        $match = Select-String -Path "cli.py" -Pattern '^VERSION = "([^"]+)"$'
        if (-not $match) { throw "Could not read VERSION from cli.py." }
        $Version = $match.Matches[0].Groups[1].Value
    }

    if (-not (Test-Path "dist\Kaelovun\Kaelovun.exe")) {
        throw "dist\Kaelovun\Kaelovun.exe not found. Run scripts\build_release.bat first."
    }

    # Never ship local settings, logs or session state.
    $data = "dist\Kaelovun\_internal\data"
    if (Test-Path $data) { Remove-Item $data -Recurse -Force }

    $makensis = (Get-Command makensis.exe -ErrorAction SilentlyContinue).Source
    if (-not $makensis) {
        $candidate = Join-Path $env:LOCALAPPDATA "tauri\NSIS\makensis.exe"
        if (Test-Path $candidate) { $makensis = $candidate }
    }
    if (-not $makensis) {
        throw "makensis.exe not found. Install NSIS 3 or add it to PATH."
    }

    & $makensis "/DAPP_VERSION=$Version" "/DROOT=$root" "installer\Kaelovun.nsi"
    if ($LASTEXITCODE -ne 0) { throw "makensis failed with exit code $LASTEXITCODE." }

    $output = "dist\Kaelovun-Setup-$Version.exe"
    if (-not (Test-Path $output)) { throw "Expected $output was not created." }
    Write-Host "Built $output"
}
finally {
    Pop-Location
}
