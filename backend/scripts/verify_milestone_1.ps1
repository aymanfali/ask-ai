$ErrorActionPreference = "Stop"

Write-Host "Starting PostgreSQL and Redis..."
docker compose up -d postgres redis
if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed to start infrastructure." }

Push-Location (Join-Path $PSScriptRoot "../backend")
try {
    if (-not (Test-Path "uv.lock")) {
        Write-Host "Resolving Python dependencies and creating uv.lock..."
        uv lock
        if ($LASTEXITCODE -ne 0) { throw "uv lock failed." }
    }

    uv sync --all-groups
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }

    $env:TEST_DATABASE_URL = "postgresql+asyncpg://ask_ai:ask_ai_local_only@localhost:5432/ask_ai"
    $env:TEST_REDIS_URL = "redis://localhost:6379/0"

    uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic migration failed." }

    uv run ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff checks failed." }

    uv run mypy src
    if ($LASTEXITCODE -ne 0) { throw "Mypy checks failed." }

    uv run pytest --cov=ask_ai --cov-report=term-missing
    if ($LASTEXITCODE -ne 0) { throw "Pytest failed." }
}
finally {
    Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:TEST_REDIS_URL -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host "Milestone 1 verification completed successfully." -ForegroundColor Green
