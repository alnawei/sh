#!/bin/bash
# MG 私有控制台 - 一键强制更新脚本 (破除CDN缓存)

echo "=========================================="
echo "开始强制更新 MG 面板与 Bot 代码..."
echo "=========================================="

# 生成当前时间戳，专门用来对付 GitHub CDN 的玄学缓存
TS=$(date +%s)
BASE_URL="https://raw.githubusercontent.com/alnawei/sh/main/MG-UI"

echo "正在从 GitHub 拉取最新代码..."
curl -sL "$BASE_URL/mg_panel.py?t=$TS" -o /root/mg_panel.py
curl -sL "$BASE_URL/mg_executor.sh?t=$TS" -o /root/mg_executor.sh
curl -sL "$BASE_URL/index.html?t=$TS" -o /root/index.html
curl -sL "$BASE_URL/mg_bot.py?t=$TS" -o /root/mg_bot.py

echo "重置文件执行权限..."
chmod +x /root/mg_panel.py
chmod +x /root/mg_executor.sh
chmod +x /root/mg_bot.py

echo "重启 MG 系统守护进程..."
systemctl restart mg-panel
systemctl restart mg-bot

echo "=========================================="
echo "✅ 更新完成！底层服务与机器人已自动重启。"
echo "👉 请回到浏览器，按下 Ctrl + F5 强制刷新网页即可看到最新效果！"
echo "=========================================="
