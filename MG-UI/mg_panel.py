#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# mg_panel.py - MG 私有协议中控调度面板

import os
import re
import time
import sqlite3
import threading
import subprocess
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory

# ================= 核心配置区 =================
DB_FILE = "/root/mg_core.db"
EXECUTOR_SCRIPT = "/root/mg_executor.sh"
MG_BIN = "/usr/local/bin/mg"
FAKE_DOMAIN = "icloud.com"
WEB_PORT = 8888

# Flask 凭证与管理员账户配置
FLASK_SECRET = os.urandom(24) # 每次重启刷新 session，足够安全
ADMIN_USER = "admin"
ADMIN_PASS = "admin"          # 建议在实际使用中修改
# ==============================================

app = Flask(__name__)
app.secret_key = FLASK_SECRET

# 数据库写入锁，防止多线程并发写入导致的锁定异常
db_lock = threading.Lock()

# ================= 基础组件与数据库 =================

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        # status: running, stopped, blocked
        c.execute('''CREATE TABLE IF NOT EXISTS mg_nodes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      port INTEGER UNIQUE, 
                      secret TEXT, 
                      limit_gb REAL, 
                      used_bytes REAL DEFAULT 0,
                      status TEXT DEFAULT 'stopped')''')
        conn.commit()
        conn.close()

# ================= 底层 Shell & iptables 调度 =================

def run_executor(command, port, secret=""):
    """调用 mg_executor.sh 执行底层操作"""
    try:
        cmd = ["bash", EXECUTOR_SCRIPT, command, str(port)]
        if secret:
            cmd.append(secret)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def iptables_safe_execute(cmd):
    """安全执行 iptables，忽略退出码报错"""
    try:
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

def setup_iptables_monitor(port):
    """初始化端口的流量监听规则，先查后插防重复"""
    iptables_safe_execute(f"iptables -C OUTPUT -p tcp --sport {port} || iptables -I OUTPUT -p tcp --sport {port}")

def remove_iptables_rules(port):
    """彻底清除某个端口的所有监听和阻断规则"""
    iptables_safe_execute(f"iptables -D OUTPUT -p tcp --sport {port}")
    iptables_safe_execute(f"iptables -D INPUT -p tcp --dport {port} -j DROP")

def block_port(port):
    """流量超限，硬核阻断"""
    iptables_safe_execute(f"iptables -C INPUT -p tcp --dport {port} -j DROP || iptables -I INPUT -p tcp --dport {port} -j DROP")

def unblock_port(port):
    """解封端口"""
    iptables_safe_execute(f"iptables -D INPUT -p tcp --dport {port} -j DROP")

def get_iptables_bytes(port):
    """精准提取 iptables 记录的 OUTPUT 字节数"""
    try:
        res = subprocess.check_output(f"iptables -vxn -L OUTPUT | grep 'spt:{port}'", shell=True).decode('utf-8')
        if res:
            # iptables 格式解析：第2列通常是 bytes
            parts = res.strip().split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    except Exception:
        pass
    return 0

# ================= 后台监控守护线程 (Traffic Monitor) =================

def traffic_monitor_loop():
    """后台独立线程：每隔 60 秒轮询 iptables 更新流量，执行熔断"""
    while True:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT port, limit_gb, status FROM mg_nodes")
            nodes = c.fetchall()
            
            for node in nodes:
                port = node['port']
                limit_bytes = int(node['limit_gb'] * 1024 * 1024 * 1024)
                current_bytes = get_iptables_bytes(port)
                
                with db_lock:
                    # 更新数据库流量
                    c.execute("UPDATE mg_nodes SET used_bytes=? WHERE port=?", (current_bytes, port))
                    
                    # 熔断机制判定
                    if current_bytes >= limit_bytes and node['status'] == 'running':
                        block_port(port)
                        run_executor('stop', port) # 杀掉进程释放资源
                        c.execute("UPDATE mg_nodes SET status='blocked' WHERE port=?", (port,))
                        print(f"[Monitor] Port {port} quota exceeded, blocked.")
                    
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Monitor Error] {e}")
        
        time.sleep(60)

# ================= Flask 鉴权与 API 路由 =================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({"success": False, "msg": "未授权访问，请先登录"}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/mg-api/login', methods=['POST'])
def login():
    data = request.json
    if data and data.get('username') == ADMIN_USER and data.get('password') == ADMIN_PASS:
        session['logged_in'] = True
        return jsonify({"success": True, "msg": "登录成功"})
    return jsonify({"success": False, "msg": "用户名或密码错误"}), 401

