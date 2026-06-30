#!/usr/bin/env sh

# 脚本设置为在遇到错误时立即退出
set -e

# --- 全局配置 ---
BIN_PATH="/usr/local/bin/mtg"
CONFIG_DIR="/etc/mtg"
RELEASE_BASE_URL="https://github.com/9seconds/mtg/releases/download/v2.1.7"
DEFAULT_FAKETLS_DOMAIN="icloud.com"

GREEN='\033[32m'
YELLOW='\033[33m'
CYAN='\033[36m'
BOLD='\033[1m'
RESET='\033[0m'

# --- 1. 系统与环境检测 ---

check_init_system() {
    pid1_comm=$(ps -o comm= 1 2>/dev/null | tail -n 1 | tr -d ' ' || echo "unknown")
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
            deps_ok=false; echo "错误: 缺少核心命令: $cmd";
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
        ubuntu|debian) apt-get update && apt-get install -y curl grep coreutils tar procps daemon ;;
        alpine) apk add --no-cache curl grep coreutils tar procps openrc ;;
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

# --- 2. 服务管理 (基于端口) ---

is_running() {
    target_port="$1"
    pid_file="/var/run/mtg_${target_port}.pid"
    if [ -f "$pid_file" ] && [ -d "/proc/$(cat "$pid_file" 2>/dev/null)" ]; then
        return 0
    else
        return 1
    fi
}

start_service() {
    target_port="$1"
    config_file="${CONFIG_DIR}/config_${target_port}"
    pid_file="/var/run/mtg_${target_port}.pid"

    if ! [ -f "$config_file" ]; then echo "错误: 端口 [${target_port}] 未配置。"; return 1; fi
    if is_running "$target_port"; then echo "端口 [${target_port}] 已在运行中。"; return; fi

    echo "正在启动端口 [${target_port}] 服务..."
    # 读取配置
    . "$config_file"
    
    args="simple-run 0.0.0.0:${target_port} ${SECRET}"
    
    # 使用 start-stop-daemon 后台运行
    start-stop-daemon --start --quiet --pidfile "$pid_file" --make-pidfile --background \
        --exec "$BIN_PATH" -- ${args}
    
    sleep 1
    if is_running "$target_port"; then 
        echo -e "${GREEN}端口 [${target_port}] 服务已成功启动。${RESET}"
    else 
        echo -e "${YELLOW}端口 [${target_port}] 服务启动失败，请检查端口是否被占用。${RESET}"
    fi
}

stop_service() {
    target_port="$1"
    pid_file="/var/run/mtg_${target_port}.pid"

    if ! is_running "$target_port"; then echo "端口 [${target_port}] 服务未在运行。"; return; fi
    
    echo "正在停止端口 [${target_port}] 服务..."
    start-stop-daemon --stop --quiet --pidfile "$pid_file"
    rm -f "$pid_file"
    echo -e "${CYAN}端口 [${target_port}] 服务已停止。${RESET}"
}

restart_service() {
    target_port="$1"
    if is_running "$target_port"; then stop_service "$target_port"; sleep 1; fi
    start_service "$target_port"
}

# --- 3. 实例操作逻辑 ---

add_new_instance() {
    install_mtg_binary_if_missing

    echo
    echo -e "${CYAN}--- 添加新端口实例 ---${RESET}"
    while true; do
        read -p "请输入要分配的监听端口 (1-65535, 留空随机): " input_port
        if [ -z "$input_port" ]; then 
            PORT=$((10000 + RANDOM % 45535))
        else
            PORT=$input_port
        fi
        
        if [ -f "${CONFIG_DIR}/config_${PORT}" ]; then
            echo -e "${YELLOW}错误: 端口 $PORT 已经配置过，请更换一个。${RESET}"
        else
            break
        fi
    done

    read -p "请输入用于 FakeTLS 伪装的域名 (默认 icloud.com): " FAKE_TLS_DOMAIN
    if [ -z "$FAKE_TLS_DOMAIN" ]; then FAKE_TLS_DOMAIN="$DEFAULT_FAKETLS_DOMAIN"; fi
    
    # 生成密钥
    SECRET=$("$BIN_PATH" generate-secret --hex "$FAKE_TLS_DOMAIN")

    # 保存配置
    config_file="${CONFIG_DIR}/config_${PORT}"
    echo "PORT=${PORT}" > "$config_file"
    echo "SECRET=${SECRET}" >> "$config_file"
    echo "FAKE_TLS_DOMAIN=${FAKE_TLS_DOMAIN}" >> "$config_file"
    
    echo -e "${GREEN}配置已保存！(端口: ${PORT}, 伪装: ${FAKE_TLS_DOMAIN})${RESET}"
    start_service "$PORT"
    show_info "$PORT"
    
    echo "按回车键继续..."
    read -r dump
}

