import os
import json
import logging
from datetime import datetime, timezone, timedelta
from telegram import Update, InputMediaVideo, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DEEP_LINK_PAYLOAD = "UB3A6P"
ADMIN_ID = 7602115007
COUNTER_FILE  = os.path.join(os.path.dirname(__file__), "counter.json")
BLACKLIST_FILE = os.path.join(os.path.dirname(__file__), "blacklist.json")
USERS_FILE     = os.path.join(os.path.dirname(__file__), "users.json")
APPROVED_FILE  = os.path.join(os.path.dirname(__file__), "approved.json")
WIB = timezone(timedelta(hours=7))

# In-memory store for requests awaiting admin decision.
# { user_id: {"chat_id": int, "waiting_msg_id": int, "full_name": str, "username": str} }
pending_requests: dict = {}

# In-memory set of admin user_ids waiting to send a media for /getid
getid_waiting: set = set()

FILE_IDS = [
    ("video", os.environ.get("FILE_ID_1", "")),
    ("video", os.environ.get("FILE_ID_2", "")),
    ("video", os.environ.get("FILE_ID_3", "")),
    ("photo", os.environ.get("FILE_ID_4", "")),
    ("photo", os.environ.get("FILE_ID_5", "")),
    ("photo", os.environ.get("FILE_ID_6", "")),
]

# ---------------------------------------------------------------------------
# Media helpers
# ---------------------------------------------------------------------------

def build_media_group():
    media = []
    for kind, fid in FILE_IDS:
        if not fid:
            return None
        if kind == "video":
            media.append(InputMediaVideo(media=fid))
        else:
            media.append(InputMediaPhoto(media=fid))
    return media

