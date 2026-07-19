#!/usr/bin/env bash
# mg_executor.sh - MG 私有协议底层无状态执行器
# 专为 Python 后端 API 调度设计，禁止添加任何阻塞式 read 交互

set -e

# --- 隐蔽化全局配置 ---
BIN_PATH="/usr/local/bin/mg"
CONFIG_DIR="/etc/mg_conf"
PID_DIR="/var/run"

# 确保配置目录存在
mkdir -p "$CONFIG_DIR"

# --- 参数解析 ---
COMMAND=$1
PORT=$2
SECRET=$3
AD_TAG=$4   # 新增：接收第四个参数作为广告 Tag

PID_FILE="${PID_DIR}/mg_${PORT}.pid"

# --- 状态检测函数 ---
is_running() {
    if [ -f "$PID_FILE" ] && [ -d "/proc/$(cat "$PID_FILE" 2>/dev/null)" ]; then
        return 0 # 运行中
    else
        return 1 # 未运行
    fi
}

# --- 核心路由 ---
case "$COMMAND" in
    start)
        if [ -z "$PORT" ] || [ -z "$SECRET" ]; then
            echo "Error: start commands require PORT and SECRET."
            exit 1
        fi
        
        if is_running; then
            echo "Port [${PORT}] is already running."
            exit 0
        fi

        echo "Starting MG instance on port [${PORT}]..."
        
        # 🚀 核心修复：如果存在 AD_TAG，则加入 -a 参数启动
        if [ -n "$AD_TAG" ] && [ "$AD_TAG" != "None" ] && [ "$AD_TAG" != "null" ]; then
            EXEC_ARGS="simple-run -a $AD_TAG 0.0.0.0:${PORT} ${SECRET}"
            echo "With Ad Tag: $AD_TAG"
        else
            EXEC_ARGS="simple-run 0.0.0.0:${PORT} ${SECRET}"
        fi

        # 使用 start-stop-daemon 后台无感拉起二进制程序
        start-stop-daemon --start --quiet --pidfile "$PID_FILE" --make-pidfile --background \
            --exec "$BIN_PATH" -- $EXEC_ARGS
        
        sleep 1
        if is_running; then 
            echo "Success: Port [${PORT}] started."
        else 
            echo "Failed: Could not start port [${PORT}]."
            exit 1
        fi
        ;;

    stop)
        if [ -z "$PORT" ]; then
            echo "Error: stop command requires PORT."
            exit 1
        fi

        if ! is_running; then
            echo "Port [${PORT}] is not running."
            exit 0
        fi
        
        echo "Stopping MG instance on port [${PORT}]..."
        start-stop-daemon --stop --quiet --pidfile "$PID_FILE"
        rm -f "$PID_FILE"
        echo "Success: Port [${PORT}] stopped."
        ;;

    delete)
        if [ -z "$PORT" ]; then
            echo "Error: delete command requires PORT."
            exit 1
        fi

        # 1. 停止进程
        if is_running; then
            start-stop-daemon --stop --quiet --pidfile "$PID_FILE"
            rm -f "$PID_FILE"
        fi

        # 2. 清理遗留的可能配置文件 (若 Python 层需要持久化可存放在此)
        rm -f "${CONFIG_DIR}/config_${PORT}"
        
        echo "Success: Port [${PORT}] completely deleted from executor layer."
        ;;

    status)
        if [ -z "$PORT" ]; then
            echo "Error: status command requires PORT."
            exit 1
        fi

        if is_running; then
            echo "running"
        else
            echo "stopped"
        fi
        ;;

    *)
        echo "Usage: $0 {start|stop|delete|status} <PORT> [SECRET] [AD_TAG]"
        exit 1
        ;;
esac
