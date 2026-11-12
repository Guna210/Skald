# scripts/dev-env.ps1
# Export cache environment variables for project-local development in Skald.
# Usage: . .\scripts\dev-env.ps1

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir -and $MyInvocation.MyCommand.Path) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $ScriptDir -and $PSCommandPath) {
    $ScriptDir = Split-Path -Parent $PSCommandPath
}
if (-not $ScriptDir) {
    Write-Error "scripts/dev-env.ps1: failed to resolve script directory"
    return
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path

$CacheDir = Join-Path $RepoRoot ".cache"
$null = New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "pip")
$null = New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "uv")
$null = New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "npm")
$null = New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "electron")
$null = New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "electron-builder")
$null = New-Item -ItemType Directory -Force -Path (Join-Path $CacheDir "devdata")
$null = New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "vendor")

$env:PIP_CACHE_DIR = Join-Path $CacheDir "pip"
$env:UV_CACHE_DIR = Join-Path $CacheDir "uv"
$env:npm_config_cache = Join-Path $CacheDir "npm"
$env:ELECTRON_CACHE = Join-Path $CacheDir "electron"
$env:ELECTRON_BUILDER_CACHE = Join-Path $CacheDir "electron-builder"
$env:SKALD_DEV_DATA = Join-Path $CacheDir "devdata"
$env:SKALD_VENDOR = Join-Path $RepoRoot "vendor"
