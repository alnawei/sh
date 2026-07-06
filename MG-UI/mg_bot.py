#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# mg_bot.py - MG 节点 Telegram 管家 (Fixed FSM & MemoryStorage)

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
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command

# ================= 全局系统配置 =================
DB_FILE = "/root/mg_core.db"
EXECUTOR_SCRIPT = "/root/mg_executor.sh"
MG_BIN = "/usr/local/bin/mg"
FAKE_DOMAIN = "icloud.com"

BOT_TOKEN = ""
ADMIN_ID = ""

router = Router()

# ================= FSM 状态机定义 =================
class AddNodeState(StatesGroup): 
    port = State()
    secret = State()
    limit = State()

class EditNodeState(StatesGroup): 
    limit = State()
    secret = State()

# ================= 底层与 DB 操作 =================
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

# ================= 鉴权中间件 =================
class AuthMiddleware(BaseMiddleware):
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

def get_main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="1. 节点列表"), KeyboardButton(text="2. 添加节点")]], resize_keyboard=True)

# ================= 基础指令与取消操作 =================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛡️ 欢迎使用 MG 私有管家！您的管理员身份已验证。\n请使用底部菜单进行操作：", reply_markup=get_main_keyboard())

@router.message(Command("cancel"))
@router.message(F.text.lower() == "/cancel")
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ 当前操作已取消。", reply_markup=get_main_keyboard())

# ================= 1. 节点列表与详情 =================
@router.message(F.text == "1. 节点列表")
async def show_node_list(message: Message, state: FSMContext):
    await state.clear()
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

# ================= 节点独立操作按钮 =================
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

# ================= 2. 修复：编辑节点 FSM =================
@router.callback_query(F.data.startswith("edit_"))
async def edit_node_start(cq: CallbackQuery, state: FSMContext):
    await cq.answer() # 第一时间响应并消除按钮转圈
    port = int(cq.data.split("_")[1])
    await state.update_data(edit_port=port)
    await cq.message.answer(f"🔧 正在编辑端口 <b>{port}</b> 的节点\n\n请输入新的总流量限额(GB)，或发送 /cancel 取消：", parse_mode="HTML")
    await state.set_state(EditNodeState.limit)

@router.message(EditNodeState.limit)
async def edit_node_limit(message: Message, state: FSMContext):
    text = message.text.strip()
    try: limit = float(text)
    except ValueError: return await message.answer("格式错误，请输入纯数字（例如 1000）：")
    
    await state.update_data(limit=limit)
    await message.answer("请输入新的 Secret 密钥：\n(回复 0 保持现有密钥不变，回复 1 重新随机生成)")
    await state.set_state(EditNodeState.secret)

@router.message(EditNodeState.secret)
async def edit_node_secret(message: Message, state: FSMContext):
    secret_input = message.text.strip()
    data = await state.get_data()
    port = data['edit_port']
    new_limit = data['limit']

    conn = get_db(); c = conn.cursor()
    c.execute("SELECT secret, status FROM mg_nodes WHERE port=?", (port,))
    row = c.fetchone()
    
    if not row:
        conn.close(); await state.clear()
        return await message.answer("编辑失败：该节点已不存在。")
        
    old_secret, status = row['secret'], row['status']

    if secret_input == '0': new_secret = old_secret
    elif secret_input == '1':
        try: new_secret = subprocess.check_output(f"{MG_BIN} generate-secret --hex {FAKE_DOMAIN}", shell=True).decode('utf-8').strip()
        except: new_secret = old_secret
    else: new_secret = secret_input

    # 停止旧进程，更新数据，启动新进程
    if status == 'running':
        run_executor('stop', port)
        
    c.execute('''UPDATE mg_nodes SET secret=?, limit_gb=?, status='running' WHERE port=?''', 
              (new_secret, new_limit, port))
    conn.commit(); conn.close()
    
    unblock_port(port)
    run_executor('start', port, new_secret)
    await state.clear()
    
    link = f"tg://proxy?server={SERVER_IP}&port={port}&secret={new_secret}"
    await message.answer(f"✅ <b>修改完成并已重载进程！</b>\n\n新直连链接：\n<code>{link}</code>", parse_mode="HTML", reply_markup=get_main_keyboard())

