# 药物原辅料知识问答助手 · 云服务器部署指南

> 部署到腾讯云香港服务器的一键方案。四容器：nginx（前端）+ FastAPI（后端）+ PostgreSQL + Redis。

---

## 一、为什么选腾讯云香港？

| 因素 | 腾讯云香港 | 大陆服务器 |
|------|-----------|-----------|
| 访问 openFDA / PubMed / ChEMBL / Tavily / Exa 等国外数据源 | ✅ 直连，快且稳 | ❌ 慢 / 超时 / 被墙，检索功能基本不可用 |
| 大陆用户访问速度 | 30~60ms，可接受 | 快，但数据源不通没意义 |
| Docker Hub 拉镜像 | ✅ 直连 | ⚠️ 慢，需配置国内镜像源 |
| 结算 | 支持国内支付、实名简单 | — |

**结论：本项目依赖国外数据源是刚需，选香港（或新加坡等境外节点）是正确选择。**
DeepSeek 是国内 API，从香港访问同样畅通，不受影响。

> 备选：如果一定要放大陆，需要另配海外反代/代理出口，增加成本和合规风险，不推荐。

---

## 二、服务器规格建议

- **轻量应用服务器 2核4G**（香港节点，约 50~80 元/月）即可流畅运行，5~10 个并发用户无压力
- 系统选 **Ubuntu 22.04 / Debian 12**
- 带宽 3Mbps 起步（SSE 流式文本为主，够用）
- 防火墙/安全组：放行 **80（HTTP）** 和 **22（SSH）**，如需 HTTPS 再加 443

---

## 三、部署步骤

### 第 1 步：准备文件

把项目整体上传到服务器（任选其一）：
- **推荐**：项目已接入 Git，`git clone` 到服务器
- 或：本地压缩项目目录（**不要**带 node_modules / .venv / .env），scp 上传解压

### 第 2 步：安装 Docker（腾讯云香港直连 Docker Hub，很快）

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # 重新登录生效
```

### 第 3 步：配置环境变量

```bash
cd deploy
cp .env.example .env
vi .env   # 填入：4 个 API Key + 数据库密码 + JWT 密钥 + 管理员密码
```

`.env` 必填项一览：

| 变量 | 说明 | 从哪拿 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | 大模型 | DeepSeek 开放平台 |
| `TAVILY_API_KEY` | 精搜 | Tavily 官网 |
| `ANYSEARCH_API_KEY` | 泛搜 | AnySearch 服务商 |
| `POSTGRES_PASSWORD` | 数据库密码 | 自己生成 |
| `JWT_SECRET` | 登录签名密钥 | 自己生成（32位+随机） |
| `ADMIN_PASSWORD` | 网页登录密码 | 自己生成 |

### 第 4 步：一键部署

```bash
bash deploy.sh
```

脚本会自动：构建后端镜像 → 启动 4 个容器 → 等待健康检查 → 输出访问地址。

### 第 5 步：验收

浏览器打开 `http://服务器IP` → 用 `.env` 里的账号密码登录 → 提问测试检索。

> ⚠️ 本地登录密码默认是 `admin@2024`，部署前**务必**在 `.env` 改掉。

---

## 四、常用运维命令

```bash
# 查看状态
docker compose ps

# 查看后端日志（排错第一入口）
docker compose logs -f backend

# 重启后端
docker compose restart backend

# 更新代码后重新部署
git pull && docker compose up -d --build

# 停止全部
docker compose down

# 数据备份（数据库卷）
docker compose exec postgres pg_dump -U postgres pharma_kb > backup.sql
```

---

## 五、常见问题

**Q1：页面能打开，但回答一直不吐字？**
→ nginx 的 SSE 缓冲已按本项目配置关闭。若仍异常，查 `docker compose logs backend` 是否报 API 密钥错误。

**Q2：检索结果为空/超时？**
→ 先在服务器上 curl 测试国外 API 连通性：
```bash
curl -sI https://eutils.ncbi.nlm.nih.gov   # PubMed
curl -sI https://api.fda.gov               # openFDA
```
香港节点直连通常 <500ms。

**Q3：HTTPS 怎么配？**
→ 腾讯云香港有免费 SSL 证书。拿到证书后在 nginx.conf 加 443 server 块，或在腾讯云控制台用 CDN/负载均衡挂证书。

**Q4：数据库数据丢了？**
→ 数据在 Docker 卷 `pgdata` 里，`docker compose down` 不会删除卷。只有 `docker compose down -v` 会清空（慎用）。

**Q5：想启用 ChEMBL MCP（本地 Node server）？**
→ 默认关闭、走 REST 检索。若启用，后端镜像需含 Node 运行时，需改 Dockerfile 加装 node，并设 `CHEMBL_MCP_ENABLED=true`。

---

## 六、本次安全加固说明

部署包对代码做了一处向后兼容的小改造（`backend/main.py`）：
- `JWT_SECRET`、管理员账号密码原先**硬编码在代码里**，现支持从环境变量读取（`JWT_SECRET` / `ADMIN_USERNAME` / `ADMIN_PASSWORD`）
- 本地开发不设这些变量时行为完全不变，公网部署则强制通过 `.env` 注入强密钥

---

**架构一览**

```
用户浏览器
   │  http://IP
   ▼
nginx(:80)  ── 前端静态文件（dist）
   │  /api/* 反代（SSE 流式，关缓冲）
   ▼
backend(:18082)  FastAPI + LangGraph Agent
   │  ├── DeepSeek（LLM）        🌐 国内 API
   │  ├── Tavily / AnySearch    🌐 国外 API（香港直连）
   │  ├── openFDA / PubMed / ChEMBL 🌐 国外数据源（香港直连）
   ├── PostgreSQL（对话/反馈存储）
   └── Redis（记忆/缓存）
```