delete_instance() {
    target_port="$1"
    config_file="${CONFIG_DIR}/config_${target_port}"

    echo
    read -p "您确定要彻底卸载并删除端口 [${target_port}] 的实例吗？ [Y/n]: " confirm
    if [ "$confirm" = "n" ] || [ "$confirm" = "N" ]; then
        echo "操作已取消。"
        return
    fi

    if is_running "$target_port"; then
        stop_service "$target_port"
    fi

    rm -f "$config_file"
    echo -e "${GREEN}端口 [${target_port}] 实例已删除。${RESET}"

    # 检查是否还有其他实例，如果没有，询问是否卸载主程序
    # shellcheck disable=SC2012
    instance_count=$(ls -1 "${CONFIG_DIR}"/config_* 2>/dev/null | wc -l)
    if [ "$instance_count" -eq 0 ]; then
        echo -e "${YELLOW}当前已无任何代理实例运行。${RESET}"
        read -p "是否需要删除 mtg 主程序释放空间？ [y/N]: " del_bin
        if [ "$del_bin" = "y" ] || [ "$del_bin" = "Y" ]; then
            rm -f "$BIN_PATH"
            echo "mtg 主程序已删除。"
        fi
    fi
}

show_info() {
    target_port="$1"
    config_file="${CONFIG_DIR}/config_${target_port}"

    if ! [ -f "$config_file" ]; then echo "错误: 端口 [${target_port}] 未配置。"; return; fi

    . "$config_file"
    
    IPV4=$(curl -s4 --connect-timeout 2 ip.sb || echo "你的IP")
    echo
    echo -e "${CYAN}======= [端口 ${PORT}] 专属链接 =======${RESET}"
    echo -e "伪装域名: ${BOLD}${FAKE_TLS_DOMAIN}${RESET}"
    echo -e "服务器IP: ${BOLD}${IPV4}${RESET}"
    echo -e "监听端口: ${BOLD}${PORT}${RESET}"
    echo -e "安全密钥: ${BOLD}${SECRET}${RESET}"
    echo
    echo -e "Telegram 直连点击:"
    echo -e "${GREEN}tg://proxy?server=${IPV4}&port=${PORT}&secret=${SECRET}${RESET}"
    echo -e "${GREEN}https://t.me/proxy?server=${IPV4}&port=${PORT}&secret=${SECRET}${RESET}"
    echo -e "${CYAN}=======================================${RESET}"
}

# --- 4. 菜单与 UI ---

list_all_instances() {
    echo -e "${CYAN}=========== 运行中的实例列表 ===========${RESET}"
    # shellcheck disable=SC2012
    instance_count=$(ls -1 "${CONFIG_DIR}"/config_* 2>/dev/null | wc -l)
    
    if [ "$instance_count" -eq 0 ]; then
        echo -e "           ${YELLOW}暂无任何配置的实例${RESET}"
    else
        printf "%-10s | %-15s | %s\n" "端口" "状态" "伪装域名"
        printf "------------------------------------------\n"
        for conf in "${CONFIG_DIR}"/config_*; do
            [ -e "$conf" ] || continue
            . "$conf"
            
            if is_running "$PORT"; then
                status="${GREEN}运行中${RESET}"
            else
                status="${YELLOW}未运行${RESET}"
            fi
            # 格式化输出
            printf "%-10s | %-24b | %s\n" "$PORT" "$status" "${FAKE_TLS_DOMAIN:-none}"
        done
    fi
    echo -e "${CYAN}========================================${RESET}"
}

manage_single_instance() {
    echo
    read -p "请输入你要管理的【端口号】: " target_port
    
    if [ -z "$target_port" ] || [ ! -f "${CONFIG_DIR}/config_${target_port}" ]; then
        echo -e "${YELLOW}错误: 该端口不存在或未配置！${RESET}"
        sleep 1
        return
    fi

    while true; do
        clear 2>/dev/null || true
        echo -e "${CYAN}>>> 管理端口实例: [${target_port}] <<<${RESET}"
        
        status="${YELLOW}未运行${RESET}"
        if is_running "$target_port"; then status="${GREEN}运行中${RESET}"; fi
        echo -e "当前状态: $status"
        echo "---------------------------------"
        echo "  1. 启动服务"
        echo "  2. 停止服务"
        echo "  3. 重启服务"
        echo "  4. 查看分享链接"
        echo "  5. 删除此端口实例"
        echo "---------------------------------"
        echo "  0. 返回主菜单"
        echo
        read -p "请输入选项: " opt
        case "$opt" in
            1) start_service "$target_port"; sleep 1 ;;
            2) stop_service "$target_port"; sleep 1 ;;
            3) restart_service "$target_port"; sleep 1 ;;
            4) show_info "$target_port"; echo "按回车键继续..."; read -r dump ;;
            5) delete_instance "$target_port"; sleep 1; return ;;
            0|q) return ;;
            *) echo "无效选项。"; sleep 1 ;;
        esac
    done
}

main_menu() {
    while true; do
        clear 2>/dev/null || true
        list_all_instances
        echo
        echo "  1. ➕ 添加新端口实例 (FakeTLS)"
        echo "  2. ⚙️  管理已有端口实例 (启停/链接/删除)"
        echo "  0. ❌ 退出脚本"
        echo
        read -p "请输入选项 [0-2]: " opt
        case "$opt" in
            1) add_new_instance ;;
            2) manage_single_instance ;;
            0|q|Q) exit 0 ;;
            *) echo "无效选项，请重新输入。"; sleep 1 ;;
        esac
    done
}

# --- 5. 启动入口 ---
main() {
    check_init_system
    check_deps
    main_menu
}

main
