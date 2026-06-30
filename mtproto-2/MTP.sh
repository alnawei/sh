#!/usr/bin/env sh

# 脚本设置为在遇到错误时不强行退出，方便部分查询语句执行
set -e

# --- 全局配置 ---
BIN_PATH="/usr/local/bin/mtg"
CONFIG_DIR="/etc/mtg"
RELEASE_BASE_URL="https://github.com/9seconds/mtg/releases/download/v2.1.7"

GREEN='\033[32m'
YELLOW='\033[33m'
CYAN='\033[36m'
BOLD='\033[1m'
RESET='\033[0m'

# --- 1. 系统与环境检测 ---
# =================================

check_init_system() {
    pid1_comm=$(ps -o comm= 1 | tail -n 1 | tr -d ' ')
    if [ "$pid1_comm" = "systemd" ]; then
        INIT_SYSTEM="systemd"
    elif [ "$pid1_comm" = "init" ] && command -v rc-service >/dev/null 2>&1; then
        INIT_SYSTEM="openrc"
    else
        INIT_SYSTEM="direct"
    fi
    mkdir -p "$CONFIG_DIR"
    mkdir -p "/var/run"
}

check_deps() {
    required_cmds="curl grep cut uname tar mktemp awk find head ps"
    if [ "$INIT_SYSTEM" != "systemd" ]; then
        required_cmds="$required_cmds start-stop-daemon"
    fi

    deps_ok=true
    for cmd in $required_cmds; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            deps_ok=false; printf "错误: 缺少核心命令: %s\n" "$cmd"
        fi
    done
    if $deps_ok; then return; fi

    echo
    read -p "脚本依赖缺失，是否尝试自动安装？ (y/N): " answer
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        echo "错误: 缺少依赖，脚本无法继续运行！"; exit 1;
    fi

    if [ -f /etc/os-release ]; then . /etc/os-release; else
        echo "错误: 无法检测到操作系统类型！"; exit 1;
    fi

    case "$ID" in
        ubuntu|debian) apt-get update && apt-get install -y curl grep coreutils tar procps daemon awk ;;
        alpine) apk add --no-cache curl grep coreutils tar procps openrc awk ;;
        *) echo "警告: 无法自动安装依赖，请手动安装所需工具。" ;;
    esac
}

detect_arch() {
    arch=$(uname -m)
    case "$arch" in
        x86_64) echo "amd64" ;;
        i386|i686) echo "386" ;;
        aarch64) echo "arm64" ;;
        armv7l) echo "armv7" ;;
        armv6l) echo "armv6" ;;
        *) echo "unsupported" ;;
    esac
}

install_mtg_binary_if_missing() {
    if [ -f "$BIN_PATH" ]; then return 0; fi

    ARCH=$(detect_arch)
    if [ "$ARCH" = "unsupported" ]; then echo "错误: 不支持的系统架构：$(uname -m)"; exit 1; fi
    echo "检测到系统架构：$ARCH"

    TAR_NAME="mtg-2.1.7-linux-${ARCH}.tar.gz"
    DOWNLOAD_URL="${RELEASE_BASE_URL}/${TAR_NAME}"
    TMP_DIR=$(mktemp -d)
    trap 'rm -rf -- "$TMP_DIR"' EXIT
    
    echo "正在下载主程序 ${DOWNLOAD_URL} …"
    curl -L "${DOWNLOAD_URL}" -o "${TMP_DIR}/${TAR_NAME}"
    echo "正在解压文件..."
    tar -xzf "${TMP_DIR}/${TAR_NAME}" -C "${TMP_DIR}"

    MTG_FOUND_PATH=$(find "${TMP_DIR}" -type f -name mtg | head -n 1)
    if [ -z "$MTG_FOUND_PATH" ]; then echo "错误：未找到 mtg 可执行文件！"; exit 1; fi

    mv "${MTG_FOUND_PATH}" "${BIN_PATH}"
    chmod +x "${BIN_PATH}"
    echo "主程序已安装至 ${BIN_PATH}"
}

