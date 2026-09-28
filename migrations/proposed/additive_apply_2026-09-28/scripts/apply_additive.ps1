param(
    [Parameter(Mandatory=$true)][string]$DatabaseUrl,
    [Parameter(Mandatory=$true)][string]$SchemaOwnerApprovalFile,
    [string]$BackupRoot = 'C:\Users\Ismail\GHUS-data\backups',
    [string]$Python = 'C:\Users\Ismail\Projects\GHUS-Platform\.venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$package = Split-Path -Parent $here
$manifestPath = & "$here\pre_apply_backup.ps1" -DatabaseUrl $DatabaseUrl -BackupRoot $BackupRoot
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$before = Join-Path $BackupRoot "ghus_v2_pre_apply_state_$stamp.json"
$after = Join-Path $BackupRoot "ghus_v2_post_apply_state_$stamp.json"
$env:V2_ADDITIVE_DATABASE_URL = $DatabaseUrl
& $Python "$here\capture_state.py" --output $before
if ($LASTEXITCODE -ne 0) { throw 'pre-apply state capture failed' }
& $Python "$here\run_package.py" up --target shared --approval-file $SchemaOwnerApprovalFile --backup-manifest $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'additive apply failed; do not continue' }
& $Python "$here\post_apply_check.py" --before $before --output $after
if ($LASTEXITCODE -ne 0) { throw 'post-apply row-count/object check failed' }
& $Python "$here\readonly_smoke.py" --repo backend
if ($LASTEXITCODE -ne 0) { throw 'backend read-only smoke failed' }
& $Python "$here\readonly_smoke.py" --repo frontend
if ($LASTEXITCODE -ne 0) { throw 'frontend read-only smoke failed' }
Write-Output "Applied package: $package"
Write-Output "Backup manifest: $manifestPath"
Write-Output "Post-apply report: $after"
