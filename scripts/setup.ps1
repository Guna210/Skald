# scripts/setup.ps1
# Development setup script for Skald on Windows.
# Creates core/.venv, sets cache directories, and installs project dependencies.

$ErrorActionPreference = "Stop"

# Determine repo root from script location
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir -and $MyInvocation.MyCommand.Path) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $ScriptDir -and $PSCommandPath) {
    $ScriptDir = Split-Path -Parent $PSCommandPath
}
if (-not $ScriptDir) {
    Write-Error "scripts/setup.ps1: failed to resolve script directory"
    exit 1
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path

# 1. Source dev-env to activate project-local caches
$DevEnvScript = Join-Path $ScriptDir "dev-env.ps1"
if (Test-Path -LiteralPath $DevEnvScript) {
    . $DevEnvScript
} else {
    Write-Error "scripts/setup.ps1: dev-env.ps1 not found at $DevEnvScript"
    exit 1
}

# 2. Check that Python 3.12.x is on PATH or available via py -3.12
# Decision: setup.ps1 accepts Python 3.12 found as 'python' or through the 'py -3.12' launcher
$PythonCmd = $null
$PythonArgs = @()

# First check 'python'
try {
    $ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $ver -eq "3.12") {
        $PythonCmd = "python"
        $PythonArgs = @()
    }
} catch {
}

# If not found as 'python', check 'py -3.12'
if (-not $PythonCmd) {
    try {
        $ver = & py -3.12 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -eq "3.12") {
            $PythonCmd = "py"
            $PythonArgs = @("-3.12")
        }
    } catch {
    }
}

if (-not $PythonCmd) {
    Write-Host "Error: Python 3.12.x was not found on PATH or via the py launcher." -ForegroundColor Red
    Write-Host "Skald requires Python 3.12.x."
    Write-Host "Please install Python 3.12 from https://www.python.org/downloads/ (check 'Add python.exe to PATH' during installation)."
    exit 1
}

# Check that Node 22.x or 24.x is on PATH
$NodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $NodeCmd) {
    Write-Host "Error: Node.js was not found on PATH." -ForegroundColor Red
    Write-Host "Skald requires Node.js 22.x or 24.x LTS."
    Write-Host "Please install Node.js from https://nodejs.org/"
    exit 1
}

$NodeVer = & node -v 2>$null
if ($NodeVer -notmatch '^v(22|24)\.') {
    Write-Host "Error: Node.js version $NodeVer is not supported." -ForegroundColor Red
    Write-Host "Skald requires Node.js 22.x or 24.x LTS."
    Write-Host "Please install Node.js from https://nodejs.org/"
    exit 1
}

# 3. Create core\.venv if missing or broken (must contain working pip)
$VenvDir = Join-Path $RepoRoot "core\.venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

$PipOk = $false
if (Test-Path -LiteralPath $VenvPython) {
    try {
        & $VenvPython -m pip --version 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $PipOk = $true
        }
    } catch {
    }
}

if (-not $PipOk) {
    Write-Host "Creating core virtual environment at $VenvDir..."
    if (Test-Path -LiteralPath $VenvDir) {
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    }
    & $PythonCmd @PythonArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create virtual environment"
        exit $LASTEXITCODE
    }
    try {
        & $VenvPython -m pip --version 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "core\.venv was created without pip. Please ensure ensurepip/pip is available."
            exit 1
        }
    } catch {
        Write-Error "core\.venv was created without pip. Please ensure ensurepip/pip is available."
        exit 1
    }
}

# 4. Upgrade pip inside core/.venv
Write-Host "Upgrading pip in core/.venv..."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to upgrade pip"
    exit $LASTEXITCODE
}

# 5. If core/pyproject.toml exists, pip install -e "core[dev]"
$CorePyproject = Join-Path $RepoRoot "core\pyproject.toml"
if (Test-Path -LiteralPath $CorePyproject) {
    Write-Host "Installing core in editable mode with dev dependencies..."
    Push-Location $RepoRoot
    try {
        & $VenvPython -m pip install -e "core[dev]"
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to install core[dev]"
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
}

# 6. If worker/pyproject.toml exists, pip install -e worker
$WorkerPyproject = Join-Path $RepoRoot "worker\pyproject.toml"
if (Test-Path -LiteralPath $WorkerPyproject) {
    Write-Host "Installing worker in editable mode..."
    Push-Location $RepoRoot
    try {
        & $VenvPython -m pip install -e worker
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to install worker"
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
}

# 7. If app/package-lock.json exists, npm ci in app/
$AppLock = Join-Path $RepoRoot "app\package-lock.json"
if (Test-Path -LiteralPath $AppLock) {
    Write-Host "Running npm ci in app/..."
    $AppDir = Join-Path $RepoRoot "app"
    Push-Location $AppDir
    try {
        & npm ci
        if ($LASTEXITCODE -ne 0) {
            Write-Error "npm ci failed"
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
}

# 8. If scripts/deps.lock.json exists, run scripts/fetch_deps.py
$DepsLock = Join-Path $RepoRoot "scripts\deps.lock.json"
$FetchDepsScript = Join-Path $RepoRoot "scripts\fetch_deps.py"
if (Test-Path -LiteralPath $DepsLock) {
    Write-Host "Fetching pinned dependencies..."
    & $VenvPython $FetchDepsScript
    if ($LASTEXITCODE -ne 0) {
        Write-Error "fetch_deps.py failed"
        exit $LASTEXITCODE
    }
}

Write-Host "Development environment setup complete."
