#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# mg_bot.py - MG 私有协议 Telegram 专属管家

import os
import random
import sqlite3
import subprocess
import calendar
import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

# ================= 配置区 =================
BOT_TOKEN = "在此填写您的 Telegram Bot Token"
ADMIN_ID = 123456789  # 【极度重要】在此填写您的个人 Telegram ID，防止他人滥用！

DB_FILE = "/root/mg_core.db"
EXECUTOR_SCRIPT = "/root/mg_executor.sh"
MG_BIN = "/usr/local/bin/mg"
FAKE_DOMAIN = "icloud.com"
# ==========================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# ================= 状态机定义 =================
class AddNodeState(StatesGroup):
    port = State()
    secret = State()
    limit = State()

class EditNodeState(StatesGroup):
    port = State()
    secret = State()
    limit = State()

# ================= 底层与 DB 操作 (与 Web 后端完全对齐) =================
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

# ================= 权限校验拦截器 =================
@router.message()
async def auth_check(message: Message, handler):
    if message.from_user.id != ADMIN_ID: return
    return await handler(message)

@router.callback_query()
async def auth_check_cb(cq: CallbackQuery, handler):
    if cq.from_user.id != ADMIN_ID: return
    return await handler(cq)

# ================= 主菜单 =================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="1. 节点列表"), KeyboardButton(text="2. 添加节点")]],
        resize_keyboard=True
    )

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛡️ 欢迎使用 MG 节点私有管家！\n请使用底部菜单进行操作：", reply_markup=get_main_keyboard())

# ================= 1. 节点列表与详情 =================
@router.message(F.text == "1. 节点列表")
async def show_node_list(message: Message):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM mg_nodes")
    nodes = [dict(row) for row in c.fetchall()]
    conn.close()
    
    running_count = sum(1 for n in nodes if n['status'] == 'running')
    stopped_count = len(nodes) - running_count
    
    await message.answer(f"📊 节点概况\n\n🟢 运行中: {running_count} 个\n⚪ 异常/停用: {stopped_count} 个")
    
    if not nodes:
        return await message.answer("当前没有任何节点记录。")

    # 按到期时间排序 (近的在前，永久有效的在后)
    def sort_key(n):
        if not n['expiry_date']: return datetime.max
        try: return datetime.strptime(n['expiry_date'], '%Y-%m-%d %H:%M:%S')
        except: return datetime.max
    nodes.sort(key=sort_key)

    buttons = []
    for n in nodes:
        status_emoji = "🟢" if n['status'] == 'running' else ("🔴" if n['status'] == 'blocked' else "⚪")
        btn_text = f"{status_emoji} IP:{SERVER_IP} 端口:{n['port']}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"detail_{n['port']}")])
    
    await message.answer("点击下方节点查看详情与操作：", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("detail_"))
async def node_detail(cq: CallbackQuery):
    port = int(cq.data.split("_")[1])
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM mg_nodes WHERE port=?", (port,))
    node = c.fetchone()
    conn.close()
    
    if not node:
        return await cq.answer("节点不存在或已被删除", show_alert=True)
    
    used_gb = round(node['used_bytes'] / (1024**3), 2)
    status_map = {'running': '🟢 运行中', 'stopped': '⚪ 已停止', 'expired': '⏳ 已到期', 'blocked': '🔴 超限阻断'}
    link = f"tg://proxy?server={SERVER_IP}&port={port}&secret={node['secret']}"
    
    text = (
        f"📄 <b>节点配置详情</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🖥 <b>服务器 IP：</b><code>{SERVER_IP}</code>\n"
        f"🔌 <b>监听端口：</b><code>{port}</code>\n"
        f"🕒 <b>到期时间：</b>{node['expiry_date'].split(' ')[0] if node['expiry_date'] else '永久有效'}\n"
        f"📊 <b>流量统计：</b>{used_gb} GB / {node['limit_gb']} GB\n"
        f"♻️ <b>重置周期：</b>{node['reset_cycle']}\n"
        f"📈 <b>当前状态：</b>{status_map.get(node['status'], '未知')}\n\n"
        f"🔑 <b>Secret 密钥：</b>\n<code>{node['secret']}</code>\n\n"
        f"🔗 <b>一键链接：</b>\n<code>{link}</code>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 一键续费(1个月)", callback_data=f"renew_{port}")],
        [InlineKeyboardButton(text="📝 编辑参数", callback_data=f"edit_{port}"), 
         InlineKeyboardButton(text="🔄 流量清零", callback_data=f"reset_{port}")],
        [InlineKeyboardButton(text="❌ 彻底删除", callback_data=f"delete_{port}")]
    ])
    
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await cq.answer()

# ================= 2. 悬浮按钮操作 =================
@router.callback_query(F.data.startswith("renew_"))
async def action_renew(cq: CallbackQuery):
    port = int(cq.data.split("_")[1])
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT expiry_date, status, secret FROM mg_nodes WHERE port=?", (port,))
    node = c.fetchone()
    if not node: return await cq.answer("节点不存在")
    
    now = datetime.now()
    base_date = now
    if node['expiry_date']:
        try:
            curr = datetime.strptime(node['expiry_date'], '%Y-%m-%d %H:%M:%S')
            if curr > now: base_date = curr
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

