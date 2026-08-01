import os
import json
import logging
import shutil
import asyncio
import time
import copy
from datetime import datetime, timezone, timedelta
from telegram import Update, InputMediaVideo, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
DATA_DIR = "/data"
APP_DIR = os.path.dirname(__file__)

os.makedirs(DATA_DIR, exist_ok=True)

DEEP_LINK_A = "UC3A6P"

ADMIN_ID = 7602115007
CHANNEL_ID = -1004363191859
ORDER_HISTORY_EXCLUDED = {
    ADMIN_ID,
    # Tambahkan User ID akun testing di bawah ini
    # Contoh:
    # 123456789
    #7955763972
}
COUNTER_FILE = os.path.join(DATA_DIR, "counter.json")
BLACKLIST_FILE = os.path.join(DATA_DIR, "blacklist.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
APPROVED_FILE = os.path.join(DATA_DIR, "approved.json")
VIP_PACKAGES_FILE = os.path.join(DATA_DIR, "vip_packages.json")
ORDER_HISTORY_FILE = os.path.join(DATA_DIR, "order_history.json")
PENDING_ORDERS_FILE = os.path.join(DATA_DIR, "pending_orders.json")
PAYMENT_LOCK_FILE = os.path.join(DATA_DIR, "payment_lock.json")
FILE_MANAGER_BACKUP_DIR = os.path.join(DATA_DIR, "backups")

def migrate_to_volume(filename):
    src = os.path.join(APP_DIR, filename)
    dst = os.path.join(DATA_DIR, filename)

    if not os.path.exists(dst) and os.path.exists(src):
        shutil.copy2(src, dst)
        logger.info(f"{filename} berhasil disalin ke Volume.")
        
# In-memory cache for vip_packages.json (deep-copied on read/write since
# callers mutate individual package dicts in place before saving).
_vip_packages_cache = None

def read_vip_packages():
    global _vip_packages_cache
    if _vip_packages_cache is not None:
        return copy.deepcopy(_vip_packages_cache)
    with open(VIP_PACKAGES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    _vip_packages_cache = copy.deepcopy(data)
    return copy.deepcopy(_vip_packages_cache)

def save_vip_packages(data):
    global _vip_packages_cache
    with open(VIP_PACKAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _vip_packages_cache = copy.deepcopy(data)

def read_order_history():
    if not os.path.exists(ORDER_HISTORY_FILE):
        return {"orders": []}

    with open(ORDER_HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_order_history(data):
    with open(ORDER_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )
        
def read_pending_orders():
    if not os.path.exists(PENDING_ORDERS_FILE):
        return {"orders": []}

    with open(PENDING_ORDERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_pending_orders(data):
    with open(PENDING_ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

def read_payment_lock():
    if not os.path.exists(PAYMENT_LOCK_FILE):
        return {}
    with open(PAYMENT_LOCK_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {int(uid): value for uid, value in data.items()}

def save_payment_lock(data):
    with open(PAYMENT_LOCK_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {str(uid): value for uid, value in data.items()},
            f,
            ensure_ascii=False,
            indent=2
        )
    
def lock_payment(user_id, package_id):
    data = read_payment_lock()
    data[user_id] = {
        "package_id": package_id
    }
    save_payment_lock(data)
    print(f"[LOCK] User {user_id} locked (package {package_id})")

def unlock_payment(user_id):
    data = read_payment_lock()
    data.pop(user_id, None)
    save_payment_lock(data)

def get_payment_lock(user_id):
    data = read_payment_lock()
    lock = data.get(user_id)
    if lock:
        print(f"[LOCK] User {user_id} already locked")
    return lock
    
def get_locked_package_id(user_id):
    lock = get_payment_lock(user_id)
    if not lock:
        return None
    return lock["package_id"]
# ==========================

# SETTINGS

# ==========================

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# In-memory cache for settings.json — read once, refreshed on every save.
_settings_cache = None

def read_settings():

    global _settings_cache

    if _settings_cache is not None:
        return dict(_settings_cache)

    if not os.path.exists(SETTINGS_FILE):

        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:

            json.dump(

                {
                    "qris_file_id": "",
                    "join_vip_enabled": True,
                    "preview_approval_enabled": True,
                    "live_chat_enabled": False,
                    "preview_auto_delete": True,
                    "preview_delete_delay": 600,
                    "channel_post_text": "",
                    "channel_auto_post": False,
                    "channel_interval": 60,
                    "channel_last_post": 0,
                    "channel_last_message_id": None,
                },

                f,

                ensure_ascii=False,

                indent=2

            )

    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:

        data = json.load(f)

    if "preview_approval_enabled" not in data:
        data["preview_approval_enabled"] = True
        save_settings(data)

        data["join_vip_enabled"] = True

        save_settings(data)
        
    if "live_chat_enabled" not in data:
        data["live_chat_enabled"] = False
        save_settings(data)

    if "preview_auto_delete" not in data:
        data["preview_auto_delete"] = True
        save_settings(data)

    if "preview_delete_delay" not in data:
        data["preview_delete_delay"] = 600
        save_settings(data)

    if "channel_post_text" not in data:
        data["channel_post_text"] = ""
        save_settings(data)
    
    if "channel_auto_post" not in data:
        data["channel_auto_post"] = False
        save_settings(data)
        
    if "channel_interval" not in data:
        data["channel_interval"] = 60
        save_settings(data)

    if "channel_last_message_id" not in data:
        data["channel_last_message_id"] = None
        save_settings(data)

    if "channel_last_post" not in data:
        data["channel_last_post"] = 0
        save_settings(data)
        
    _settings_cache = dict(data)

    return data

def save_settings(data):

    global _settings_cache

    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:

        json.dump(

            data,

            f,

            ensure_ascii=False,

            indent=2

        )

    _settings_cache = dict(data)
    
def load_preview():
    try:
        with open("/data/preview.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"preview": []}

        if "preview" not in data or not isinstance(data["preview"], list):
            return {"preview": []}

        return data

    except (FileNotFoundError, json.JSONDecodeError):
        return {"preview": []}


def save_preview(data):
    with open("/data/preview.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
def load_preview_media():
    data = load_preview()
    media = []

    for item in data.get("preview", []):
        media_type = item.get("type", "").lower()
        file_id = item.get("file_id", "").strip()

        if media_type in ("photo", "video") and file_id:
            media.append((media_type, file_id))

    return media
    

WIB = timezone(timedelta(hours=7))

# In-memory store for requests awaiting admin decision.
# { user_id: {"chat_id": int, "waiting_msg_id": int, "full_name": str, "username": str} }
pending_requests: dict = {}
admin_request_order: list = []

# In-memory set of admin user_ids waiting to send a media for /getid
getid_waiting: set = set()
# User yang sedang dalam proses upload bukti transfer
# Contoh:
# upload_waiting[user_id] = {
#     "paket": "VIP 1 Bulan",
#     "harga": "Rp50.000"
# }
upload_waiting = {}
next_order_id = 1
admin_edit_waiting = {}
admin_add_waiting = {}
admin_qris_waiting = set()
admin_channel_waiting = set()
admin_channel_interval_waiting = set()
last_stats_message = {}
last_repeat_message = {}
admin_request_messages = {}   # user_id -> message_id
admin_request_counts = {}     # user_id -> jumlah percobaan

last_delivered_messages = {}
preview_delete_tasks = {}
admin_reply_waiting = {}
blocked_notified = set()
file_manager_edit_waiting = {}     # user_id -> FILE_MANAGER_FILES index
file_manager_restore_waiting = {}  # user_id -> FILE_MANAGER_FILES index

# Kelola Preview (preview.json) state
preview_edit_waiting = {}  # user_id -> {"index": int, "chat_id": int, "message_id": int}
preview_add_waiting = {}   # user_id -> {"chat_id": int, "message_id": int}

# --- Anti Deeplink Spam ---
# RAM-only, independent of admin_request_counts (which has no time window
# and is only cleared manually by admin via Reset/Abaikan). Tracks recent
# repeat-tap timestamps per user to detect rapid-fire deep link abuse from
# already-approved users. Threshold: 6 taps within 10 seconds — a human
# retapping a slow-loading deep link rarely exceeds a couple of taps in
# that window, while sustained sub-2-second intervals across 6 taps is
# well beyond normal impatient tapping and indicates scripted spam.
DEEPLINK_SPAM_WINDOW_SECONDS = 10
DEEPLINK_SPAM_THRESHOLD = 6
deeplink_spam_tracker = {}  # user_id -> list of recent tap timestamps

FILE_IDS_A = load_preview_media()

# ---------------------------------------------------------------------------
# Media helpers
# ---------------------------------------------------------------------------

def build_media_group(file_ids):

    media = []

    for kind, fid in file_ids:

        if not fid:

            return None

        if kind == "video":

            media.append(InputMediaVideo(media=fid))

        else:

            media.append(InputMediaPhoto(media=fid))

    return media

async def deliver_album(bot, chat_id: int, file_ids):

    """Send the progress message, album, then confirmation to chat_id."""

    media = build_media_group(file_ids)

    if not media:

        logger.error("One or more FILE_ID env vars are missing.")

        return False

    try:

        progress = await bot.send_message(
            chat_id,
            f"📦 Mengirim Batch 1/1 ({len(media)} media)...\nMohon tunggu..."
    )

        media_messages = await bot.send_media_group(
            chat_id,
            media=media
        )

        await progress.delete()
        
        delivered = [
            msg.message_id
            for msg in media_messages
        ]
        
        success_msg = await bot.send_message(
            chat_id,
            (
                "<b>📢 Bot Resmi milik @BocilVIP89</b>\n"
                f"✅ Semua {len(media)} media terkirim!"
            ),
            parse_mode="HTML"
        )

        delivered.append(
            success_msg.message_id
        )
        
        if chat_id == ADMIN_ID:
             return True
            
            
        preview_messages = delivered.copy()
        
        last_delivered_messages[
            chat_id
        ] = delivered

        settings = read_settings()

        if (
            chat_id != ADMIN_ID
            and settings["preview_auto_delete"]
        ):

            old_task = preview_delete_tasks.pop(
                chat_id,
                None
            )

            if old_task:
                old_task.cancel()

            task = asyncio.create_task(
                delete_messages_after_delay(
                    chat_id,
                    preview_messages,
                    bot,
                    settings["preview_delete_delay"]
                )
            )

            preview_delete_tasks[chat_id] = task

        return True

    except Exception as e:

        logger.error(f"Failed to deliver album to {chat_id}: {e}")

        return False
# ---------------------------------------------------------------------------
# Approved users 
# ---------------------------------------------------------------------------

# In-memory cache for approved.json — read once, refreshed on every save.
_approved_cache = None

def read_approved() -> set:
    global _approved_cache
    if _approved_cache is not None:
        return set(_approved_cache)
    try:
        if not os.path.exists(APPROVED_FILE):
            _approved_cache = set()
            return set(_approved_cache)
        with open(APPROVED_FILE, "r") as f:
            _approved_cache = set(json.load(f).get("approved", []))
        return set(_approved_cache)
    except Exception:
        return set()

def save_approved(approved: set):
    global _approved_cache
    try:
        with open(APPROVED_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"approved": list(approved)},
                f,
                ensure_ascii=False,
                indent=2
            )

        _approved_cache = set(approved)

    except Exception as e:
        logger.error(f"Approved write error: {e}")
# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------

# In-memory cache for blacklist.json — avoids re-reading the file from disk
# on every /banned interaction. Refreshed automatically after every
# successful write (ban, unban, reset) via write_blacklist().
_blacklist_cache = None

def read_blacklist() -> dict:
    global _blacklist_cache

    if _blacklist_cache is not None:
        return dict(_blacklist_cache)

    try:
        if not os.path.exists(BLACKLIST_FILE):
            _blacklist_cache = {}
            return dict(_blacklist_cache)
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
        _blacklist_cache = result
        return dict(_blacklist_cache)
    except Exception as e:
        logger.error(f"Blacklist read error: {e}")
        return {}

def write_blacklist(bl: dict):
    global _blacklist_cache
    try:
        entries = [
            {
                "user_id": uid,
                "full_name": info["full_name"],
                "username": info["username"]
            }
            for uid, info in bl.items()
        ]

        with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"banned": entries},
                f,
                ensure_ascii=False,
                indent=2
            )

        _blacklist_cache = dict(bl)

    except Exception as e:
        logger.error(f"Blacklist write error: {e}")
        
def get_package(package_id: int):

    data = read_vip_packages()

    for pkg in data["packages"]:

        if pkg["id"] == package_id:

            return pkg

    return None
# ---------------------------------------------------------------------------
# User registry
# ---------------------------------------------------------------------------

# In-memory cache for users.json — read once, refreshed on every save.
_users_cache = None

def read_user_registry() -> dict:
    global _users_cache
    if _users_cache is not None:
        return dict(_users_cache)
    try:
        if not os.path.exists(USERS_FILE):
            _users_cache = {}
            return dict(_users_cache)
        with open(USERS_FILE, "r") as f:
            data = json.load(f)
        _users_cache = {int(k): v for k, v in data.items()}
        return dict(_users_cache)
    except Exception as e:
        logger.error(f"User registry read error: {e}")
        return {}

def save_user_to_registry(user_id: int, full_name: str, username: str):

    global _users_cache

    registry = read_user_registry()

    registry[user_id] = {

        "full_name": full_name,

        "username": username

    }

    try:

        with open(USERS_FILE, "w") as f:

            json.dump(

                {str(k): v for k, v in registry.items()},

                f,

                ensure_ascii=False,

                indent=2

            )

        _users_cache = dict(registry)

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
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=text,
            parse_mode="Markdown",
            disable_notification=True
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

# ---------------------------------------------------------------------------
# /start — deep link handler with approval gate
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return

    payload = context.args[0]

    if payload != DEEP_LINK_A:
        return

    selected_files = FILE_IDS_A

    user = update.effective_user
    user_id = user.id
    full_name = user.full_name or "-"
    username = f"@{user.username}" if user.username else "-"
    # Silently ignore banned users
    if user_id in read_blacklist():
        if user_id not in blocked_notified:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🚫 Akses Anda telah dibatasi."
            )
            blocked_notified.add(user_id)
        return

    # Admin always bypasses approval
    if user_id == ADMIN_ID:
        ok = await deliver_album(
             context.bot,
             update.effective_chat.id,
             selected_files
        )
        if ok:
            save_user_to_registry(user_id, full_name, username)
            increment_counter()
            await notify_admin(context.bot, full_name, username, user_id)
        return
        
    settings = read_settings()

    # Already approved
    if user_id in read_approved():

        if user_id not in admin_request_counts:
            admin_request_counts[user_id] = 1
        else:
            admin_request_counts[user_id] += 1

        # --- Anti Deeplink Spam detection ---
        now_ts = time.monotonic()
        recent_taps = deeplink_spam_tracker.get(user_id, [])
        recent_taps = [
            t for t in recent_taps
            if now_ts - t <= DEEPLINK_SPAM_WINDOW_SECONDS
        ]
        recent_taps.append(now_ts)

        if len(recent_taps) >= DEEPLINK_SPAM_THRESHOLD:
            deeplink_spam_tracker.pop(user_id, None)
            admin_request_counts.pop(user_id, None)
            admin_request_messages.pop(user_id, None)
            pending_requests.pop(user_id, None)

            bl = read_blacklist()
            bl[user_id] = {"full_name": full_name, "username": username}
            write_blacklist(bl)

            approved = read_approved()
            if user_id in approved:
                approved.discard(user_id)
                save_approved(approved)

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "⚠️ Percobaan Deeplink Ulang\n\n"
                    f"👤 {full_name}\n"
                    f"🔄 <b>Percobaan: {DEEPLINK_SPAM_THRESHOLD}x</b>\n\n"
                    "🚫 Status: Auto Banned (Spam)"
                ),
                parse_mode="HTML",
            )

            return

        deeplink_spam_tracker[user_id] = recent_taps

        old_message_id = admin_request_messages.get(user_id)

        if old_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=ADMIN_ID,
                    message_id=old_message_id
                )
            except Exception:
                pass

        admin_msg = await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "⚠️ Percobaan Deeplink Ulang\n\n"
                f"👤 {full_name}\n"
                f"🔁 <b>Percobaan: {admin_request_counts[user_id]}x</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "♻️ Izinkan Lagi",
                        callback_data=f"reset|{user_id}"
                    ),
                    InlineKeyboardButton(
                        "🚫 Ban",
                        callback_data=f"ban|{user_id}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "❌ Abaikan",
                        callback_data=f"ignore|{user_id}"
                    ),
                ]
            ])
        )

        admin_request_messages[user_id] = (
            admin_msg.message_id
        )
        old_task = preview_delete_tasks.pop(
            update.effective_chat.id,
            None
        )

        if old_task:
            old_task.cancel()

        old_messages = last_delivered_messages.pop(
            update.effective_chat.id,
            None
        )

        if old_messages:
            for message_id in old_messages:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=message_id
                    )
                except Exception:
                    pass
                    
        await clear_last_repeat(
            update.effective_chat.id,
            context.bot
        )

        if settings["join_vip_enabled"]:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📦 Pilih Paket VIP",
                        callback_data="vipmenu"
                    )
                ]
            ])
        else:
            keyboard = None

        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "📍 Permintaan ulang belum tersedia.\n\n"
                "Coba lagi nanti ya. ୨୧"
            ),
            reply_markup=keyboard
        )

        last_repeat_message[
            update.effective_chat.id
        ] = msg.message_id

        return

    if not settings["preview_approval_enabled"]:
        ok = await deliver_album(
             context.bot,
             update.effective_chat.id,
             selected_files
        )

        if ok:
            save_user_to_registry(user_id, full_name, username)
            increment_counter()
            await notify_admin(context.bot, full_name, username, user_id)

            approved = read_approved()
            
            if user_id not in approved:
               approved.add(user_id)
               save_approved(approved)

        return

    # Already waiting for approval — ignore duplicate taps
    if user_id in pending_requests:
        return

    # Send waiting message to user
    waiting_msg = await update.message.reply_text("⏳ Video preview sedang diproses…\n\nEstimasi waktu: 1–3 menit.")

    # Store pending request
    pending_requests[user_id] = {

        "chat_id": update.effective_chat.id,

        "waiting_msg_id": waiting_msg.message_id,

        "full_name": full_name,

        "username": username,

        "payload": payload,

}

    # Send approval request to admin
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Izinkan", callback_data=f"izin|{user_id}"),
            InlineKeyboardButton("❌ Tolak",   callback_data=f"tolak|{user_id}"),
        ]
    ])
    admin_msg = await context.bot.send_message(
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

    admin_request_messages[user_id] = (
        admin_msg.message_id
    )
    admin_request_order.append(
        user_id
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

    if action == "izin":
        
        pending = pending_requests.pop(user_id, None)
        admin_request_messages.pop(
            user_id,
            None
        )
        # Edit admin message to reflect decision
        name_str = pending["full_name"] if pending else str(user_id)

        try:
            await query.edit_message_text(
                f"✅ Diizinkan — {name_str}"
            )
        finally:
            admin_request_messages.pop(
                user_id,
                None
            )
        try:
            await query.message.pin(
                disable_notification=True
            )
        except Exception:
            pass
            
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
         
            selected_files = FILE_IDS_A

            # Deliver album
            ok = await deliver_album(
                context.bot,
                chat_id,
                selected_files
            )

    elif action == "reset":

        approved = read_approved()

        approved.discard(user_id)

        save_approved(approved)

        admin_request_messages.pop(
            user_id,
            None
        )

        admin_request_counts.pop(
            user_id,
            None
        )

        await query.message.delete()

        return
        
    elif action == "ignore":

        admin_request_messages.pop(
            user_id,
            None
        )

        admin_request_counts.pop(
            user_id,
            None
        )

        await query.message.delete()

        return

    elif action == "ban":

        registry = read_user_registry()
        if user_id in registry:
            full_name = registry[user_id]["full_name"]
            username  = registry[user_id]["username"]
        else:
            full_name = "-"
            username  = "-"
            try:
                chat = await context.bot.get_chat(user_id)
                full_name = chat.full_name or "-"
                username  = f"@{chat.username}" if chat.username else "-"
            except Exception:
                pass

        bl = read_blacklist()
        bl[user_id] = {"full_name": full_name, "username": username}
        write_blacklist(bl)

        approved = read_approved()
        if user_id in approved:
            approved.discard(user_id)
            save_approved(approved)

        admin_request_messages.pop(
            user_id,
            None
        )

        admin_request_counts.pop(
            user_id,
            None
        )

        await query.message.delete()

        return
        
    elif action == "tolak":
        pending = pending_requests.pop(user_id, None)
        admin_request_messages.pop(
            user_id,
            None
        )
        name_str = pending["full_name"] if pending else str(user_id)
        await query.edit_message_text(
            f"❌ Ditolak — {name_str}"
        )

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

async def vipmenu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    packages = read_vip_packages()["packages"]

    buttons = []

    for package in packages:
        if not package.get("aktif", True):
            continue

        buttons.append([
            InlineKeyboardButton(
                package["nama"],
                callback_data=f"vip_{package['id']}"
        )
    ])

    keyboard = InlineKeyboardMarkup(buttons)

    await query.edit_message_text(
        "👑 Membership VIP\n\n"
        "Silakan pilih paket vip bocil.",
        reply_markup=keyboard
    )
    
async def vip1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        package_id = int(query.data.split("_")[1])
        package = get_package(package_id)
    
        keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton(
            "✨ Bergabung",
            callback_data=f"bayar_{package_id}"
        ),
        InlineKeyboardButton(
            "🔙 Kembali",
            callback_data="vipmenu"
        )
    ]
])

        await query.edit_message_text(

        f"{package['nama']}\n\n"

        f"{package['deskripsi']}\n\n"

        "──────────────\n"
        
        f"💰 Harga : {package['harga']}",

        reply_markup=keyboard

)

