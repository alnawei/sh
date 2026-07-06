#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# mg_bot.py - MG 节点 Telegram 管家 (Dynamic Config & Auto Auth)

import os
import random
import sqlite3
import subprocess
import calendar
import asyncio
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict

from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, TelegramObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

# ================= 全局系统配置 =================
DB_FILE = "/root/mg_core.db"
EXECUTOR_SCRIPT = "/root/mg_executor.sh"
MG_BIN = "/usr/local/bin/mg"
FAKE_DOMAIN = "icloud.com"

# 动态配置载体
BOT_TOKEN = ""
ADMIN_ID = ""

router = Router()

# ================= 状态机与底层交互 =================
class AddNodeState(StatesGroup): port, secret, limit = State(), State(), State()
class EditNodeState(StatesGroup): port, secret, limit = State(), State(), State()

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn

def get_server_ip():
    try: return os.popen("curl -s4 --connect-timeout 2 ip.sb || echo '127.0.0.1'").read().strip()
    except: return "127.0.0.1"

SERVER_IP = get_server_ip()

def run_executor(command, port, secret=""):
    try:
        cmd = ["bash", EXECUTOR_SCRIPT, command, str(port)]
        if secret: cmd.append(secret)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def iptables_safe_execute(cmd):
    try: subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def setup_iptables_monitor(port):
    iptables_safe_execute(f"iptables -C OUTPUT -p tcp --sport {port} || iptables -I OUTPUT -p tcp --sport {port}")

def remove_iptables_rules(port):
    iptables_safe_execute(f"iptables -D OUTPUT -p tcp --sport {port}")
    iptables_safe_execute(f"iptables -D INPUT -p tcp --dport {port} -j DROP")

def unblock_port(port):
    iptables_safe_execute(f"iptables -D INPUT -p tcp --dport {port} -j DROP")

def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return sourcedate.replace(year=year, month=month, day=day)

# ================= 鉴权中间件 (Middleware) =================
class AuthMiddleware(BaseMiddleware):
    """全局安全看门狗：如果不是数据库设定的 ADMIN_ID，拦截所有消息与点击"""
    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: Dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user and str(user.id) != str(ADMIN_ID):
            if isinstance(event, Message):
                await event.answer("❌ 警告：您没有管理员权限，操作已被系统拦截。")
            elif isinstance(event, CallbackQuery):
                await event.answer("❌ 无管理员权限！", show_alert=True)
            return
        return await handler(event, data)

router.message.middleware(AuthMiddleware())
router.callback_query.middleware(AuthMiddleware())

# ================= 菜单与业务逻辑 =================
def get_main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="1. 节点列表"), KeyboardButton(text="2. 添加节点")]], resize_keyboard=True)

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛡️ 欢迎使用 MG 私有管家！您的管理员身份已验证。\n请使用底部菜单进行操作：", reply_markup=get_main_keyboard())

@router.message(F.text == "1. 节点列表")
async def show_node_list(message: Message):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM mg_nodes")
    nodes = [dict(row) for row in c.fetchall()]
    conn.close()
    
    running = sum(1 for n in nodes if n['status'] == 'running')
    await message.answer(f"📊 节点概况\n\n🟢 运行中: {running} 个\n⚪ 停用/阻断: {len(nodes) - running} 个")
    if not nodes: return await message.answer("当前没有任何节点记录。")

    def sort_key(n):
        if not n['expiry_date']: return datetime.max
        try: return datetime.strptime(n['expiry_date'], '%Y-%m-%d %H:%M:%S')
        except: return datetime.max
    nodes.sort(key=sort_key)

    buttons = []
    for n in nodes:
        emoji = "🟢" if n['status'] == 'running' else ("🔴" if n['status'] == 'blocked' else "⚪")
        buttons.append([InlineKeyboardButton(text=f"{emoji} IP:{SERVER_IP} 端口:{n['port']}", callback_data=f"detail_{n['port']}")])
    await message.answer("点击下方节点查看详情：", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("detail_"))
