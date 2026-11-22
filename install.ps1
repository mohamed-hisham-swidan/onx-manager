#Requires -Version 5.1
<#
.SYNOPSIS
    ONX Manager — Windows Installer (Local Desktop Mode by default)
.DESCRIPTION
    Installs an isolated Python 3.12 runtime via uv, installs ONX Manager backend
    dependencies, builds the static SPA bundle if Node/npm is present, runs
    Alembic migrations, creates an `onx` CLI shim, and installs Desktop & Start
    Menu shortcuts.
#>
[CmdletBinding()]
param(
    [ValidateSet('local', 'vps')]
    [string]$Mode = 'local',
    [string]$InstallDir = '',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$Uninstall,
    [switch]$VerboseOutput
)

$ErrorActionPreference = 'Stop'
$PythonExactProbe = 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)'
$RepoUrl = if ($env:ONX_REPO_URL) { $env:ONX_REPO_URL } else { 'https://github.com/mohamed-hisham-swidan/onx-manager.git' }

function Write-Step([string]$Msg) {
    Write-Host "  [+] $Msg" -ForegroundColor Cyan
}

function Write-Ok([string]$Msg) {
    Write-Host "  [OK] $Msg" -ForegroundColor Green
}

function Write-WarnLine([string]$Msg) {
    Write-Host "  [!] $Msg" -ForegroundColor Yellow
}

function Resolve-LocalRepoRoot {
    if ($PSScriptRoot) {
        $pyProj = Join-Path $PSScriptRoot 'backend\pyproject.toml'
        $fePkg = Join-Path $PSScriptRoot 'frontend\package.json'
        if ((Test-Path $pyProj) -and (Test-Path $fePkg)) {
            return $PSScriptRoot
        }
    }
    $cwd = (Get-Location).Path
    if ((Test-Path (Join-Path $cwd 'backend\pyproject.toml')) -and (Test-Path (Join-Path $cwd 'frontend\package.json'))) {
        return $cwd
    }
    return $null
}

$LocalRepo = Resolve-LocalRepoRoot
if (-not $InstallDir) {
    if ($LocalRepo) {
        $InstallDir = $LocalRepo
    } else {
        $InstallDir = Join-Path $env:LOCALAPPDATA 'onx-manager'
    }
}

$DesktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'ONX Manager.lnk'
$StartMenuShortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'ONX Manager.lnk'
$BinDir = Join-Path $InstallDir 'bin'
$OnxCmd = Join-Path $BinDir 'onx.cmd'

if ($Uninstall) {
    Write-Host ""
    Write-Host "  ONX Manager — Windows Uninstaller" -ForegroundColor White
    if ($DryRun) {
        Write-Host "  [DRY RUN] Would remove shortcuts ($DesktopShortcut, $StartMenuShortcut) and $OnxCmd"
        Write-Host "  [DRY RUN] Would preserve user data, servers, backups, and config keys."
        exit 0
    }
    foreach ($lnk in @($DesktopShortcut, $StartMenuShortcut, $OnxCmd)) {
        if (Test-Path $lnk) {
            Remove-Item -Force $lnk
            Write-Ok "Removed $lnk"
        }
    }
    Write-Ok "Uninstalled shortcuts and CLI shim. User data and config in $InstallDir were preserved."
    exit 0
}

$BindHost = if ($Mode -eq 'vps') { '0.0.0.0' } else { '127.0.0.1' }

if ($DryRun) {
    Write-Host "  [DRY RUN] ONX Manager Windows Installer Plan"
    Write-Host "    ONX_DEPLOYMENT_PROFILE=$Mode"
    Write-Host "    INSTALL_DIR=$InstallDir"
    Write-Host "    ONX_PANEL_BIND_HOST=$BindHost"
    Write-Host "    ONX_PANEL_BIND_PORT=$Port"
    Write-Host "    PYTHON_PIN=3.12 (exact via uv)"
    Write-Host "    SHORTCUTS=$DesktopShortcut | $StartMenuShortcut"
    exit 0
}

Write-Host ""
Write-Host "  ONX Manager Windows Installer (v0.1.0)" -ForegroundColor White
Write-Host "  Profile: $Mode | Target: $InstallDir | Port: $Port" -ForegroundColor Gray
Write-Host ""

# 1. Ensure repository checkout exists
$BackendDir = Join-Path $InstallDir 'backend'
$FrontendDir = Join-Path $InstallDir 'frontend'
if (-not (Test-Path (Join-Path $BackendDir 'pyproject.toml'))) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is required to clone ONX Manager into $InstallDir."
    }
    Write-Step "Cloning ONX Manager into $InstallDir..."
    & git clone --depth 1 $RepoUrl $InstallDir
    if ($LASTEXITCODE -ne 0) { throw "git clone failed." }
}

# 2. Ensure uv and Python 3.12 isolated venv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Step "Installing uv package manager..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $uvLocalBin = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path $uvLocalBin) {
        $env:Path = "$uvLocalBin;$env:Path"
    }
}

$VenvDir = Join-Path $BackendDir '.venv'
$VenvPy = Join-Path $VenvDir 'Scripts\python.exe'

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Step "Provisioning isolated Python 3.12 runtime via uv..."
    & uv python install 3.12
    $venvOk = $false
    if (Test-Path $VenvPy) {
        & $VenvPy -c $PythonExactProbe 2>$null
        if ($LASTEXITCODE -eq 0) { $venvOk = $true }
    }
    if (-not $venvOk) {
        Write-Step "Creating Python 3.12 virtual environment..."
        & uv venv --clear --python 3.12 $VenvDir
        if ($LASTEXITCODE -ne 0) { throw "uv venv creation failed." }
    }
    Write-Step "Installing backend Python 3.12 dependencies..."
    & uv pip install --python $VenvPy -r (Join-Path $BackendDir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw "uv pip install requirements failed." }
    & uv pip install --python $VenvPy --no-deps -e $BackendDir
    if ($LASTEXITCODE -ne 0) { throw "uv pip install editable package failed." }
    Write-Ok "Python 3.12 backend environment ready"
} else {
    throw "uv could not be installed automatically. Install uv from https://docs.astral.sh/uv/ or Python 3.12 and re-run install.ps1."
}

