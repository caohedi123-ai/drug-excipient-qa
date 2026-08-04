"""本地 E2E 开发启动器（非生产入口）。

仅用于本地运行 E2E：在导入应用前于进程内环境设置
  - AUTH_DISABLED=1 : 关闭 JWT 鉴权（requires_auth 中读取，生产默认不设置）
  - PATH 补充 PostgreSQL 16 bin : 使 asyncpg 能加载 libpq.dll（Windows 环境常见缺失）

生产部署请直接 `python main.py`（或 uvicorn main:app），不要使用本文件。
"""
import os

os.environ["AUTH_DISABLED"] = "1"

_PG_BIN = r"C:\Program Files\PostgreSQL\16\bin"
_path = os.environ.get("PATH", "")
if _PG_BIN not in _path:
    os.environ["PATH"] = _PG_BIN + ";" + _path

import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=18082, reload=False)
