# PowerShell script for daily FinAdvisor cycle
# Can be scheduled via Windows Task Scheduler
# Usage: run daily at 18:00 (after MOEX close)

$env:PYTHONIOENCODING = "utf-8"
Set-Location -LiteralPath "D:\finn-help"
.venv\Scripts\finn auto 2>&1 | Out-File -FilePath "data\daily_$(Get-Date -Format 'yyyy-MM-dd').log" -Encoding utf8
