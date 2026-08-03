# 交接文档：药物原辅料知识问答助手 · 云服务器部署

> **交接给 CodeBuddy** | 2026-08-03 14:30
> 项目部署已上线，本文档包含接手修复问题所需的全部上下文。

---

## 一、现状速览

| 项目 | 状态 |
|------|------|
| 线上地址 | **http://119.28.14.114**（腾讯云香港轻量 2核4G） |
| 登录 | `admin` / `pharma@2024`（⚠️ 待改） |
| 服务状态 | ✅ 全部正常（nginx + backend + postgres + redis 四容器） |
| 前端版本 | 2026-08-03 14:26 重新构建（`index-CXT7J7sW.js`） |
| 后端版本 | 2026-08-03 14:27 重建镜像，包含用户 12:20 最新代码 |
| 对话记忆 | ✅ PostgreSQL checkpointer（已修复降级问题） |
| API Keys | ✅ DeepSeek/Tavily/AnySearch 已同步 |

---

## 二、服务器连接

```
主机:   119.28.14.114
用户:   ubuntu
密码:   Sino123456789@      （⚠️ 敏感，勿外传）
系统:   Ubuntu 22.04.5 LTS
```

- 腾讯云轻量应用服务器，控制台可网页登录（同样账号）
- **注意**：SSH 用户是 `ubuntu` 不是 `root`；所有 docker 命令需 `sudo`

---

## 三、部署架构

```
/home/ubuntu/pharma-kb/
├── backend/          # FastAPI + LangGraph（Python 3.11）
├── frontend/         # Vite + React 19（dist 已构建）
└── deploy/           # 部署编排（重要！）
    ├── docker-compose.yml      # 四容器编排
    ├── Dockerfile.backend      # 后端镜像（代码 COPY 进镜像）
    ├── nginx.conf              # SSE 流式配置
    ├── .env                    # 生产密钥（勿提交 git）
    ├── deploy.sh               # 服务器端一键部署
    └── remote_deploy.py        # 本地一键部署脚本
```

四容器：
```
nginx:80 → 前端静态 + /api 反代（SSE 关缓冲）
backend:18082 → FastAPI + LangGraph Agent
postgres:5432 → 对话/反馈/checkpoint
redis:6379 → 缓存/记忆
```

**关键机制**：
- 后端代码是 **COPY 进镜像** 的 → 改代码必须 `docker compose up -d --build backend`，restart 不生效
- 前端 dist 是 **bind mount 挂载** 的 → 更新 dist 后必须 `docker compose restart nginx`
- ⚠️ **bind mount inode 坑**：`rm -rf dist` 重建目录后必须重启 nginx 重新挂载，否则看到旧文件/空目录

---

## 四、运维命令（SSH 到服务器后）

```bash
cd /home/ubuntu/pharma-kb/deploy

# 看后端日志（排错第一入口）
sudo docker compose logs -f backend

# 重启后端
sudo docker compose restart backend

# 更新代码后重建（后端改代码必用）
sudo docker compose up -d --build backend

# 前端更新后重启 nginx
sudo docker compose restart nginx

# 健康检查（含 checkpointer 状态）
curl -s http://localhost:80/api/health
```

---

## 五、今天的踩坑记录（修复问题必读）

### 1. PostgresSaver API 变更（已修，改在本地代码里）
- **症状**：健康检查 `checkpointer.degraded=true`，reason 为 `'_GeneratorContextManager' object has no attribute 'setup'`
- **根因**：`langgraph-checkpoint-postgres==2.0.1` 的 `PostgresSaver.from_conn_string()` 从普通方法改成了 **@contextmanager**，旧代码直接 `.setup()` 必然失败
- **修复**（`backend/agent/graph.py`）：
  ```python
  from psycopg_pool import ConnectionPool
  conninfo = settings.database_url_sync.replace("postgresql+psycopg2://", "postgresql://")
  pool = ConnectionPool(conninfo=conninfo, max_size=10, open=False)
  pool.open()
  checkpointer = PostgresSaver(pool)
  checkpointer.setup()
  ```
