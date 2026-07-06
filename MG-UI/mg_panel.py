#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# mg_panel.py - MG 私有协议中控调度面板 (Production + Watchdog Version)

import os
import time
import socket
import sqlite3
import threading
import subprocess
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

# ================= 基础组件与数据库 =================

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=20.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        
        # 1. 核心表创建
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
                      
        # 2. 版本平滑迁移 (自动检测并新增字段)
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
                print(f"[DB Upgrade] Added new column: {col_name}")
                
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
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    except Exception:
        pass
    return 0

def is_process_alive(port):
    """【新增】双重健康检查：验证 PID 存活且 Socket 监听正常"""
    pid_file = f"/var/run/mg_{port}.pid"
    if not os.path.exists(pid_file):
        return False
        
    try:
        with open(pid_file, 'r') as f:
            pid = f.read().strip()
        if not pid or not os.path.isdir(f"/proc/{pid}"):
            return False
    except:
        return False
        
    # Socket 检查，防止进程假死
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except:
        return False

# ================= 守护线程：全能主控管家 =================

def master_monitor_loop():
    """后台独立线程：轮询处理流量统计、超限熔断、到期阻断、周期重置与看门狗自愈"""
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
                
                need_update = False
                new_status = status
                new_used_bytes = current_bytes
                new_last_reset = last_reset
                
                # 【环节 A】: 检查周期重置
                if reset_cycle == 'daily' and last_reset != current_date_str:
                    remove_iptables_rules(port)
                    setup_iptables_monitor(port)
                    new_used_bytes, new_last_reset, need_update = 0, current_date_str, True
                elif reset_cycle == 'monthly' and last_reset[:7] != current_month_str:
                    remove_iptables_rules(port)
                    setup_iptables_monitor(port)
                    new_used_bytes, new_last_reset, need_update = 0, current_date_str, True

                # 【环节 B】: 检查到期
                is_expired = False
                if expiry_date_str:
                    try:
                        expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d %H:%M:%S')
                        if now > expiry_date: is_expired = True
                    except: pass
                        
                if is_expired and status == 'running':
                    block_port(port)
                    run_executor('stop', port)
                    new_status, need_update = 'expired', True

                # 【环节 C】: 检查超流量
                check_bytes = new_used_bytes if need_update else current_bytes
                if not is_expired and check_bytes >= limit_bytes and status == 'running':
                    block_port(port)
                    run_executor('stop', port)
                    new_status, need_update = 'blocked', True

                # 【环节 D】: 看门狗自愈 (如果应当运行，但实际挂了)
                if new_status == 'running' and not is_process_alive(port):
                    print(f"[Watchdog] Port {port} is dead! Auto-healing...")
                    pid_file = f"/var/run/mg_{port}.pid"
                    if os.path.exists(pid_file):
                        try: os.remove(pid_file)
                        except: pass
                    unblock_port(port)
                    run_executor('start', port, node['secret'])

                # 【环节 E】: 数据回写
                if need_update or current_bytes > node['used_bytes']:
                    with db_lock:
                        try:
                            write_conn = get_db()
                            write_cursor = write_conn.cursor()
                            write_cursor.execute('''
                                UPDATE mg_nodes 
                                SET used_bytes=?, status=?, last_reset_date=? 
                                WHERE port=?
                            ''', (new_used_bytes, new_status, new_last_reset, port))
                            write_conn.commit()
                            write_conn.close()
                        except: pass
                            
        except Exception as e:
            print(f"[Master Monitor Error] {e}")
        
        time.sleep(60)

