#!/bin/bash
# ClawMate Daemon 一键安装脚本
# 用法: curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
# 或:   wget -qO- https://raw.githubusercontent.com/.../install.sh | bash

set -euo pipefail

# ===== 配置 =====
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/clawmate"
SERVICE_FILE="/etc/systemd/system/clawmate.service"
BINARY_NAME="clawmate"
PORT="${CLAWMATE_PORT:-5533}"
VERSION="${CLAWMATE_VERSION:-latest}"

# ===== 颜色输出 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ===== 检查 root 权限 =====
require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    error "此脚本需要 root 权限运行。"
    echo "请使用: sudo bash install.sh"
    exit 1
  fi
}

# ===== 检测系统架构 =====
detect_arch() {
  local arch
  arch=$(uname -m)
  case "$arch" in
    x86_64|amd64)
      echo "amd64"
      ;;
    aarch64|arm64)
      echo "arm64"
      ;;
    armv7l|armv6l)
      echo "arm"
      ;;
    *)
      error "不支持的系统架构: $arch"
      exit 1
      ;;
  esac
}

# ===== 检测操作系统 =====
detect_os() {
  local os
  os=$(uname -s | tr '[:upper:]' '[:lower:]')
  case "$os" in
    linux)
      echo "linux"
      ;;
    darwin)
      echo "darwin"
      ;;
    *)
      error "不支持的操作系统: $os"
      exit 1
      ;;
  esac
}

# ===== 创建配置目录和 config.json 模板 =====
create_config() {
  if [ -f "$CONFIG_DIR/config.json" ]; then
    warn "配置文件已存在: $CONFIG_DIR/config.json"
    read -r -p "是否覆盖? (y/N): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
      info "保留现有配置文件"
      return
    fi
  fi

  mkdir -p "$CONFIG_DIR"

  cat > "$CONFIG_DIR/config.json" << 'CONFEOF'
{
  "port": 5533,
  "host": "0.0.0.0",
  "roots": [
    {
      "id": "default",
      "label": "默认目录",
      "dir": "/home/openclaw/media"
    }
  ],
  "defaultRootId": "default",
  "pageSize": 60,
  "cacheDir": "/var/cache/clawmate",
  "logLevel": "info"
}
CONFEOF

  # Replace port with configured value
  if [ "$PORT" != "5533" ]; then
    sed -i "s/\"port\": 5533/\"port\": $PORT/" "$CONFIG_DIR/config.json"
  fi

  ok "配置文件已创建: $CONFIG_DIR/config.json"
}

# ===== 创建 systemd service 文件 =====
create_service() {
  local user="${CLAWMATE_USER:-openclaw}"

  # Check if user exists
  if ! id -u "$user" >/dev/null 2>&1; then
    warn "用户 '$user' 不存在，将使用当前用户 '$SUDO_USER'"
    user="${SUDO_USER:-$(whoami)}"
  fi

  # Create cache dir
  mkdir -p /var/cache/clawmate
  chown "$user:$user" /var/cache/clawmate 2>/dev/null || true

  cat > "$SERVICE_FILE" << UNITEOF
[Unit]
Description=ClawMate File Manager
Documentation=https://github.com/example/clawmate
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${user}
Group=${user}
ExecStart=${INSTALL_DIR}/${BINARY_NAME}
Restart=on-failure
RestartSec=5
Environment=CLAWMATE_PORT=${PORT}
Environment=CLAWMATE_CONFIG=${CONFIG_DIR}/config.json

# 安全加固
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/cache/clawmate
PrivateTmp=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

# 日志
StandardOutput=journal
StandardError=journal
SyslogIdentifier=clawmate

[Install]
WantedBy=multi-user.target
UNITEOF

  ok "systemd service 已创建: $SERVICE_FILE"
}

