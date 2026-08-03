# -*- coding: utf-8 -*-
"""诊断 nginx 挂载问题"""
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('119.28.14.114', 22, 'ubuntu', 'Sino123456789@', timeout=10)

cmds = [
    ("容器挂载信息", "sudo docker inspect deploy-nginx-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} ({{.Type}})\n{{end}}'"),
    ("宿主机 dist", "ls -la /home/ubuntu/pharma-kb/frontend/dist/ && echo --- && ls -la /home/ubuntu/pharma-kb/frontend/"),
    ("compose nginx 段", "sed -n '/nginx:/,$p' /home/ubuntu/pharma-kb/deploy/docker-compose.yml"),
]

for label, cmd in cmds:
    print(f"=== {label} ===")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    print(stdout.read().decode()[:1500])
    err = stderr.read().decode()[:300]
    if err.strip():
        print("[ERR]", err[:300])

client.close()
