$pgBin = "C:\Program Files\PostgreSQL\16\bin"

# 修改服务配置指向 D 盘
$binPath = '"' + $pgBin + '\pg_ctl.exe" runservice -N "postgresql-x64-16" -D "D:\pgdata"'
sc.exe config postgresql-x64-16 binPath= $binPath
Write-Host "Service config updated"

# 启动服务
Start-Service postgresql-x64-16
Start-Sleep 4
$svc = Get-Service postgresql-x64-16
Write-Host "Service: $($svc.Status)"

# 等待 PostgreSQL 完全就绪
Start-Sleep 2

# 创建数据库
$env:PGPASSWORD = "postgres"
& "$pgBin\psql.exe" -U postgres -p 5432 -c "ALTER USER postgres WITH PASSWORD 'postgres';"
& "$pgBin\psql.exe" -U postgres -p 5432 -c "CREATE DATABASE pharma_kb ENCODING 'UTF8';"
Write-Host "Database pharma_kb created"

# 验证
& "$pgBin\psql.exe" -U postgres -p 5432 -l
Write-Host "DONE"