async def send_qris_message(chat_id, context, package, package_id):

    settings = read_settings()

    qris_file_id = settings.get("qris_file_id", "")

    if not qris_file_id:

        await context.bot.send_message(

            chat_id=chat_id,

            text="❌ QRIS belum dikonfigurasi."

        )

        return

    msg = await context.bot.send_photo(

        chat_id=chat_id,

        photo=qris_file_id,

        caption=(

            "*PEMBAYARAN GROUP BOCIL*\n"

            "*────── . 👇🏻 . ──────*\n\n"

            "*Pilihan Paket*\n"

            f"*{package['nama']}*\n"

            f"*💰 Nominal {package['harga']}*\n\n"

            "*Scan kode QR diatas untuk melakukan pembayaran, bayar sesuai pilihan paket lalu kirim (screenshot/foto) transfer Anda disini sebagai bukti.*\n\n"

            "*✅ Pembayaran via*\n"

            "*(Ovo, Dana, Shopeepay, Gopay, TNG, Maybank, USDT)*\n\n"

        ),

        parse_mode="Markdown",

        reply_markup=InlineKeyboardMarkup([

            [

                InlineKeyboardButton(

                    "📤 Sudah Transfer",

                    callback_data=f"upload_bukti_{package_id}"

                ),

                InlineKeyboardButton(

                    "❌ Batalkan",

                    callback_data="cancel_order"

                )

            ]

        ])

    )
    for order_id, data in upload_waiting.items():
        if (
            data["user_id"] == chat_id
            and data["package_id"] == package_id
        ):
            upload_waiting[order_id]["qris_msg_id"] = msg.message_id
            break
        
async def bayar1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if get_payment_lock(query.from_user.id):
        await query.answer(
            "⏳ Anda masih memiliki transaksi yang belum selesai.",
            show_alert=True
        )

        package_id = get_locked_package_id(query.from_user.id)

        package = get_package(package_id)

        await send_qris_message(
            query.message.chat_id,
            context,
            package,
            package_id
        )

        return

    await query.answer()

    global next_order_id

    package_id = int(query.data.split("_")[1])
    package = get_package(package_id)

    order_id = next_order_id
    next_order_id += 1

    username = (
        f"@{query.from_user.username}"
        if query.from_user.username
        else "-"
    )

    upload_waiting[order_id] = {
        "order_id": order_id,
        "user_id": query.from_user.id,
        "photo_uploaded": False,
        "processing": False,
        "processing_msg_id": None,
        "reupload": False,
        "package_id": package["id"],
        "paket": package["nama"],
        "harga": package["harga"],
        "full_name": query.from_user.full_name,
        "username": username
    }

    pending = read_pending_orders()

    pending["orders"].append(
        upload_waiting[order_id].copy()
    )

    save_pending_orders(pending)

    await send_qris_message(
        query.message.chat_id,
        context,
        package,
        package_id
    )

    lock_payment(query.from_user.id, package_id)
            
async def upload_bukti_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    global next_order_id

    user = query.from_user

    # Jika user sudah punya order, jangan buat order baru
    for order_id, data in upload_waiting.items():

        if data["user_id"] == user.id:

            if data.get("upload_msg_id"):
                try:
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=data["upload_msg_id"]
                    )
                except Exception:
                    pass

            msg = await query.message.reply_text(
                "Silakan upload screenshot bukti transfer disini.\n\n"
            )

            upload_waiting[order_id]["upload_msg_id"] = msg.message_id
            return

    msg = await query.message.reply_text(
        "Silakan upload screenshot bukti transfer disini.\n\n"
    )
    
