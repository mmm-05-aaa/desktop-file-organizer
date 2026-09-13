param(
    [string]$Version = "0.1.0-alpha"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$Build = Join-Path $Root "build/windows"
$Dist = Join-Path $Root "dist"

Remove-Item $Build -Recurse -Force -ErrorAction SilentlyContinue
New-Item $Build -ItemType Directory -Force | Out-Null
New-Item $Dist -ItemType Directory -Force | Out-Null

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name desktop-file-organizer `
    --distpath (Join-Path $Build "app") `
    --workpath (Join-Path $Build "pyinstaller") `
    --specpath $Build `
    (Join-Path $Root "organizer.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$Iscc = @(
    "C:\Program Files\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup compiler was not found" }

& $Iscc "/DAppVersion=$Version" "/DBuildDir=$(Join-Path $Build 'app')" `
    "/DOutputDir=$Dist" (Join-Path $PSScriptRoot "desktop-organizer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
