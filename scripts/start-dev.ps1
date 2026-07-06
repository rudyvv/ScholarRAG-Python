<#
.SYNOPSIS
    Start Paismart RAG infrastructure services for local development.
.DESCRIPTION
    Orchestrates docker-compose with the main and dev override files.
    Supports build, detach, and teardown modes.
.PARAMETER Build
    Rebuild custom images (Elasticsearch with IK analyzer) before starting.
.PARAMETER Down
    Tear down all running services instead of starting them.
.EXAMPLE
    .\scripts\start-dev.ps1
    .\scripts\start-dev.ps1 -Build
    .\scripts\start-dev.ps1 -Down
#>

param(
    [switch]$Build,
    [switch]$Down
)

$COMPOSE_FILE   = "docker-compose.yml"
$COMPOSE_DEV    = "docker-compose.dev.yml"
$COMPOSE_FILES  = "-f $COMPOSE_FILE -f $COMPOSE_DEV"

# Resolve project root (directory containing docker-compose.yml)
$PROJECT_ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $PROJECT_ROOT

if (-not (Test-Path -LiteralPath ".env")) {
    Write-Host "[WARN] .env file not found. Copy .env.example to .env first." -ForegroundColor Yellow
    Write-Host "       cp .env.example .env" -ForegroundColor Yellow
    exit 1
}

if ($Down) {
    Write-Host "[INFO] Tearing down Paismart RAG infrastructure ..." -ForegroundColor Cyan
    docker compose $COMPOSE_FILES down
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] All services stopped." -ForegroundColor Green
    } else {
        Write-Host "[ERR] Failed to stop services." -ForegroundColor Red
        exit 1
    }
    exit
}

if ($Build) {
    Write-Host "[INFO] Building custom images ..." -ForegroundColor Cyan
    docker compose $COMPOSE_FILES build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERR] Build failed." -ForegroundColor Red
        exit 1
    }
}

Write-Host "[INFO] Starting Paismart RAG infrastructure ..." -ForegroundColor Cyan
Write-Host "       Compose files: $COMPOSE_FILE, $COMPOSE_DEV" -ForegroundColor Gray

docker compose $COMPOSE_FILES up -d

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] All services started." -ForegroundColor Green
    Write-Host ""
    Write-Host "Service ports (development):" -ForegroundColor Cyan
    Write-Host "  MySQL:       localhost:${env:MYSQL_PORT:-3306}" -ForegroundColor Gray
    Write-Host "  Redis:       localhost:${env:REDIS_PORT:-6379}" -ForegroundColor Gray
    Write-Host "  MinIO API:   localhost:${env:MINIO_API_PORT:-19000}" -ForegroundColor Gray
    Write-Host "  MinIO Admin: localhost:${env:MINIO_CONSOLE_PORT:-19001}" -ForegroundColor Gray
    Write-Host "  Elastic:     localhost:${env:ELASTICSEARCH_PORT:-9200}" -ForegroundColor Gray
    Write-Host "  RabbitMQ:    localhost:${env:RABBITMQ_PORT:-5672}" -ForegroundColor Gray
    Write-Host "  RabbitMQ UI: localhost:${env:RABBITMQ_MANAGEMENT_PORT:-15672}" -ForegroundColor Gray
    Write-Host "  Milvus:      localhost:${env:MILVUS_PORT:-19530}" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Check status: docker compose ps" -ForegroundColor Cyan
} else {
    Write-Host "[ERR] Failed to start services." -ForegroundColor Red
    exit 1
}
