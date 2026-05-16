#!/usr/bin/env bash

set -Eeuo pipefail

INSTALL_URL="${XUI_INSTALL_URL:-https://raw.githubusercontent.com/vaxilu/x-ui/master/install.sh}"
DEFAULT_USERNAME="${XUI_DEFAULT_USERNAME:-admin}"
DEFAULT_PASSWORD="${XUI_DEFAULT_PASSWORD:-admin}"
DEFAULT_PORT="${XUI_DEFAULT_PORT:-54321}"

RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
BOLD="\033[1m"
RESET="\033[0m"

run_as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

pause() {
  echo
  read -r -p "按回车返回主菜单: "
}

header() {
  clear 2>/dev/null || true
}

is_installed() {
  [[ -f /etc/systemd/system/x-ui.service || -x /usr/local/x-ui/x-ui || -x /usr/bin/x-ui ]]
}

require_installed() {
  if ! is_installed; then
    echo -e "${RED}请先安装 x-ui 面板。${RESET}"
    pause
    return 1
  fi
}

check_status() {
  if ! is_installed; then
    echo "not-installed"
  elif systemctl is-active --quiet x-ui 2>/dev/null; then
    echo "running"
  else
    echo "stopped"
  fi
}

show_status() {
  case "$(check_status)" in
    running) echo -e "面板状态: ${GREEN}已运行${RESET}" ;;
    stopped) echo -e "面板状态: ${YELLOW}未运行${RESET}" ;;
    *) echo -e "面板状态: ${RED}未安装${RESET}" ;;
  esac

  if is_installed && systemctl is-enabled x-ui >/dev/null 2>&1; then
    echo -e "是否开机自启: ${GREEN}是${RESET}"
  elif is_installed; then
    echo -e "是否开机自启: ${RED}否${RESET}"
  fi

  if pgrep -f "xray-linux" >/dev/null 2>&1; then
    echo -e "xray 状态: ${GREEN}运行${RESET}"
  elif is_installed; then
    echo -e "xray 状态: ${RED}未运行${RESET}"
  fi
}

run_install_script() {
  local tmp

  tmp="$(mktemp)"
  if ! curl -Ls "$INSTALL_URL" -o "$tmp"; then
    rm -f "$tmp"
    echo -e "${RED}下载安装脚本失败。${RESET}"
    pause
    return
  fi

  printf 'y\n%s\n%s\n%s\n' "$DEFAULT_USERNAME" "$DEFAULT_PASSWORD" "$DEFAULT_PORT" |
    run_as_root bash "$tmp"
  rm -f "$tmp"
}

install_xui() {
  header
  if is_installed; then
    echo -e "${YELLOW}面板已安装，如需更新请选择 2。${RESET}"
    pause
    return
  fi
  echo "正在安装 x-ui..."
  echo "默认用户名: ${DEFAULT_USERNAME}"
  echo "默认密码: ${DEFAULT_PASSWORD}"
  echo "默认端口: ${DEFAULT_PORT}"
  echo
  run_install_script
  pause
}

update_xui() {
  header
  require_installed || return
  echo "正在更新 x-ui..."
  echo "更新完成后会保持默认用户名、密码和端口。"
  echo
  run_install_script
  pause
}

uninstall_xui() {
  header
  require_installed || return
  read -r -p "确定卸载 x-ui 吗？[Y/n] " answer
  if [[ "$answer" =~ ^[Nn]$ ]]; then
    echo "已取消。"
    pause
    return
  fi
  run_as_root systemctl stop x-ui 2>/dev/null || true
  run_as_root systemctl disable x-ui 2>/dev/null || true
  run_as_root rm -f /etc/systemd/system/x-ui.service
  run_as_root systemctl daemon-reload 2>/dev/null || true
  run_as_root systemctl reset-failed 2>/dev/null || true
  run_as_root rm -rf /etc/x-ui /usr/local/x-ui
  echo -e "${GREEN}x-ui 已卸载。${RESET}"
  pause
}

