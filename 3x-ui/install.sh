#!/bin/bash

# ==========================================
# 3x-ui 自动化安装脚本
# ==========================================

# 1. 在这里修改为你想要的固定参数
PANEL_PORT=54321              # 固定面板端口
PANEL_USER="admin"   # 固定登录账号
PANEL_PASS="admin"   # 固定登录密码 (密钥)

# 确保脚本以 root 权限运行
if [[ $EUID -ne 0 ]]; then
   echo "错误: 请使用 root 权限运行此脚本 (例如: sudo bash script.sh)" 
   exit 1
fi

echo "=========================================="
echo "开始自动安装 3x-ui..."
echo "面板端口将设置为: $PANEL_PORT"
echo "面板账号将设置为: $PANEL_USER"
echo "=========================================="

# 2. 调用官方安装脚本，并通过 EOF 自动输入交互指令
# 交互顺序通常为: 是否自定义(y) -> 账号 -> 密码 -> 端口
bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh) <<EOF
y
$PANEL_USER
$PANEL_PASS
$PANEL_PORT
EOF

# 3. 安装完成后的提示
echo "=========================================="
echo "3x-ui 安装与配置完成！"
echo "请确保服务器防火墙已放行端口: $PANEL_PORT"
echo "访问地址: http://服务器IP:$PANEL_PORT"
echo "=========================================="
