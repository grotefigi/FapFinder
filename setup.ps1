param([string]$PythonExe = 'python', [switch]$CpuOnly, [switch]$SkipModel)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Assert-Exit([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." } }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $PythonExe -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,13), 'Please use Python 3.10 through 3.13 (3.12 recommended).'; print(sys.version)"
    Assert-Exit 'Python version check'
    & $PythonExe -m venv .venv
    Assert-Exit 'Virtual environment creation'
}
& '.\.venv\Scripts\python.exe' -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt
Assert-Exit 'Application dependencies'
$TorchIndex = if ($CpuOnly) { 'https://download.pytorch.org/whl/cpu' } else { 'https://download.pytorch.org/whl/cu128' }
& '.\.venv\Scripts\python.exe' -m pip install --disable-pip-version-check --no-cache-dir 'torch==2.10.0' --index-url $TorchIndex
Assert-Exit 'PyTorch installation'
if (-not $SkipModel) {
    & '.\.venv\Scripts\python.exe' scripts\download_model.py
    Assert-Exit 'Local model download'
}
Write-Host 'Setup complete. Double-click Start FapFinder.vbs.'