# 3. Build static frontend SPA bundle if missing
$DistIndex = Join-Path $FrontendDir 'dist\index.html'
if (-not (Test-Path $DistIndex)) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Step "Building production frontend SPA bundle..."
        Push-Location $FrontendDir
        try {
            & npm ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
            & npm run build
            if ($LASTEXITCODE -ne 0) { throw "npm run build failed." }
            Write-Ok "Frontend SPA bundle built"
        } finally {
            Pop-Location
        }
    } else {
        Write-WarnLine "npm not found and frontend\dist\index.html is missing. Install Node.js 22 LTS and run 'npm --prefix frontend run build' to enable single-process UI serving."
    }
} else {
    Write-Ok "Static frontend bundle present"
}

# 4. Write .env and run database migrations
$ConfigDir = Join-Path $BackendDir 'config'
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendDir 'data\servers') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendDir 'data\backups') | Out-Null

$EnvFile = Join-Path $InstallDir '.env'
$DistDir = Join-Path $FrontendDir 'dist'
$DbPath = (Join-Path $BackendDir 'data\onx.db') -replace '\\', '/'
$JwtPath = (Join-Path $ConfigDir 'jwt_private_key.pem') -replace '\\', '/'
$BackupKeyPath = (Join-Path $ConfigDir 'backup_encryption_key.bin') -replace '\\', '/'

if (-not (Test-Path $EnvFile)) {
    @"
# Generated by ONX Manager Windows installer
ONX_DEPLOYMENT_PROFILE=$Mode
ONX_PANEL_BIND_HOST=$BindHost
ONX_PANEL_BIND_PORT=$Port
ONX_STATIC_DIR=$DistDir
ONX_DATABASE_URL=sqlite+aiosqlite:///$DbPath
ONX_JWT_PRIVATE_KEY_PATH=$JwtPath
ONX_BACKUP_ENCRYPTION_KEY_PATH=$BackupKeyPath
"@ | Set-Content -Path $EnvFile -Encoding UTF8
    Write-Ok "Created $EnvFile"
} else {
    Write-Ok "Preserved existing $EnvFile"
}

Write-Step "Running Alembic database migrations..."
$AlembicExe = Join-Path $VenvDir 'Scripts\alembic.exe'
Push-Location $BackendDir
try {
    $env:ONX_DATABASE_URL = "sqlite+aiosqlite:///$DbPath"
    & $AlembicExe upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head failed." }
    Write-Ok "Database schema up to date"
} finally {
    Pop-Location
}

# 5. Create 'onx.cmd' CLI shim and Desktop / Start Menu shortcuts
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
@"
@echo off
setlocal
set "ONX_HOME=$InstallDir"
set "VENV_PY=%ONX_HOME%\backend\.venv\Scripts\python.exe"
set "CMD=%~1"
if "%CMD%"=="" set "CMD=open"
if /i "%CMD%"=="start" (
    "%VENV_PY%" "%ONX_HOME%\launcher.py" --backend-only --headless --profile $Mode --port $Port
) else if /i "%CMD%"=="stop" (
    "%VENV_PY%" "%ONX_HOME%\launcher.py" --stop
) else if /i "%CMD%"=="restart" (
    "%VENV_PY%" "%ONX_HOME%\launcher.py" --restart --backend-only --headless --profile $Mode --port $Port
) else if /i "%CMD%"=="status" (
    "%VENV_PY%" "%ONX_HOME%\launcher.py" --status
) else if /i "%CMD%"=="logs" (
    "%VENV_PY%" "%ONX_HOME%\launcher.py" --logs
) else if /i "%CMD%"=="open" (
    "%VENV_PY%" "%ONX_HOME%\launcher.py" open --profile $Mode --port $Port
) else (
    "%VENV_PY%" "%ONX_HOME%\launcher.py" %*
)
"@ | Set-Content -Path $OnxCmd -Encoding ASCII

$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($UserPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable('Path', "$BinDir;$UserPath", 'User')
    Write-Ok "Added $BinDir to User PATH"
}

try {
    $Shell = New-Object -ComObject WScript.Shell
    foreach ($LnkPath in @($DesktopShortcut, $StartMenuShortcut)) {
        $Shortcut = $Shell.CreateShortcut($LnkPath)
        $Shortcut.TargetPath = $VenvPy
        $Shortcut.Arguments = "`"$(Join-Path $InstallDir 'launcher.py')`" open --profile $Mode --port $Port"
        $Shortcut.WorkingDirectory = $InstallDir
        $Shortcut.WindowStyle = 7
        $Shortcut.Description = 'Launch ONX Manager'
        $Shortcut.Save()
    }
    Write-Ok "Created Desktop and Start Menu shortcuts"
} catch {
    Write-WarnLine "Could not create Windows shortcuts automatically: $_"
}

Write-Host ""
Write-Host "  ONX Manager installed successfully ($Mode mode)!" -ForegroundColor Green
Write-Host "  Open via the 'ONX Manager' Desktop/Start Menu shortcut or run: onx open" -ForegroundColor White
Write-Host "  URL: http://127.0.0.1:$Port/" -ForegroundColor Cyan
Write-Host ""