async def cancel_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    unlock_payment(user_id)

    pending = read_pending_orders()

    pending["orders"] = [
        order
        for order in pending["orders"]
        if order["user_id"] != user_id
    ]

    save_pending_orders(pending)

    for order_id, data in list(upload_waiting.items()):

        if data["user_id"] == user_id:

            if data.get("upload_msg_id"):
                try:
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=data["upload_msg_id"]
                    )
                except Exception:
                    pass

            if data.get("qris_msg_id"):
                try:
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=data["qris_msg_id"]
                    )
                except Exception:
                    pass

            upload_waiting.pop(order_id)

    await query.message.reply_text(
        "❌ Order berhasil dibatalkan.\n\n"
    )
# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------

async def adminvip_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    admin_add_waiting[query.from_user.id] = {
        "step": "nama"
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Batal",
                callback_data="adminvip_packages"
            )
        ]
    ])
    await query.edit_message_caption(
        caption=(
            "➕ <b>Tambah Paket</b>\n\n"
            "Silakan masukkan nama paket baru."
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    
async def adminvip_package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[1])
    package = get_package(package_id)

    keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton(
            "📝 Edit Nama",
            callback_data=f"adminvip_name_{package_id}"
        )
    ],
    [
        InlineKeyboardButton(
            "💰 Edit Harga",
            callback_data=f"adminvip_price_{package_id}"
        )
    ],
    [
        InlineKeyboardButton(
            "📄 Edit Deskripsi",
            callback_data=f"adminvip_desc_{package_id}"
        )
    ],
    [
        InlineKeyboardButton(
            "🔗 Edit Link",
            callback_data=f"adminvip_link_{package_id}"
        )
    ],
    [
        InlineKeyboardButton(
            "🗑 Hapus Paket",
            callback_data=f"adminvip_delete_{package_id}"
        )
    ],
    [
        InlineKeyboardButton(
            "🔙 Kembali",
            callback_data="adminvip_packages_back"
        )
]
    ])
    await query.edit_message_caption(
        caption=(
            f"{package['nama']}\n\n"
            f"💰 {package['harga']}"
        ),
        reply_markup=keyboard
    )
async def adminvip_packages_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    packages = read_vip_packages()["packages"]

    keyboard = []

    for package in packages:
        keyboard.append([
            InlineKeyboardButton(
                f"{package['nama']}",
                callback_data=f"adminvip_{package['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "➕ Tambah Paket",
            callback_data="adminvip_add"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 Kembali",
            callback_data="adminvip_back"
        )
    ])

    await query.edit_message_media(
        media=InputMediaPhoto(
            media=os.environ["PACKAGE_BANNER_FILE_ID"],
            caption=(
                "Pilih paket yang ingin dikelola:"
            ),
            parse_mode="HTML",
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def payment_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_media(
        media=InputMediaPhoto(
            media=os.environ["PAYMENT_BANNER_FILE_ID"],
            caption="💳 <b>PEMBAYARAN</b>",
            parse_mode="HTML",
        ),
        reply_markup=build_payment_keyboard(),
    )
   
async def adminvip_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_media(
        media=InputMediaPhoto(
            media=os.environ["PAYMENT_BANNER_FILE_ID"],
            caption="💳 <b>PEMBAYARAN</b>",
            parse_mode="HTML",
        ),
        reply_markup=build_payment_keyboard(),
    )
    
async def adminvip_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()

    keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton(
            "📝 Edit Pesan",
            callback_data="channel_edit"
        ),
        InlineKeyboardButton(
            "⏱ Edit Interval",
            callback_data="channel_interval"
        )
    ],
    [
        InlineKeyboardButton(
            f"{'🟢' if settings['channel_auto_post'] else '🔴'} Auto Post",
            callback_data="channel_toggle"
        ),
        InlineKeyboardButton(
            "📤 Kirim",
            callback_data="channel_send"
        )
    ],
    [
        InlineKeyboardButton(
            "🔙 Kembali",
            callback_data="adminvip_back"
        )
    ]
    ])

    await query.edit_message_text(
        "📢 Channel Post\n\n"
        f"Auto Post  : {'🟢 ON' if settings['channel_auto_post'] else '🔴 OFF'}\n"
        f"Interval : {settings['channel_interval']} menit\n\n"
        "<pre>"
        "Pesan\n"
        "────────────────────\n"
        f"{settings['channel_post_text'] if settings['channel_post_text'] else 'Belum diatur.'}"
        "</pre>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
async def channel_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    admin_channel_waiting.add(query.from_user.id)

    await query.edit_message_text(
        "📝 Edit Channel Post\n\n"
        "Silakan kirim teks Channel Post baru.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Kembali", callback_data="adminvip_channel")]
        ])
    )
    
async def channel_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()

    settings["channel_auto_post"] = not settings["channel_auto_post"]

    save_settings(settings)

    await adminvip_channel_callback(update, context)
  
async def channel_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Menit", callback_data="channel_set_1")],
        [InlineKeyboardButton("15 Menit", callback_data="channel_set_15")],
        [InlineKeyboardButton("30 Menit", callback_data="channel_set_30")],
        [InlineKeyboardButton("1 Jam", callback_data="channel_set_60")],
        [InlineKeyboardButton("2 Jam", callback_data="channel_set_120")],
        [InlineKeyboardButton("6 Jam", callback_data="channel_set_360")],
        [InlineKeyboardButton("12 Jam", callback_data="channel_set_720")],
        [InlineKeyboardButton("24 Jam", callback_data="channel_set_1440")],
        [InlineKeyboardButton("🔙 Kembali", callback_data="adminvip_channel")]
    ])

    await query.edit_message_text(
        "⏱ Interval Channel Post",
        reply_markup=keyboard
    )
    
async def channel_set_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    minutes = int(query.data.replace("channel_set_", ""))

    settings = read_settings()
    settings["channel_interval"] = minutes
    save_settings(settings)

    await adminvip_channel_callback(update, context)
    
async def channel_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    settings = read_settings()

    if not settings["channel_post_text"]:
        await query.answer(
            "⚠️ Channel Post masih kosong.",
            show_alert=True
        )
        return

    if settings["channel_last_message_id"]:
        try:
            await context.bot.delete_message(
                chat_id=CHANNEL_ID,
                message_id=settings["channel_last_message_id"]
            )
        except Exception:
            pass

    msg = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=settings["channel_post_text"]
    )

    settings["channel_last_message_id"] = msg.message_id
    settings["channel_last_post"] = int(time.time())
    save_settings(settings)

    await query.answer(
        "✅ Berhasil dikirim.",
        show_alert=True
    )
    
async def payment_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    history = read_order_history()

    if not history["orders"]:

        await query.edit_message_caption(
            caption=(
                "📋 <b>ORDER HISTORY</b>\n\n"
                "Belum ada transaksi."
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Pembayaran",
                        callback_data="adminvip_payment"
                    )
                ]
            ]),
            parse_mode="HTML",
        )
        return

    total_order = len(history["orders"])

    total_pendapatan = 0

    packages = read_vip_packages()["packages"]

    for order in history["orders"]:

        package = next(
            (
                p for p in packages
                if p["id"] == order["package_id"]
            ),
            None
        )

        if not package:
            continue

        harga = (
            package["harga"]
            .replace("Rp", "")
            .replace(".", "")
            .replace(",", "")
            .strip()
        )

        if harga.isdigit():
            total_pendapatan += int(harga)

    tanggal_order = {}

    for order in history["orders"]:

        tanggal = order["time"].split(",")[0]

        if tanggal not in tanggal_order:

            tanggal_order[tanggal] = 0

        tanggal_order[tanggal] += 1

    keyboard = []

    for tanggal, jumlah in sorted(

        tanggal_order.items(),

        reverse=True

    ):

        keyboard.append([
            InlineKeyboardButton(
                f"📅 {tanggal} ({jumlah})",
                callback_data=f"history_{tanggal}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 Pembayaran",
            callback_data="adminvip_payment"
        )
    ])

    await query.edit_message_caption(
        caption=(
            "📋 <b>ORDER HISTORY</b>\n\n"

            f"💰 Total Pendapatan\n"
            f"Rp{total_pendapatan:,}".replace(",", ".") + "\n\n"

            f"📦 Total Order : {total_order}\n\n"

            "📅 Pilih tanggal transaksi di bawah ini."
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )

async def payment_history_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    tanggal = query.data.replace("history_", "")

    history = read_order_history()

    orders = []

    for order in history["orders"]:

        if order["time"].startswith(tanggal):

            orders.append(order)

    if not orders:

        await query.edit_message_text(
            "❌ Tidak ada transaksi."
        )
        return

    text = f"📅 {tanggal}\n\n"

    for i, order in enumerate(orders, start=1):

        package = get_package(order["package_id"])

        jam = order["time"].split(",")[1].strip()

        harga = (
            package["harga"]
            if package
            else "-"
        )

    text += (
        f"📋 Order #{i}\n\n"
        f"👤 {order['full_name']}\n"
        f"🆔 {order['user_id']}\n"
        f"🔗 {order['username']}\n\n"
        f"📦 {package['nama']}\n"
        f"💰 {harga}\n\n"
        f"🕒 {jam}\n\n"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🗑 Hapus Tanggal Ini",
                callback_data=f"history_delete_{tanggal}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="payment_history"
            )
        ]
    ])

    await query.edit_message_text(
        text,
        reply_markup=keyboard
    )

async def payment_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    history = read_order_history()

    total_order = len(history["orders"])

    total_pendapatan = 0

    packages = read_vip_packages()["packages"]

    for order in history["orders"]:

        package = next(
            (
                p for p in packages
                if p["id"] == order["package_id"]
            ),
            None
        )

        if not package:
            continue

        harga = (
            package["harga"]
            .replace("Rp", "")
            .replace(".", "")
            .replace(",", "")
            .strip()
        )

        if harga.isdigit():
            total_pendapatan += int(harga)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Batal",
                callback_data="adminvip_payment"
            ),
            InlineKeyboardButton(
                "✅ Ya, Clear",
                callback_data="payment_clear_yes"
            )
        ]
    ])

    await query.edit_message_text(
        "⚠️ Clear Order\n\n"
        "Seluruh Order History akan dihapus.\n\n"

        f"📦 Total Order\n"
        f"{total_order}\n\n"

        f"💰 Total Pendapatan\n"
        f"Rp{total_pendapatan:,}".replace(",", ".") + "\n\n"

        "Data tidak dapat dikembalikan.",
        reply_markup=keyboard
    )
    
async def payment_clear_yes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    save_order_history({
        "orders": []
    })

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Pembayaran",
                callback_data="payment_back"
            )
        ]
    ])

    await query.edit_message_text(
        "✅ Order History berhasil dibersihkan.",
        reply_markup=keyboard
    )
    
async def payment_history_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    tanggal = query.data.replace("history_delete_", "")

    history = read_order_history()

    packages = read_vip_packages()["packages"]

    total_order = 0
    total_pendapatan = 0

    for order in history["orders"]:

        if not order["time"].startswith(tanggal):
            continue

        total_order += 1

        package = get_package(order["package_id"])

        if not package:
            continue

        harga = (
            package["harga"]
            .replace("Rp", "")
            .replace(".", "")
            .replace(",", "")
            .strip()
        )

        if harga.isdigit():
            total_pendapatan += int(harga)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Batal",
                callback_data=f"history_{tanggal}"
            ),
            InlineKeyboardButton(
                "✅ Ya, Hapus",
                callback_data=f"history_delete_yes_{tanggal}"
            )
        ]
    ])

    await query.edit_message_text(
        "⚠️ Hapus Tanggal Ini\n\n"

        f"📅 {tanggal}\n\n"

        f"📦 Total Order\n"
        f"{total_order}\n\n"

        f"💰 Total Pendapatan\n"
        f"Rp{total_pendapatan:,}".replace(",", ".") + "\n\n"

        "Data tidak dapat dikembalikan.",
        reply_markup=keyboard
    )

async def payment_history_delete_yes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    tanggal = query.data.replace("history_delete_yes_", "")

    history = read_order_history()

    history["orders"] = [
        order
        for order in history["orders"]
        if not order["time"].startswith(tanggal)
    ]

    save_order_history(history)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Order History",
                callback_data="payment_history"
            )
        ]
    ])

    await query.edit_message_text(
        "✅ Transaksi tanggal berhasil dihapus.",
        reply_markup=keyboard
    )
    
