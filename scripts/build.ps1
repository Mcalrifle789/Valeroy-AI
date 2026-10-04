<#
.SYNOPSIS
    Build every Valeroy native layer that has a toolchain available.

    Rust core (valeroy-core)      - required; the gateway and TUI need it.
    C / C++ natives               - optional speedups; Python fallbacks exist.
    Go gateway (valeroy-gateway)  - optional; the Python gateway is the fallback.

    Each layer is independent: a missing compiler skips that layer with a note
    instead of failing the whole build.
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "build\native"
New-Item -ItemType Directory -Force -Path $out | Out-Null

function Have($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# --- Rust core (required) --------------------------------------------------
if (Have cargo) {
    Write-Host "[valeroy] building Rust core (valeroy-core)" -ForegroundColor Cyan
    Push-Location (Join-Path $root "backend\core")
    cargo build --release
    Pop-Location
} else {
    Write-Error "cargo not found. Install Rust from https://rustup.rs - the core is required."
}

# --- C / C++ natives (optional) --------------------------------------------
$bat = Join-Path $PSScriptRoot "build-native.bat"
if (Test-Path $bat) {
    Write-Host "[valeroy] building C / C++ native layers" -ForegroundColor Cyan
    & cmd /c "`"$bat`""
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "native C/C++ build reported an issue; Python fallbacks will be used."
    }
}

# --- Go gateway (optional) -------------------------------------------------
if (Have go) {
    Write-Host "[valeroy] building Go gateway (valeroy-gateway)" -ForegroundColor Cyan
    Push-Location (Join-Path $root "backend\gateway")
    $exe = Join-Path $out "valeroy-gateway.exe"
    go build -o $exe .
    Pop-Location
    Write-Host "[valeroy] Go gateway -> $exe" -ForegroundColor Green
} else {
    Write-Host "[valeroy] go not found - skipping the Go gateway (the Python gateway is used)." -ForegroundColor Yellow
}

Write-Host "[valeroy] build complete -> $out" -ForegroundColor Green