# ================= 3. 修复：添加节点 FSM =================
@router.message(F.text == "2. 添加节点")
async def add_node_start(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎲 随机生成", callback_data="add_random_port")]])
    await message.answer("请输入你要添加的端口号（回复随机生成请点击下方按钮）：\n(发送 /cancel 取消操作)", reply_markup=kb)
    await state.set_state(AddNodeState.port)

@router.message(AddNodeState.port)
@router.callback_query(F.data == "add_random_port", AddNodeState.port)
async def add_node_port(update, state: FSMContext):
    if isinstance(update, CallbackQuery):
        await update.answer()
        port = str(random.randint(10000, 60000))
        message = update.message
        await message.answer(f"✅ 已选择随机端口：{port}")
    else:
        port = update.text.strip()
        message = update
        if not port.isdigit(): return await message.answer("格式错误，请输入纯数字端口！")
    
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id FROM mg_nodes WHERE port=?", (port,))
    if c.fetchone():
        conn.close()
        return await message.answer(f"端口 {port} 已被占用，请重新输入或随机生成！")
    conn.close()

    await state.update_data(port=int(port))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔑 自动生成 Secret", callback_data="add_random_secret")]])
    await message.answer("请输入节点的【Secret 密钥】：\n或点击下方自动生成。", reply_markup=kb)
    await state.set_state(AddNodeState.secret)

@router.message(AddNodeState.secret)
@router.callback_query(F.data == "add_random_secret", AddNodeState.secret)
async def add_node_secret(update, state: FSMContext):
    if isinstance(update, CallbackQuery):
        await update.answer()
        try: secret = subprocess.check_output(f"{MG_BIN} generate-secret --hex {FAKE_DOMAIN}", shell=True).decode('utf-8').strip()
        except: return await update.message.answer("二进制程序调用失败，请手动输入。")
        message = update.message
        await message.answer(f"✅ 已生成 Secret：\n<code>{secret}</code>", parse_mode="HTML")
    else:
        secret = update.text.strip()
        message = update

    await state.update_data(secret=secret)
    await message.answer("请输入每月的【总流量限额 (GB)】：\n例如输入 1000 （默认按每月自然重置计算）")
    await state.set_state(AddNodeState.limit)

@router.message(AddNodeState.limit)
async def add_node_limit(message: Message, state: FSMContext):
    try: limit = float(message.text.strip())
    except: return await message.answer("格式错误，请输入有效数字 (如 500 或 1000)。")

    data = await state.get_data()
    port, secret = data['port'], data['secret']
    expiry_date = add_months(datetime.now(), 1).strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db(); c = conn.cursor()
    c.execute('''INSERT INTO mg_nodes (port, secret, limit_gb, status, reset_cycle, expiry_date) 
                 VALUES (?, ?, ?, 'running', 'monthly', ?)''', (port, secret, limit, expiry_date))
    conn.commit(); conn.close()
    
    setup_iptables_monitor(port)
    unblock_port(port)
    run_executor('start', port, secret)

    await state.clear()
    link = f"tg://proxy?server={SERVER_IP}&port={port}&secret={secret}"
    await message.answer(f"🎉 <b>节点建立成功！</b>\n\n一键直连链接：\n<code>{link}</code>", parse_mode="HTML", reply_markup=get_main_keyboard())


# ================= 动态读取配置启动机制 =================
def fetch_bot_config():
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
    # 【非常关键】引入 MemoryStorage 提供上下文记忆
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    print(f"[MG Bot] 配置载入成功！管理员ID: {ADMIN_ID}，开始监听 Telegram 消息...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
