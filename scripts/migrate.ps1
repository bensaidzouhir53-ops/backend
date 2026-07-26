# Run Alembic migrations against PostgreSQL
# Usage (from backend folder): .\scripts\migrate.ps1

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $env:DATABASE_URL) {
    Write-Host "DATABASE_URL not set — using localhost default from .env.example"
    if (Test-Path ".env") {
        Get-Content ".env" | ForEach-Object {
            if ($_ -match '^\s*DATABASE_URL=(.+)$') { $env:DATABASE_URL = $matches[1].Trim() }
        }
    }
}

Write-Host "Running: alembic upgrade head"
alembic upgrade head
Write-Host "Done. Tables created: orders, tracking_events, alembic_version"
