param(
    [Parameter(Mandatory=$true)][string]$DatabaseUrl,
    [string]$BackupRoot = 'C:\Users\Ismail\GHUS-data\backups',
    [string]$PgDump = 'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe'
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PgDump)) { throw "pg_dump not found: $PgDump" }
$normalized = $DatabaseUrl -replace '^postgresql\+psycopg2://','postgresql://' -replace '^postgresql\+psycopg://','postgresql://'
$uri = [Uri]$normalized
if ($uri.Host -in @('localhost','127.0.0.1')) { throw 'Pre-apply production backup refuses a local database URL.' }
$userInfo = $uri.UserInfo.Split(':',2)
$user = [Uri]::UnescapeDataString($userInfo[0])
$password = if ($userInfo.Count -gt 1) { [Uri]::UnescapeDataString($userInfo[1]) } else { '' }
$database = $uri.AbsolutePath.TrimStart('/')
$port = if ($uri.Port -gt 0) { $uri.Port } else { 5432 }
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$dump = Join-Path $BackupRoot "ghus_production_full_$stamp.dump"
$manifest = "$dump.manifest.json"
$priorPassword = $env:PGPASSWORD
try {
    $env:PGPASSWORD = $password
    & $PgDump --format=custom --compress=9 --no-owner --no-privileges --host=$($uri.Host) --port=$port --username=$user --file=$dump $database
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
} finally {
    $env:PGPASSWORD = $priorPassword
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
