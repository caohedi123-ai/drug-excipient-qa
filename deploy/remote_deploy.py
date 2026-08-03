"""
药物原辅料知识问答助手 - 远程部署脚本
用法：python deploy/remote_deploy.py
功能：SSH 到服务器 → 装 Docker → tar 传文件 → 配置 .env → docker compose 启动
"""
import paramiko
import os
import time
import tarfile
import io

# ── 服务器信息 ──
HOST = "119.28.14.114"
PORT = 22
USER = "ubuntu"
PASSWORD = "Sino123456789@"

# ── 项目路径 ──
PROJECT_ROOT = r"D:\药物原辅料知识问答助手"
REMOTE_DIR = "/home/ubuntu/pharma-kb"

EXCLUDE_DIRS = {'node_modules', '.venv', 'venv', '__pycache__', '.git', '.codebuddy', 'dist'}
EXCLUDE_FILES_PATTERN = {'*.log', '*.err', '*.pyc', '.env', '.env.*', '_*.py', 'e2e_*.json', 'lookup_*.json', '$null'}

def ssh_run(client, cmd, label="", timeout=300):
    """执行远程命令"""
    if label:
        print(f"\n[>>>] {label}")
    print(f"    $ {cmd[:100]}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    exit_code = stdout.channel.recv_exit_status()
    if out.strip():
        for line in out.strip().splitlines()[-15:]:  # 只打印最后 15 行
            print(f"    {line}")
    if err.strip():
        for line in err.strip().splitlines()[-10:]:
            print(f"    [ERR] {line}")
    return exit_code, out, err


def build_tar(project_root):
    """构建 tar.gz 字节流，排除大目录"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for dirpath, dirnames, filenames in os.walk(project_root):
            rel = os.path.relpath(dirpath, project_root)
            if rel == '.':
                rel_dir = ''
            else:
                rel_dir = rel.replace('\\', '/')
            
            # 排除大目录
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            
            for fname in filenames:
                # 排除 .env 和临时文件
                if fname in EXCLUDE_DIRS:
                    continue
                if any(fname.endswith(ext) for ext in ('.log', '.err', '.pyc', '$null')):
                    continue
                if fname.startswith('_') and fname.endswith('.py'):
                    continue
                if fname in ('.env', '.env.example') and rel_dir == 'deploy':
                    continue  # .env.example 保留，.env 排除
                
                abs_path = os.path.join(dirpath, fname)
                arcname = os.path.join(rel_dir, fname) if rel_dir else fname
                
                try:
                    tar.add(abs_path, arcname=arcname)
                except Exception as e:
                    pass  # 跳过无法读取的文件
    
    buf.seek(0)
    size_mb = buf.getbuffer().nbytes / (1024 * 1024)
    return buf.read(), size_mb


def main():
    print("=" * 60)
    print("🚀 药物原辅料知识问答助手 - 远程部署")
    print(f"📍 {USER}@{HOST}")
    print("=" * 60)

    # ── Step 1: SSH 连接 ──
    print("\n[1/7] 连接服务器...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, PORT, USER, PASSWORD, timeout=15)
    except Exception as e:
        print(f"❌ SSH 连接失败: {e}")
        return
    print("✅ 连接成功")

    # ── Step 2: 安装 Docker ──
    print("\n[2/7] 检查 Docker...")
    rc, _, _ = ssh_run(client, "docker --version", "Docker 版本")
    if rc != 0:
        print("⏳ Docker 未安装，正在安装（约 1 分钟）...")
        ssh_run(client, "curl -fsSL https://get.docker.com | sh", "安装 Docker", timeout=300)
    
    # 确保 ubuntu 用户在 docker 组（免 sudo 执行 docker 命令）
    ssh_run(client, "sudo usermod -aG docker $USER || true", "加入 docker 组")
    # 检查 docker 守护进程
    ssh_run(client, "sudo systemctl enable docker 2>/dev/null; sudo systemctl start docker 2>/dev/null; docker --version", "验证 Docker")
    
    rc2, out, _ = ssh_run(client, "docker compose version", "Compose 版本")
    if rc2 != 0:
        # 如果 docker compose 子命令不可用，尝试 docker-compose
        ssh_run(client, "apt-get update && apt-get install -y docker-compose-plugin", "安装 compose 插件", timeout=120)

    # ── Step 3: 创建远程目录 ──
    print("\n[3/7] 创建项目目录...")
    ssh_run(client, f"mkdir -p {REMOTE_DIR}", "创建目录")

    # ── Step 4: tar 上传项目文件 ──
    print("\n[4/7] 打包并上传项目文件...")
    tar_data, size_mb = build_tar(PROJECT_ROOT)
    print(f"    包大小: {size_mb:.1f} MB")
    
    # 用 sftp 写入临时 tar 包
    sftp = client.open_sftp()
    remote_tar = f"/tmp/pharma-deploy.tar.gz"
    with sftp.file(remote_tar, 'wb') as f:
        f.write(tar_data)
    sftp.close()
    print("✅ 文件上传完成")
    
    # 解压到目标目录
    ssh_run(client, f"cd {REMOTE_DIR} && tar xzf {remote_tar} && rm {remote_tar}", "解压项目")

    # ── Step 5: 生成 .env ──
    print("\n[5/7] 生成部署配置...")
    env_content = r"""# 生产环境变量 - 2026-08-03 生成
# ⚠️ 部署后务必修改以下密钥！
POSTGRES_PASSWORD=PharmaKB_2024_Secure_Pw
HOST=0.0.0.0
PORT=18082
DEBUG=false

# ── 大模型 API（从你的 .env 复制过来）──
DEEPSEEK_API_KEY=sk-你的deepseek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-flash

# ── 检索 API ──
TAVILY_API_KEY=tvly-你的tavily密钥
ANYSEARCH_API_KEY=你的anysearch密钥

# ── 安全（务必修改！）──
JWT_SECRET=pharma-jwt-$(openssl rand -hex 16)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=pharma@2024
"""
    env_path = f"{REMOTE_DIR}/deploy/.env"
    ssh_run(client, f"""cat > {env_path} << 'ENVEOF'
{env_content}
ENVEOF""", "写入 .env")
    
    # 生成随机 JWT secret
    ssh_run(client, f"sed -i 's/pharma-jwt-$(openssl rand -hex 16)/pharma-jwt-$(openssl rand -hex 16)/' {env_path}")

    # ── Step 6: 构建并启动 ──
    print("\n[6/7] 构建镜像并启动服务（首次约 3-5 分钟）...")
    ssh_run(client, f"cd {REMOTE_DIR}/deploy && sudo docker compose up -d --build", "docker compose up", timeout=600)

    # ── Step 7: 健康检查 ──
    print("\n[7/7] 等待服务就绪...")
    ready = False
    for i in range(60):
        rc, out, _ = ssh_run(client, "curl -sf http://localhost:80/api/health || echo FAIL", "健康检查", timeout=10)
        if rc == 0 and "FAIL" not in out:
            ready = True
            break
        time.sleep(3)
    
    print("\n" + "=" * 60)
    if ready:
        print("🎉 部署完成！")
        print("=" * 60)
        print(f"  🌐 访问地址: http://{HOST}")
        print(f"  👤 默认账号: admin")
        print(f"   默认密码: pharma@2024")
        print(f"")
        print(f"  ⚠️  请立即做以下修改（SSH 到服务器）：")
        print(f"    cd {REMOTE_DIR}/deploy")
        print(f"    sudo vi .env   # 填入真实 API Key，改密码和 JWT_SECRET")
        print(f"    sudo docker compose restart backend")
        print(f"")
        print(f"  📋 运维命令：")
        print(f"    sudo docker compose logs -f backend    # 看日志")
        print(f"    sudo docker compose restart backend    # 重启")
        print(f"    sudo docker compose down               # 停止")
    else:
        print("⚠️  服务未在 3 分钟内就绪，查看日志排查：")
        ssh_run(client, f"cd {REMOTE_DIR}/deploy && sudo docker compose logs --tail=80 backend", "后端日志")
    
    client.close()

if __name__ == "__main__":
    main()
