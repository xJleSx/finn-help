# PowerShell-обёртка для Windows Task Scheduler.
# Не является отдельным планировщиком — вызывает finn auto раз в день.
# Основной планировщик: src/scheduler/service.py (внутри API-процесса).

$env:PYTHONIOENCODING = "utf-8"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
.venv\Scripts\finn auto 2>&1 | Out-File -FilePath "data\daily_$(Get-Date -Format 'yyyy-MM-dd').log" -Encoding utf8