# --- 2. 服务管理 (基于端口号) ---
# =================================

is_running() {
    check_port="$1"
    pid_file="/var/run/mtg_${check_port}.pid"
    if [ -f "$pid_file" ]; then
        pid_val=$(cat "$pid_file" 2>/dev/null || echo "0")
        if [ -d "/proc/$pid_val" ]; then
            return 0
        fi
    fi
    return 1
}

start_service() {
    op_port="$1"
    config_file="${CONFIG_DIR}/config_${op_port}"
    pid_file="/var/run/mtg_${op_port}.pid"

    if ! [ -f "$config_file" ]; then echo "错误: 端口 [$op_port] 未配置。"; return 1; fi
    if is_running "$op_port"; then echo "端口 [$op_port] 已在运行中。"; return 0; fi

    echo "正在启动端口 [$op_port] 代理服务..."
    PORT=""; SECRET=""
    . "$config_file"
    
    start-stop-daemon --start --quiet --pidfile "$pid_file" --make-pidfile --background \
        --exec "$BIN_PATH" -- simple-run "0.0.0.0:${PORT}" "${SECRET}"
    sleep 1
    
    if is_running "$op_port"; then 
        printf '%b端口 [%s] 服务已启动。%b\n' "${GREEN}" "$op_port" "${RESET}"
    else 
        printf '%b端口 [%s] 服务启动失败。%b\n' "${YELLOW}" "$op_port" "${RESET}"
    fi
}

stop_service() {
    op_port="$1"
    pid_file="/var/run/mtg_${op_port}.pid"

    if ! is_running "$op_port"; then echo "端口 [$op_port] 未在运行。"; return 0; fi
    
    echo "正在停止端口 [$op_port] 服务..."
    start-stop-daemon --stop --quiet --pidfile "$pid_file"
    rm -f "$pid_file"
    echo "端口 [$op_port] 服务已停止。"
}

restart_service() {
    op_port="$1"
    if is_running "$op_port"; then stop_service "$op_port"; sleep 1; fi
    start_service "$op_port"
}

show_info() {
    info_port="$1"
    config_file="${CONFIG_DIR}/config_${info_port}"

    if ! [ -f "$config_file" ]; then echo "错误: 端口 [$info_port] 未配置。"; return; fi

    PORT=""; SECRET=""; FAKE_TLS_DOMAIN=""
    . "$config_file"
    
    IPV4=$(curl -s4 --connect-timeout 2 ip.sb || echo "你的服务器IP")
    echo
    printf '%b======= 端口 [%s] MTProxy 链接 =======%b\n' "${CYAN}" "$info_port" "${RESET}"
    echo "服务器地址: ${IPV4}"
    echo "端口:       ${PORT}"
    echo "密钥:       ${SECRET}"
    echo "伪装域名:   ${FAKE_TLS_DOMAIN}"
    echo
    printf '%btg://proxy?server=%s&port=%s&secret=%s%b\n' "${GREEN}" "${IPV4}" "${PORT}" "${SECRET}" "${RESET}"
    printf '%bhttps://t.me/proxy?server=%s&port=%s&secret=%s%b\n' "${GREEN}" "${IPV4}" "${PORT}" "${SECRET}" "${RESET}"
    echo
}

# --- 3. 核心功能逻辑 ---
# =================================

list_instances() {
    count=0
    for conf in "$CONFIG_DIR"/config_*; do
        if ! [ -f "$conf" ]; then continue; fi
        count=$((count+1))
        
        # 提取端口号 (移除 "config_" 前缀)
        port_name="${conf##*_}"
        
        PORT=""; SECRET=""; FAKE_TLS_DOMAIN=""
        . "$conf"
        
        if is_running "$port_name"; then 
            status="${GREEN}运行中${RESET}"
        else 
            status="${YELLOW}已停止${RESET}"
        fi
        
        printf ' [%d] 端口: %b%-5s%b | 伪装: %-18s | 状态: %b\n' "$count" "${CYAN}" "$PORT" "${RESET}" "${FAKE_TLS_DOMAIN:-无}" "$status"
    done
    if [ "$count" -eq 0 ]; then
        printf ' %b当前无任何线路配置。%b\n' "${YELLOW}" "${RESET}"
    fi
}

