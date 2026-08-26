#!/bin/bash

set -e

APP_DIR=$(cd "$(dirname "$0")" && pwd)
SERVICE_NAME="longbridge2tg"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_DIR="/etc/longbridge2tg"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
VENV_DIR="${APP_DIR}/.venv"
# sudo 运行时 whoami 是 root；服务应该以真实登录用户运行。
SERVICE_USER="${SUDO_USER:-$(whoami)}"

echo "====================================="
echo "  开始安装 longbridge2tg (Debian/Ubuntu)"
echo "====================================="

if [ "$EUID" -ne 0 ]; then
    echo "请使用 root 权限运行: sudo bash install.sh"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "找不到 python3，请先执行: apt update && apt install -y python3 python3-venv python3-pip"
    exit 1
fi

# longbridge SDK 的 Linux wheel 要求 glibc >= 2.39（Debian 13 / Ubuntu 24.04+）。
GLIBC_VERSION=$(ldd --version | head -1 | awk '{for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+\.[0-9]+$/) {print $i; exit}}')
GLIBC_MAJOR=${GLIBC_VERSION%%.*}
GLIBC_MINOR=${GLIBC_VERSION##*.}
if [ -z "${GLIBC_VERSION}" ] || [ "${GLIBC_MAJOR}" -lt 2 ] || { [ "${GLIBC_MAJOR}" -eq 2 ] && [ "${GLIBC_MINOR}" -lt 39 ]; }; then
    echo "当前 glibc 版本为 ${GLIBC_VERSION:-未知}，过低（需要 >= 2.39，longbridge SDK 限制）。"
    echo "请改用 Docker 部署，步骤见 README.md 的 Docker 部署一节。"
    exit 1
fi

if [ ! -f "${APP_DIR}/config.yaml" ] && [ ! -f "${CONFIG_FILE}" ]; then
    echo "警告: 未找到配置文件。"
    echo "请复制 config.example.yaml 为 config.yaml 并填好后重新运行，或稍后手动放到 ${CONFIG_FILE}"
fi

echo "创建 Python 虚拟环境..."
if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
else
    echo "已存在 .venv，跳过创建"
fi

echo "安装依赖..."
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install "${APP_DIR}"

mkdir -p "${CONFIG_DIR}"
if [ ! -f "${CONFIG_FILE}" ] && [ -f "${APP_DIR}/config.yaml" ]; then
    cp "${APP_DIR}/config.yaml" "${CONFIG_FILE}"
    chmod 600 "${CONFIG_FILE}"
    chown "${SERVICE_USER}" "${CONFIG_FILE}"
    echo "配置文件已安装到 ${CONFIG_FILE}"
fi

echo "生成 systemd 服务文件: ${SERVICE_FILE}"
cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=Longbridge stock position Telegram reporter
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
Environment=LB2TG_CONFIG=${CONFIG_FILE}
ExecStart=${VENV_DIR}/bin/python -m longbridge2tg --config ${CONFIG_FILE}
Restart=always
RestartSec=5

# Minimal hardening for a service that only needs its config and network.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"

echo "====================================="
echo "  安装完成，服务已启动！"
echo "====================================="
echo "常用命令:"
echo "状态检查 : systemctl status ${SERVICE_NAME}"
echo "查看日志 : journalctl -u ${SERVICE_NAME} -f"
echo "停止服务 : systemctl stop ${SERVICE_NAME}"
echo "重启服务 : systemctl restart ${SERVICE_NAME}"
