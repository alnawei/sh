#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# mg_panel.py - MG 私有协议中控调度面板

import os
import time
import sqlite3
import threading
import subprocess
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from datetime import datetime

# ================= 核心配置区 =================
DB_FILE = "/root/mg_core.db"
EXECUTOR_SCRIPT = "/root/mg_executor.sh"
MG_BIN = "/usr/local/bin/mg"
FAKE_DOMAIN = "icloud.com"
WEB_PORT = 8888

# Flask 凭证与管理员账户配置
FLASK_SECRET = os.urandom(24) 
ADMIN_USER = "admin"
ADMIN_PASS = "admin"          
# ==============================================

app = Flask(__name__)
app.secret_key = FLASK_SECRET

# 数据库全局读写互斥锁
db_lock = threading.Lock()

# ================= 基础组件与数据库 =================

def get_db():
    # 【修复1】追加 timeout=20，遭遇写锁排队等待而不是直接崩溃
    conn = sqlite3.connect(DB_FILE, timeout=20.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        
        # 1. 创建核心表（包含生产级新字段）
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
        
        # 2. 字段平滑升级检测 (兼容旧版本数据库)
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

# ================= 底层 Shell & iptables 调度 =================

def run_executor(command, port, secret=""):
    try:
        cmd = ["bash", EXECUTOR_SCRIPT, command, str(port)]
        if secret:
            cmd.append(secret)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def iptables_safe_execute(cmd):
    try:
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

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

# ================= 后台监控守护线程 (主控管家) =================

def master_monitor_loop():
    """后台独立线程：每隔 60 秒轮询一次，处理流量统计、超限熔断、到期阻断、周期重置"""
    while True:
        try:
            # 获取当前时间（格式化用于比对）
            now = datetime.now()
            current_date_str = now.strftime('%Y-%m-%d')
            current_month_str = now.strftime('%Y-%m')
            
            # 1. 读操作：获取所有节点
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT * FROM mg_nodes")
            nodes = [dict(row) for row in c.fetchall()]
            conn.close()
            
            # 2. 遍历处理每个节点
            for node in nodes:
                port = node['port']
                limit_bytes = int(node['limit_gb'] * 1024 * 1024 * 1024)
                status = node['status']
                reset_cycle = node['reset_cycle']
                last_reset = node['last_reset_date']
                expiry_date_str = node['expiry_date']
                
                # 获取实时物理流量
                current_bytes = get_iptables_bytes(port)
                
                # --- 核心状态机逻辑 ---
                need_update = False
                new_status = status
                new_used_bytes = current_bytes
                new_last_reset = last_reset
                
                # 【动作 A】: 检查周期重置 (每日/每月)
                if reset_cycle == 'daily' and last_reset != current_date_str:
                    remove_iptables_rules(port)
                    setup_iptables_monitor(port)
                    new_used_bytes = 0
                    new_last_reset = current_date_str
                    need_update = True
                    
                elif reset_cycle == 'monthly' and last_reset[:7] != current_month_str:
                    remove_iptables_rules(port)
                    setup_iptables_monitor(port)
                    new_used_bytes = 0
                    new_last_reset = current_date_str
                    need_update = True

                # 【动作 B】: 检查是否到期 (Expiry Date)
                is_expired = False
                if expiry_date_str:
                    try:
                        expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d %H:%M:%S')
                        if now > expiry_date:
                            is_expired = True
                    except:
                        pass # 日期格式错误则忽略
                        
                if is_expired and status == 'running':
                    block_port(port)
                    run_executor('stop', port)
                    new_status = 'expired'
                    need_update = True
                    print(f"[Monitor] Port {port} expired, blocked.")

                # 【动作 C】: 检查是否超流量 (Quota Exceeded)
                # 注意：如果刚才触发了重置，这里的 current_bytes 就不能用原来的了
                check_bytes = new_used_bytes if need_update else current_bytes
                
                if not is_expired and check_bytes >= limit_bytes and status == 'running':
                    block_port(port)
                    run_executor('stop', port)
                    new_status = 'blocked'
                    need_update = True
                    print(f"[Monitor] Port {port} quota exceeded, blocked.")

                # 【动作 D】: 写入数据库 (如果有任何状态、重置或流量变更)
                # 即便没有状态变更，只要流量有增长也需要更新
                if need_update or current_bytes > node['used_bytes']:
                    with db_lock:
                        try:
                            write_conn = get_db()
                            write_cursor = write_conn.cursor()
                            
                            # 更新流量、状态、最后重置时间
                            write_cursor.execute('''
                                UPDATE mg_nodes 
                                SET used_bytes=?, status=?, last_reset_date=? 
                                WHERE port=?
                            ''', (new_used_bytes, new_status, new_last_reset, port))
                            
                            write_conn.commit()
                            write_conn.close()
                        except Exception as db_e:
                            print(f"[Monitor DB Write Error] {db_e}")
                            
        except Exception as e:
            print(f"[Monitor Master Error] {e}")
        
        # 休息 60 秒后再次全面巡检
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
    
    try:
        secret = subprocess.check_output(f"{MG_BIN} generate-secret --hex {FAKE_DOMAIN}", shell=True).decode('utf-8').strip()
    except:
        return jsonify({"success": False, "msg": "底层 Secret 生成失败，请检查二进制文件环境"})
    
    # 【修复2】严格包裹写操作，遇到锁等待 timeout 机制生效
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
    except sqlite3.OperationalError as e:
        return jsonify({"success": False, "msg": f"数据库写入排队超时: {str(e)}"})

    # 耗时的 shell 调用放到锁外面，绝不占用数据库锁
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
    action = data.get('action') 
    
    # 读操作不在锁内
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT secret, status FROM mg_nodes WHERE port=?", (port,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"success": False, "msg": "未找到该节点"})
    
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

    # 【修复3】单独用锁包裹修改操作，随开随关
    with db_lock:
        try:
            write_conn = get_db()
            write_cursor = write_conn.cursor()
            write_cursor.execute("UPDATE mg_nodes SET status=? WHERE port=?", (new_status, port))
            write_conn.commit()
            write_conn.close()
        except sqlite3.OperationalError as e:
            return jsonify({"success": False, "msg": f"数据库忙，更新状态失败: {str(e)}"})
    
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
        
    return jsonify({"success": True, "msg": "节点已彻底删除"})

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
        
    return jsonify({"success": True, "msg": "流量已重置清零"})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


if __name__ == '__main__':
    init_db()
    
    # 将原来的 monitor_thread 替换为新的 master_monitor_loop
    monitor_thread = threading.Thread(target=master_monitor_loop)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    print(f"[MG-Panel] Starting private console on port {WEB_PORT}...")
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True)
    
    print(f"[MG-Panel] Starting private console on port {WEB_PORT}...")
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True)
