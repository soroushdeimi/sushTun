#Requires -Version 5
<#
  Downloads the third-party redistributables the app runs against:
  xray.exe + geoip.dat + geosite.dat (XTLS/Xray-core) and wintun.dll.
  These are gitignored; run this once for local dev and in CI before building.
#>
param(
    [switch]$Force,
    [string]$WintunVersion = "0.14.1"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$tmp = Join-Path $env:TEMP ("xrayui-deps-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

function Need($name) {
    $p = Join-Path $root $name
    return $Force -or -not (Test-Path $p)
}

try {
    if ((Need "xray.exe") -or (Need "geoip.dat") -or (Need "geosite.dat")) {
        Write-Host "Downloading Xray-core..."
        $zip = Join-Path $tmp "xray.zip"
        Invoke-WebRequest -Uri "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip" -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "xray") -Force
        foreach ($f in @("xray.exe", "geoip.dat", "geosite.dat")) {
            Copy-Item -Force (Join-Path $tmp "xray\$f") (Join-Path $root $f)
        }
    }
    else { Write-Host "Xray files present; skipping." }

    if (Need "wintun.dll") {
        Write-Host "Downloading wintun $WintunVersion..."
        $zip = Join-Path $tmp "wintun.zip"
        Invoke-WebRequest -Uri "https://www.wintun.net/builds/wintun-$WintunVersion.zip" -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "wintun") -Force
        Copy-Item -Force (Join-Path $tmp "wintun\wintun\bin\amd64\wintun.dll") (Join-Path $root "wintun.dll")
    }
    else { Write-Host "wintun.dll present; skipping." }

    Write-Host "Dependencies ready in $root"
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