@app.route('/mg-api/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return jsonify({"success": True})

@app.route('/mg-api/nodes', methods=['GET'])
@login_required
def get_nodes():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, port, secret, limit_gb, used_bytes, status FROM mg_nodes ORDER BY port ASC")
    nodes = [dict(row) for row in c.fetchall()]
    conn.close()
    
    server_ip = os.popen("curl -s4 --connect-timeout 2 ip.sb || echo '127.0.0.1'").read().strip()
    
    # 格式化数据给前端
    for node in nodes:
        node['used_gb'] = round(node['used_bytes'] / (1024**3), 3)
        node['link'] = f"tg://proxy?server={server_ip}&port={node['port']}&secret={node['secret']}"
        
    return jsonify({"success": True, "data": nodes})

@app.route('/mg-api/node/add', methods=['POST'])
@login_required
def add_node():
    data = request.json
    port = int(data.get('port'))
    limit_gb = float(data.get('limit_gb'))
    
    # 使用 subprocess 直接获取 secret
    try:
        secret = subprocess.check_output(f"{MG_BIN} generate-secret --hex {FAKE_DOMAIN}", shell=True).decode('utf-8').strip()
    except:
        return jsonify({"success": False, "msg": "底层 Secret 生成失败，请检查二进制文件环境"})
    
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute("INSERT INTO mg_nodes (port, secret, limit_gb, status) VALUES (?, ?, ?, 'running')", 
                      (port, secret, limit_gb))
            conn.commit()
            conn.close()
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "msg": f"端口 {port} 已存在"})

    # 初始化网络与进程
    setup_iptables_monitor(port)
    unblock_port(port)
    success = run_executor('start', port, secret)
    
    if success:
        return jsonify({"success": True, "msg": "节点已成功创建并运行"})
    else:
        return jsonify({"success": False, "msg": "数据库写入成功，但底层进程拉起失败"})

@app.route('/mg-api/node/toggle', methods=['POST'])
@login_required
def toggle_node():
    data = request.json
    port = int(data.get('port'))
    action = data.get('action') # 'start' or 'stop'
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT secret, status FROM mg_nodes WHERE port=?", (port,))
    row = c.fetchone()
    if not row:
        return jsonify({"success": False, "msg": "未找到该节点"})
    
    status = row['status']
    secret = row['secret']

    if action == 'start' and status != 'running':
        # 强制清除 block 状态并启动
        unblock_port(port)
        run_executor('start', port, secret)
        new_status = 'running'
    elif action == 'stop' and status == 'running':
        # 停止进程但保留 iptables 统计
        run_executor('stop', port)
        new_status = 'stopped'
    else:
        return jsonify({"success": True, "msg": "状态无需变更"})

    with db_lock:
        c.execute("UPDATE mg_nodes SET status=? WHERE port=?", (new_status, port))
        conn.commit()
    conn.close()
    
    return jsonify({"success": True, "msg": f"节点已{ '启动' if new_status == 'running' else '停止' }"})

@app.route('/mg-api/node/delete', methods=['POST'])
@login_required
def delete_node():
    port = int(request.json.get('port'))
    
    # 清理所有底层配置和进程
    run_executor('delete', port)
    remove_iptables_rules(port)
    
    # 清理数据库
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM mg_nodes WHERE port=?", (port,))
        conn.commit()
        conn.close()
        
    return jsonify({"success": True, "msg": "节点已彻底删除"})

@app.route('/mg-api/node/reset_traffic', methods=['POST'])
@login_required
def reset_traffic():
    port = int(request.json.get('port'))
    
    # 重置 iptables 计数：先删再加即可清零
    remove_iptables_rules(port)
    setup_iptables_monitor(port)
    
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE mg_nodes SET used_bytes=0 WHERE port=?", (port,))
        conn.commit()
        conn.close()
        
    return jsonify({"success": True, "msg": "流量已重置清零"})

# ================= 网页前端路由 =================

@app.route('/')
def index():
    # 第三步：将在这里下发基于 Vue 的 X-UI 风格单页面
    return send_from_directory('.', 'index.html')

# ================= 启动引导 =================

if __name__ == '__main__':
    # 1. 初始化数据库
    init_db()
    
    # 2. 启动后台流量监控线程 (设为 Daemon，随主进程退出而退出)
    monitor_thread = threading.Thread(target=traffic_monitor_loop)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # 3. 启动 Flask 面板 (绑定在 0.0.0.0，关闭 debug 防泄漏)
    print(f"[MG-Panel] Starting private console on port {WEB_PORT}...")
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True)
