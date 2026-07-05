#!/bin/bash
# MG 私有控制台 一键安装脚本

echo "=========================================="
echo "开始安装 MG 私有环境..."
echo "=========================================="

# 1. 更新系统并安装必要的环境
apt-get update
apt-get install -y curl wget python3 python3-pip iptables sqlite3 tar

# 2. 安装 Flask (适配最新的 Debian/Ubuntu 系统)
pip3 install flask --break-system-packages 2>/dev/null || pip3 install flask

# 3. 下载核心程序，并进行“私有化改名” (改名为 mg)
BIN_PATH="/usr/local/bin/mg"
if [ ! -f "$BIN_PATH" ]; then
    echo "正在下载核心组件..."
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64) DL_ARCH="amd64" ;;
        aarch64) DL_ARCH="arm64" ;;
        *) echo "不支持的架构: $ARCH"; exit 1 ;;
    esac
    
    wget -qO /tmp/mg_core.tar.gz "https://github.com/9seconds/mtg/releases/download/v2.1.7/mtg-2.1.7-linux-${DL_ARCH}.tar.gz"
    tar -xzf /tmp/mg_core.tar.gz -C /tmp
    
    # 找到解压出的原名文件，重命名并移动到 /usr/local/bin/mg
    find /tmp -type f -name mtg -exec mv {} "$BIN_PATH" \;
    chmod +x "$BIN_PATH"
    rm -rf /tmp/mg_core*
fi

# 4. 从 GitHub 仓库下载面板主程序
echo "正在拉取面板代码..."
# 请确保你的 GitHub 仓库路径已经改为了 mg-panel
curl -sL https://raw.githubusercontent.com/alnawei/sh/main/mg-panel/mg_panel.py -o /root/mg_panel.py

# 5. 配置 Systemd 守护进程 (实现后台运行和开机自启)
echo "配置后台服务..."
cat > /etc/systemd/system/mg-panel.service <<EOF
[Unit]
Description=MG Web Panel
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /root/mg_panel.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# 6. 启动服务
systemctl daemon-reload
systemctl enable mg-panel
systemctl restart mg-panel

echo "=========================================="
echo "✅ 安装完成！"
echo "👉 请在浏览器访问: http://$(curl -s4 ip.sb):8888"
echo " (请确保服务器防火墙已放行 8888 端口)"
echo "=========================================="
