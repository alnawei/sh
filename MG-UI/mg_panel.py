#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# mg_panel.py - MG 私有协议中控调度面板 (Production + Watchdog Version)

import os
import time
import socket
import sqlite3
import threading
import subprocess
import calendar
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory

# ================= 核心配置区 =================
DB_FILE = "/root/mg_core.db"
EXECUTOR_SCRIPT = "/root/mg_executor.sh"
MG_BIN = "/usr/local/bin/mg"
FAKE_DOMAIN = "icloud.com"
WEB_PORT = 8888

FLASK_SECRET = os.urandom(24) 
ADMIN_USER = "admin"
ADMIN_PASS = "admin"          
# ==============================================

app = Flask(__name__)
app.secret_key = FLASK_SECRET
db_lock = threading.Lock()

# ================= 辅助函数：自然月递增 =================
def add_months(sourcedate, months):
    """精准自然月递增（自动处理 31 号到 28/30 号的容错进位）"""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return sourcedate.replace(year=year, month=month, day=day)

# ================= 基础组件与数据库 =================

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=20.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS mg_nodes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      port INTEGER UNIQUE, 
                      secret TEXT, 
                      limit_gb REAL, 
                      used_bytes REAL DEFAULT 0,
                      status TEXT DEFAULT 'stopped',
                      reset_cycle TEXT DEFAULT 'never',
                      expiry_date TEXT DEFAULT '',
                      last_reset_date TEXT DEFAULT '')''')
        
                      
        c.execute("PRAGMA table_info(mg_nodes)")
        existing_columns = [col['name'] for col in c.fetchall()]
        
        migrations = {
            "reset_cycle": "ALTER TABLE mg_nodes ADD COLUMN reset_cycle TEXT DEFAULT 'never'",
            "expiry_date": "ALTER TABLE mg_nodes ADD COLUMN expiry_date TEXT DEFAULT ''",
            "last_reset_date": "ALTER TABLE mg_nodes ADD COLUMN last_reset_date TEXT DEFAULT ''"
        }
        
        for col_name, alter_sql in migrations.items():
            if col_name not in existing_columns:
                c.execute(alter_sql)
        # 【新增】创建设置表
        c.execute('''CREATE TABLE IF NOT EXISTS mg_settings (key TEXT PRIMARY KEY, value TEXT)''')        
        conn.commit()
        conn.close()

# ================= 底层 Shell & 看门狗探活 =================

def run_executor(command, port, secret=""):
    try:
        cmd = ["bash", EXECUTOR_SCRIPT, command, str(port)]
        if secret: cmd.append(secret)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def iptables_safe_execute(cmd):
    try: subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def setup_iptables_monitor(port):
    iptables_safe_execute(f"iptables -C OUTPUT -p tcp --sport {port} || iptables -I OUTPUT -p tcp --sport {port}")

def remove_iptables_rules(port):
    iptables_safe_execute(f"iptables -D OUTPUT -p tcp --sport {port}")
    iptables_safe_execute(f"iptables -D INPUT -p tcp --dport {port} -j DROP")

def block_port(port):
    iptables_safe_execute(f"iptables -C INPUT -p tcp --dport {port} -j DROP || iptables -I INPUT -p tcp --dport {port} -j DROP")

def unblock_port(port):
    iptables_safe_execute(f"iptables -D INPUT -p tcp --dport {port} -j DROP")

def get_iptables_bytes(port):
    try:
        res = subprocess.check_output(f"iptables -vxn -L OUTPUT | grep 'spt:{port}'", shell=True).decode('utf-8')
        if res:
            parts = res.strip().split()
            if len(parts) >= 2 and parts[1].isdigit(): return int(parts[1])
    except: pass
    return 0

def is_process_alive(port):
    pid_file = f"/var/run/mg_{port}.pid"
    if not os.path.exists(pid_file): return False
    try:
        with open(pid_file, 'r') as f: pid = f.read().strip()
        if not pid or not os.path.isdir(f"/proc/{pid}"): return False
    except: return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except: return False

# ================= 守护线程：全能主控管家 =================

def master_monitor_loop():
    while True:
        try:
            now = datetime.now()
            current_date_str = now.strftime('%Y-%m-%d')
            current_month_str = now.strftime('%Y-%m')
            
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT * FROM mg_nodes")
            nodes = [dict(row) for row in c.fetchall()]
            conn.close()
            
            for node in nodes:
                port = node['port']
                limit_bytes = int(node['limit_gb'] * 1024 * 1024 * 1024)
                status = node['status']
                reset_cycle = node['reset_cycle']
                last_reset = node['last_reset_date']
                expiry_date_str = node['expiry_date']
                current_bytes = get_iptables_bytes(port)
                
                need_update, new_status, new_used_bytes, new_last_reset = False, status, current_bytes, last_reset
                
                # A: 周期重置
                if reset_cycle == 'daily' and last_reset != current_date_str:
                    remove_iptables_rules(port); setup_iptables_monitor(port)
                    new_used_bytes, new_last_reset, need_update = 0, current_date_str, True
                elif reset_cycle == 'monthly' and last_reset[:7] != current_month_str:
                    remove_iptables_rules(port); setup_iptables_monitor(port)
                    new_used_bytes, new_last_reset, need_update = 0, current_date_str, True

                # B: 到期检查
                is_expired = False
                if expiry_date_str:
                    try:
                        if now > datetime.strptime(expiry_date_str, '%Y-%m-%d %H:%M:%S'): is_expired = True
                    except: pass
                        
                if is_expired and status == 'running':
                    block_port(port); run_executor('stop', port)
                    new_status, need_update = 'expired', True

                # C: 超流量检查
                check_bytes = new_used_bytes if need_update else current_bytes
                if not is_expired and check_bytes >= limit_bytes and status == 'running':
                    block_port(port); run_executor('stop', port)
                    new_status, need_update = 'blocked', True

                # D: 看门狗自愈
                if new_status == 'running' and not is_process_alive(port):
                    pid_file = f"/var/run/mg_{port}.pid"
                    if os.path.exists(pid_file):
                        try: os.remove(pid_file)
                        except: pass
                    unblock_port(port); run_executor('start', port, node['secret'])

                # E: 数据回写
                if need_update or current_bytes > node['used_bytes']:
                    with db_lock:
                        try:
                            write_conn = get_db()
                            write_cursor = write_conn.cursor()
                            write_cursor.execute('UPDATE mg_nodes SET used_bytes=?, status=?, last_reset_date=? WHERE port=?', 
                                                 (new_used_bytes, new_status, new_last_reset, port))
                            write_conn.commit(); write_conn.close()
                        except: pass
        except: pass
        time.sleep(60)

# ================= Flask 鉴权与 API 路由 =================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'): return jsonify({"success": False, "msg": "未授权访问"}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/mg-api/login', methods=['POST'])
def login():
    data = request.json
    if data and data.get('username') == ADMIN_USER and data.get('password') == ADMIN_PASS:
        session['logged_in'] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "msg": "凭证错误"}), 401

@app.route('/mg-api/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return jsonify({"success": True})

@app.route('/mg-api/nodes', methods=['GET'])
@login_required
def get_nodes():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM mg_nodes ORDER BY port ASC")
    nodes = [dict(row) for row in c.fetchall()]
    conn.close()
    
    server_ip = os.popen("curl -s4 --connect-timeout 2 ip.sb || echo '127.0.0.1'").read().strip()
    for node in nodes:
        node['server_ip'] = server_ip   # <--- 请在后端补充这一行
        node['used_gb'] = round(node['used_bytes'] / (1024**3), 3)
        node['link'] = f"tg://proxy?server={server_ip}&port={node['port']}&secret={node['secret']}"
    return jsonify({"success": True, "data": nodes})

@app.route('/mg-api/node/add', methods=['POST'])
@login_required
def add_node():
    data = request.json
    port = int(data.get('port'))
    limit_gb = float(data.get('limit_gb'))
    reset_cycle = data.get('reset_cycle', 'never')
    
    # 严格遵循：如果前端传空字符串，代表永久有效；如果压根没传这个 key，后端给予自然月 1 个月默认值。
    expiry_date = data.get('expiry_date')
    if expiry_date is None:
        expiry_date = add_months(datetime.now(), 1).strftime('%Y-%m-%d %H:%M:%S')
    
    custom_secret = data.get('secret', '').strip()
    if custom_secret:
        secret = custom_secret
    else:
        try: secret = subprocess.check_output(f"{MG_BIN} generate-secret --hex {FAKE_DOMAIN}", shell=True).decode('utf-8').strip()
        except: return jsonify({"success": False, "msg": "底层 Secret 生成失败"})
    
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute('''INSERT INTO mg_nodes 
                         (port, secret, limit_gb, status, reset_cycle, expiry_date) 
                         VALUES (?, ?, ?, 'running', ?, ?)''', 
                      (port, secret, limit_gb, reset_cycle, expiry_date))
            conn.commit(); conn.close()
    except sqlite3.IntegrityError: return jsonify({"success": False, "msg": f"端口 {port} 已存在"})
    except sqlite3.OperationalError as e: return jsonify({"success": False, "msg": f"数据库忙: {e}"})

    setup_iptables_monitor(port)
    unblock_port(port)
    run_executor('start', port, secret)
    return jsonify({"success": True, "msg": "节点创建成功"})

@app.route('/mg-api/node/edit', methods=['POST'])
@login_required
def edit_node():
    data = request.json
    port = int(data.get('port'))
    limit_gb = float(data.get('limit_gb'))
    reset_cycle = data.get('reset_cycle', 'never')
    expiry_date = data.get('expiry_date', '')
    custom_secret = data.get('secret', '').strip()

    conn = get_db(); c = conn.cursor()
    c.execute("SELECT secret, status FROM mg_nodes WHERE port=?", (port,))
    row = c.fetchone(); conn.close()
    if not row: return jsonify({"success": False, "msg": "未找到该节点"})
    
    old_secret, status = row['secret'], row['status']
    new_secret = custom_secret if custom_secret else old_secret

    if (new_secret != old_secret) and status == 'running':
        run_executor('stop', port)

    with db_lock:
        try:
            write_conn = get_db(); write_cursor = write_conn.cursor()
            write_cursor.execute('UPDATE mg_nodes SET limit_gb=?, reset_cycle=?, expiry_date=?, secret=? WHERE port=?', 
                                 (limit_gb, reset_cycle, expiry_date, new_secret, port))
            if status in ['blocked', 'expired']:
                write_cursor.execute("UPDATE mg_nodes SET status='running' WHERE port=?", (port,))
                status = 'running'
                unblock_port(port)
            write_conn.commit(); write_conn.close()
        except sqlite3.OperationalError as e: return jsonify({"success": False, "msg": f"数据库忙: {e}"})
            
    if status == 'running':
        unblock_port(port)
        run_executor('start', port, new_secret)
            
    return jsonify({"success": True, "msg": "节点配置已修改"})

@app.route('/mg-api/node/renew', methods=['POST'])
@login_required
def renew_node():
    """【新增】一键续费路由：支持自然月递增"""
    data = request.json
    port = int(data.get('port'))
    months = int(data.get('months', 1))

    conn = get_db(); c = conn.cursor()
    c.execute("SELECT expiry_date, status, secret FROM mg_nodes WHERE port=?", (port,))
    row = c.fetchone(); conn.close()
    
    if not row: return jsonify({"success": False, "msg": "未找到该节点"})
    
    current_expiry_str = row['expiry_date']
    status = row['status']
    secret = row['secret']
    now = datetime.now()

    # 判定续费起点：如果是未过期，从原到期日累加；如果已过期/无到期日，从现在开始累加
    base_date = now
    if current_expiry_str:
        try:
            current_expiry = datetime.strptime(current_expiry_str, '%Y-%m-%d %H:%M:%S')
            if current_expiry > now:
                base_date = current_expiry
        except: pass

    new_expiry = add_months(base_date, months)
    new_expiry_str = new_expiry.strftime('%Y-%m-%d %H:%M:%S')

    with db_lock:
        try:
            write_conn = get_db(); write_cursor = write_conn.cursor()
            write_cursor.execute("UPDATE mg_nodes SET expiry_date=? WHERE port=?", (new_expiry_str, port))
            
            # 如果是被过期阻断的，续费后重置为 running
            if status == 'expired':
                write_cursor.execute("UPDATE mg_nodes SET status='running' WHERE port=?", (port,))
                status = 'running'
                unblock_port(port)
                
            write_conn.commit(); write_conn.close()
        except sqlite3.OperationalError as e:
            return jsonify({"success": False, "msg": f"数据库忙: {e}"})

    # 拉起刚被复活的进程
    if status == 'running':
        unblock_port(port)
        run_executor('start', port, secret)

    return jsonify({"success": True, "msg": f"续费成功，新到期时间: {new_expiry_str}"})

@app.route('/mg-api/node/toggle', methods=['POST'])
@login_required
def toggle_node():
    data = request.json
    port = int(data.get('port'))
    action = data.get('action') 
    
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT secret, status FROM mg_nodes WHERE port=?", (port,))
    row = c.fetchone(); conn.close()
    
    if not row: return jsonify({"success": False, "msg": "未找到该节点"})
    status, secret = row['status'], row['secret']

    if action == 'start' and status != 'running':
        unblock_port(port); run_executor('start', port, secret)
        new_status = 'running'
    elif action == 'stop' and status == 'running':
        run_executor('stop', port)
        new_status = 'stopped'
    else: return jsonify({"success": True, "msg": "状态无需变更"})

    with db_lock:
        write_conn = get_db(); write_cursor = write_conn.cursor()
        write_cursor.execute("UPDATE mg_nodes SET status=? WHERE port=?", (new_status, port))
        write_conn.commit(); write_conn.close()
    return jsonify({"success": True, "msg": f"节点已{ '启动' if new_status == 'running' else '停止' }"})

@app.route('/mg-api/node/delete', methods=['POST'])
@login_required
def delete_node():
    port = int(request.json.get('port'))
    run_executor('delete', port); remove_iptables_rules(port)
    with db_lock:
        conn = get_db(); c = conn.cursor()
        c.execute("DELETE FROM mg_nodes WHERE port=?", (port,))
        conn.commit(); conn.close()
    return jsonify({"success": True, "msg": "节点已删除"})

@app.route('/mg-api/node/reset_traffic', methods=['POST'])
@login_required
def reset_traffic():
    port = int(request.json.get('port'))
    remove_iptables_rules(port); setup_iptables_monitor(port)
    with db_lock:
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE mg_nodes SET used_bytes=0 WHERE port=?", (port,))
        conn.commit(); conn.close()
    return jsonify({"success": True, "msg": "流量已清零"})

@app.route('/')
def index(): return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    init_db()
    monitor_thread = threading.Thread(target=master_monitor_loop)
    monitor_thread.daemon = True; monitor_thread.start()
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True)