def build_settings_keyboard(settings):
    """Bangun keyboard halaman Pengaturan dari state settings saat ini.
    Dipakai bersama oleh render penuh (edit_message_media) maupun update
    ringan (edit_message_caption) supaya keduanya selalu konsisten."""

    if settings["preview_delete_delay"] < 60:
        preview_time = (
            f"{settings['preview_delete_delay']} Detik"
        )
    else:
        preview_time = (
            f"{settings['preview_delete_delay'] // 60} Menit"
        )

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{'🟢' if settings['join_vip_enabled'] else '🔴'} Order {'ON' if settings['join_vip_enabled'] else 'OFF'}",
                callback_data="adminvip_toggle_join"
            ),
            InlineKeyboardButton(
                f"{'🟢' if settings['preview_approval_enabled'] else '🔴'} Preview {'ON' if settings['preview_approval_enabled'] else 'OFF'}",
                callback_data="adminvip_toggle_preview"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'🟢' if settings['live_chat_enabled'] else '🔴'} Chat {'ON' if settings['live_chat_enabled'] else 'OFF'}",
                callback_data="adminvip_toggle_livechat"
            ),
            InlineKeyboardButton(
                f"{'🟢' if settings['preview_auto_delete'] else '🔴'} Delete {'ON' if settings['preview_auto_delete'] else 'OFF'}",
                callback_data="preview_toggle"
            )
        ],
        [
            InlineKeyboardButton(
                f"⏱️ {preview_time}",
                callback_data="preview_timer"
            ),
            InlineKeyboardButton(
                "🖼 Kelola Preview",
                callback_data="adminvip_prv_list"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="adminvip_back"
            )
        ]
    ])


async def adminvip_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()
    keyboard = build_settings_keyboard(settings)

    from telegram import InputMediaPhoto

    await query.edit_message_media(
        media=InputMediaPhoto(
            media=os.environ["SETTINGS_BANNER_FILE_ID"],
            caption="⚙️ Pengaturan"
        ),
        reply_markup=keyboard
    )
    
async def adminvip_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📈 Lihat",
                callback_data="stats_view"
            ),
            InlineKeyboardButton(
                "🗑 Reset",
                callback_data="stats_reset"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="adminvip_back"
            )
        ]
    ])

    await query.edit_message_text(
        "📊 Statistik",
        reply_markup=keyboard
    )
    
async def stats_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    await send_stats(
        query.message.chat_id,
        context.bot
    )
    
async def stats_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    await do_reset_stats(
        query.message.chat_id,
        context.bot
    )
async def adminvip_packages_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await adminvip_packages_callback(update, context)
   
async def clear_last_stats(chat_id: int, bot):
    old_message = last_stats_message.pop(chat_id, None)

    if old_message:
        try:
            await bot.delete_message(
                chat_id=chat_id,
                message_id=old_message
            )
        except Exception:
            pass
            
async def clear_last_repeat(chat_id: int, bot):
    old_message = last_repeat_message.pop(chat_id, None)

    if old_message:
        try:
            await bot.delete_message(
                chat_id=chat_id,
                message_id=old_message
            )
        except Exception:
            pass
 
async def delete_messages_after_delay(
    chat_id,
    message_ids,
    bot,
    delay=6
):
    try:
        current_task = asyncio.current_task()

        if chat_id == ADMIN_ID:
            return

        await asyncio.sleep(delay)

        await asyncio.gather(
            *[
                bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )
                for message_id in message_ids
            ],
            return_exceptions=True
        )

        try:
            await clear_last_repeat(
                chat_id,
                bot
            )

            settings = read_settings()

            if settings["join_vip_enabled"]:
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "📦 Pilih Paket VIP",
                            callback_data="vipmenu"
                        )
                    ]
                ])
            else:
                keyboard = None

            msg = await bot.send_message(
                chat_id=chat_id,
                text=(
                    "⏰ Masa Preview sudah selesai.\n\n"
                    "Koleksi selengkapnya ada di grup VIP\n\n"
                    "Chat Admin: @BocilVIP89 👈"
                ),
                reply_markup=keyboard
            )

            last_repeat_message[
                chat_id
            ] = msg.message_id

        except Exception:
            pass

    finally:
        if (
            preview_delete_tasks.get(chat_id)
            is current_task
        ):
            preview_delete_tasks.pop(
                chat_id,
                None
            )
            
async def adminvip_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await clear_last_stats(
        query.message.chat_id,
        context.bot
    )

    settings = read_settings()

    admin_panel_text = (
        "<b>👑 ADMIN VIP PANEL</b>\n"
        "<pre>"

        f"👥 Users       : {len(read_user_registry())}\n"
        f"📦 Packages    : {len(read_vip_packages()['packages'])}\n"
        f"📢 Auto Post   : {'🟢' if settings['channel_auto_post'] else '🔴'}\n"
        f"🗑 Auto Delete : {'🟢' if settings['preview_auto_delete'] else '🔴'}\n"
        f"⏱ Timer       : {settings['preview_delete_delay']} detik\n"

        "</pre>"
    )

    keyboard = build_adminvip_keyboard()

    await query.edit_message_media(
        media=InputMediaPhoto(
            media=os.environ["ADMIN_BANNER_FILE_ID"],
            caption=admin_panel_text,
            parse_mode="HTML",
        ),
        reply_markup=keyboard,
    )
    
async def adminvip_qris_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📷 Ganti QRIS",
                callback_data="adminvip_qris_change"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="payment_back"
            )
        ]
    ])

    if settings["qris_file_id"]:
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=settings["qris_file_id"],
            caption="🖼 QRIS Saat Ini",
            reply_markup=keyboard
        )
        try:
            await query.message.delete()
        except Exception:
            pass
    else:
        await query.edit_message_text(
            "⚠️ QRIS belum diatur.",
            reply_markup=keyboard
        )
    
async def adminvip_qris_change_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    admin_qris_waiting.add(query.from_user.id)

    await query.message.reply_text(
        "📷 Silakan kirim foto QRIS baru.\n\n"
        "Ketik /cancel untuk membatalkan."
    )
    
async def adminvip_toggle_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()

    settings["join_vip_enabled"] = not settings["join_vip_enabled"]

    save_settings(settings)

    # Hanya caption & keyboard yang berubah, banner Pengaturan tetap sama.
    await query.edit_message_caption(
        caption="⚙️ Pengaturan",
        reply_markup=build_settings_keyboard(settings)
    )
    
async def adminvip_toggle_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()
    settings["preview_approval_enabled"] = not settings["preview_approval_enabled"]
    save_settings(settings)

    # Hanya caption & keyboard yang berubah, banner Pengaturan tetap sama.
    await query.edit_message_caption(
        caption="⚙️ Pengaturan",
        reply_markup=build_settings_keyboard(settings)
    )

async def adminvip_toggle_livechat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()

    settings["live_chat_enabled"] = not settings["live_chat_enabled"]

    save_settings(settings)

    # Hanya caption & keyboard yang berubah, banner Pengaturan tetap sama.
    await query.edit_message_caption(
        caption="⚙️ Pengaturan",
        reply_markup=build_settings_keyboard(settings)
    )
   
async def preview_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()

    settings["preview_auto_delete"] = not settings["preview_auto_delete"]

    save_settings(settings)

    # Hanya caption & keyboard yang berubah, banner Pengaturan tetap sama.
    await query.edit_message_caption(
        caption="⚙️ Pengaturan",
        reply_markup=build_settings_keyboard(settings)
    )
    
async def preview_timer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "30 Detik",
                callback_data="preview_set_30"
            )
        ],
        [
            InlineKeyboardButton(
                "1 Menit",
                callback_data="preview_set_60"
            )
        ],
        [
            InlineKeyboardButton(
                "3 Menit",
                callback_data="preview_set_180"
            )
        ],
        [
            InlineKeyboardButton(
                "5 Menit",
                callback_data="preview_set_300"
            )
        ],
        [
            InlineKeyboardButton(
                "10 Menit",
                callback_data="preview_set_600"
            )
        ],
        [
            InlineKeyboardButton(
                "15 Menit",
                callback_data="preview_set_900"
            )
        ],
        [
            InlineKeyboardButton(
                "30 Menit",
                callback_data="preview_set_1800"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="adminvip_settings"
            )
        ]
    ])

    # Masih di banner Pengaturan yang sama, hanya caption & keyboard yang
    # berubah -> edit_message_caption (edit_message_text akan gagal karena
    # pesan ini sudah berupa media).
    await query.edit_message_caption(
        caption="⏱ Preview Timer",
        reply_markup=keyboard
    )
    
async def preview_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    seconds = int(
        query.data.replace(
            "preview_set_",
            ""
        )
    )

    settings = read_settings()

    settings["preview_delete_delay"] = seconds

    save_settings(settings)

    # Kembali ke tampilan Pengaturan: banner tidak berubah, cukup
    # caption & keyboard.
    await query.edit_message_caption(
        caption="⚙️ Pengaturan",
        reply_markup=build_settings_keyboard(settings)
    )


async def adminvip_preview_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{'🟢' if settings['preview_auto_delete'] else '🔴'} Auto Delete",
                callback_data="preview_toggle"
            )
        ],
        [
            InlineKeyboardButton(
                f"⏱ Preview Pertama : {settings['preview_delete_delay']} dtk",
                callback_data="preview_timer"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="adminvip_settings"
            )
        ]
    ])

    await query.edit_message_text(
        "🖼 Preview",
        reply_markup=keyboard
    )
    
def build_preview_caption(idx: int, total: int, media_type: str) -> str:
    jenis = "Video" if media_type == "video" else "Foto"

    return (
        "🖼 Kelola Preview\n\n"
        f"Preview {idx + 1} / {total}\n"
        f"Jenis: {jenis}"
    )


def build_preview_nav_keyboard(idx: int, total: int):
    prev_idx = (idx - 1) % total
    next_idx = (idx + 1) % total

    keyboard = [
        [
            InlineKeyboardButton(
                "◀️",
                callback_data=f"adminvip_prv_nav_{prev_idx}"
            ),
            InlineKeyboardButton(
                f"{idx + 1}/{total}",
                callback_data="adminvip_prv_noop"
            ),
            InlineKeyboardButton(
                "▶️",
                callback_data=f"adminvip_prv_nav_{next_idx}"
            )
        ],
        [
            InlineKeyboardButton(
                "✏️ Edit",
                callback_data=f"adminvip_prv_edit_{idx}"
            ),
            InlineKeyboardButton(
                "🗑 Hapus",
                callback_data=f"adminvip_prv_del_{idx}"
            )
        ]
    ]

    if idx == 0 or idx == total - 1:
        keyboard.append([
            InlineKeyboardButton(
                "➕ Tambah",
                callback_data="adminvip_prv_add"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 Kembali",
            callback_data="adminvip_prv_back"
        )
    ])

    return InlineKeyboardMarkup(keyboard)


def build_preview_empty_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Tambah",
                callback_data="adminvip_prv_add"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="adminvip_prv_back"
            )
        ]
    ])


async def send_preview_page(context: ContextTypes.DEFAULT_TYPE, chat_id: int, idx: int):
    """Kirim halaman katalog Preview sebagai pesan baru (dipakai saat belum
    ada pesan media yang bisa di-edit, mis. saat pertama kali membuka menu
    atau saat daftar Preview baru saja kosong)."""

    data = load_preview()
    items = data.get("preview", [])

    if not items:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🖼 Kelola Preview\n\n"
                "Belum ada Preview.\n\n"
                "Silakan tambah Preview baru."
            ),
            reply_markup=build_preview_empty_keyboard()
        )

    total = len(items)
    idx = idx % total
    item = items[idx]
    media_type = item.get("type", "").lower()
    file_id = item.get("file_id", "").strip()

    caption = build_preview_caption(idx, total, media_type)
    keyboard = build_preview_nav_keyboard(idx, total)

    if media_type == "video":
        return await context.bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption=caption,
            reply_markup=keyboard
        )

    return await context.bot.send_photo(
        chat_id=chat_id,
        photo=file_id,
        caption=caption,
        reply_markup=keyboard
    )


async def render_preview_page(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, idx: int):
    """Perbarui pesan katalog Preview di tempat (edit_message_media) supaya
    chat tidak menumpuk. Jika pesan yang sedang ditampilkan bukan media
    (mis. daftar baru saja kosong lalu diisi lagi), fallback: hapus pesan
    lama lalu kirim pesan media baru."""

    data = load_preview()
    items = data.get("preview", [])

    if not items:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    "🖼 Kelola Preview\n\n"
                    "Belum ada Preview.\n\n"
                    "Silakan tambah Preview baru."
                ),
                reply_markup=build_preview_empty_keyboard()
            )
            return
        except Exception:
            pass

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass

        await send_preview_page(context, chat_id, 0)
        return

    total = len(items)
    idx = idx % total
    item = items[idx]
    media_type = item.get("type", "").lower()
    file_id = item.get("file_id", "").strip()

    caption = build_preview_caption(idx, total, media_type)
    keyboard = build_preview_nav_keyboard(idx, total)

    media = (
        InputMediaVideo(file_id, caption=caption)
        if media_type == "video"
        else InputMediaPhoto(file_id, caption=caption)
    )

    try:
        await context.bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=media,
            reply_markup=keyboard
        )
        return
    except Exception:
        pass

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

    await send_preview_page(context, chat_id, idx)