# ================= 3. 添加节点 FSM =================
@router.message(F.text == "2. 添加节点")
async def add_node_start(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎲 随机生成 5 位数", callback_data="add_random_port")]])
    await message.answer("请输入要监听的【端口号】(1000-65535)：\n或点击下方随机生成。", reply_markup=kb)
    await state.set_state(AddNodeState.port)

@router.message(AddNodeState.port)
@router.callback_query(F.data == "add_random_port", AddNodeState.port)
async def add_node_port(update, state: FSMContext):
    port = ""
    if isinstance(update, CallbackQuery):
        port = str(random.randint(10000, 60000))
        await update.answer()
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
        return await message.answer(f"端口 {port} 已存在，请重新输入或随机生成！")
    conn.close()

    await state.update_data(port=int(port))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔑 自动生成 Secret", callback_data="add_random_secret")]])
    await message.answer("请输入节点的【Secret 密钥】：\n或点击下方自动生成。", reply_markup=kb)
    await state.set_state(AddNodeState.secret)

@router.message(AddNodeState.secret)
@router.callback_query(F.data == "add_random_secret", AddNodeState.secret)
async def add_node_secret(update, state: FSMContext):
    secret = ""
    if isinstance(update, CallbackQuery):
        try: secret = subprocess.check_output(f"{MG_BIN} generate-secret --hex {FAKE_DOMAIN}", shell=True).decode('utf-8').strip()
        except: return await update.message.answer("系统二进制程序调用失败，请手动输入。")
        await update.answer()
        message = update.message
        await message.answer(f"✅ 已生成 Secret：\n<code>{secret}</code>", parse_mode="HTML")
    else:
        secret = update.text.strip()
        message = update

    await state.update_data(secret=secret)
    await message.answer("请输入每月的【总流量限额 (GB)】：\n默认每月重置，请输入纯数字，例如 1000")
    await state.set_state(AddNodeState.limit)

@router.message(AddNodeState.limit)
async def add_node_limit(message: Message, state: FSMContext):
    limit = message.text.strip()
    try: limit = float(limit)
    except: return await message.answer("格式错误，请输入有效数字 (如 500 或 1000)。")

    data = await state.get_data()
    port, secret = data['port'], data['secret']
    expiry_date = add_months(datetime.now(), 1).strftime('%Y-%m-%d %H:%M:%S')

    # 落库并启动
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

# ================= 4. 编辑节点 FSM =================
@router.callback_query(F.data.startswith("edit_"))
async def edit_node_start(cq: CallbackQuery, state: FSMContext):
    port = int(cq.data.split("_")[1])
    await state.update_data(old_port=port)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="保持不变", callback_data=f"keep_port")]])
    await cq.message.answer(f"【修改参数】\n当前监听端口：{port}\n请输入新的端口号：", reply_markup=kb)
    await state.set_state(EditNodeState.port)
    await cq.answer()

@router.message(EditNodeState.port)
@router.callback_query(F.data == "keep_port", EditNodeState.port)
async def edit_node_port(update, state: FSMContext):
    data = await state.get_data()
    old_port = data['old_port']
    new_port = old_port
    message = update.message if isinstance(update, CallbackQuery) else update
    
    if not isinstance(update, CallbackQuery):
        val = update.text.strip()
        if val.isdigit(): new_port = int(val)
        else: return await message.answer("请输入正确的数字端口！")
    
    await state.update_data(new_port=new_port)
    
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT secret FROM mg_nodes WHERE port=?", (old_port,))
    old_secret = c.fetchone()[0]
    conn.close()
    
    await state.update_data(old_secret=old_secret)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="保持不变", callback_data="keep_secret")]])
    await message.answer(f"当前密钥：\n<code>{old_secret}</code>\n\n请输入新的密钥：", parse_mode="HTML", reply_markup=kb)
    await state.set_state(EditNodeState.secret)

@router.message(EditNodeState.secret)
@router.callback_query(F.data == "keep_secret", EditNodeState.secret)
async def edit_node_secret(update, state: FSMContext):
    data = await state.get_data()
    new_secret = data['old_secret']
    message = update.message if isinstance(update, CallbackQuery) else update
    
    if not isinstance(update, CallbackQuery):
        new_secret = update.text.strip()

    await state.update_data(new_secret=new_secret)
    
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT limit_gb FROM mg_nodes WHERE port=?", (data['old_port'],))
    old_limit = c.fetchone()[0]
    conn.close()

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="保持不变", callback_data="keep_limit")]])
    await message.answer(f"当前流量限额：{old_limit} GB\n\n请输入新的流量限额(纯数字)：", reply_markup=kb)
    await state.set_state(EditNodeState.limit)

@router.message(EditNodeState.limit)
@router.callback_query(F.data == "keep_limit", EditNodeState.limit)
async def edit_node_limit(update, state: FSMContext):
    data = await state.get_data()
    old_port, new_port = data['old_port'], data['new_port']
    new_secret = data['new_secret']
    message = update.message if isinstance(update, CallbackQuery) else update
    
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT limit_gb, status FROM mg_nodes WHERE port=?", (old_port,))
    row = c.fetchone()
    new_limit, status = row[0], row[1]
    
    if not isinstance(update, CallbackQuery):
        try: new_limit = float(update.text.strip())
        except: return await message.answer("请输入有效数字。")
    
    # 执行替换逻辑
    if status == 'running':
        run_executor('stop', old_port)
        remove_iptables_rules(old_port)
    
    c.execute('''UPDATE mg_nodes SET port=?, secret=?, limit_gb=?, status='running' 
                 WHERE port=?''', (new_port, new_secret, new_limit, old_port))
    conn.commit(); conn.close()
    
    setup_iptables_monitor(new_port)
    unblock_port(new_port)
    run_executor('start', new_port, new_secret)
    
    await state.clear()
    link = f"tg://proxy?server={SERVER_IP}&port={new_port}&secret={new_secret}"
    await message.answer(f"✅ <b>修改完成并已重启进程！</b>\n\n新直连链接：\n<code>{link}</code>", parse_mode="HTML")

# ================= 启动轮询 =================
async def main():
    dp.include_router(router)
    print("Bot 启动成功...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
