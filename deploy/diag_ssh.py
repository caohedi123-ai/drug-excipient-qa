"""诊断 SSH 连接问题"""
import paramiko

HOST = "119.28.14.114"
PASSWORD = "Sino123456789"

users = ["root", "ubuntu", "admin"]

for user in users:
    print(f"\n尝试 {user}@{HOST} ...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, 22, user, PASSWORD, timeout=10, allow_agent=False, look_for_keys=False)
        print(f"  ✅ 成功！用户 {user}")
        stdin, stdout, stderr = client.exec_command("whoami && uname -a && cat /etc/os-release | head -3")
        print(stdout.read().decode())
        client.close()
        break
    except paramiko.AuthenticationException as e:
        print(f"  ❌ 认证失败: {e}")
    except paramiko.SSHException as e:
        print(f"  ❌ SSH 错误: {e}")
    except Exception as e:
        print(f"  ❌ 其他错误: {e}")
    finally:
        client.close()
else:
    print("\n所有用户都认证失败，可能原因：")
    print("1. 服务器刚创建，SSH 服务还在启动中（等 2 分钟再试）")
    print("2. 密码不是 SSH 登录密码（可能是网页控制台密码）")
    print("3. 服务器只允许密钥认证")
    print("\n建议：在腾讯云控制台用「登录」按钮进入网页终端，执行：")
    print("  sudo apt install openssh-server")
    print("  echo 'ubuntu:你的密码' | sudo chpasswd")
    print("  sudo sed -i 's/#PasswordAuthentication/PasswordAuthentication/' /etc/ssh/sshd_config")
    print("  sudo systemctl restart ssh")
