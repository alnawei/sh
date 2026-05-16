#!/usr/bin/env bash

set -Eeuo pipefail

VERSION="0.1.0"
PROJECT_NAME="KEJI.SH"
SCRIPT_URL="${SCRIPT_URL:-https://raw.githubusercontent.com/alnawei/sh/main/toolbox.sh}"

latest_script_url() {
  local separator="?"

  if [[ "$SCRIPT_URL" == *"?"* ]]; then
    separator="&"
  fi

  echo "${SCRIPT_URL}${separator}t=$(date +%s)"
}

install_k_command() {
  local target="/usr/local/bin/k"
  local tmp

  tmp="$(mktemp)"
  cat >"$tmp" <<EOF
#!/usr/bin/env bash
SCRIPT_URL="$SCRIPT_URL"
separator="?"
if [[ "\$SCRIPT_URL" == *"?"* ]]; then
  separator="&"
fi
bash <(curl -fsSL -H 'Cache-Control: no-cache' "\${SCRIPT_URL}\${separator}t=\$(date +%s)") "\$@"
EOF
  chmod +x "$tmp"

  if [[ -w "$(dirname "$target")" ]]; then
    mv "$tmp" "$target"
  else
    sudo mv "$tmp" "$target"
  fi

  echo "已安装快捷命令: k"
  echo "以后在命令行输入 k 即可启动脚本。"
}

if [[ "${1:-}" == "--version" ]]; then
  echo "$PROJECT_NAME $VERSION"
  exit 0
fi

if [[ "${1:-}" == "--install-k" ]]; then
  install_k_command
  exit 0
fi

RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[34m"
CYAN="\033[36m"
BOLD="\033[1m"
RESET="\033[0m"

pause() {
  echo
  read -r -p "按回车返回菜单..."
}

run_as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

write_root_file() {
  local path="$1"

  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    tee "$path" >/dev/null
  else
    sudo tee "$path" >/dev/null
  fi
}

header() {
  clear 2>/dev/null || true
  echo -e "${CYAN}${BOLD}"
  cat <<'LOGO'
 _  __ _____     _ ___   ____  _   _
| |/ /| ____|   | |_ _| / ___|| | | |
| ' / |  _|  _  | || |  \___ \| |_| |
| . \ | |___| |_| || | _ ___) |  _  |
|_|\_\|_____|\___/|___(_)____/|_| |_|
LOGO
  echo -e "${RESET}"
  echo -e "${BLUE}Linux 运维工具箱 v${VERSION}${RESET}"
  echo -e "${CYAN}命令行输入 ${YELLOW}${BOLD}k${RESET}${CYAN} 可快速启动脚本${RESET}"
  echo
}

feature_placeholder() {
  local title="$1"
  header
  echo -e "${CYAN}${title}${RESET}"
  echo
  echo -e "${YELLOW}此功能待添加。${RESET}"
  pause
}

bbr_status() {
  local congestion_algorithm
  local queue_algorithm
  local available_algorithms

  congestion_algorithm="$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || true)"
  queue_algorithm="$(sysctl -n net.core.default_qdisc 2>/dev/null || true)"
  available_algorithms="$(cat /proc/sys/net/ipv4/tcp_available_congestion_control 2>/dev/null || true)"

  echo "当前 TCP 算法: ${congestion_algorithm:-未知}"
  echo "当前队列算法: ${queue_algorithm:-未知}"
  echo "可用 TCP 算法: ${available_algorithms:-未知}"
}

current_acceleration_name() {
  local congestion="$1"
  local qdisc="$2"

  case "${congestion}+${qdisc}" in
    bbr+fq) echo "BBR+FQ加速" ;;
    bbr+fq_pie) echo "BBR+FQ_PIE加速" ;;
    bbr+cake) echo "BBR+CAKE加速" ;;
    bbrplus+fq) echo "BBRplus+FQ版加速" ;;
    *) echo "${congestion:-未知}+${qdisc:-未知}" ;;
  esac
}

bbr_summary() {
  local congestion_algorithm
  local queue_algorithm
  local acceleration_name

  congestion_algorithm="$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || true)"
  queue_algorithm="$(sysctl -n net.core.default_qdisc 2>/dev/null || true)"
  acceleration_name="$(current_acceleration_name "$congestion_algorithm" "$queue_algorithm")"

  if [[ "$congestion_algorithm" == "bbr" || "$congestion_algorithm" == "bbrplus" ]]; then
    echo -e "BBR 状态: ${GREEN}已启动${RESET}"
    echo "当前加速: ${acceleration_name}"
  else
    echo -e "BBR 状态: ${YELLOW}未启动${RESET}"
    echo "当前加速: ${acceleration_name}"
  fi
}

