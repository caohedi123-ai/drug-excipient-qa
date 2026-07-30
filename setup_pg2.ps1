$ErrorActionPreference = "Stop"
$pgBin = "C:\Program Files\PostgreSQL\16\bin"
$logFile = "D:\pg_setup_log.txt"
"=== Setup started at $(Get-Date) ===" | Out-File $logFile

# 1. 停止服务
"Stopping service..." | Out-File $logFile -Append
Stop-Service postgresql-x64-16 -Force 2>&1 | Out-File $logFile -Append
Start-Sleep 2
"Service stopped" | Out-File $logFile -Append

# 2. 创建 D 盘数据目录
"Creating D:\pgdata..." | Out-File $logFile -Append
New-Item -ItemType Directory -Path D:\pgdata -Force 2>&1 | Out-File $logFile -Append

# 3. initdb
"Running initdb..." | Out-File $logFile -Append
$result = & "$pgBin\initdb.exe" -D D:\pgdata -U postgres --auth-host=md5 --auth-local=trust --encoding=UTF8 2>&1
$result | Out-File $logFile -Append
"initdb exit code: $LASTEXITCODE" | Out-File $logFile -Append

# 4. 修改服务配置
"Updating service config..." | Out-File $logFile -Append
$binPath = '"' + $pgBin + '\pg_ctl.exe" runservice -N "postgresql-x64-16" -D "D:\pgdata"'
sc.exe config postgresql-x64-16 binPath= $binPath 2>&1 | Out-File $logFile -Append

# 5. 启动服务
"Starting service..." | Out-File $logFile -Append
Start-Service postgresql-x64-16 2>&1 | Out-File $logFile -Append
Start-Sleep 3
$svc = Get-Service postgresql-x64-16
"Service status: $($svc.Status)" | Out-File $logFile -Append

# 6. 创建数据库
"Creating pharma_kb database..." | Out-File $logFile -Append
$env:PGPASSWORD = "postgres"
& "$pgBin\psql.exe" -U postgres -p 5432 -c "ALTER USER postgres WITH PASSWORD 'postgres';" 2>&1 | Out-File $logFile -Append
& "$pgBin\psql.exe" -U postgres -p 5432 -c "CREATE DATABASE pharma_kb ENCODING 'UTF8';" 2>&1 | Out-File $logFile -Append

"=== Setup completed at $(Get-Date) ===" | Out-File $logFile -Append
"SUCCESS" | Out-File $logFile -Append
