# -*- coding: utf-8 -*-
"""打包最新 backend 上传覆盖服务器并重启"""
import tarfile
import io
import os
import paramiko

LOCAL_BACKEND = r"D:\药物原辅料知识问答助手\backend"
HOST = "119.28.14.114"
USER = "ubuntu"
PASSWORD = "Sino123456789@"

# 1. 打包 backend（排除缓存/日志/venv/mcp）
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tar:
    for dirpath, dirnames, filenames in os.walk(LOCAL_BACKEND):
        rel = os.path.relpath(dirpath, LOCAL_BACKEND)
        rel_dir = "" if rel == "." else rel.replace("\\", "/")
        dirnames[:] = [
            d
            for d in dirnames
            if d not in (".venv", "venv", "__pycache__", "node_modules", "mcp")
        ]
        for fname in filenames:
            if fname.endswith((".log", ".err", ".pyc")) or fname.startswith("_"):
                continue
            abs_path = os.path.join(dirpath, fname)
            arcname = os.path.join(rel_dir, fname) if rel_dir else fname
            try:
                tar.add(abs_path, arcname=arcname)
            except Exception:
                pass
data = buf.getvalue()
print(f"backend 包大小: {len(data)/1024:.0f} KB")

# 2. 上传解压覆盖
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, 22, USER, PASSWORD, timeout=10)
sftp = client.open_sftp()
with sftp.file("/tmp/backend-new.tar.gz", "wb") as f:
    f.write(data)
sftp.close()

cmd = (
    "cd /home/ubuntu/pharma-kb && tar xzf /tmp/backend-new.tar.gz -C backend "
    "&& rm /tmp/backend-new.tar.gz && echo 已解压覆盖 "
    "&& ls -la backend/tools/sources/cde.py backend/tools/sources/patent_search.py "
    "backend/agent/nodes/final_search.py"
)
stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
print(stdout.read().decode())
err = stderr.read().decode()
if err.strip():
    print("[ERR]", err[:300])
client.close()
print("✅ backend 最新代码已上传")