# ================= Flask 鉴权与 API 路由 =================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({"success": False, "msg": "未授权访问"}), 401
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
    expiry_date = data.get('expiry_date', '')
    
    custom_secret = data.get('secret', '').strip()
    if custom_secret:
        secret = custom_secret
    else:
        try:
            secret = subprocess.check_output(f"{MG_BIN} generate-secret --hex {FAKE_DOMAIN}", shell=True).decode('utf-8').strip()
        except:
            return jsonify({"success": False, "msg": "底层 Secret 生成失败"})
    
    try:
        with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute('''INSERT INTO mg_nodes 
                         (port, secret, limit_gb, status, reset_cycle, expiry_date) 
                         VALUES (?, ?, ?, 'running', ?, ?)''', 
                      (port, secret, limit_gb, reset_cycle, expiry_date))
            conn.commit()
            conn.close()
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "msg": f"端口 {port} 已存在"})
    except sqlite3.OperationalError as e:
        return jsonify({"success": False, "msg": f"数据库忙: {e}"})

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

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT secret, status FROM mg_nodes WHERE port=?", (port,))
    row = c.fetchone()
    conn.close()
    
    if not row: return jsonify({"success": False, "msg": "未找到该节点"})
    
    old_secret = row['secret']
    status = row['status']
    new_secret = custom_secret if custom_secret else old_secret
    secret_changed = (new_secret != old_secret)

    if secret_changed and status == 'running':
        run_executor('stop', port)

    with db_lock:
        try:
            write_conn = get_db()
            write_cursor = write_conn.cursor()
            write_cursor.execute('''
                UPDATE mg_nodes 
                SET limit_gb=?, reset_cycle=?, expiry_date=?, secret=?
                WHERE port=?
            ''', (limit_gb, reset_cycle, expiry_date, new_secret, port))
            
            # 如果处于限制状态被编辑，先假定解封，交由巡检管家再次裁定
            if status in ['blocked', 'expired']:
                write_cursor.execute("UPDATE mg_nodes SET status='running' WHERE port=?", (port,))
                status = 'running'
                unblock_port(port)
                
            write_conn.commit()
            write_conn.close()
        except sqlite3.OperationalError as e:
            return jsonify({"success": False, "msg": f"数据库忙: {e}"})
            
    if status == 'running':
        unblock_port(port)
        run_executor('start', port, new_secret)
            
    return jsonify({"success": True, "msg": "节点配置已修改"})

@app.route('/mg-api/node/toggle', methods=['POST'])
@login_required
def toggle_node():
    data = request.json
    port = int(data.get('port'))
    action = data.get('action') 
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT secret, status FROM mg_nodes WHERE port=?", (port,))
    row = c.fetchone()
    conn.close()
    
    if not row: return jsonify({"success": False, "msg": "未找到该节点"})
    
    status = row['status']
    secret = row['secret']

    if action == 'start' and status != 'running':
        unblock_port(port)
        run_executor('start', port, secret)
        new_status = 'running'
    elif action == 'stop' and status == 'running':
        run_executor('stop', port)
        new_status = 'stopped'
    else:
        return jsonify({"success": True, "msg": "状态无需变更"})

    with db_lock:
        write_conn = get_db()
        write_cursor = write_conn.cursor()
        write_cursor.execute("UPDATE mg_nodes SET status=? WHERE port=?", (new_status, port))
        write_conn.commit()
        write_conn.close()
    
    return jsonify({"success": True, "msg": f"节点已{ '启动' if new_status == 'running' else '停止' }"})

@app.route('/mg-api/node/delete', methods=['POST'])
@login_required
def delete_node():
    port = int(request.json.get('port'))
    run_executor('delete', port)
    remove_iptables_rules(port)
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM mg_nodes WHERE port=?", (port,))
        conn.commit()
        conn.close()
    return jsonify({"success": True, "msg": "节点已删除"})

@app.route('/mg-api/node/reset_traffic', methods=['POST'])
@login_required
def reset_traffic():
    port = int(request.json.get('port'))
    remove_iptables_rules(port)
    setup_iptables_monitor(port)
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE mg_nodes SET used_bytes=0 WHERE port=?", (port,))
        conn.commit()
        conn.close()
    return jsonify({"success": True, "msg": "流量已清零"})

@app.route('/')
def index(): return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    init_db()
    monitor_thread = threading.Thread(target=master_monitor_loop)
    monitor_thread.daemon = True
    monitor_thread.start()
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True)
