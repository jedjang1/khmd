param(
 [Parameter(Mandatory=$true)][ValidateSet('verify','example','demo')][string]$Mode,
 [Parameter(Mandatory=$true)][string]$Library,
 [Parameter(Mandatory=$true)][string]$Output,
 [Parameter(Mandatory=$true)][string]$Python,
 [Parameter(Mandatory=$true)][string]$Rscript,
 [string]$Bundle=(Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference='Stop'
& $Python -B -X utf8 (Join-Path $Bundle 'tools/run_local.py') $Mode --bundle $Bundle --library $Library --output $Output --rscript $Rscript
$Code=$LASTEXITCODE
if($Code -ne 0){throw "LOCAL_$Mode FAILED exit=$Code; retained evidence=$Output"}
