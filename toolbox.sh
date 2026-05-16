#!/usr/bin/env bash

set -Eeuo pipefail

VERSION="0.1.0"
PROJECT_NAME="KEJI.SH"
SCRIPT_URL="${SCRIPT_URL:-https://raw.githubusercontent.com/alnawei/sh/main/toolbox.sh}"

install_k_command() {
  local target="/usr/local/bin/k"
  local tmp

  tmp="$(mktemp)"
  cat >"$tmp" <<EOF
#!/usr/bin/env bash
bash <(curl -fsSL "$SCRIPT_URL") "\$@"
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
YELLOW="\033[33m"
BLUE="\033[34m"
CYAN="\033[36m"
BOLD="\033[1m"
RESET="\033[0m"

pause() {
  echo
  read -r -p "按回车返回菜单..."
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

show_menu() {
  header
  echo "1.  系统信息查询"
  echo "2.  系统更新"
  echo "3.  系统清理"
  echo "4.  安装常用工具"
  echo
  echo "00. 更新脚本"
  echo "0.  退出脚本"
  echo
}

update_script() {
  header
  echo -e "${CYAN}更新脚本${RESET}"
  echo
  install_k_command
  pause
}

main() {
  while true; do
    show_menu
    read -r -p "请输入你的选择: " choice
    case "$choice" in
      1) feature_placeholder "系统信息查询" ;;
      2) feature_placeholder "系统更新" ;;
      3) feature_placeholder "系统清理" ;;
      4) feature_placeholder "安装常用工具" ;;
      00) update_script ;;
      0) echo "已退出。"; exit 0 ;;
      *) echo -e "${RED}无效选择。${RESET}"; sleep 1 ;;
    esac
  done
}

main "$@"