add_instance() {
    install_mtg_binary_if_missing
    echo
    printf '%b--- 添加新线路 ---%b\n' "${CYAN}" "${RESET}"
    
    while true; do
        read -p "请输入新的监听端口 (留空则随机分配): " NEW_PORT
        if [ -z "$NEW_PORT" ]; then 
            NEW_PORT=$(awk 'BEGIN{srand(); print int(10000 + rand()*50000)}')
        fi
        
        # 验证端口是否只有数字
        if ! [ "$NEW_PORT" -eq "$NEW_PORT" ] 2>/dev/null; then
            echo "错误: 端口必须是数字。"
            continue
        fi

        if [ -f "${CONFIG_DIR}/config_${NEW_PORT}" ]; then
            echo "错误: 端口 $NEW_PORT 已经存在，请重新输入。"
        else
            break
        fi
    done
    
    read -p "请输入用于伪装的域名 (默认 icloud.com): " NEW_DOMAIN
    if [ -z "$NEW_DOMAIN" ]; then NEW_DOMAIN="icloud.com"; fi
    
    NEW_SECRET=$("$BIN_PATH" generate-secret --hex "$NEW_DOMAIN")
    
    config_file="${CONFIG_DIR}/config_${NEW_PORT}"
    echo "PORT=${NEW_PORT}" > "$config_file"
    echo "SECRET=${NEW_SECRET}" >> "$config_file"
    echo "FAKE_TLS_DOMAIN=${NEW_DOMAIN}" >> "$config_file"
    
    echo
    printf '%b配置已生成并保存！%b\n' "${GREEN}" "${RESET}"
    start_service "$NEW_PORT"
    show_info "$NEW_PORT"
    
    read -p "按回车键返回主菜单..." dummy
}

edit_instance() {
    old_port="$1"
    conf="${CONFIG_DIR}/config_${old_port}"
    PORT=""; SECRET=""; FAKE_TLS_DOMAIN=""
    . "$conf"
    
    echo
    printf '%b--- 修改线路参数 ---%b\n' "${CYAN}" "${RESET}"
    read -p "请输入新的端口 (当前: $old_port, 留空保持不变): " EDIT_PORT
    if [ -z "$EDIT_PORT" ]; then EDIT_PORT=$old_port; fi
    
    if [ "$EDIT_PORT" != "$old_port" ] && [ -f "${CONFIG_DIR}/config_${EDIT_PORT}" ]; then
        echo "错误: 新端口 $EDIT_PORT 已经被其他线路占用！修改失败。"
        sleep 2
        return
    fi
    
    read -p "请输入新的伪装域名 (当前: $FAKE_TLS_DOMAIN, 留空保持不变): " EDIT_DOMAIN
    if [ -z "$EDIT_DOMAIN" ]; then EDIT_DOMAIN=$FAKE_TLS_DOMAIN; fi
    
    # 停止旧服务
    if is_running "$old_port"; then stop_service "$old_port"; fi
    
    # 重新生成 Secret
    NEW_SECRET=$("$BIN_PATH" generate-secret --hex "$EDIT_DOMAIN")
    
    # 如果端口变了，删除旧配置文件
    if [ "$EDIT_PORT" != "$old_port" ]; then
        rm -f "$conf"
    fi
    
    new_conf="${CONFIG_DIR}/config_${EDIT_PORT}"
    echo "PORT=${EDIT_PORT}" > "$new_conf"
    echo "SECRET=${NEW_SECRET}" >> "$new_conf"
    echo "FAKE_TLS_DOMAIN=${EDIT_DOMAIN}" >> "$new_conf"
    
    echo
    printf '%b线路已修改并保存！密钥已重新生成。%b\n' "${GREEN}" "${RESET}"
    start_service "$EDIT_PORT"
    read -p "按回车键继续..." dummy
}