async def adminvip_prv_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Batalkan mode tambah/edit yang mungkin masih menggantung jika admin
    # menavigasi keluar tanpa mengirim media.
    preview_edit_waiting.pop(query.from_user.id, None)
    preview_add_waiting.pop(query.from_user.id, None)

    # Pesan menu Pengaturan berupa teks, jadi edit_message_media akan
    # ditolak Telegram (tidak bisa mengubah pesan teks jadi media) —
    # render_preview_page menangani ini: coba edit di tempat dulu, dan
    # hanya jika gagal, hapus pesan lama lalu kirim satu pesan katalog
    # baru. Hasil akhirnya selalu satu halaman aktif, menu Pengaturan
    # tidak pernah tertinggal di chat.
    await render_preview_page(
        context,
        query.message.chat.id,
        query.message.message_id,
        0
    )


async def adminvip_prv_noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def adminvip_prv_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    idx = int(query.data.split("_")[3])

    await render_preview_page(
        context,
        query.message.chat.id,
        query.message.message_id,
        idx
    )


async def adminvip_prv_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    preview_add_waiting[query.from_user.id] = {
        "chat_id": query.message.chat.id,
        "message_id": query.message.message_id
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Batal",
                callback_data="adminvip_prv_add_cancel"
            )
        ]
    ])

    text = (
        "➕ Tambah Preview\n\n"
        "Silakan kirim foto atau video untuk dijadikan Preview baru."
    )

    # Pesan bisa berupa teks (saat daftar Preview kosong) atau media (saat
    # menambah dari halaman katalog yang sudah berisi Preview).
    try:
        await query.edit_message_caption(
            caption=text,
            reply_markup=keyboard
        )
    except Exception:
        await query.edit_message_text(
            text,
            reply_markup=keyboard
        )


async def adminvip_prv_add_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    preview_add_waiting.pop(query.from_user.id, None)

    data = load_preview()
    items = data.get("preview", [])
    idx = max(len(items) - 1, 0)

    await render_preview_page(
        context,
        query.message.chat.id,
        query.message.message_id,
        idx
    )


async def adminvip_prv_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    idx = int(query.data.split("_")[3])

    preview_edit_waiting[query.from_user.id] = {
        "index": idx,
        "chat_id": query.message.chat.id,
        "message_id": query.message.message_id
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Batal",
                callback_data=f"adminvip_prv_nav_{idx}"
            )
        ]
    ])

    await query.edit_message_caption(
        caption=(
            "✏️ Edit Preview\n\n"
            "Silakan kirim foto atau video baru untuk mengganti Preview ini."
        ),
        reply_markup=keyboard
    )


async def adminvip_prv_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    idx = int(query.data.split("_")[3])

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Ya",
                callback_data=f"adminvip_prv_delyes_{idx}"
            ),
            InlineKeyboardButton(
                "❌ Batal",
                callback_data=f"adminvip_prv_nav_{idx}"
            )
        ]
    ])

    await query.edit_message_caption(
        caption="Hapus Preview ini?",
        reply_markup=keyboard
    )


async def adminvip_prv_delyes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global FILE_IDS_A

    query = update.callback_query
    await query.answer()

    idx = int(query.data.split("_")[3])

    data = load_preview()
    items = data.get("preview", [])

    if 0 <= idx < len(items):
        items.pop(idx)
        data["preview"] = items
        save_preview(data)
        FILE_IDS_A = load_preview_media()

    # Tampilkan Preview berikutnya jika masih ada di index yang sama;
    # jika item terakhir yang dihapus, mundur ke Preview sebelumnya.
    # render_preview_page otomatis menampilkan halaman kosong jika habis.
    next_idx = idx if idx < len(items) else idx - 1

    await render_preview_page(
        context,
        query.message.chat.id,
        query.message.message_id,
        max(next_idx, 0)
    )

async def adminvip_prv_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()

    if settings["preview_delete_delay"] < 60:
        preview_time = (
            f"{settings['preview_delete_delay']} Detik"
        )
    else:
        preview_time = (
            f"{settings['preview_delete_delay'] // 60} Menit"
        )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{'🟢' if settings['join_vip_enabled'] else '🔴'} Order {'ON' if settings['join_vip_enabled'] else 'OFF'}",
                callback_data="adminvip_toggle_join"
            ),
            InlineKeyboardButton(
                f"{'🟢' if settings['preview_approval_enabled'] else '🔴'} Preview {'ON' if settings['preview_approval_enabled'] else 'OFF'}",
                callback_data="adminvip_toggle_preview"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'🟢' if settings['live_chat_enabled'] else '🔴'} Chat {'ON' if settings['live_chat_enabled'] else 'OFF'}",
                callback_data="adminvip_toggle_livechat"
            ),
            InlineKeyboardButton(
                f"{'🟢' if settings['preview_auto_delete'] else '🔴'} Delete {'ON' if settings['preview_auto_delete'] else 'OFF'}",
                callback_data="preview_toggle"
            )
        ],
        [
            InlineKeyboardButton(
                f"⏱️ {preview_time}",
                callback_data="preview_timer"
            ),
            InlineKeyboardButton(
                "🖼 Kelola Preview",
                callback_data="adminvip_prv_list"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="adminvip_back"
            )
        ]
    ])

    from telegram import InputMediaPhoto

    await query.edit_message_media(
        media=InputMediaPhoto(
            media=os.environ["SETTINGS_BANNER_FILE_ID"],
            caption="⚙️ Pengaturan"
        ),
        reply_markup=keyboard
    )

async def preview_media_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global FILE_IDS_A

    user_id = update.effective_user.id

    if update.message.photo:
        media_type = "photo"
        file_id = update.message.photo[-1].file_id
    elif update.message.video:
        media_type = "video"
        file_id = update.message.video.file_id
    else:
        return

    data = load_preview()
    items = data.get("preview", [])

    if user_id in preview_edit_waiting:
        state = preview_edit_waiting.pop(user_id)
        idx = state["index"]

        if 0 <= idx < len(items):
            items[idx] = {"type": media_type, "file_id": file_id}
            data["preview"] = items
            save_preview(data)
            FILE_IDS_A = load_preview_media()

        try:
            await update.message.delete()
        except Exception:
            pass

        await render_preview_page(context, state["chat_id"], state["message_id"], idx)
        return

    if user_id in preview_add_waiting:
        state = preview_add_waiting.pop(user_id)

        items.append({"type": media_type, "file_id": file_id})
        data["preview"] = items
        save_preview(data)
        FILE_IDS_A = load_preview_media()

        try:
            await update.message.delete()
        except Exception:
            pass

        new_idx = len(items) - 1

        await render_preview_page(context, state["chat_id"], state["message_id"], new_idx)
        return


async def adminvip_name_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    admin_edit_waiting[query.from_user.id] = {
        "package_id": package_id,
        "field": "nama",
        "chat_id": query.message.chat.id,
        "message_id": query.message.message_id
     }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Batal",
                callback_data=f"adminvip_{package_id}"
            )
        ]
    ])
    await query.edit_message_caption(
        caption=(
            f"📝 <b>Edit Nama</b>\n\n"
            f"Nama saat ini:\n"
            f"{package['nama']}\n\n"
            "Silakan kirim nama baru."
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    
async def adminvip_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    admin_edit_waiting[query.from_user.id] = {
        "package_id": package_id,
        "field": "harga",
        "chat_id": query.message.chat.id,
        "message_id": query.message.message_id
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Batal",
                callback_data=f"adminvip_{package_id}"
            )
        ]
    ])

    await query.edit_message_caption(
        caption=(
            f"💰 <b>Edit Harga</b>\n\n"
            f"Harga saat ini:\n"
            f"{package['harga']}\n\n"
            "Silakan update harga baru."
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    
async def adminvip_desc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    admin_edit_waiting[query.from_user.id] = {
        "package_id": package_id,
        "field": "deskripsi",
        "chat_id": query.message.chat.id,
        "message_id": query.message.message_id
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Batal",
                callback_data=f"adminvip_{package_id}"
            )
        ]
    ])

    await query.edit_message_caption(
        caption=(
            f"📄 <b>Edit Deskripsi</b>\n\n"
            f"Deskripsi saat ini:\n"
            f"{package['deskripsi']}\n\n"
            "Silakan update deskripsi baru."
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    
async def adminvip_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    admin_edit_waiting[query.from_user.id] = {
        "package_id": package_id,
        "field": "vip_link",
        "chat_id": query.message.chat.id,
        "message_id": query.message.message_id
    }

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "❌ Batal",
                callback_data=f"adminvip_{package_id}"
            )
        ]
    ])

    await query.edit_message_caption(
        caption=(
            f"🔗 <b>Edit Link VIP</b>\n\n"
            f"Link saat ini:\n"
            f"{package['vip_link']}\n\n"
            "Silakan kirim link VIP baru.\n\n"
            "Contoh:\nhttps://t.me/..."
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    
async def adminvip_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Ya, Hapus",
                callback_data=f"adminvip_delete_yes_{package_id}"
            ),
            InlineKeyboardButton(
                "❌ Batal",
                callback_data=f"adminvip_{package_id}"
            )
        ]
    ])

    await query.edit_message_caption(
        caption=(
            f"⚠️ <b>Yakin ingin menghapus paket ini?</b>\n\n"
            f"{package['nama']}\n"
            f"💰 {package['harga']}"
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    
async def adminvip_delete_yes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    package_id = int(query.data.split("_")[3])

    packages = read_vip_packages()

    packages["packages"] = [

        p for p in packages["packages"]

        if p["id"] != package_id

    ]

    save_vip_packages(packages)

    await adminvip_packages_callback(update, context)
    
async def admin_edit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in admin_edit_waiting:
        return

    data = admin_edit_waiting.pop(user_id)

    packages = read_vip_packages()

    package = None

    for p in packages["packages"]:
        if p["id"] == data["package_id"]:
            package = p

            if data["field"] == "nama":
                p["nama"] = update.message.text.strip()

            elif data["field"] == "harga":
                p["harga"] = update.message.text.strip()

            elif data["field"] == "deskripsi":
                p["deskripsi"] = update.message.text

            elif data["field"] == "vip_link":
                p["vip_link"] = update.message.text.strip()

            break

    save_vip_packages(packages)

    try:
        await update.message.delete()
    except:
        pass

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📝 Edit Nama",
                callback_data=f"adminvip_name_{package['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Edit Harga",
                callback_data=f"adminvip_price_{package['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "📄 Edit Deskripsi",
                callback_data=f"adminvip_desc_{package['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔗 Edit Link",
                callback_data=f"adminvip_link_{package['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 Hapus Paket",
                callback_data=f"adminvip_delete_{package['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="adminvip_packages_back"
            )
        ]
    ])

    await context.bot.edit_message_caption(
        chat_id=data["chat_id"],
        message_id=data["message_id"],
        caption=(
            f"{package['nama']}\n\n"
            f"💰 {package['harga']}"
        ),
        reply_markup=keyboard,
    )

