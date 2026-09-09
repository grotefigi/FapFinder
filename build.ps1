$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Get-Process -Name FapFinder -ErrorAction SilentlyContinue) {
    throw 'Close FapFinder before updating its application files. Your library will be preserved.'
}
function Assert-Exit([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." } }
& '.\.venv\Scripts\python.exe' -m pip install --disable-pip-version-check --no-cache-dir -r requirements-dev.txt
Assert-Exit 'Build dependencies'
& '.\.venv\Scripts\python.exe' -m pytest tests -q
Assert-Exit 'Tests'
& '.\.venv\Scripts\python.exe' scripts\build_icon.py
Assert-Exit 'Icon generation'
$StageRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'build\portable-stage'))
$BuildRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'build')) + [System.IO.Path]::DirectorySeparatorChar
if (-not $StageRoot.StartsWith($BuildRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The packaging staging directory must stay inside this project build folder.'
}
if (Test-Path -LiteralPath (Join-Path $StageRoot 'FapFinder\data')) {
    throw 'The staging folder contains app data. Move that data to a safe location before rebuilding.'
}
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --distpath $StageRoot FapFinder.spec
Assert-Exit 'Windows packaging'
# Copy application files into the portable folder without deleting its existing user data.
if (Get-Process -Name FapFinder -ErrorAction SilentlyContinue) {
    throw 'FapFinder opened during packaging. Close it, then rerun this build to finish the update.'
}
$PortableRoot = Join-Path $PSScriptRoot 'dist\FapFinder'
New-Item -ItemType Directory -Path $PortableRoot -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $StageRoot 'FapFinder') -Force | Copy-Item -Destination $PortableRoot -Recurse -Force
$BuiltModel = Join-Path $PSScriptRoot 'dist\FapFinder\data\models\siglip2-base-patch16-224'
New-Item -ItemType Directory -Path $BuiltModel -Force | Out-Null
if (Test-Path -LiteralPath 'data\models\siglip2-base-patch16-224\READY.json') {
    Copy-Item -Path 'data\models\siglip2-base-patch16-224\*' -Destination $BuiltModel -Force
}
Copy-Item -LiteralPath 'README.md' -Destination 'dist\FapFinder\README.md' -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination 'dist\FapFinder\THIRD_PARTY_NOTICES.md' -Force
Copy-Item -LiteralPath 'LICENSE' -Destination 'dist\FapFinder\LICENSE' -Force
$PortableDocs = Join-Path $PortableRoot 'docs'
New-Item -ItemType Directory -Path $PortableDocs -Force | Out-Null
Get-ChildItem -LiteralPath 'docs' | Copy-Item -Destination $PortableDocs -Recurse -Force
& '.\.venv\Scripts\python.exe' scripts\copy_notices.py
Assert-Exit 'Dependency notices'
Write-Host 'Build ready: dist\FapFinder\FapFinder.exe. Keep the whole FapFinder folder together.'
