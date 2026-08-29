param([switch]$Force)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runner = Join-Path $ProjectRoot "scripts\run_discovery.ps1"
if (-not (Test-Path -LiteralPath $Runner)) { throw "Discovery runner not found: $Runner" }

$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

foreach ($Definition in @(
    @{ Name = "JobHunter-Morning"; Time = "08:00"; Slot = "0800" },
    @{ Name = "JobHunter-Evening"; Time = "18:00"; Slot = "1800" }
)) {
    $Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -Slot $($Definition.Slot)"
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments -WorkingDirectory $ProjectRoot
    $Trigger = New-ScheduledTaskTrigger -Daily -At $Definition.Time
    $Existing = Get-ScheduledTask -TaskName $Definition.Name -ErrorAction SilentlyContinue
    if ($Existing -and -not $Force) { Write-Host "$($Definition.Name) already exists; use -Force to replace it."; continue }
    Register-ScheduledTask -TaskName $Definition.Name -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force:$Force | Out-Null
    Write-Host "Installed $($Definition.Name) at $($Definition.Time) local Windows time."
}