async def deliver_album(bot, chat_id: int):
    """Send the progress message, album, then confirmation to chat_id."""
    media = build_media_group()
    if not media:
        logger.error("One or more FILE_ID env vars are missing.")
        return False
    try:
        progress = await bot.send_message(chat_id, "📦 Mengirim Batch 1/1 (6 media)...\nMohon tunggu...")
        await bot.send_media_group(chat_id, media=media)
        await progress.delete()
        await bot.send_message(
            chat_id,
            "<b>📢 Bot Resmi milik @BocilVIP89</b>\n"
            "✅ Semua 6 media terkirim!",
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to deliver album to {chat_id}: {e}")
        return False

# ---------------------------------------------------------------------------
# Approved users 
# ---------------------------------------------------------------------------

def read_approved() -> set:
    try:
        if not os.path.exists(APPROVED_FILE):
            return set()
        with open(APPROVED_FILE, "r") as f:
            return set(json.load(f).get("approved", []))
    except Exception:
        return set()

def save_approved(approved: set):
    try:
        with open(APPROVED_FILE, "w") as f:
            json.dump({"approved": list(approved)}, f)
    except Exception as e:
        logger.error(f"Approved write error: {e}")

# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------

def read_blacklist() -> dict:
    try:
        if not os.path.exists(BLACKLIST_FILE):
            return {}
        with open(BLACKLIST_FILE, "r") as f:
            data = json.load(f)
        entries = data.get("banned", [])
        result = {}
        for entry in entries:
            if isinstance(entry, dict):
                uid = entry.get("user_id")
                if uid:
                    result[int(uid)] = {
                        "full_name": entry.get("full_name", "-"),
                        "username": entry.get("username", "-"),
                    }
            elif isinstance(entry, int):
                result[entry] = {"full_name": "-", "username": "-"}
        return result
    except Exception as e:
        logger.error(f"Blacklist read error: {e}")
        return {}

def write_blacklist(bl: dict):
    try:
        entries = [
            {"user_id": uid, "full_name": info["full_name"], "username": info["username"]}
            for uid, info in bl.items()
        ]
        with open(BLACKLIST_FILE, "w") as f:
            json.dump({"banned": entries}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Blacklist write error: {e}")

# ---------------------------------------------------------------------------
# User registry
# ---------------------------------------------------------------------------

def read_user_registry() -> dict:
    try:
        if not os.path.exists(USERS_FILE):
            return {}
        with open(USERS_FILE, "r") as f:
            data = json.load(f)
        return {int(k): v for k, v in data.items()}
    except Exception as e:
        logger.error(f"User registry read error: {e}")
        return {}

def save_user_to_registry(user_id: int, full_name: str, username: str):
    registry = read_user_registry()
    registry[user_id] = {"full_name": full_name, "username": username}
    try:
        with open(USERS_FILE, "w") as f:
            json.dump({str(k): v for k, v in registry.items()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"User registry write error: {e}")

# ---------------------------------------------------------------------------
# Counter
# ---------------------------------------------------------------------------

def read_counter() -> int:
    try:
        if os.path.exists(COUNTER_FILE):
            with open(COUNTER_FILE, "r") as f:
                return json.load(f).get("count", 0)
        return 0
    except Exception:
        return 0

def increment_counter() -> int:
    try:
        data = {"count": 0}
        if os.path.exists(COUNTER_FILE):
            with open(COUNTER_FILE, "r") as f:
                data = json.load(f)
        data["count"] += 1
        with open(COUNTER_FILE, "w") as f:
            json.dump(data, f)
        return data["count"]
    except Exception as e:
        logger.error(f"Counter error: {e}")
        return -1

# ---------------------------------------------------------------------------
# Admin notification (no counter shown)
# ---------------------------------------------------------------------------

async def notify_admin(bot, full_name: str, username: str, user_id: int):
    now = datetime.now(WIB).strftime("%d %b %Y, %H:%M:%S WIB")
    text = (
        f"🟢 *Media VIP Diakses*\n\n"
        f"Name: {full_name}\n"
        f"Username: {username}\n"
        f"User ID: `{user_id}`\n\n"
        f"Time: {now}"
    )
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

# ---------------------------------------------------------------------------
# /start — deep link handler with approval gate
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] != DEEP_LINK_PAYLOAD:
        return

    user = update.effective_user
    user_id   = user.id
    full_name = user.full_name or "-"
    username  = f"@{user.username}" if user.username else "-"

    # Silently ignore banned users
    if user_id in read_blacklist():
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🚫 Akses Anda telah dibatasi."
        )
        return


    # Admin always bypasses approval
    if user_id == ADMIN_ID:
        ok = await deliver_album(context.bot, update.effective_chat.id)
        if ok:
            save_user_to_registry(user_id, full_name, username)
            increment_counter()
            await notify_admin(context.bot, full_name, username, user_id)
        return

    # Already approved — deliver immediately
    if user_id in read_approved():
        ok = await deliver_album(context.bot, update.effective_chat.id)
        if ok:
            save_user_to_registry(user_id, full_name, username)
            increment_counter()
            await notify_admin(context.bot, full_name, username, user_id)
        return

    # Already waiting for approval — ignore duplicate taps
    if user_id in pending_requests:
        return

    # Send waiting message to user
    waiting_msg = await update.message.reply_text("⏳ Bot sedang idle…\n\nEstimasi waktu: 40 menit.\n\nJoin VIP? @BocilVIP89")

    # Store pending request
    pending_requests[user_id] = {
        "chat_id":       update.effective_chat.id,
        "waiting_msg_id": waiting_msg.message_id,
        "full_name":     full_name,
        "username":      username,
    }

    # Send approval request to admin
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Izinkan", callback_data=f"izin|{user_id}"),
            InlineKeyboardButton("❌ Tolak",   callback_data=f"tolak|{user_id}"),
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🔔 *Permintaan Akses VIP*\n\n"
            f"Name: {full_name}\n"
            f"Username: {username}\n"
            f"User ID: `{user_id}`"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

# ---------------------------------------------------------------------------
# Callback query — admin presses ✅ Izinkan or ❌ Tolak
# ---------------------------------------------------------------------------

async def approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Only the admin can act on these buttons
    if query.from_user.id != ADMIN_ID:
        return

    try:
        action, uid_str = query.data.split("|", 1)
        user_id = int(uid_str)
    except Exception:
        return

    pending = pending_requests.pop(user_id, None)

    if action == "izin":
        # Edit admin message to reflect decision
        name_str = pending["full_name"] if pending else str(user_id)
        await query.edit_message_text(f"✅ Diizinkan — {name_str}")

        # Add to approved list
        approved = read_approved()
        approved.add(user_id)
        save_approved(approved)

        if pending:
            chat_id = pending["chat_id"]
            # Delete waiting message
            try:
                await context.bot.delete_message(chat_id, pending["waiting_msg_id"])
            except Exception:
                pass
            # Deliver album
            ok = await deliver_album(context.bot, chat_id)
            if ok:
                save_user_to_registry(user_id, pending["full_name"], pending["username"])
                increment_counter()
                await notify_admin(context.bot, pending["full_name"], pending["username"], user_id)

    elif action == "tolak":
        name_str = pending["full_name"] if pending else str(user_id)
        await query.edit_message_text(f"❌ Ditolak — {name_str}")

        # Add to blacklist
        full_name = pending["full_name"] if pending else "-"
        username  = pending["username"]  if pending else "-"
        bl = read_blacklist()
        bl[user_id] = {"full_name": full_name, "username": username}
        write_blacklist(bl)

        if pending:
            chat_id = pending["chat_id"]
            # Delete waiting message
            try:
                await context.bot.delete_message(chat_id, pending["waiting_msg_id"])
            except Exception:
                pass
            # Notify user of rejection
            try:
                await context.bot.send_message(chat_id, "❌ Permintaan akses ditolak.")
            except Exception:
                pass

# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban USER_ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /ban USER_ID")
        return

    registry = read_user_registry()
    if target_id in registry:
        full_name = registry[target_id]["full_name"]
        username  = registry[target_id]["username"]
    else:
        full_name = "-"
        username  = "-"
        try:
            chat = await context.bot.get_chat(target_id)
            full_name = chat.full_name or "-"
            username  = f"@{chat.username}" if chat.username else "-"
        except Exception:
            pass

    bl = read_blacklist()
    bl[target_id] = {"full_name": full_name, "username": username}
    write_blacklist(bl)

    # Also remove from approved list if present
    approved = read_approved()
    if target_id in approved:
        approved.discard(target_id)
        save_approved(approved)

    await update.message.reply_text("✅ User banned.")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban USER_ID")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /unban USER_ID")
        return

    bl = read_blacklist()
    bl.pop(target_id, None)
    write_blacklist(bl)
    await update.message.reply_text("✅ User unbanned.")