# ===== 下载二进制（占位） =====
download_binary() {
  local os arch url
  os=$(detect_os)
  arch=$(detect_arch)

  info "检测到系统: ${os}/${arch}"

  # 占位: 实际部署时替换为真实下载 URL
  # 示例 URL 格式:
  #   https://github.com/USER/clawmate/releases/download/v1.0.0/clawmate_${os}_${arch}
  local download_url="${CLAWMATE_DOWNLOAD_URL:-}"

  if [ -z "$download_url" ]; then
    warn "未设置下载 URL (CLAWMATE_DOWNLOAD_URL)"
    warn "请手动将 clawmate 二进制文件放置到: ${INSTALL_DIR}/${BINARY_NAME}"
    warn "或通过环境变量指定: CLAWMATE_DOWNLOAD_URL=https://... install.sh"

    # Check if binary already exists
    if [ -f "${INSTALL_DIR}/${BINARY_NAME}" ]; then
      ok "发现已有二进制文件: ${INSTALL_DIR}/${BINARY_NAME}"
      return
    fi

    error "未找到二进制文件，安装中止。"
    echo ""
    echo "手动安装步骤:"
    echo "  1. 编译或下载 clawmate 二进制"
    echo "  2. sudo cp clawmate ${INSTALL_DIR}/${BINARY_NAME}"
    echo "  3. sudo chmod +x ${INSTALL_DIR}/${BINARY_NAME}"
    echo "  4. 重新运行此脚本: sudo bash install.sh"
    exit 1
  fi

  # 下载二进制
  info "正在下载 ${BINARY_NAME} ..."
  local tmpfile
  tmpfile=$(mktemp)
  if curl -fsSL --progress-bar -o "$tmpfile" "$download_url"; then
    mv "$tmpfile" "${INSTALL_DIR}/${BINARY_NAME}"
    chmod +x "${INSTALL_DIR}/${BINARY_NAME}"
    ok "二进制文件已下载并安装到: ${INSTALL_DIR}/${BINARY_NAME}"
  else
    rm -f "$tmpfile"
    error "下载失败: $download_url"
    exit 1
  fi
}

# ===== 启用并启动服务 =====
enable_service() {
  info "重新加载 systemd 配置..."
  systemctl daemon-reload

  info "启用 clawmate 服务（开机自启）..."
  systemctl enable clawmate

  info "启动 clawmate 服务..."
  if systemctl is-active --quiet clawmate 2>/dev/null; then
    systemctl restart clawmate
    ok "服务已重启"
  else
    systemctl start clawmate
    ok "服务已启动"
  fi

  # 等待服务就绪
  sleep 2
  if systemctl is-active --quiet clawmate; then
    ok "服务运行正常"
  else
    error "服务启动失败，请检查日志: journalctl -xeu clawmate"
    return 1
  fi
}

# ===== 打印安装摘要 =====
print_summary() {
  local ip
  ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

  echo ""
  echo -e "${GREEN}${BOLD}============================================${NC}"
  echo -e "${GREEN}${BOLD}  🦞 ClawMate 安装完成！${NC}"
  echo -e "${GREEN}${BOLD}============================================${NC}"
  echo ""
  echo -e "  访问地址:   ${BOLD}http://${ip}:${PORT}${NC}"
  echo -e "  配置文件:   ${CONFIG_DIR}/config.json"
  echo -e "  二进制路径: ${INSTALL_DIR}/${BINARY_NAME}"
  echo ""
  echo -e "  管理命令:"
  echo -e "    systemctl status  clawmate   # 查看状态"
  echo -e "    systemctl restart clawmate   # 重启服务"
  echo -e "    systemctl stop    clawmate   # 停止服务"
  echo -e "    journalctl -xeu   clawmate   # 查看日志"
  echo ""
  echo -e "  卸载:"
  echo -e "    sudo systemctl stop clawmate"
  echo -e "    sudo systemctl disable clawmate"
  echo -e "    sudo rm -f ${SERVICE_FILE}"
  echo -e "    sudo rm -f ${INSTALL_DIR}/${BINARY_NAME}"
  echo -e "    sudo rm -rf ${CONFIG_DIR}"
  echo ""
}

# ===== 主流程 =====
main() {
  echo ""
  echo -e "${BOLD}🦞 ClawMate Daemon 一键安装${NC}"
  echo "=================================="
  echo ""

  # 检查权限
  if [ "$(id -u)" -ne 0 ]; then
    error "需要 root 权限。请使用: sudo bash install.sh"
    echo ""
    echo "非 root 模式 (仅本地开发):"
    echo "  CLAWMATE_PORT=5533 ./clawmate"
    exit 1
  fi

  # 执行安装步骤
  detect_arch > /dev/null  # 验证架构
  create_config
  download_binary
  create_service
  enable_service
  print_summary
}

# 运行主流程
main "$@"
