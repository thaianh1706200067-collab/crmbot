import os
import asyncio
import aiohttp
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# 確保在 Python 3.12+ / 3.14 環境下具備全域 Event Loop
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

BOT_TOKEN = "8873928485:AAE6uAy_40mJq3doO8OVi8AwzFWM2I3Ue5o"
GAS_URL = "https://script.google.com/macros/s/AKfycbxlkgD0qFHvei_x0li8l9OtEl9-jFoirdf_Q0iwKrOVLokLXdY7-hIDkyE8h6Q0Bumn/exec"

# ==================== 權限名單設定區 ====================
# 最高主管名單（可建檔、可查閱全部資料）：
ADMIN_USERS = [
    8428414321,   # 妳的 ID
]

# 一般查閱成員名單（僅可瀏覽客戶總表與資料卡，無建檔權限）：
# 若有新業務或助理，讓對方去 @userinfobot 取得數字 ID 後加入括號中（用逗號隔開）
VIEWER_USERS = [
    # 123456789,
]

# 檢查是否為主管
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USERS

# 檢查是否具備系統存取權（主管或查閱成員）
def has_access(user_id: int) -> bool:
    return user_id in ADMIN_USERS or user_id in VIEWER_USERS
# =======================================================

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

# 主選單
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_access(user_id):
        await update.message.reply_text("⚠️ 本系統為內部商業 CRM 機密資料庫，未授權人員無法存取。")
        return

    identity_text = "👑 *主管模式*" if is_admin(user_id) else "👀 *成員查閱模式*"
    text = f"💼 *【商業客戶管理系統 (CRM)】*\n身分：{identity_text}\n請選擇操作功能："
    await update.message.reply_text(text, reply_markup=get_main_menu_markup(), parse_mode="Markdown")

# 建檔指令：只有主管有權限
async def add_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global local_clients
    user_id = update.effective_user.id

    # 1. 權限檢查：僅主管可建檔
    if not is_admin(user_id):
        await update.message.reply_text("⛔ *權限不足*：您僅具備客戶資料查閱權限，無法新增建檔！", parse_mode="Markdown")
        return

    # 2. 格式檢查
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
        f"資料已同步存入 Google 試算表「商業客戶資料庫」。"
    )
    await update.message.reply_text(reply_text, parse_mode="Markdown")

    asyncio.create_task(fetch_gas({
        "action": "add_client",
        "name": name,
        "phone": phone,
        "company": company,
        "notes": notes
    }))

# 按鈕回調
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global local_clients
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    try:
        await query.answer()
    except Exception:
        pass

    # 攔截所有未授權按鈕點擊
    if not has_access(user_id):
        try:
            await query.answer("⚠️ 未獲授權，無法存取內部資料！", show_alert=True)
        except Exception:
            pass
        return

    identity_text = "👑 *主管模式*" if is_admin(user_id) else "👀 *成員查閱模式*"

    if data == "back_main":
        text = f"💼 *【商業客戶管理系統 (CRM)】*\n身分：{identity_text}\n請選擇操作功能："
        await safe_edit_text(query, text, get_main_menu_markup())
        return

    elif data == "show_guide":
        if is_admin(user_id):
            text = (
                "📖 *【主管快速建檔指引】*\n"
                "隨時在對話框直接輸入：\n"
                "`/client 姓名 電話 公司職稱 需求備註`\n\n"
                "例如：\n"
                "`/client 陳總 0922888999 創世紀投資 對系統導入感興趣`"
            )
        else:
            text = (
                "📖 *【查閱成員使用指引】*\n"
                "您當前為查閱權限：\n"
                "• 可點擊「💼 查看客戶總表」瀏覽客戶資料\n"
                "• 如需新增或修改資料，請聯繫主管執行。"
            )
        keyboard = [[InlineKeyboardButton("⬅️ 回主選單", callback_data="back_main")]]
        await safe_edit_text(query, text, InlineKeyboardMarkup(keyboard))
        return

    elif data == "list_clients":
        if not local_clients:
            text = "💼 *【客戶總表】*\n目前資料庫尚無客戶資料！"
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
            await safe_edit_text(query, "查無此客戶資料！", InlineKeyboardMarkup([[InlineKeyboardButton("⬅️️ 返回列表", callback_data="list_clients")]]))
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

async def start_web_server():
    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    
    commands = [
        BotCommand("menu", "開啟 CRM 主選單"),
        BotCommand("client", "新增客戶 (僅限主管)"),
    ]
    app.add_handler(CommandHandler("start", menu))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("client", add_client))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # 啟動 Web 探針供 Render 保活
    await start_web_server()

    # 初始化 Telegram 機器人
    await app.initialize()
    await app.bot.set_my_commands(commands)
    await app.start()
    await app.updater.start_polling()

    # 背景同步資料庫
    asyncio.create_task(bg_sync_clients())

    print("商業 CRM 機器人已成功在線運作中！")

    stop_event = asyncio.Event()
    await stop_event.wait()

def main():
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
