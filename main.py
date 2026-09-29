import os
import asyncio
import aiohttp
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# 全新 CRM 專屬機器人配置
BOT_TOKEN = "8873928485:AAE6uAy_40mJq3doO8OVi8AwzFWM2I3Ue5o"
ADMIN_CHAT_ID = 7203467559  # 只有妳本人能操作
GAS_URL = "https://script.google.com/macros/s/AKfycbxlkgD0qFHvei_x0li8l9OtEl9-jFoirdf_Q0iwKrOVLokLXdY7-hIDkyE8h6Q0Bumn/exec"

# 本地快取（確保點擊按鈕 0.1 秒秒開）
local_clients = {}

async def fetch_gas(params):
    try:
        timeout = aiohttp.ClientTimeout(total=4.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(GAS_URL, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        print(f"[GAS 連線] {e}")
    return None

async def bg_sync_clients():
    global local_clients
    res = await fetch_gas({"action": "get_clients"})
    if isinstance(res, dict):
        local_clients = {int(k): v for k, v in res.items()}

def get_main_menu_markup():
    keyboard = [
        [InlineKeyboardButton("💼 查看客戶總表", callback_data="list_clients")],
        [InlineKeyboardButton("➕ 快速建檔指引", callback_data="show_guide")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def safe_edit_text(query, text, reply_markup=None):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise e

# 主選單指令：/menu 或 /start
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ 本系統為個人商業 CRM 機密資料庫，未授權無法存取。")
        return

    text = "💼 *【商業客戶管理系統 (CRM)】*\n請選擇操作功能："
    await update.message.reply_text(text, reply_markup=get_main_menu_markup(), parse_mode="Markdown")

# 建檔指令：/client 姓名 電話 公司職稱 需求備註
async def add_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global local_clients
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ 權限不足。")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📋 *建檔格式說明：*\n"
            "`/client 姓名 電話 公司職稱 需求備註`\n\n"
            "💡 *範例：*\n"
            "`/client 王大明 0912345678 鼎盛科技 預約下週三提案、預算50萬`",
            parse_mode="Markdown"
        )
        return

    name = args[0]
    phone = args[1]
    company = args[2] if len(args) > 2 else "未填寫"
    notes = " ".join(args[3:]) if len(args) > 3 else "暫無特別備註"

    new_id = (max(local_clients.keys(), default=0)) + 1
    local_clients[new_id] = {
        "name": name,
        "phone": phone,
        "company": company,
        "notes": notes,
        "created_at": "剛剛"
    }

    reply_text = (
        f"✅ *客戶建檔成功！*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 編號：`#{new_id}`\n"
        f"👤 姓名：*{name}*\n"
        f"📞 電話：`{phone}`\n"
        f"🏢 公司/職稱：{company}\n"
        f"📝 需求備註：{notes}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"資料已同步存入 Google 試算表。"
    )
    await update.message.reply_text(reply_text, parse_mode="Markdown")

    asyncio.create_task(fetch_gas({
        "action": "add_client",
        "name": name,
        "phone": phone,
        "company": company,
        "notes": notes
    }))

# 按鈕回調處理
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global local_clients
    query = update.callback_query
    data = query.data

    try:
        await query.answer()
    except Exception:
        pass

    if data == "back_main":
        text = "💼 *【商業客戶管理系統 (CRM)】*\n請選擇操作功能："
        await safe_edit_text(query, text, get_main_menu_markup())
        return

    elif data == "show_guide":
        text = (
            "📖 *【快速建檔指引】*\n"
            "隨時在對話框直接輸入：\n"
            "`/client 姓名 電話 公司職稱 需求備註`\n\n"
            "例如：\n"
            "`/client 陳總 0922888999 創世紀投資 對系統導入感興趣`"
        )
        keyboard = [[InlineKeyboardButton("⬅️ 回主選單", callback_data="back_main")]]
        await safe_edit_text(query, text, InlineKeyboardMarkup(keyboard))
        return

    elif data == "list_clients":
        if not local_clients:
            text = "💼 *【客戶總表】*\n目前資料庫尚無客戶資料！\n請直接輸入 `/client` 快速新增。"
            keyboard = [[InlineKeyboardButton("⬅️ 回主選單", callback_data="back_main")]]
            await safe_edit_text(query, text, InlineKeyboardMarkup(keyboard))
            return

        text = "💼 *【客戶管理總表】*\n點選客戶檢視完整檔案："
        keyboard = []
        for c_id, c_info in local_clients.items():
            btn_text = f"#{c_id} {c_info.get('name')} ({c_info.get('company')})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"view_client_{c_id}")])
        keyboard.append([InlineKeyboardButton("⬅️ 回主選單", callback_data="back_main")])
        await safe_edit_text(query, text, InlineKeyboardMarkup(keyboard))
        return

    elif data.startswith("view_client_"):
        c_id = int(data.split("_")[2])
        client = local_clients.get(c_id)
        if not client:
            await safe_edit_text(query, "查無此客戶資料！", InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回列表", callback_data="list_clients")]]))
            return

        text = (
            f"👤 *客戶詳細檔案 - #{c_id}*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"• 姓名：*{client.get('name')}*\n"
            f"• 電話：`{client.get('phone')}`\n"
            f"• 公司/職稱：{client.get('company')}\n"
            f"• 需求/備註：{client.get('notes')}\n"
            f"━━━━━━━━━━━━━━━"
        )
        keyboard = [
            [InlineKeyboardButton("⬅️ 返回客戶列表", callback_data="list_clients")],
            [InlineKeyboardButton("🏠 回主選單", callback_data="back_main")]
        ]
        await safe_edit_text(query, text, InlineKeyboardMarkup(keyboard))
        return

async def health_check(request):
    return web.Response(text="CRM Bot is running!")

async def post_init(application: Application):
    commands = [
        BotCommand("menu", "開啟 CRM 主選單"),
        BotCommand("client", "新增客戶 (例: /client 姓名 電話 公司 備註)"),
    ]
    await application.bot.set_my_commands(commands)

    # 啟動 Web 服務保持活躍
    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    # 開機後背景載入客戶清單
    asyncio.create_task(bg_sync_clients())

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", menu))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("client", add_client))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("商業 CRM 機器人已上線...")
    app.run_polling()

if __name__ == "__main__":
    main()
