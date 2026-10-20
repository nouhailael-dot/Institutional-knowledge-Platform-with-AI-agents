param(
    [string]$BackupRoot = 'C:\Users\Ismail\GHUS-data\backups',
    [string]$PgDump = 'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe'
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PgDump)) { throw "pg_dump not found: $PgDump" }
$required = @('PGHOST','PGPORT','PGUSER','PGDATABASE','PGPASSFILE')
$missing = @($required | Where-Object { [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) })
if ($missing.Count -gt 0) { throw ('Missing required PostgreSQL environment variables: ' + ($missing -join ', ')) }
if (-not (Test-Path -LiteralPath $env:PGPASSFILE -PathType Leaf)) { throw 'PGPASSFILE does not name an existing file.' }
if ($env:PGHOST -in @('localhost','127.0.0.1')) { throw 'Pre-apply production backup refuses a local target.' }
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$dump = Join-Path $BackupRoot "ghus_production_full_$stamp.dump"
$manifest = "$dump.manifest.json"
$priorPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD')
try {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    & $PgDump --format=custom --compress=9 --no-owner --no-privileges --file=$dump
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
} finally {
    if ($null -eq $priorPassword) {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    } else {
        $env:PGPASSWORD = $priorPassword
    }
}
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dump).Hash.ToLower()
$data = [ordered]@{
    created_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    dump_path = $dump
    sha256 = $hash
    bytes = (Get-Item -LiteralPath $dump).Length
    format = 'PostgreSQL custom full dump; no owner; no privileges'
}
$data | ConvertTo-Json | Set-Content -LiteralPath $manifest -Encoding utf8
Write-Output $manifest
