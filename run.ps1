# Start JobPortal on Windows. The first run creates a virtual environment in .venv and installs JobPortal into it.
#   .\run.ps1              open the app (its own window, or your browser if no window is available)
#   .\run.ps1 --browser    open it in your browser
#   .\run.ps1 --doctor     check that everything JobPortal needs is installed
# Double-clicking run.bat does the same as .\run.ps1.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Test-Python($cmd, $cmdArgs) {
    try {
        & $cmd @cmdArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

$py = $null; $pyArgs = @()
if ($env:PYTHON) { $py = $env:PYTHON }
elseif ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-Python "py" @("-3"))) { $py = "py"; $pyArgs = @("-3") }
elseif ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-Python "python" @())) { $py = "python" }
if (-not $py) {
    Write-Host "JobPortal needs Python 3.11 or newer. Install it from https://www.python.org/downloads/ (check 'Add python.exe to PATH')."
    exit 1
}

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating the Python environment in .venv ..."
    & $py @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$stamp = Join-Path $PSScriptRoot ".venv\.jobportal-installed"
if (-not (Test-Path $stamp) -or ((Get-Item "pyproject.toml").LastWriteTime -gt (Get-Item $stamp).LastWriteTime)) {
    Write-Host "Installing JobPortal and its dependencies ..."
    & $venvPy -m pip install -q --upgrade pip
    & $venvPy -m pip install -q -e .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    New-Item -ItemType File -Force -Path $stamp | Out-Null
}
& $venvPy -m jobportal @args
exit $LASTEXITCODE