- **两个易错点**：ConnectionPool 不认 SQLAlchemy 的 `+psycopg2` 前缀要 replace；需要 `psycopg[binary]` 依赖（已加进 requirements.txt）

### 2. checkpoint_migrations 事务坑（已修，部署时处理）
- **症状**：`current transaction is aborted, commands ignored until end of transaction block`
- **根因**：psycopg 事务机制——`SELECT checkpoint_migrations` 抛 UndefinedTable 后事务进入 aborted 状态，后续建表全部失败
- **修复**：预建 `checkpoint_migrations (v INTEGER PRIMARY KEY)` 表再启动

### 3. 前端 403 / 显示旧版本（已修）
- **根因1**：打包时排除了 dist → nginx 挂载空目录 → 403
- **根因2**：dist 是 7/30 旧构建，但 src 8/2 改过 → 部署了旧前端
- **教训**：部署前检查 `find frontend/src -newer frontend/dist/index.html`；重新构建：`cd frontend && npm run build`

### 4. SSH 用户/权限（已修）
- 腾讯云 Ubuntu 默认用户 `ubuntu`（不是 root）
- `/opt` 无权限 → 项目放 `/home/ubuntu/pharma-kb/`

---

## 六、安全加固（已完成 + 待办）

**已完成**：
- `backend/main.py`：JWT_SECRET / ADMIN_USERNAME / ADMIN_PASSWORD 从硬编码改为环境变量注入（`os.environ.get` 向后兼容）

**待办（交给 CodeBuddy）**：
1. ⚠️ **改登录密码**：`deploy/.env` 的 `ADMIN_PASSWORD` 还是 `pharma@2024`，改成强密码后 `sudo docker compose restart backend`
2. ⚠️ **确认 JWT_SECRET**：检查是否强随机（部署脚本用 openssl 生成过，需验证）
3. **HTTPS**：腾讯云香港可申请免费 SSL 证书，nginx 加 443 配置
4. **数据库备份自动化**：建议 cron 每日 `pg_dump`（pgdata 是 Docker 卷，`docker compose down -v` 会清空，慎用）
5. **监控告警**：目前无监控，至少加 UptimeRobot 类免费探测

---

## 七、更新部署流程（用户说"更新部署"时）

```
1. 检查 git status，确认用户改了什么
2. 检查前端 dist 是否最新：find src -newer dist/index.html，不是则 npm run build
3. 打包上传：backend（排除 .venv/__pycache__/日志/mcp）→ tar 解压覆盖
               frontend/dist → tar 解压覆盖（先 rm -rf dist 再解压）
4. sudo docker compose up -d --build backend   （后端代码进镜像）
5. sudo docker compose restart nginx           （前端挂载重挂）
6. curl http://localhost:80/api/health 验证
7. md5 校验容器内 vs 宿主机关键文件
```

---

## 八、本地环境

- 项目根：`D:\药物原辅料知识问答助手`
- 后端：`backend/`（Python，本地 .venv，FastAPI 18082 端口）
- 前端：`frontend/`（Vite + React 19，dev 5173 端口，proxy 到 18082）
- 本地数据库：PostgreSQL 16（D 盘 pgdata，库名 pharma_kb）+ Redis
- 本地 `.env`：`backend/.env`（已含真实 API Keys，勿提交 git）
- git：3 个 commit，工作区还有未提交修改（用户 12:20 的更新 + 今天的修复）

---

## 九、已知待修复问题（用户口述，具体内容需沟通确认）

用户说"有一些问题"要 CodeBuddy 修，但**未列出具体清单**。接手时先问清楚：
- 检索/回答质量问题？（检索内核相关：`backend/tools/sources/*`、`agent/nodes/*`）
- 前端界面问题？（`frontend/src/components/*`）
- 部署运维问题？

**建议**：让用户打开 http://119.28.14.114 实际操作，把具体问题截图给 CodeBuddy，比口述更准确。

---

*交接人：WorkBuddy DevOps | 2026-08-03*