reset_user() {
  header
  require_installed || return
  run_as_root /usr/local/x-ui/x-ui setting -username "$DEFAULT_USERNAME" -password "$DEFAULT_PASSWORD"
  run_as_root systemctl restart x-ui
  echo -e "${GREEN}用户名和密码已重置为 ${DEFAULT_USERNAME}/${DEFAULT_PASSWORD}。${RESET}"
  pause
}

reset_config() {
  header
  require_installed || return
  run_as_root /usr/local/x-ui/x-ui setting -reset
  run_as_root systemctl restart x-ui
  echo -e "${GREEN}面板设置已重置。${RESET}"
  pause
}

set_port() {
  header
  require_installed || return
  run_as_root /usr/local/x-ui/x-ui setting -port "$DEFAULT_PORT"
  run_as_root systemctl restart x-ui
  echo -e "${GREEN}面板端口已重置为 ${DEFAULT_PORT}。${RESET}"
  pause
}

show_config() {
  header
  require_installed || return
  run_as_root /usr/local/x-ui/x-ui setting -show true
  pause
}

start_xui() {
  header
  require_installed || return
  run_as_root systemctl start x-ui
  show_status
  pause
}

stop_xui() {
  header
  require_installed || return
  run_as_root systemctl stop x-ui
  show_status
  pause
}

restart_xui() {
  header
  require_installed || return
  run_as_root systemctl restart x-ui
  show_status
  pause
}

status_xui() {
  header
  require_installed || return
  run_as_root systemctl status x-ui -l --no-pager
  pause
}

log_xui() {
  header
  require_installed || return
  run_as_root journalctl -u x-ui.service -e --no-pager
  pause
}

enable_xui() {
  header
  require_installed || return
  run_as_root systemctl enable x-ui
  show_status
  pause
}

disable_xui() {
  header
  require_installed || return
  run_as_root systemctl disable x-ui
  show_status
  pause
}

install_bbr() {
  header
  bash <(curl -Ls https://raw.githubusercontent.com/teddysun/across/master/bbr.sh)
  pause
}

ssl_cert_issue() {
  header
  echo "SSL 证书申请仍使用官方 x-ui 菜单流程。"
  echo "请在官方菜单里选择 16。"
  echo
  if command -v x-ui >/dev/null 2>&1; then
    run_as_root x-ui
  else
    echo -e "${RED}x-ui 未安装。${RESET}"
    pause
  fi
}

show_menu() {
  header
  echo -e "  ${GREEN}x-ui 面板管理脚本${RESET}"
  echo "  0. 退出脚本"
  echo "————————————————"
  echo "  1. 安装 x-ui"
  echo "  2. 更新 x-ui"
  echo "  3. 卸载 x-ui"
  echo "————————————————"
  echo "  4. 重置用户名密码"
  echo "  5. 重置面板设置"
  echo "  6. 设置面板端口"
  echo "  7. 查看当前面板设置"
  echo "————————————————"
  echo "  8. 启动 x-ui"
  echo "  9. 停止 x-ui"
  echo "  10. 重启 x-ui"
  echo "  11. 查看 x-ui 状态"
  echo "  12. 查看 x-ui 日志"
  echo "————————————————"
  echo "  13. 设置 x-ui 开机自启"
  echo "  14. 取消 x-ui 开机自启"
  echo "————————————————"
  echo "  15. 一键安装 bbr (最新内核)"
  echo "  16. 一键申请SSL证书(acme申请)"
  echo
  show_status
  echo
}

main() {
  while true; do
    show_menu
    read -r -p "请输入选择 [0-16]: " choice
    case "$choice" in
      0) exit 0 ;;
      1) install_xui ;;
      2) update_xui ;;
      3) uninstall_xui ;;
      4) reset_user ;;
      5) reset_config ;;
      6) set_port ;;
      7) show_config ;;
      8) start_xui ;;
      9) stop_xui ;;
      10) restart_xui ;;
      11) status_xui ;;
      12) log_xui ;;
      13) enable_xui ;;
      14) disable_xui ;;
      15) install_bbr ;;
      16) ssl_cert_issue ;;
      *) echo "请输入正确的数字 [0-16]"; sleep 1 ;;
    esac
  done
}

main "$@"