async def show_add_preview(message, data):

    preview = (
        "📝 <b>PREVIEW PAKET</b>\n\n"
        "<pre>"
        f"Nama       : {data['nama']}\n"
        f"Harga      : {data['harga']}\n"
        f"Deskripsi  : {data['deskripsi']}\n"
        f"Link       : {data['vip_link']}"
        "</pre>\n\n"
        "Silakan periksa data sebelum disimpan."
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📝 Edit Nama",
                callback_data="adminaddedit_nama"
            )
        ],

        [
            InlineKeyboardButton(
                "💰 Edit Harga",
                callback_data="adminaddedit_harga"
            )
        ],

        [
            InlineKeyboardButton(
                "📄 Edit Deskripsi",
                callback_data="adminaddedit_deskripsi"
            )
        ],

        [
            InlineKeyboardButton(
                "🔗 Edit Link",
                callback_data="adminaddedit_vip_link"
            )
        ],

        [
            InlineKeyboardButton(
                "✅ Simpan",
                callback_data="adminadd_save"
            ),
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data="adminvip_back"
            )
        ]

    ])

    await message.reply_text(
        preview,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    
async def admin_add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in admin_add_waiting:
        return

    data = admin_add_waiting[user_id]
    text = update.message.text.strip()
    
    if "editing" in data:
        field = data.pop("editing")

        if field == "nama":
            data["nama"] = text

        elif field == "harga":
            data["harga"] = text

        elif field == "deskripsi":
            data["deskripsi"] = update.message.text

        elif field == "vip_link":
            data["vip_link"] = text

        await show_add_preview(update.message, data)
        return

    if data["step"] == "nama":
        data["nama"] = text
        data["step"] = "harga"

        await update.message.reply_text(
            "💰 Masukkan harga paket."
        )
        return

    elif data["step"] == "harga":
        data["harga"] = text
        data["step"] = "deskripsi"

        await update.message.reply_text(
            "📄 Masukkan deskripsi paket."
        )
        return

    elif data["step"] == "deskripsi":
        data["deskripsi"] = update.message.text
        data["step"] = "vip_link"

        await update.message.reply_text(
            "🔗 Masukkan link VIP."
        )
        return

    elif data["step"] == "vip_link":
        data["vip_link"] = text
        data["step"] = "preview"

        await show_add_preview(update.message, data)
        return
  
async def admin_text_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id in admin_edit_waiting:
        await admin_edit_receive(update, context)

    if user_id in admin_add_waiting:
        await admin_add_receive(update, context)

    if update.effective_user.id in admin_channel_waiting:

        admin_channel_waiting.remove(update.effective_user.id)

        settings = read_settings()

        settings["channel_post_text"] = update.message.text

        save_settings(settings)

        await update.message.reply_text(
            "✅ Channel Post berhasil disimpan."
        )

        return

    if update.effective_user.id in admin_channel_interval_waiting:

        admin_channel_interval_waiting.remove(
            update.effective_user.id
        )

        if not update.message.text.isdigit():

            await update.message.reply_text(
                "❌ Interval harus berupa angka."
            )

            return

        settings = read_settings()

        settings["channel_interval"] = int(
            update.message.text
        )

        save_settings(settings)

        await update.message.reply_text(
            "✅ Interval berhasil disimpan."
        )

        return

    if update.effective_user.id in admin_reply_waiting:

        user_id = admin_reply_waiting.pop(
            update.effective_user.id
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=update.message.text
        )

        await update.message.reply_text(
            "✅ Pesan berhasil dikirim."
        )

        return

    if update.effective_user.id in file_manager_edit_waiting:

        idx = file_manager_edit_waiting.pop(
            update.effective_user.id
        )

        await file_manager_edit_receive(update, context, idx)

        return

    await livechat_receive(update, context)
    
async def livechat_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):

    settings = read_settings()

    if not settings["live_chat_enabled"]:
        return

    if update.effective_user.id == ADMIN_ID:
        return

    if update.effective_user.id in read_blacklist():
        return

    user_id = update.effective_user.id

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💬 Balas",
                callback_data=f"reply|{update.effective_user.id}"
            )
        ]
    ])

    waktu = datetime.now(WIB).strftime("%d %b %Y • %H:%M WIB")

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "📩 Pesan Baru\n\n"
            f"👤 {update.effective_user.full_name}\n"
            f"🔗 @{update.effective_user.username if update.effective_user.username else '-'}\n"
            f"🆔 {update.effective_user.id}\n"
            f"🕒 {waktu}\n\n"
            f"💬 {update.message.text}"
        ),
        reply_markup=keyboard
    )
        
async def adminadd_save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if user_id not in admin_add_waiting:
        await query.answer("Data tidak ditemukan.", show_alert=True)
        return

    data = admin_add_waiting.pop(user_id)

    packages = read_vip_packages()

    new_id = 1
    if packages["packages"]:
        new_id = max(p["id"] for p in packages["packages"]) + 1

    packages["packages"].append({
        "id": new_id,
        "nama": data["nama"],
        "harga": data["harga"],
        "deskripsi": data["deskripsi"],
        "vip_link": data["vip_link"]
    })

    save_vip_packages(packages)

    await adminvip_packages_callback(update, context)
    
async def adminadd_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if user_id not in admin_add_waiting:
        await query.answer(
            "Data tidak ditemukan.",
            show_alert=True
        )
        return

    field = query.data.replace("adminaddedit_", "")

    admin_add_waiting[user_id]["editing"] = field

    title = {
        "nama": "📝 Kirim nama paket baru.",
        "harga": "💰 Kirim harga baru.",
        "deskripsi": "📄 Kirim deskripsi baru.",
        "vip_link": "🔗 Kirim link VIP baru."
    }

    await query.edit_message_text(
        title[field]
    )
    
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
    blocked_notified.discard(target_id)
    await update.message.reply_text("✅ User unbanned.")

BLACKLIST_PAGE_SIZE = 10
BLACKLIST_DIVIDER = "━━━━━━━━━━━━━━━━━━"

def build_blacklist_view(page: int = 1):
    bl = read_blacklist()
    total = len(bl)

    if total == 0:
        text = "🚫 Blacklist\n\nTidak ada user yang di-blacklist."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Kembali", callback_data="adminvip_back")]
        ])
        return text, keyboard

    total_pages = (total + BLACKLIST_PAGE_SIZE - 1) // BLACKLIST_PAGE_SIZE
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    # Newest banned user first
    items = list(bl.items())[::-1]
    start = (page - 1) * BLACKLIST_PAGE_SIZE
    end = start + BLACKLIST_PAGE_SIZE
    page_items = items[start:end]

    lines = [
        "🚫 Blacklist",
        "",
        f"📊 {total} user • Halaman {page}/{total_pages}",
        BLACKLIST_DIVIDER
    ]

    keyboard_rows = []
    manage_buttons = []

    for i, (uid, info) in enumerate(page_items, start=start + 1):
        if info["full_name"] and info["full_name"] != "-":
            display_name = info["full_name"]
        elif info["username"] and info["username"] != "-":
            display_name = info["username"]
        else:
            display_name = str(uid)

        lines.append(f"{i}. 👤 {display_name}")

        manage_buttons.append(
            InlineKeyboardButton(
                f"⚙️ {display_name}",
                callback_data=f"banned_manage_{uid}_{page}"
            )
        )

    for j in range(0, len(manage_buttons), 2):
        keyboard_rows.append(manage_buttons[j:j + 2])

    text = "\n".join(lines).rstrip()

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀ Sebelumnya", callback_data=f"banned_page_{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Selanjutnya ▶", callback_data=f"banned_page_{page + 1}"))

    if nav_row:
        keyboard_rows.append(nav_row)
    keyboard_rows.append([InlineKeyboardButton("🔙 Kembali", callback_data="adminvip_back")])

    keyboard = InlineKeyboardMarkup(keyboard_rows)

    return text, keyboard

async def banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text, keyboard = build_blacklist_view(1)
    await update.message.reply_text(text, reply_markup=keyboard)

async def banned_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    page = int(query.data.replace("banned_page_", ""))
    text, keyboard = build_blacklist_view(page)
    await query.edit_message_text(text, reply_markup=keyboard)

async def banned_reset_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    page = int(query.data.replace("banned_reset_ask_", ""))
    bl = read_blacklist()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Batal", callback_data=f"banned_page_{page}"),
            InlineKeyboardButton("✅ Ya, Reset", callback_data="banned_reset_yes")
        ]
    ])
    await query.edit_message_text(
        "⚠️ Reset seluruh blacklist?\n\n"
        f"Total {len(bl)} user yang di-blacklist akan dipulihkan.",
        reply_markup=keyboard
    )

async def banned_reset_yes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    write_blacklist({})
    text, keyboard = build_blacklist_view(1)
    await query.edit_message_text(text, reply_markup=keyboard)

async def banned_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    data = query.data.replace("banned_manage_", "")
    uid_str, page_str = data.rsplit("_", 1)
    uid = int(uid_str)
    page = int(page_str)

    bl = read_blacklist()
    info = bl.get(uid)
    if not info:
        text, keyboard = build_blacklist_view(page)
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    uname = info["username"] if info["username"] and info["username"] != "-" else "-"
    text = (
        f"{BLACKLIST_DIVIDER}\n\n"
        f"👤 {info['full_name']}\n"
        f"🔗 {uname}\n"
        f"🆔 {uid}\n\n"
        f"{BLACKLIST_DIVIDER}\n\n"
        "Pilih tindakan."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Unban", callback_data=f"banned_unban_ask_{uid}_{page}")],
        [InlineKeyboardButton("🔙 Kembali ke Blacklist", callback_data=f"banned_page_{page}")]
    ])
    await query.edit_message_text(text, reply_markup=keyboard)

async def banned_unban_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    data = query.data.replace("banned_unban_ask_", "")
    uid_str, page_str = data.rsplit("_", 1)
    uid = int(uid_str)
    page = int(page_str)

    bl = read_blacklist()
    info = bl.get(uid)
    if not info:
        text, keyboard = build_blacklist_view(page)
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Batal", callback_data=f"banned_manage_{uid}_{page}"),
            InlineKeyboardButton("✅ Ya, Unban", callback_data=f"banned_unban_yes_{uid}_{page}")
        ]
    ])
    await query.edit_message_text(
        "⚠️ Unban user ini?\n\n"
        f"👤 {info['full_name']}\n"
        f"🆔 {uid}",
        reply_markup=keyboard
    )

async def banned_unban_yes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    data = query.data.replace("banned_unban_yes_", "")
    uid_str, page_str = data.rsplit("_", 1)
    uid = int(uid_str)
    page = int(page_str)

    bl = read_blacklist()
    bl.pop(uid, None)
    write_blacklist(bl)
    blocked_notified.discard(uid)

    text, keyboard = build_blacklist_view(page)
    await query.edit_message_text(text, reply_markup=keyboard)

async def adminvip_blacklist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    text, keyboard = build_blacklist_view(1)
    await query.edit_message_text(text, reply_markup=keyboard)

# ==================================================
# FILE MANAGER
# ==================================================
# (icon, display filename, absolute path on the Railway Volume)
FILE_MANAGER_FILES = [
    ("📦", "vip_packages.json", VIP_PACKAGES_FILE),
    ("⚙️", "settings.json", SETTINGS_FILE),
    ("👥", "users.json", USERS_FILE),
    ("✅", "approved.json", APPROVED_FILE),
    ("🚫", "blacklist.json", BLACKLIST_FILE),
    ("📊", "counter.json", COUNTER_FILE),
    ("📜", "order_history.json", ORDER_HISTORY_FILE),
    ("⏳", "pending_orders.json", PENDING_ORDERS_FILE),
    ("🔒", "payment_lock.json", PAYMENT_LOCK_FILE),
]

def split_text_into_chunks(text: str, limit: int = 3500):
    chunks = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks

def create_file_manager_backup(name: str, path: str):
    if not os.path.exists(path):
        return None
    os.makedirs(FILE_MANAGER_BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now(WIB).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(FILE_MANAGER_BACKUP_DIR, f"{name}.{timestamp}.bak")
    shutil.copy2(path, backup_path)
    return backup_path

def build_filemgr_list_view():
    available = [
        (idx, icon, name)
        for idx, (icon, name, path) in enumerate(FILE_MANAGER_FILES)
        if os.path.exists(path)
    ]

    keyboard_rows = []

    if not available:
        text = "🗂 File Manager\n\nTidak ada file yang ditemukan."
    else:
        text = "🗂 File Manager\n\nPilih file JSON untuk dikelola."
        for idx, icon, name in available:
            keyboard_rows.append([
                InlineKeyboardButton(f"{icon} {name}", callback_data=f"filemgr_open_{idx}")
            ])

    keyboard_rows.append([InlineKeyboardButton("🔙 Kembali", callback_data="adminvip_back")])

    keyboard = InlineKeyboardMarkup(keyboard_rows)
    return text, keyboard

async def filemgr_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    text, keyboard = build_filemgr_list_view()
    await query.edit_message_text(text, reply_markup=keyboard)

async def filemgr_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    idx = int(query.data.replace("filemgr_open_", ""))
    if idx < 0 or idx >= len(FILE_MANAGER_FILES):
        text, keyboard = build_filemgr_list_view()
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    icon, name, path = FILE_MANAGER_FILES[idx]
    if not os.path.exists(path):
        text, keyboard = build_filemgr_list_view()
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👁 View", callback_data=f"filemgr_view_{idx}"),
            InlineKeyboardButton("📥 Backup", callback_data=f"filemgr_backup_{idx}")
        ],
        [
            InlineKeyboardButton("✏️ Edit", callback_data=f"filemgr_edit_ask_{idx}"),
            InlineKeyboardButton("📤 Restore", callback_data=f"filemgr_restore_ask_{idx}")
        ],
        [InlineKeyboardButton("🔙 Kembali", callback_data="filemgr_list")]
    ])
    await query.edit_message_text(f"{icon} {name}\n\nPilih tindakan.", reply_markup=keyboard)

async def filemgr_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    idx = int(query.data.replace("filemgr_view_", ""))
    if idx < 0 or idx >= len(FILE_MANAGER_FILES):
        return

    icon, name, path = FILE_MANAGER_FILES[idx]
    if not os.path.exists(path):
        await query.message.reply_text(f"❌ {name} tidak ditemukan.")
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        await query.message.reply_text(f"❌ Gagal membaca {name}. File mungkin rusak.")
        return

    chunks = split_text_into_chunks(pretty)
    total_chunks = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        prefix = f"👁 {name} ({i}/{total_chunks})\n\n" if total_chunks > 1 else f"👁 {name}\n\n"
        await query.message.reply_text(f"{prefix}{chunk}")

