Write-Host "[1/5] 停止 PostgreSQL 服务..."
Stop-Service postgresql-x64-16 -Force -ErrorAction SilentlyContinue
net stop postgresql-x64-16 2>$null
Start-Sleep 3
Write-Host "服务已停止"

Write-Host "[2/5] 在 D:\pgdata 初始化数据目录..."
$pgBin = "C:\Program Files\PostgreSQL\16\bin"
if (-not (Test-Path D:\pgdata)) { New-Item -ItemType Directory -Path D:\pgdata -Force }
& "$pgBin\initdb.exe" -D D:\pgdata -U postgres --auth-host=md5 --auth-local=trust --encoding=UTF8 --locale=Chinese_PRC.UTF8
Write-Host "initdb 完成"

Write-Host "[3/5] 修改 PostgreSQL 服务指向 D 盘..."
sc.exe config postgresql-x64-16 binPath= "\"$pgBin\pg_ctl.exe\" runservice -N \"postgresql-x64-16\" -D \"D:\pgdata\""
Write-Host "服务配置已更新"

Write-Host "[4/5] 启动 PostgreSQL 服务..."
Start-Service postgresql-x64-16
Start-Sleep 3
$svc = Get-Service postgresql-x64-16
Write-Host "服务状态: $($svc.Status)"

Write-Host "[5/5] 创建数据库..."
$env:PGPASSWORD = "postgres"
& "$pgBin\psql.exe" -U postgres -p 5432 -c "ALTER USER postgres WITH PASSWORD 'postgres';"
& "$pgBin\psql.exe" -U postgres -p 5432 -c "CREATE DATABASE pharma_kb ENCODING 'UTF8';"
Write-Host "数据库 pharma_kb 创建完成"

Write-Host ""
Write-Host "=== PostgreSQL D盘部署完成 ==="
