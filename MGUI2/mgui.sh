#!/bin/bash
# MG 私有控制台 - 全局交互式管理菜单

# --- 颜色定义 ---
red='\033[0;31m'
green='\033[0;32m'
yellow='\033[0;33m'
plain='\033[0m'

# 检查是否为 root 用户
[[ $EUID -ne 0 ]] && echo -e "${red}错误: 必须使用 root 用户运行此脚本！${plain}\n" && exit 1

# 提取面板当前端口
get_panel_port() {
    if [ -f "/root/mg_panel.py" ]; then
        grep "PANEL_PORT =" /root/mg_panel.py | awk -F '=' '{print $2}' | tr -d ' '
    else
        echo "未知"
    fi
}

show_status() {
    if systemctl is-active --quiet mg-panel 2>/dev/null; then
        echo -e "面板状态: ${green}已运行${plain}"
        echo -e "面板端口: ${green}$(get_panel_port)${plain}"
    else
        echo -e "面板状态: ${red}未运行 / 未安装${plain}"
    fi
}

# --- 核心功能调用 ---
install_mg() { bash <(curl -sL https://raw.githubusercontent.com/alnawei/sh/main/MG-UI/install.sh); }
update_mg() { bash <(curl -sL https://raw.githubusercontent.com/alnawei/sh/main/MG-UI/update.sh); }
uninstall_mg() { bash <(curl -sL https://raw.githubusercontent.com/alnawei/sh/main/MG-UI/uninstall.sh); }

# --- 菜单界面 ---
show_menu() {
    clear
    echo -e "
  ${green}🛡️ MG 私有节点管控中心${plain} 
  ${yellow}--- 核心操作 ---${plain}
  ${green}1.${plain} 安装 MG 面板
  ${green}2.${plain} 更新 MG 面板 (强制破除缓存)
  ${green}3.${plain} 彻底卸载 MG
  ${yellow}--- 面板控制 ---${plain}
  ${green}4.${plain} 启动 MG 面板
  ${green}5.${plain} 停止 MG 面板
  ${green}6.${plain} 重启 MG 面板
  ${green}7.${plain} 查看 面板运行状态
  ${green}8.${plain} 查看 面板实时日志 (Ctrl+C 退出)
  ${yellow}--- 面板设置 ---${plain}
  ${green}9.${plain} 修改 面板登录账号与密码
  ${green}10.${plain}修改 面板访问端口
  ${yellow}----------------${plain}
  ${green}0.${plain} 退出菜单
    "
    show_status
    echo && read -p "请输入选择 [0-10]: " num

    case "${num}" in
        0) exit 0 ;;
        1) install_mg ;;
        2) update_mg ;;
        3) uninstall_mg ;;
        4) systemctl start mg-panel && echo -e "${green}MG 面板已启动${plain}" ;;
        5) systemctl stop mg-panel && echo -e "${green}MG 面板已停止${plain}" ;;
        6) systemctl restart mg-panel && echo -e "${green}MG 面板已重启${plain}" ;;
        7) systemctl status mg-panel ;;
        8) journalctl -u mg-panel -n 100 -f ;;
        9) 
            if [ ! -f "/root/mg_panel.py" ]; then echo -e "${red}错误: 未找到面板文件，请先安装！${plain}"; else
                read -p "请输入新账号: " new_user
                read -p "请输入新密码: " new_pass
                sed -i "s/PANEL_USER = .*/PANEL_USER = \"$new_user\"/g" /root/mg_panel.py
                sed -i "s/PANEL_PASS = .*/PANEL_PASS = \"$new_pass\"/g" /root/mg_panel.py
                systemctl restart mg-panel
                echo -e "${green}✅ 账号密码已修改并重启生效！${plain}"
            fi
            ;;
        10)
            if [ ! -f "/root/mg_panel.py" ]; then echo -e "${red}错误: 未找到面板文件，请先安装！${plain}"; else
                read -p "请输入新面板端口 (1-65535): " new_port
                sed -i "s/PANEL_PORT = .*/PANEL_PORT = $new_port/g" /root/mg_panel.py
                systemctl restart mg-panel
                echo -e "${green}✅ 面板端口已修改为 $new_port 并重启生效！${plain} (请记得去安全组放行新端口)"
            fi
            ;;
        *) echo -e "${red}请输入正确的数字 [0-10]${plain}" ;;
    esac
}

# 循环显示菜单，直到用户选择退出
while true; do
    show_menu
    echo -e "\n按任意键继续..."
    read -n 1 -s -r -p ""
done