load_kernel_module() {
  local module="$1"

  if command -v modprobe >/dev/null 2>&1; then
    run_as_root modprobe "$module" >/dev/null 2>&1 || true
  fi
}

apply_tcp_acceleration() {
  local title="$1"
  local congestion="$2"
  local qdisc="$3"

  header
  echo -e "${CYAN}${title}${RESET}"
  echo

  load_kernel_module "tcp_${congestion}"
  load_kernel_module "sch_${qdisc}"

  if ! grep -qw "$congestion" /proc/sys/net/ipv4/tcp_available_congestion_control 2>/dev/null; then
    echo -e "${RED}当前内核未检测到 ${congestion} 支持。${RESET}"
    echo "请先升级到支持 ${congestion} 的 Linux 内核。"
    pause
    return
  fi

  read -r -p "确定启用 ${title} 吗？[y/N] " answer
  if [[ ! "$answer" =~ ^[Yy]$ ]]; then
    echo "已取消。"
    pause
    return
  fi

  run_as_root mkdir -p /etc/sysctl.d
  printf '%s\n' \
    "net.core.default_qdisc=${qdisc}" \
    "net.ipv4.tcp_congestion_control=${congestion}" |
    write_root_file /etc/sysctl.d/99-keji-bbr.conf

  if run_as_root sysctl -w "net.core.default_qdisc=${qdisc}" >/dev/null 2>&1 &&
    run_as_root sysctl -w "net.ipv4.tcp_congestion_control=${congestion}" >/dev/null 2>&1; then
    echo -e "${GREEN}${title} 已启用。${RESET}"
  else
    echo -e "${RED}配置已写入，但立即生效失败。${RESET}"
    echo "可能是当前内核不支持 ${qdisc} 队列算法，可以重启后再查看状态。"
  fi

  echo
  bbr_status
  pause
}

bbr_manage() {
  while true; do
    header
    echo -e "${CYAN}BBR 管理${RESET}"
    echo "------------------------"
    bbr_status
    echo "------------------------"
    echo "———————————————————————————— 加速启用 ————————————————————————————"
    echo "1.  使用BBR+FQ加速          2.  使用BBR+FQ_PIE加速"
    echo "3.  使用BBR+CAKE加速        4.  使用BBRplus+FQ版加速"
    echo "——————————————————————————————————————————————————————————————————"
    bbr_summary
    echo
    echo "0.  返回主菜单"
    echo
    read -r -p "请输入你的选择: " sub_choice
    case "$sub_choice" in
      1) apply_tcp_acceleration "BBR+FQ加速" "bbr" "fq" ;;
      2) apply_tcp_acceleration "BBR+FQ_PIE加速" "bbr" "fq_pie" ;;
      3) apply_tcp_acceleration "BBR+CAKE加速" "bbr" "cake" ;;
      4) apply_tcp_acceleration "BBRplus+FQ版加速" "bbrplus" "fq" ;;
      0) return ;;
      *) echo -e "${RED}无效选择。${RESET}"; sleep 1 ;;
    esac
  done
}

show_menu() {
  header
  echo "1.  系统信息查询"
  echo "2.  系统更新"
  echo "3.  系统清理"
  echo "4.  BBR 管理"
  echo
  echo "00. 更新脚本"
  echo "0.  退出脚本"
  echo
}

update_script() {
  local tmp

  header
  echo -e "${CYAN}更新脚本${RESET}"
  echo
  install_k_command
  echo
  echo "正在拉取最新脚本并重新启动..."

  tmp="$(mktemp)"
  if curl -fsSL -H 'Cache-Control: no-cache' "$(latest_script_url)" -o "$tmp"; then
    chmod +x "$tmp"
    exec bash "$tmp"
  else
    rm -f "$tmp"
    echo -e "${RED}拉取最新脚本失败，请稍后重试。${RESET}"
    pause
  fi
}

main() {
  while true; do
    show_menu
    read -r -p "请输入你的选择: " choice
    case "$choice" in
      1) feature_placeholder "系统信息查询" ;;
      2) feature_placeholder "系统更新" ;;
      3) feature_placeholder "系统清理" ;;
      4) bbr_manage ;;
      00) update_script ;;
      0) echo "已退出。"; exit 0 ;;
      *) echo -e "${RED}无效选择。${RESET}"; sleep 1 ;;
    esac
  done
}

main "$@"
