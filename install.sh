#!/bin/bash
# ClawMate 安装脚本
# 用法:
#   sudo bash install.sh                     # 安装到当前目录
#   sudo bash install.sh /opt/clawmate       # 安装到指定路径
#   sudo bash install.sh --with-subtitle     # 安装字幕功能（~2GB）
#   sudo bash install.sh /opt/clawmate --with-subtitle

set -euo pipefail

# 解析参数
SUBITLE_FLAG=""
POSITIONAL_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --with-subtitle) SUBITLE_FLAG=1 ;;
    *) POSITIONAL_ARGS+=("$arg") ;;
  esac
done

CLAWMATE_DIR="${POSITIONAL_ARGS[0]:-$(cd "$(dirname "$0")" && pwd)}"
CLAWMATE_USER="${SUDO_USER:-$USER}"
CLAWMATE_PORT="${CLAWMATE_PORT:-5533}"

if [ "$EUID" -ne 0 ]; then
  echo "请用 sudo 执行（需写 /etc/systemd/system）"
  echo "  sudo bash install.sh $CLAWMATE_DIR"
  exit 1
fi

# 确保 config.json 存在
_CFG_PATH="$CLAWMATE_DIR/dev/config.json"
if [ ! -f "$_CFG_PATH" ]; then
  echo "创建 config.json（从 config.example.json 复制）..."
  cp "$CLAWMATE_DIR/config.example.json" "$_CFG_PATH"
  echo "⚠️  请编辑 $_CFG_PATH 填入实际配置"
fi

# 安装依赖
echo "安装 Python 依赖..."
pip3 install -r "$CLAWMATE_DIR/requirements.txt" --quiet

if [ -n "$SUBITLE_FLAG" ]; then
  echo "安装字幕功能依赖（faster-whisper ~2GB）..."
  pip3 install -r "$CLAWMATE_DIR/requirements-opt.txt" --quiet
  echo "  启用字幕功能：config.json 中设置 feedback.enable_subtitle: true"
fi

# 创建 systemd 服务
echo "安装 systemd 服务..."
cat > /etc/systemd/system/clawmate.service << UNIT
[Unit]
Description=ClawMate File Manager
After=network.target

[Service]
Type=simple
User=$CLAWMATE_USER
WorkingDirectory=$CLAWMATE_DIR/dev
ExecStart=/usr/bin/python3 main.py
Restart=on-failure
RestartSec=5
Environment=CLAWMATE_PORT=$CLAWMATE_PORT
Environment=CLAWMATE_CONFIG=$CLAWMATE_DIR/dev/config.json
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now clawmate
systemctl status clawmate --no-pager

echo ""
echo "✅ ClawMate 已安装"
echo "   路径: $CLAWMATE_DIR"
echo "   端口: $CLAWMATE_PORT"
echo "   systemctl restart clawmate  # 重启"
echo "   journalctl -u clawmate -f   # 看日志"
