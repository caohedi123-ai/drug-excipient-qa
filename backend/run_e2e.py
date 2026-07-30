import subprocess, sys
result = subprocess.run(
    [sys.executable, "-X", "utf8", "e2e_v2.py"],
    capture_output=True, text=True, cwd="d:/药物原辅料知识问答助手/backend", timeout=1200
)
with open("e2e_out.txt", "w", encoding="utf-8") as f:
    f.write(result.stdout)
    if result.stderr:
        f.write("\n---STDERR---\n")
        f.write(result.stderr)
print("E2E done, exit code:", result.returncode)