async def node_detail(cq: CallbackQuery):
    port = int(cq.data.split("_")[1])
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM mg_nodes WHERE port=?", (port,))
    node = c.fetchone()
    conn.close()
    
    if not node: return await cq.answer("节点已被删除", show_alert=True)
    used_gb = round(node['used_bytes'] / (1024**3), 2)
    s_map = {'running': '🟢 运行中', 'stopped': '⚪ 已停止', 'expired': '⏳ 已到期', 'blocked': '🔴 超限阻断'}
    link = f"tg://proxy?server={SERVER_IP}&port={port}&secret={node['secret']}"
    
    text = (f"📄 <b>节点详情</b>\n━━━━━━━━━━━━━━━\n"
            f"🖥 <b>IP：</b><code>{SERVER_IP}</code>\n🔌 <b>端口：</b><code>{port}</code>\n"
            f"🕒 <b>到期：</b>{node['expiry_date'].split(' ')[0] if node['expiry_date'] else '永久有效'}\n"
            f"📊 <b>流量：</b>{used_gb} / {node['limit_gb']} GB\n"
            f"♻️ <b>重置：</b>{node['reset_cycle']}\n📈 <b>状态：</b>{s_map.get(node['status'], '未知')}\n\n"
            f"🔑 <b>密钥：</b>\n<code>{node['secret']}</code>\n\n🔗 <b>链接：</b>\n<code>{link}</code>")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 一键续费(1个月)", callback_data=f"renew_{port}")],
        [InlineKeyboardButton(text="📝 编辑参数", callback_data=f"edit_{port}"), InlineKeyboardButton(text="🔄 流量清零", callback_data=f"reset_{port}")],
        [InlineKeyboardButton(text="❌ 彻底删除", callback_data=f"delete_{port}")]
    ])
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await cq.answer()

@router.callback_query(F.data.startswith("renew_"))
async def action_renew(cq: CallbackQuery):
    port = int(cq.data.split("_")[1])
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT expiry_date, status, secret FROM mg_nodes WHERE port=?", (port,))
    node = c.fetchone()
    if not node: return await cq.answer("节点不存在")
    
    base_date = datetime.now()
    if node['expiry_date']:
        try:
            curr = datetime.strptime(node['expiry_date'], '%Y-%m-%d %H:%M:%S')
            if curr > base_date: base_date = curr
        except: pass
    
    new_expiry = add_months(base_date, 1).strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE mg_nodes SET expiry_date=? WHERE port=?", (new_expiry, port))
    
    if node['status'] == 'expired':
        c.execute("UPDATE mg_nodes SET status='running' WHERE port=?", (port,))
        unblock_port(port)
        run_executor('start', port, node['secret'])
        
    conn.commit(); conn.close()
    await cq.answer("✅ 续费成功，延期 1 个自然月！", show_alert=True)
    await cq.message.delete()

@router.callback_query(F.data.startswith("reset_"))
async def action_reset(cq: CallbackQuery):
    port = int(cq.data.split("_")[1])
    remove_iptables_rules(port); setup_iptables_monitor(port)
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE mg_nodes SET used_bytes=0 WHERE port=?", (port,))
    conn.commit(); conn.close()
    await cq.answer("✅ 流量已清零！", show_alert=True)

@router.callback_query(F.data.startswith("delete_"))
async def action_delete(cq: CallbackQuery):
    port = int(cq.data.split("_")[1])
    run_executor('delete', port); remove_iptables_rules(port)
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM mg_nodes WHERE port=?", (port,))
    conn.commit(); conn.close()
    await cq.answer("🗑️ 节点已被彻底删除！", show_alert=True)
    await cq.message.delete()

# ================= 动态读取配置启动机制 =================
def fetch_bot_config():
    """读取 DB 里的 Token 和 Admin ID，容错处理"""
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS mg_settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute("SELECT key, value FROM mg_settings WHERE key IN ('bot_token', 'admin_id')")
        rows = c.fetchall(); conn.close()
        conf = {}
        for r in rows: conf[r['key']] = r['value']
        return conf.get('bot_token', '').strip(), conf.get('admin_id', '').strip()
    except: return "", ""

async def main():
    global BOT_TOKEN, ADMIN_ID
    print("[MG Bot] 守护进程已启动，检查 Web 配置中...")
    
    while True:
        token, admin_id = fetch_bot_config()
        if token and admin_id:
            BOT_TOKEN, ADMIN_ID = token, admin_id
            break
        print("[MG Bot] 尚未在 Web 页面配置 Token 或 Admin ID，系统挂起，10秒后重试...")
        await asyncio.sleep(10)
        
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    print(f"[MG Bot] 配置载入成功！管理员ID: {ADMIN_ID}，开始监听 Telegram 消息...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
