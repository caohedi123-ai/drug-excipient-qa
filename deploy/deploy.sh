#!/usr/bin/env bash
# ============================================================
# 药物原辅料知识问答助手 - 一键部署脚本
# 用法（在云服务器 deploy/ 目录下执行）：
#   bash deploy.sh
# ============================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

cd "$(dirname "$0")"

# ── [1/5] 检查 Docker ──
info "[1/5] 检查 Docker 环境..."
command -v docker >/dev/null 2>&1 || fail "未安装 Docker。腾讯云香港服务器请先执行：curl -fsSL https://get.docker.com | sh"
docker compose version >/dev/null 2>&1 || fail "Docker Compose 不可用（需 v2）"

# ── [2/5] 检查 .env ──
info "[2/5] 检查 .env 配置文件..."
if [ ! -f .env ]; then
    cp .env.example .env
    fail "已生成 .env 模板。请先编辑 .env 填入 API Key / 数据库密码 / JWT 密钥，再重新运行本脚本。"
fi

# 校验必填项是否还是占位值
if grep -qE "请改成|sk-你的|tvly-你的|你的anysearch" .env; then
    fail "检测到 .env 中仍有占位值未填写，请编辑 .env 后再运行。"
fi

# ── [3/5] 校验前端构建产物 ──
info "[3/5] 校验前端构建产物..."
if [ ! -d ../frontend/dist ]; then
    warn "缺少 frontend/dist 构建产物。将在服务器上重新构建前端（需要 Node 22）..."
    command -v node >/dev/null 2>&1 || fail "服务器无 Node，请本地构建前端后上传 dist 目录，或先安装 Node 22。"
    (cd ../frontend && npm ci && npm run build) || fail "前端构建失败"
fi

# ── [4/5] 构建并启动 ──
info "[4/5] 构建并启动容器（首次拉取镜像可能需要几分钟）..."
docker compose up -d --build

# ── [5/5] 等待服务就绪 ──
info "[5/5] 等待服务就绪..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:80/api/health >/dev/null 2>&1; then
        info "✅ 部署完成！服务已就绪。"
        IP=$(curl -sf ifconfig.me 2>/dev/null || echo "服务器IP")
        echo ""
        echo "===================================================="
        echo "  访问地址：http://${IP}"
        echo "  登录账号：$(grep '^ADMIN_USERNAME=' .env | cut -d= -f2)"
        echo "  登录密码：.env 中 ADMIN_PASSWORD 的值"
        echo "  查看日志：docker compose logs -f backend"
        echo "===================================================="
        exit 0
    fi
    sleep 2
done

fail "服务未在 2 分钟内就绪。请执行 docker compose logs backend 排查。"