delete_instance() {
    del_port="$1"
    echo
    read -p "确定要彻底删除端口 $del_port 的线路吗？(y/N): " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        stop_service "$del_port"
        rm -f "${CONFIG_DIR}/config_${del_port}"
        printf '%b已删除线路 %s%b\n' "${GREEN}" "$del_port" "${RESET}"
        
        # 检查是否还有剩余线路，如果没有则一并删除主程序
        sys_count=0
        for c in "${CONFIG_DIR}"/config_*; do
            if [ -f "$c" ]; then sys_count=$((sys_count+1)); fi
        done
        if [ "$sys_count" -eq 0 ]; then
            echo "当前已无任何线路，正在删除主程序..."
            rm -f "$BIN_PATH"
        fi
        sleep 1
    fi
}

manage_instance() {
    m_port="$1"
    while true; do
        clear 2>/dev/null || true
        conf="${CONFIG_DIR}/config_${m_port}"
        if ! [ -f "$conf" ]; then return; fi # 如果配置文件不在了（已被删除），退回主菜单
        
        PORT=""; SECRET=""; FAKE_TLS_DOMAIN=""
        . "$conf"
        
        if is_running "$m_port"; then 
            status="${GREEN}运行中${RESET}"
        else 
            status="${YELLOW}已停止${RESET}"
        fi
        
        printf '%b======= 管理线路 [端口: %s] =======%b\n' "${CYAN}" "$PORT" "${RESET}"
        echo "运行状态: $status"
        echo "伪装域名: $FAKE_TLS_DOMAIN"
        echo "代理密钥: $SECRET"
        echo "-------------------------------------"
        echo " 1. 启动服务"
        echo " 2. 停止服务"
        echo " 3. 重启服务"
        echo " 4. 查看 MTProxy 完整分享链接"
        echo " 5. 修改此线路 (端口 / 伪装域名 / 重新生成密钥)"
        echo " 6. 彻底删除此线路"
        echo " 0. 返回主菜单"
        echo
        read -p "请输入选项: " opt
        case "$opt" in
            1) start_service "$m_port"; read -p "按回车键继续..." dummy ;;
            2) stop_service "$m_port"; read -p "按回车键继续..." dummy ;;
            3) restart_service "$m_port"; read -p "按回车键继续..." dummy ;;
            4) show_info "$m_port"; read -p "按回车键继续..." dummy ;;
            5) edit_instance "$m_port"; return ;; # 端口可能发生改变，强制退回主菜单刷新
            6) delete_instance "$m_port"; return ;;
            0) return ;;
            *) echo "无效选项。"; sleep 1 ;;
        esac
    done
}

prompt_manage_instance() {
    echo
    read -p "请输入要管理的端口号: " input_port
    if [ -z "$input_port" ]; then return; fi
    if ! [ -f "${CONFIG_DIR}/config_${input_port}" ]; then
        printf '%b错误: 未找到端口 %s 的配置！%b\n' "${YELLOW}" "$input_port" "${RESET}"
        sleep 2
        return
    fi
    manage_instance "$input_port"
}

# --- 4. 主流程 ---
# =================================

main_menu() {
    while true; do
        clear 2>/dev/null || true
        printf '%b======= MTG (MTProxy) 多端口动态管理面板 =======%b\n' "${BOLD}${CYAN}" "${RESET}"
        echo
        list_instances
        echo
        printf '%b====================================================%b\n' "${CYAN}" "${RESET}"
        echo " 1. 添加新线路"
        echo " 2. 管理已有线路 (启动/停止/修改/删除)"
        echo " 0. 退出脚本"
        echo
        read -p "请输入选项: " opt
        case "$opt" in
            1) add_instance ;;
            2) prompt_manage_instance ;;
            0|q|Q) exit 0 ;;
            *) echo "无效选项，请重新输入。"; sleep 1 ;;
        esac
    done
}

main() {
    check_init_system
    check_deps
    main_menu
}

main