async def filemgr_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    idx = int(query.data.replace("filemgr_backup_", ""))
    if idx < 0 or idx >= len(FILE_MANAGER_FILES):
        return

    icon, name, path = FILE_MANAGER_FILES[idx]
    if not os.path.exists(path):
        await query.message.reply_text(f"❌ {name} tidak ditemukan.")
        return

    with open(path, "rb") as f:
        await query.message.reply_document(document=f, filename=name, caption=f"📥 Backup {name}")

async def filemgr_edit_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    idx = int(query.data.replace("filemgr_edit_ask_", ""))
    if idx < 0 or idx >= len(FILE_MANAGER_FILES):
        return

    icon, name, path = FILE_MANAGER_FILES[idx]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Batal", callback_data=f"filemgr_open_{idx}"),
            InlineKeyboardButton("✅ Ya, Edit", callback_data=f"filemgr_edit_confirm_{idx}")
        ]
    ])
    await query.edit_message_text(
        f"⚠️ Edit {name}?\n\n"
        "Setelah dikonfirmasi, kirim teks JSON baru untuk menggantikan isi file ini.",
        reply_markup=keyboard
    )

async def filemgr_edit_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    idx = int(query.data.replace("filemgr_edit_confirm_", ""))
    if idx < 0 or idx >= len(FILE_MANAGER_FILES):
        return

    icon, name, path = FILE_MANAGER_FILES[idx]
    file_manager_edit_waiting[query.from_user.id] = idx

    await query.edit_message_text(
        f"✏️ Edit {name}\n\n"
        "Silakan kirim teks JSON baru untuk file ini."
    )

def invalidate_file_manager_cache(name: str):
    # File Manager writes bypass read_*/save_* helpers, so drop the matching
    # cache here; the next read_*() call will reload it fresh from disk.
    global _settings_cache, _vip_packages_cache, _users_cache, _approved_cache, _blacklist_cache
    if name == "settings.json":
        _settings_cache = None
    elif name == "vip_packages.json":
        _vip_packages_cache = None
    elif name == "users.json":
        _users_cache = None
    elif name == "approved.json":
        _approved_cache = None
    elif name == "blacklist.json":
        _blacklist_cache = None

async def file_manager_edit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int):
    if idx < 0 or idx >= len(FILE_MANAGER_FILES):
        return

    icon, name, path = FILE_MANAGER_FILES[idx]

    try:
        data = json.loads(update.message.text)
    except Exception:
        await update.message.reply_text(f"❌ JSON tidak valid. {name} tidak diubah.")
        return

    create_file_manager_backup(name, path)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    invalidate_file_manager_cache(name)

    await update.message.reply_text(
        f"✅ {name} berhasil diperbarui.\n"
        "📥 Backup otomatis telah dibuat sebelum perubahan."
    )

async def filemgr_restore_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    idx = int(query.data.replace("filemgr_restore_ask_", ""))
    if idx < 0 or idx >= len(FILE_MANAGER_FILES):
        return

    icon, name, path = FILE_MANAGER_FILES[idx]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Batal", callback_data=f"filemgr_open_{idx}"),
            InlineKeyboardButton("✅ Ya, Restore", callback_data=f"filemgr_restore_confirm_{idx}")
        ]
    ])
    await query.edit_message_text(
        f"⚠️ Restore {name}?\n\n"
        "Setelah dikonfirmasi, upload file .json baru untuk menggantikan file ini.",
        reply_markup=keyboard
    )

async def filemgr_restore_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    idx = int(query.data.replace("filemgr_restore_confirm_", ""))
    if idx < 0 or idx >= len(FILE_MANAGER_FILES):
        return

    icon, name, path = FILE_MANAGER_FILES[idx]
    file_manager_restore_waiting[query.from_user.id] = idx

    await query.edit_message_text(
        f"📤 Restore {name}\n\n"
        "Silakan upload file .json baru untuk menggantikan file ini."
    )

async def file_manager_restore_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    idx = file_manager_restore_waiting.pop(user_id)
    if idx < 0 or idx >= len(FILE_MANAGER_FILES):
        return

    icon, name, path = FILE_MANAGER_FILES[idx]

    document = update.message.document
    if not document or not document.file_name.lower().endswith(".json"):
        await update.message.reply_text(f"❌ File harus berformat .json. {name} tidak diubah.")
        return

    tg_file = await document.get_file()
    raw_bytes = await tg_file.download_as_bytearray()

    try:
        data = json.loads(bytes(raw_bytes).decode("utf-8"))
    except Exception:
        await update.message.reply_text(f"❌ JSON tidak valid. {name} tidak diubah.")
        return

    create_file_manager_backup(name, path)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    invalidate_file_manager_cache(name)

    await update.message.reply_text(
        f"✅ {name} berhasil di-restore.\n"
        "📥 Backup otomatis telah dibuat sebelum perubahan."
    )

def build_adminvip_keyboard():
    keyboard = []
    
    keyboard.append([
        InlineKeyboardButton(
            "📦 Kelola Paket",
            callback_data="adminvip_packages"
        ),
        InlineKeyboardButton(
            "📊 Statistik",
            callback_data="adminvip_stats"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "💳 Pembayaran",
            callback_data="adminvip_payment"
        ),
        InlineKeyboardButton(
            "🚫 Blacklist",
            callback_data="adminvip_blacklist"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🗂 File Manager",
            callback_data="filemgr_list"
        ),
        InlineKeyboardButton(
            "📢 Channel Post",
            callback_data="adminvip_channel"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⚙️ Pengaturan",
            callback_data="adminvip_settings"
        )
    ])

    return InlineKeyboardMarkup(keyboard)
    
def build_payment_keyboard():

    keyboard = []

    keyboard.append([
        InlineKeyboardButton(
            "📋 Order History",
            callback_data="payment_history"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🗑 Clear Order",
            callback_data="payment_clear"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🖼 Edit QRIS",
            callback_data="payment_qris"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 Menu Admin",
            callback_data="adminvip_back"
        )
    ])

    return InlineKeyboardMarkup(keyboard)
    
async def adminvip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    settings = read_settings()

    admin_panel_text = (
        "<b>👑 ADMIN VIP PANEL</b>\n"
        "<pre>"

        f"👥 Users       : {len(read_user_registry())}\n"
        f"📦 Packages    : {len(read_vip_packages()['packages'])}\n"
        f"📢 Auto Post   : {'🟢' if settings['channel_auto_post'] else '🔴'}\n"
        f"🗑 Auto Delete : {'🟢' if settings['preview_auto_delete'] else '🔴'}\n"
        f"⏱ Timer       : {settings['preview_delete_delay']} detik\n"

        "</pre>"
    )

    await update.message.reply_photo(
        photo=os.environ["ADMIN_BANNER_FILE_ID"],
        caption=admin_panel_text,
        reply_markup=build_adminvip_keyboard(),
        parse_mode="HTML",
    )

async def send_stats(chat_id: int, bot):
    count = read_counter()

    old_message = last_stats_message.get(chat_id)

    if old_message:
        try:
            await bot.delete_message(
                chat_id=chat_id,
                message_id=old_message
            )
        except Exception:
            pass

    msg = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"📊 *Stats Bot*\n\n"
            f"Total penggunaan `UC3A6P`: *{count}x*"
        ),
        parse_mode="Markdown",

    )

    last_stats_message[chat_id] = msg.message_id
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    await send_stats(
        update.effective_chat.id,
        context.bot
    )

async def do_reset_stats(chat_id: int, bot):
    try:
        with open(COUNTER_FILE, "w") as f:
            json.dump({"count": 0}, f)
    except Exception as e:
        logger.error(f"Failed to reset counter: {e}")
        return

    old_message = last_stats_message.get(chat_id)

    if old_message:
        try:
            await bot.delete_message(
                chat_id=chat_id,
                message_id=old_message
            )
        except Exception:
            pass

    msg = await bot.send_message(
        chat_id=chat_id,
        text="✅ Statistik berhasil direset!"
    )

    last_stats_message[chat_id] = msg.message_id

async def resetstats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    await do_reset_stats(
        update.effective_chat.id,
        context.bot
    )
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

async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id in getid_waiting:

        await getid_receive(update, context)

        return

    if user_id in admin_qris_waiting:

        await admin_qris_receive(update, context)

        return

    if user_id in file_manager_restore_waiting:

        await file_manager_restore_receive(update, context)

        return

    if user_id in preview_edit_waiting or user_id in preview_add_waiting:

        await preview_media_receive(update, context)

        return

    await payment_receive(update, context)
    
async def payment_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    order_id = None

    for oid, data in upload_waiting.items():

        if data["user_id"] == user_id:

            order_id = oid

    if order_id is None:

        return
        
    if upload_waiting[order_id].get("processing"):

        if upload_waiting[order_id].get("processing_msg_id") is None:

            msg = await update.message.reply_text(
                "⏳ Bukti transfer sedang diproses.\n\n"
                "Mohon tunggu sebentar."
            )

            upload_waiting[order_id]["processing_msg_id"] = msg.message_id

        return
        
    if upload_waiting[order_id].get("photo_uploaded"):

        await update.message.reply_text(
            "✅ Bukti transfer sudah diterima.\n\n"
            "Mohon tunggu verifikasi admin."
        )

        return

    if not update.message.photo:

        await update.message.reply_text(

            "⚠️ Silakan kirim bukti transfer dalam bentuk foto."

        )

        return

    upload_waiting[order_id]["processing"] = True
    
    upload_waiting[order_id]["photo_file_id"] = update.message.photo[-1].file_id

    upload_waiting[order_id]["photo_uploaded"] = True
    
    pending = read_pending_orders()

    for i, order in enumerate(pending["orders"]):

        if order["order_id"] == order_id:

            pending["orders"][i] = upload_waiting[order_id].copy()

            break

    save_pending_orders(pending)

    user = update.effective_user

    username = f"@{user.username}" if user.username else "-"

    await context.bot.send_photo(

        chat_id=ADMIN_ID,

        photo=upload_waiting[order_id]["photo_file_id"],

        caption=(

            "📥 Bukti Transfer Baru\n\n"

            f"👤 Nama : {user.full_name}\n"

            f"🔗 Username : {username}\n"

            f"🆔 User ID : {user.id}\n\n"

            f"📦 Paket : {upload_waiting[order_id]['paket']}\n"

            f"💰 Harga : {upload_waiting[order_id]['harga']}"

        )

    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Terima",
                callback_data=f"pay_ok|{order_id}"
            ),
            InlineKeyboardButton(
                "📷 Foto Ulang",
                callback_data=f"pay_no|{order_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🚫 Ban User",
                callback_data=f"pay_ban|{order_id}"
            )
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "📋 Verifikasi Pembayaran\n\n"
            f"👤 {user.full_name}\n"
            f"📦 {upload_waiting[order_id]['paket']}\n"
            f"💰 {upload_waiting[order_id]['harga']}"
        ),
        reply_markup=keyboard
    )

    if not upload_waiting[order_id].get("reupload"):

        status_msg = await update.message.reply_text(
            "✅ Pembayaran kamu sedang diproses.\n"
            "⏳ Estimasi waktu: 1–3 menit...\n\n"
        )

        upload_waiting[order_id]["status_msg_id"] = status_msg.message_id

    else:

        upload_waiting[order_id]["reupload"] = False

async def admin_qris_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in admin_qris_waiting:

        return

    if not update.message.photo:

        await update.message.reply_text(

            "❌ Kirim dalam bentuk foto."

        )

        return

    file_id = update.message.photo[-1].file_id

    settings = read_settings()

    settings["qris_file_id"] = file_id

    save_settings(settings)
    
    logger.info(settings)

    admin_qris_waiting.discard(user_id)

    await update.message.reply_photo(

        photo=file_id,

        caption="✅ QRIS berhasil diperbarui."

    )
