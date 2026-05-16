#!/usr/bin/env bash

set -Eeuo pipefail

VERSION="0.1.0"
PROJECT_NAME="MYTOOL.SH"

if [[ "${1:-}" == "--version" ]]; then
  echo "$PROJECT_NAME $VERSION"
  exit 0
fi

RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[34m"
CYAN="\033[36m"
BOLD="\033[1m"
RESET="\033[0m"

need_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo -e "${YELLOW}此功能需要 sudo 权限。${RESET}"
    sudo -v
  fi
}

run_as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

pause() {
  echo
  read -r -p "按回车返回菜单..."
}

detect_pm() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v yum >/dev/null 2>&1; then
    echo "yum"
  elif command -v pacman >/dev/null 2>&1; then
    echo "pacman"
  elif command -v apk >/dev/null 2>&1; then
    echo "apk"
  else
    echo "unknown"
  fi
}

header() {
  clear
  echo -e "${CYAN}${BOLD}"
  cat <<'LOGO'
 __  __ __   __ _____ ___   ___  _       ____  _   _
|  \/  |\ \ / /|_   _/ _ \ / _ \| |     / ___|| | | |
| |\/| | \ V /   | || | | | | | | |     \___ \| |_| |
| |  | |  | |    | || |_| | |_| | |___ _ ___) |  _  |
|_|  |_|  |_|    |_| \___/ \___/|_____(_)____/|_| |_|
LOGO
  echo -e "${RESET}"
  echo -e "${BLUE}Linux 运维工具箱 v${VERSION}${RESET}"
  echo
}

system_info() {
  header
  echo -e "${CYAN}系统信息${RESET}"
  echo "主机名: $(hostname)"
  echo "用户: $(whoami)"
  echo "内核: $(uname -r)"
  echo "架构: $(uname -m)"
  echo "系统:"
  if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    echo "  ${PRETTY_NAME:-unknown}"
  else
    uname -a
  fi
  echo
  echo "CPU:"
  lscpu 2>/dev/null | sed -n '1,8p' || true
  echo
  echo "内存:"
  free -h 2>/dev/null || true
  echo
  echo "磁盘:"
  df -hT 2>/dev/null | sed -n '1,12p' || true
  pause
}

system_update() {
  header
  need_root
  pm="$(detect_pm)"
  echo -e "${CYAN}系统更新: ${pm}${RESET}"
  case "$pm" in
    apt) run_as_root apt-get update && run_as_root apt-get upgrade -y ;;
    dnf) run_as_root dnf upgrade -y ;;
    yum) run_as_root yum update -y ;;
    pacman) run_as_root pacman -Syu --noconfirm ;;
    apk) run_as_root apk update && run_as_root apk upgrade ;;
    *) echo -e "${RED}未识别到受支持的包管理器。${RESET}" ;;
  esac
  pause
}

system_clean() {
  header
  need_root
  pm="$(detect_pm)"
  echo -e "${CYAN}系统清理: ${pm}${RESET}"
  case "$pm" in
    apt) run_as_root apt-get autoremove -y && run_as_root apt-get clean ;;
    dnf) run_as_root dnf autoremove -y && run_as_root dnf clean all ;;
    yum) run_as_root yum autoremove -y || true; run_as_root yum clean all ;;
    pacman) run_as_root pacman -Sc --noconfirm ;;
    apk) run_as_root apk cache clean ;;
    *) echo -e "${RED}未识别到受支持的包管理器。${RESET}" ;;
  esac
  if command -v docker >/dev/null 2>&1; then
    echo
    read -r -p "是否清理 Docker 未使用资源？[y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      run_as_root docker system prune -f
    fi
  fi
  pause
}