async def banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    bl = read_blacklist()
    if not bl:
        await update.message.reply_text("🚫 Tidak ada user yang dibanned.")
        return
    lines = []
    for i, (uid, info) in enumerate(sorted(bl.items()), start=1):
        uname = info["username"] if info["username"] != "-" else "-"
        lines.append(
            f"{i}.\nName: {info['full_name']}\nUsername: {uname}\nUser ID: `{uid}`"
        )
    await update.message.reply_text(
        f"🚫 *Blacklisted Users*\n\n" + "\n\n".join(lines),
        parse_mode="Markdown",
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    count = read_counter()
    await update.message.reply_text(
        f"📊 *Stats Bot*\n\nTotal penggunaan `UB3A6P`: *{count}x*",
        parse_mode="Markdown",
    )

async def resetstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        with open(COUNTER_FILE, "w") as f:
            json.dump({"count": 0}, f)
    except Exception as e:
        logger.error(f"Failed to reset counter: {e}")
        return
    await update.message.reply_text("✅ Statistik berhasil direset!")

# ---------------------------------------------------------------------------
# /getid — admin tool to retrieve Telegram file_id from any media
# ---------------------------------------------------------------------------

async def getid_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    getid_waiting.add(update.effective_user.id)
    await update.message.reply_text(
        "📎 Kirim satu file media (foto, video, dokumen, audio, voice, animasi, atau sticker).\n\n"
        "Ketik /cancel untuk membatalkan."
    )

async def getid_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in getid_waiting:
        return
    getid_waiting.discard(user_id)

    msg = update.message
    file_id = None
    kind = None

    if msg.photo:
        file_id = msg.photo[-1].file_id
        kind = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        kind = "video"
    elif msg.document:
        file_id = msg.document.file_id
        kind = "document"
    elif msg.audio:
        file_id = msg.audio.file_id
        kind = "audio"
    elif msg.voice:
        file_id = msg.voice.file_id
        kind = "voice"
    elif msg.animation:
        file_id = msg.animation.file_id
        kind = "animation"
    elif msg.sticker:
        file_id = msg.sticker.file_id
        kind = "sticker"

    if file_id:
        await msg.reply_text(
            f"✅ File ID ({kind}):\n\n{file_id}"
        )
    else:
        await msg.reply_text("⚠️ Tidak ada media yang terdeteksi. Kirim ulang atau /cancel.")
        getid_waiting.add(user_id)

async def getid_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    getid_waiting.discard(update.effective_user.id)
    await update.message.reply_text("❌ /getid dibatalkan.")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable is not set.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("stats",      stats))
    app.add_handler(CommandHandler("resetstats", resetstats))
    app.add_handler(CommandHandler("ban",        ban))
    app.add_handler(CommandHandler("unban",      unban))
    app.add_handler(CommandHandler("banned",     banned))
    app.add_handler(CommandHandler("getid",      getid_start))
    app.add_handler(CommandHandler("cancel",     getid_cancel))
    app.add_handler(CallbackQueryHandler(approval_callback, pattern=r"^(izin|tolak)\|"))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL |
        filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL,
        getid_receive,
    ))

    
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()