async def payment_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    try:
        action, oid = query.data.split("|", 1)
        order_id = int(oid)
    except Exception:
        return

    data = upload_waiting.get(order_id)

    user_id = data["user_id"] if data else None
    if not data:
        await query.edit_message_text(
            "⚠️ Data pembayaran sudah tidak tersedia."
        )
        return

    if action == "pay_ok":
        package = get_package(data["package_id"])
        vip_link = package["vip_link"]

        try:
            await context.bot.delete_message(
                chat_id=user_id,
                message_id=data["status_msg_id"]
            )
        except Exception:
            pass
    
        try:
            if data.get("processing_msg_id"):
                await context.bot.delete_message(
                    chat_id=user_id,
                    message_id=data["processing_msg_id"]
                )
        except Exception:
            pass
            
        try:
            await query.edit_message_text(
                "✅ Pembayaran telah disetujui."
            )
        except Exception as e:
            logger.error(f"Edit admin message error: {e}")
    
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "👉🏻 Pembayaran berhasil diverifikasi.\n\n"
                f"Silakan bergabung ke VIP:\n{vip_link}"
            )
        )
        
        if user_id not in ORDER_HISTORY_EXCLUDED:

            history = read_order_history()

            history["orders"].append({
                "user_id": user_id,
                "full_name": data["full_name"],
                "username": data["username"],
                "package_id": data["package_id"],
                "time": datetime.now(WIB).strftime("%d %b %Y, %H:%M:%S WIB")
            })

            logger.info(history)

            save_order_history(history)

        upload_waiting.pop(order_id, None)
        pending = read_pending_orders()

        pending["orders"] = [
            order
            for order in pending["orders"]
            if order["order_id"] != order_id
        ]

        save_pending_orders(pending)
        
        unlock_payment(user_id)

    elif action == "pay_no":
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "📷 Bukti transfer belum valid.\n"
                "Silakan upload ulang bukti transfer."
            )
        )
        upload_waiting[order_id]["photo_uploaded"] = False
        upload_waiting[order_id]["reupload"] = True
        upload_waiting[order_id]["processing"] = False
        upload_waiting[order_id]["processing_msg_id"] = None
        upload_waiting[order_id]["photo_file_id"] = None
        
        pending = read_pending_orders()

        for i, order in enumerate(pending["orders"]):
            if order["order_id"] == order_id:
                pending["orders"][i] = upload_waiting[order_id].copy()
                break

        save_pending_orders(pending)
        
        await query.edit_message_text(
            "❌ Pembayaran ditolak."
        )
    elif action == "pay_ban":

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Ya, Batasi",
                    callback_data=f"pay_ban_yes|{order_id}"
                ),
                InlineKeyboardButton(
                    "❌ Batal",
                    callback_data=f"pay_ban_cancel|{order_id}"
                )
            ]
        ])

        await query.edit_message_text(
            "⚠️ Konfirmasi\n\n"
            "Yakin ingin membatasi akses user ini?",
            reply_markup=keyboard
        )
        
    elif action == "pay_ban_cancel":

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Terima",
                    callback_data=f"pay_ok|{order_id}"
                ),
                InlineKeyboardButton(
                    "📷 Foto Ulang",
                    callback_data=f"pay_no|{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🚫 Ban Users",
                    callback_data=f"pay_ban|{order_id}"
                )
            ]
        ])

        await query.edit_message_text(
            text=(
                "📋 Verifikasi Pembayaran\n\n"
                f"👤 {data['full_name']}\n"
                f"📦 {data['paket']}\n"
                f"💰 {data['harga']}"
            ),
            reply_markup=keyboard
        )
        
    elif action == "pay_ban_yes":
        blacklist = read_blacklist()
        
        blacklist[user_id] = {
            "full_name": data["full_name"],
            "username": data["username"]
        }

        write_blacklist(blacklist)

        upload_waiting.pop(order_id, None)

        pending = read_pending_orders()

        pending["orders"] = [
            order
            for order in pending["orders"]
            if order["order_id"] != order_id
        ]

        save_pending_orders(pending)

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🚫 Akses Anda telah dibatasi."
                )
            )
        except Exception:
            pass

        await query.edit_message_text(
            "✅ User berhasil dibatasi."
        )
        
async def livechat_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split("|")[1])

    admin_reply_waiting[query.from_user.id] = user_id

    await query.message.reply_text(
        "💬 Silakan kirim balasan untuk user."
    )
        
async def getid_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    getid_waiting.discard(update.effective_user.id)
    await update.message.reply_text("❌ /getid dibatalkan.")
#---------------------------------------------------------------------------
# POST DARI BOT
#---------------------------------------------------------------------------
async def channeltest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text="✅ Test post dari bot."
    )

    await update.message.reply_text(
        "Berhasil mengirim ke channel."
    )
# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
migrate_to_volume("vip_packages.json")
migrate_to_volume("settings.json")
migrate_to_volume("users.json")
migrate_to_volume("approved.json")
migrate_to_volume("blacklist.json")
migrate_to_volume("counter.json")
migrate_to_volume("order_history.json")
migrate_to_volume("pending_orders.json")

def restore_pending_orders():
    global upload_waiting
    global next_order_id

    pending = read_pending_orders()

    upload_waiting = {}

    max_order_id = 0

    for order in pending["orders"]:

        order_id = order["order_id"]

        upload_waiting[order_id] = order

        if order_id > max_order_id:
            max_order_id = order_id

    next_order_id = max_order_id + 1
    
# ---------------------------------------------------------------------------
# AUTO CHANNEL POST
# ---------------------------------------------------------------------------

async def channel_auto_post_loop(app):
    try:
        while True:
            settings = read_settings()

            if (
                settings["channel_auto_post"]
                and settings["channel_post_text"]
            ):
                now = int(time.time())
                interval = settings["channel_interval"] * 60

                if now - settings["channel_last_post"] >= interval:

                    if settings["channel_last_message_id"]:
                        try:
                            await app.bot.delete_message(
                                chat_id=CHANNEL_ID,
                                message_id=settings["channel_last_message_id"]
                            )
                        except Exception:
                            pass

                    msg = await app.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=settings["channel_post_text"]
                    )

                    settings["channel_last_message_id"] = msg.message_id
                    settings["channel_last_post"] = now

                    save_settings(settings)

            await asyncio.sleep(30)

    except asyncio.CancelledError:
        raise

    except Exception as e:
        logger.error(f"Channel Auto Post Error: {e}")
    
async def set_admin_commands(app):
    await app.bot.set_my_commands(
        [
            BotCommand("adminvip", "Buka Admin VIP"),
            BotCommand("banned", "Kelola Blacklist"),
        ],
        scope=BotCommandScopeChat(chat_id=ADMIN_ID),
    )

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable is not set.")

    restore_pending_orders()
    
    app = ApplicationBuilder().token(token).build()

    async def start_background(app):
        await set_admin_commands(app)
        app.bot_data["channel_task"] = asyncio.create_task(channel_auto_post_loop(app))

    async def stop_background(app):
        task = app.bot_data.get("channel_task")
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app.post_init = start_background
    app.post_shutdown = stop_background
    
    app.add_handler(CommandHandler("getid", getid_start))
    app.add_handler(CommandHandler("cancel", getid_cancel))
    app.add_handler(CommandHandler("channeltest", channeltest))
    
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("adminvip",   adminvip))
    app.add_handler(CommandHandler("stats",      stats))
    app.add_handler(CommandHandler("resetstats", resetstats))
    app.add_handler(CommandHandler("ban",        ban))
    app.add_handler(CommandHandler("unban",      unban))
    app.add_handler(CommandHandler("banned",     banned))
    # High-frequency customer callbacks registered first so they are matched
    # with the fewest possible regex checks (order impacts routing latency).
    app.add_handler(
        CallbackQueryHandler(
            vip1_callback,
            pattern=r"^vip_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            bayar1_callback,
            pattern=r"^bayar_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            upload_bukti_callback,
            pattern=r"^upload_bukti_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            cancel_order_callback,
            pattern=r"^cancel_order$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            livechat_reply_callback,
            pattern=r"^reply\|"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            approval_callback,
            pattern=r"^(izin|tolak|reset|ignore|ban)\|"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            banned_page_callback,
            pattern=r"^banned_page_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            banned_reset_yes_callback,
            pattern=r"^banned_reset_yes$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            banned_reset_ask_callback,
            pattern=r"^banned_reset_ask_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            banned_unban_yes_callback,
            pattern=r"^banned_unban_yes_\d+_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            banned_unban_ask_callback,
            pattern=r"^banned_unban_ask_\d+_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            banned_manage_callback,
            pattern=r"^banned_manage_\d+_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            adminvip_blacklist_callback,
            pattern=r"^adminvip_blacklist$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filemgr_list_callback,
            pattern=r"^filemgr_list$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filemgr_open_callback,
            pattern=r"^filemgr_open_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filemgr_view_callback,
            pattern=r"^filemgr_view_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filemgr_backup_callback,
            pattern=r"^filemgr_backup_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filemgr_edit_confirm_callback,
            pattern=r"^filemgr_edit_confirm_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filemgr_edit_ask_callback,
            pattern=r"^filemgr_edit_ask_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filemgr_restore_confirm_callback,
            pattern=r"^filemgr_restore_confirm_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filemgr_restore_ask_callback,
            pattern=r"^filemgr_restore_ask_\d+$"
        )
    )
    app.add_handler(
    CallbackQueryHandler(
        payment_admin_callback,
        pattern=r"^(pay_ok|pay_no|pay_ban|pay_ban_yes|pay_ban_cancel)\|"
    ))
    app.add_handler(
    CallbackQueryHandler(
        vipmenu_callback,
        pattern=r"^vipmenu$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_packages_callback,
        pattern=r"^adminvip_packages$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_payment_callback,
        pattern=r"^adminvip_payment$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_channel_callback,
        pattern=r"^adminvip_channel$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        channel_edit_callback,
        pattern=r"^channel_edit$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        channel_toggle_callback,
        pattern=r"^channel_toggle$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        channel_send_callback,
        pattern=r"^channel_send$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        channel_interval_callback,
        pattern=r"^channel_interval$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        channel_set_interval_callback,
        pattern=r"^channel_set_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        payment_back_callback,
        pattern=r"^payment_back$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        payment_history_callback,
        pattern=r"^payment_history$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        payment_clear_callback,
        pattern=r"^payment_clear$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        payment_clear_yes_callback,
        pattern=r"^payment_clear_yes$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        payment_history_delete_yes_callback,
        pattern=r"^history_delete_yes_"
    ))
    app.add_handler(
    CallbackQueryHandler(
        payment_history_delete_callback,
        pattern=r"^history_delete_"
    ))
    app.add_handler(
    CallbackQueryHandler(
        payment_history_detail_callback,
        pattern=r"^history_"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_settings_callback,
        pattern=r"^adminvip_settings$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_stats_callback,
        pattern=r"^adminvip_stats$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        stats_view_callback,
        pattern=r"^stats_view$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        stats_reset_callback,
        pattern=r"^stats_reset$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_packages_back_callback,
        pattern=r"^adminvip_packages_back$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_package_callback,
        pattern=r"^adminvip_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_add_callback,
        pattern=r"^adminvip_add$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_back_callback,
        pattern=r"^adminvip_back$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_name_callback,
        pattern=r"^adminvip_name_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_price_callback,
        pattern=r"^adminvip_price_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_desc_callback,
        pattern=r"^adminvip_desc_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_link_callback,
        pattern=r"^adminvip_link_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_delete_callback,
        pattern=r"^adminvip_delete_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminadd_save_callback,
        pattern=r"^adminadd_save$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_delete_yes_callback,
        pattern=r"^adminvip_delete_yes_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminadd_edit_callback,
        pattern=r"^adminaddedit_(nama|harga|deskripsi|vip_link)$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_qris_callback,
        pattern=r"^adminvip_qris$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_qris_callback,
        pattern=r"^payment_qris$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_qris_change_callback,
        pattern=r"^adminvip_qris_change$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_toggle_join_callback,
        pattern=r"^adminvip_toggle_join$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_preview_settings_callback,
        pattern=r"^adminvip_preview_settings$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_prv_list_callback,
        pattern=r"^adminvip_prv_list$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_prv_nav_callback,
        pattern=r"^adminvip_prv_nav_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_prv_noop_callback,
        pattern=r"^adminvip_prv_noop$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_prv_add_callback,
        pattern=r"^adminvip_prv_add$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_prv_add_cancel_callback,
        pattern=r"^adminvip_prv_add_cancel$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_prv_edit_callback,
        pattern=r"^adminvip_prv_edit_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_prv_del_callback,
        pattern=r"^adminvip_prv_del_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_prv_delyes_callback,
        pattern=r"^adminvip_prv_delyes_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_prv_back_callback,
        pattern=r"^adminvip_prv_back$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_toggle_preview_callback,
        pattern=r"^adminvip_toggle_preview$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        adminvip_toggle_livechat_callback,
        pattern=r"^adminvip_toggle_livechat$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        preview_toggle_callback,
        pattern=r"^preview_toggle$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        preview_timer_callback,
        pattern=r"^preview_timer$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        preview_set_callback,
        pattern=r"^preview_set_\d+$"
    ))
    app.add_handler(
    MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL,
        photo_router,
    ))
    
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL |
        filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL,
        getid_receive,
    ))
    
    app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        admin_text_receive,
    ))
    
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()