install_basic_tools() {
  header
  need_root
  pm="$(detect_pm)"
  echo -e "${CYAN}安装常用工具${RESET}"
  case "$pm" in
    apt) run_as_root apt-get update && run_as_root apt-get install -y curl wget git vim nano htop unzip ca-certificates ;;
    dnf) run_as_root dnf install -y curl wget git vim nano htop unzip ca-certificates ;;
    yum) run_as_root yum install -y curl wget git vim nano htop unzip ca-certificates ;;
    pacman) run_as_root pacman -Sy --noconfirm curl wget git vim nano htop unzip ca-certificates ;;
    apk) run_as_root apk add --no-cache curl wget git vim nano htop unzip ca-certificates ;;
    *) echo -e "${RED}未识别到受支持的包管理器。${RESET}" ;;
  esac
  pause
}

install_docker() {
  header
  echo -e "${YELLOW}将从 Docker 官方安装脚本安装 Docker。${RESET}"
  read -r -p "继续？[y/N] " answer
  if [[ ! "$answer" =~ ^[Yy]$ ]]; then
    return
  fi
  curl -fsSL https://get.docker.com | sh
  run_as_root systemctl enable docker 2>/dev/null || true
  run_as_root systemctl start docker 2>/dev/null || true
  docker --version || true
  pause
}

docker_status() {
  header
  if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}未安装 Docker。${RESET}"
    pause
    return
  fi
  echo -e "${CYAN}Docker 状态${RESET}"
  docker --version
  echo
  docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" || true
  pause
}

network_info() {
  header
  echo -e "${CYAN}网络信息${RESET}"
  echo "公网 IP:"
  curl -fsSL https://api.ipify.org 2>/dev/null || echo "获取失败"
  echo
  echo
  echo "监听端口:"
  ss -tulpen 2>/dev/null | sed -n '1,20p' || netstat -tulpen 2>/dev/null | sed -n '1,20p' || true
  pause
}

service_manage() {
  header
  if ! command -v systemctl >/dev/null 2>&1; then
    echo -e "${RED}当前系统不支持 systemctl。${RESET}"
    pause
    return
  fi
  read -r -p "服务名: " service
  [[ -z "$service" ]] && return
  echo
  echo "1. 查看状态"
  echo "2. 启动"
  echo "3. 停止"
  echo "4. 重启"
  echo "5. 开机自启"
  echo "6. 取消自启"
  read -r -p "请选择: " action
  case "$action" in
    1) systemctl status "$service" --no-pager ;;
    2) run_as_root systemctl start "$service" ;;
    3) run_as_root systemctl stop "$service" ;;
    4) run_as_root systemctl restart "$service" ;;
    5) run_as_root systemctl enable "$service" ;;
    6) run_as_root systemctl disable "$service" ;;
    *) echo "无效选择" ;;
  esac
  pause
}

show_menu() {
  header
  echo "1.  系统信息查询"
  echo "2.  系统更新"
  echo "3.  系统清理"
  echo "4.  安装常用工具"
  echo "5.  安装 Docker"
  echo "6.  Docker 状态"
  echo "7.  网络信息"
  echo "8.  systemd 服务管理"
  echo
  echo "00. 脚本更新"
  echo "0.  退出脚本"
  echo
}

self_update() {
  header
  echo "请重新执行 GitHub Pages 或 Raw URL 中的最新命令即可获取新版脚本。"
  echo
  echo "示例:"
  echo "bash <(curl -fsSL https://USERNAME.github.io/REPO/toolbox.sh)"
  pause
}

main() {
  while true; do
    show_menu
    read -r -p "请输入你的选择: " choice
    case "$choice" in
      1) system_info ;;
      2) system_update ;;
      3) system_clean ;;
      4) install_basic_tools ;;
      5) install_docker ;;
      6) docker_status ;;
      7) network_info ;;
      8) service_manage ;;
      00) self_update ;;
      0) echo "已退出。"; exit 0 ;;
      *) echo -e "${RED}无效选择。${RESET}"; sleep 1 ;;
    esac
  done
}

main "$@"

