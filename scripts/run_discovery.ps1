param(
    [ValidateSet("0800", "1800", "manual")]
    [string]$Slot = "manual"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $ProjectRoot

$EffectiveSlot = if ($Slot -eq "manual") { Get-Date -Format "HHmm" } else { $Slot }
$LogDirectory = Join-Path $ProjectRoot "logs\discovery"
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$LogPath = Join-Path $LogDirectory "$(Get-Date -Format 'yyyy-MM-dd')_$EffectiveSlot.log"
$Activate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path -LiteralPath $Activate) { & $Activate }
$Python = "python"

"[$(Get-Date -Format o)] Discovery started; slot=$EffectiveSlot" | Tee-Object -FilePath $LogPath
try {
    & $Python -m job_hunter.cli discover *>&1 | Tee-Object -FilePath $LogPath -Append
    $DiscoveryExitCode = $LASTEXITCODE
    "[$(Get-Date -Format o)] Discovery finished; exit_code=$DiscoveryExitCode" | Tee-Object -FilePath $LogPath -Append
    exit $DiscoveryExitCode
}
catch {
    "[$(Get-Date -Format o)] ERROR: $($_.Exception.Message)" | Tee-Object -FilePath $LogPath -Append
    exit 1
}
