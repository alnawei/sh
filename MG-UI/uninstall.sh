#!/bin/bash
# MG 私有控制台 - 一键彻底卸载脚本

echo "=========================================="
echo "开始彻底卸载 MG 私有环境..."
echo "=========================================="

# 1. 停止并禁用 Systemd 守护进程
echo "[1/4] 停止并移除系统守护进程..."
systemctl stop mg-panel 2>/dev/null
systemctl disable mg-panel 2>/dev/null
rm -f /etc/systemd/system/mg-panel.service
systemctl daemon-reload

# 2. 暴力击杀所有底层存活的代理进程
echo "[2/4] 清理底层 MG 运行进程..."
pkill -f 'mg simple-run' 2>/dev/null
pkill -f 'mg_panel.py' 2>/dev/null

# 3. 备份数据库 (防误杀)
echo "[3/4] 备份数据库..."
if [ -f "/root/mg_core.db" ]; then
    mv /root/mg_core.db /root/mg_core.db.bak_$(date +%Y%m%d_%H%M%S)
    echo "  -> 数据库已备份至 /root/mg_core.db.bak_时间戳"
fi
# 如果你有旧版数据名也顺手备份
if [ -f "/root/mg_data.db" ]; then
    mv /root/mg_data.db /root/mg_data.db.bak_$(date +%Y%m%d_%H%M%S)
fi

# 4. 删除所有面板文件和核心底层程序
echo "[4/4] 抹除核心文件..."
rm -f /root/mg_panel.py /root/mg_executor.sh /root/index.html
rm -rf /etc/mg_conf
rm -f /usr/local/bin/mg
rm -rf /var/run/mg_*.pid

echo "=========================================="
echo "✅ 卸载完成！你的服务器已经恢复纯净状态。"
echo "=========================================="
