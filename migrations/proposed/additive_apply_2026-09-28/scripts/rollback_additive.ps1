param(
    [Parameter(Mandatory=$true)][string]$DatabaseUrl,
    [Parameter(Mandatory=$true)][string]$SchemaOwnerApprovalFile,
    [Parameter(Mandatory=$true)][string]$BackupManifest,
    [string]$Python = 'C:\Users\Ismail\Projects\GHUS-Platform\.venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:V2_ADDITIVE_DATABASE_URL = $DatabaseUrl
& $Python "$here\run_package.py" down --target shared --approval-file $SchemaOwnerApprovalFile --backup-manifest $BackupManifest --confirm-rollback
if ($LASTEXITCODE -ne 0) { throw 'additive rollback failed' }
Write-Output 'Additive package rolled back. The production backup was not restored.'
