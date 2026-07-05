import os
import sqlite3
import subprocess
from flask import Flask, render_template_string, request, redirect

app = Flask(__name__)

# ================= 配置区 =================
# 数据库和底层程序全部改名隐蔽
DB_FILE = "/root/mg_data.db"
MG_BIN = "/usr/local/bin/mg"
FAKE_DOMAIN = "icloud.com"
PANEL_PORT = 8888
# ==========================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>MG 私有控制台</title>
    <style>
        body { background-color: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 40px; margin: 0; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: #89b4fa; border-bottom: 2px solid #313244; padding-bottom: 10px; font-size: 24px; }
        .card { background-color: #181825; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border-bottom: 1px solid #313244; padding: 12px; text-align: left; }
        th { color: #a6adc8; font-weight: normal; }
        .btn { background-color: #a6e3a1; color: #11111b; padding: 8px 16px; border-radius: 4px; text-decoration: none; border: none; cursor: pointer; font-weight: bold; }
        .btn:hover { opacity: 0.9; }
        .btn-danger { background-color: #f38ba8; color: #11111b; }
        .form-group { margin-bottom: 15px; display: inline-block; margin-right: 15px; }
        input { padding: 8px; background-color: #313244; border: 1px solid #45475a; color: #cdd6f4; border-radius: 4px; outline: none; }
        input:focus { border-color: #89b4fa; }
        .link-box { background: #11111b; padding: 5px; border-radius: 4px; font-family: monospace; font-size: 12px; color: #a6e3a1; word-break: break-all; }
        .status-ok { color: #a6e3a1; font-weight: bold; }
        .status-bad { color: #f38ba8; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ MG 私有控制台</h1>
        
        <div class="card">
            <h3>➕ 添加入站</h3>
            <form action="/add" method="POST">
                <div class="form-group">
                    <label>端口: </label>
                    <input type="number" name="port" required placeholder="例如: 20000" min="1" max="65535">
                </div>
                <div class="form-group">
                    <label>流量限制 (GB): </label>
                    <input type="number" step="0.1" name="limit_gb" required placeholder="例如: 50">
                </div>
                <button type="submit" class="btn">创建运行</button>
            </form>
        </div>

        <div class="card">
            <h3>📊 节点状态</h3>
            <table>
                <tr>
                    <th>端口</th>
                    <th>已用流量</th>
                    <th>状态</th>
                    <th>直连链接</th>
                    <th>操作</th>
                </tr>
                {% for p in proxies %}
                <tr>
                    <td><strong>{{ p.port }}</strong></td>
                    <td>{{ p.used_gb }} / {{ p.limit_gb }} GB</td>
                    <td>
                        {% if p.used_gb < p.limit_gb %}
                            <span class="status-ok">🟢 运行中</span>
                        {% else %}
                            <span class="status-bad">🔴 超限阻断</span>
                        {% endif %}
                    </td>
                    <td><div class="link-box">{{ p.link }}</div></td>
                    <td><a href="/delete/{{ p.port }}" class="btn btn-danger" onclick="return confirm('确定删除该端口？')">删除</a></td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
"""

def get_used_bytes(port):
    try:
        res = subprocess.check_output(f"iptables -vxn -L OUTPUT | grep 'spt:{port}'", shell=True).decode()
        return int(res.strip().split()[1])
    except:
        return 0

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS proxies
                 (port INTEGER PRIMARY KEY, secret TEXT, limit_gb REAL, used_bytes REAL)''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT port, secret, limit_gb FROM proxies")
    rows = c.fetchall()
    conn.close()

    server_ip = os.popen("curl -s4 ip.sb").read().strip()
    
    proxies = []
    for r in rows:
        port, secret, limit_gb = r
        used_bytes = get_used_bytes(port)
        used_gb = round(used_bytes / (1024**3), 2)
        link = f"tg://proxy?server={server_ip}&port={port}&secret={secret}"
        proxies.append({'port': port, 'limit_gb': limit_gb, 'used_gb': used_gb, 'link': link})
        
    return render_template_string(HTML_TEMPLATE, proxies=proxies)

@app.route('/add', methods=['POST'])
def add():
    port = int(request.form['port'])
    limit_gb = float(request.form['limit_gb'])
    secret = os.popen(f"{MG_BIN} generate-secret --hex {FAKE_DOMAIN}").read().strip()
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO proxies (port, secret, limit_gb, used_bytes) VALUES (?, ?, ?, 0)", (port, secret, limit_gb))
    conn.commit()
    conn.close()

    os.system(f"iptables -C OUTPUT -p tcp --sport {port} 2>/dev/null || iptables -I OUTPUT -p tcp --sport {port}")
    os.system(f"iptables -D INPUT -p tcp --dport {port} -j DROP 2>/dev/null")
    os.system(f"pkill -f '0.0.0.0:{port}' 2>/dev/null")
    os.system(f"nohup {MG_BIN} simple-run 0.0.0.0:{port} {secret} >/dev/null 2>&1 &")
    
    return redirect('/')

@app.route('/delete/<int:port>')
def delete(port):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM proxies WHERE port=?", (port,))
    conn.commit()
    conn.close()

    os.system(f"pkill -f '0.0.0.0:{port}'")
    os.system(f"iptables -D OUTPUT -p tcp --sport {port} 2>/dev/null")
    os.system(f"iptables -D INPUT -p tcp --dport {port} -j DROP 2>/dev/null")
    
    return redirect('/')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=PANEL_PORT)
