#!/bin/bash
# ============================================
# StockPicker 部署脚本 - Ubuntu/Debian
# 用法: bash deploy.sh
# ============================================

set -e

APP_DIR="/opt/stock-picker"
SERVICE_NAME="stock-picker"
PYTHON="python3"

echo "=== [1/6] 安装系统依赖 ==="
apt update -qq
apt install -y -qq python3 python3-pip python3-venv git

echo "=== [2/6] 创建应用目录 ==="
mkdir -p "$APP_DIR"
# 注意：代码需要手动上传，脚本不会覆盖已有代码
if [ ! -f "$APP_DIR/backend/app/main.py" ]; then
    echo "请先将代码上传到 $APP_DIR"
    echo "在本地执行: scp -r ./backend ./frontend <用户名>@<服务器IP>:$APP_DIR/"
    exit 1
fi

echo "=== [3/6] 创建 Python 虚拟环境 ==="
cd "$APP_DIR/backend"
if [ ! -d "venv" ]; then
    $PYTHON -m venv venv
fi
source venv/bin/activate

echo "=== [4/6] 安装 Python 依赖 ==="
pip install --quiet --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install --quiet -r requirements.txt
else
    echo "requirements.txt 不存在，请确认依赖已安装"
    exit 1
fi

echo "=== [5/6] 配置环境变量 ==="
if [ ! -f "$APP_DIR/backend/.env" ]; then
    cat > "$APP_DIR/backend/.env" << 'EOF'
# ====== 请修改以下配置 ======
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
DATABASE_URL=sqlite+aiosqlite:///./stock_picker.db
EOF
    echo "已生成 .env 模板，请编辑 $APP_DIR/backend/.env 填入正确配置"
fi

echo "=== [6/6] 注册 systemd 服务 ==="
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=StockPicker Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR/backend
Environment="PATH=$APP_DIR/backend/venv/bin"
ExecStart=$APP_DIR/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl start $SERVICE_NAME

echo ""
echo "=== 部署完成 ==="
echo "服务状态: systemctl status $SERVICE_NAME"
echo "查看日志: journalctl -u $SERVICE_NAME -f"
echo "重启服务: systemctl restart $SERVICE_NAME"
echo "API 地址: http://$(hostname -I | awk '{print $1}'):8000"
echo ""
echo "请确保阿里云安全组已放行 8000 端口！"
