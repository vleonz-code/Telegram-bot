import os
import json
import logging
import shutil
from datetime import datetime, timezone, timedelta
from telegram import Update, InputMediaVideo, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
DATA_DIR = "/data"
APP_DIR = os.path.dirname(__file__)

os.makedirs(DATA_DIR, exist_ok=True)

DEEP_LINK_PAYLOAD = "UB3A6P"
ADMIN_ID = 7602115007
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

def migrate_to_volume(filename):
    src = os.path.join(APP_DIR, filename)
    dst = os.path.join(DATA_DIR, filename)

    if not os.path.exists(dst) and os.path.exists(src):
        shutil.copy2(src, dst)
        logger.info(f"{filename} berhasil disalin ke Volume.")
        
def read_vip_packages():
    with open(VIP_PACKAGES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
        
def save_vip_packages(data):
    with open(VIP_PACKAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
# ==========================

# SETTINGS

# ==========================

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

def read_settings():

    if not os.path.exists(SETTINGS_FILE):

        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:

            json.dump(

                {

                    "qris_file_id": "",

                    "join_vip_enabled": True,
                    "preview_approval_enabled": True

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

    return data

def save_settings(data):

    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:

        json.dump(

            data,

            f,

            ensure_ascii=False,

            indent=2

        )
    
WIB = timezone(timedelta(hours=7))

# In-memory store for requests awaiting admin decision.
# { user_id: {"chat_id": int, "waiting_msg_id": int, "full_name": str, "username": str} }
pending_requests: dict = {}

# In-memory set of admin user_ids waiting to send a media for /getid
getid_waiting: set = set()
# User yang sedang dalam proses upload bukti transfer
# Contoh:
# upload_waiting[user_id] = {
#     "paket": "VIP 1 Bulan",
#     "harga": "Rp50.000"
# }
upload_waiting = {}
admin_edit_waiting = {}
admin_add_waiting = {}
admin_qris_waiting = set()
last_stats_message = {}

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

        progress = await bot.send_message(

            chat_id,

            "📦 Mengirim Batch 1/1 (6 media)...\nMohon tunggu..."

        )

        await bot.send_media_group(chat_id, media=media)

        await progress.delete()

        await bot.send_message(

            chat_id,

            "<b>📢 Bot Resmi milik @BocilVIP89</b>\n"

            "✅ Semua 6 media terkirim!",

            parse_mode="HTML"

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

            await bot.send_message(

                chat_id,

                "🎬 Penasaran dengan previewnya?\n\n"
                 "Join VIP untuk akses lebih lengkap.",

                reply_markup=keyboard

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
        with open(APPROVED_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"approved": list(approved)},
                f,
                ensure_ascii=False,
                indent=2
            )

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

    except Exception as e:
        logger.error(f"Blacklist write error: {e}")
        
def get_package(package_id: int):

    with open(VIP_PACKAGES_FILE, "r", encoding="utf-8") as f:

        data = json.load(f)

    for pkg in data["packages"]:

        if pkg["id"] == package_id:

            return pkg

    return None
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
        
    settings = read_settings()

    if not settings["preview_approval_enabled"]:
        ok = await deliver_album(context.bot, update.effective_chat.id)

        if ok:
            save_user_to_registry(user_id, full_name, username)
            increment_counter()
            await notify_admin(context.bot, full_name, username, user_id)

            approved = read_approved()
            
            if user_id not in approved:
               approved.add(user_id)
               save_approved(approved)

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
    waiting_msg = await update.message.reply_text("⏳ Video preview sedang diproses…\n\nEstimasi waktu: 1–3 menit.")

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
        "Silakan pilih salah satu paket.",
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
            "🔙 Kembali",
            callback_data="vipmenu"
        ),
        InlineKeyboardButton(
            "💳 Bergabung",
            callback_data=f"bayar_{package_id}"
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
        
async def bayar1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[1])
    package = get_package(package_id)

    settings = read_settings()
    qris_file_id = settings.get("qris_file_id", "")

    if not qris_file_id:
        await query.message.reply_text(
            "❌ QRIS belum dikonfigurasi."
        )
        return

    await context.bot.send_photo(
        chat_id=query.message.chat_id,
        photo=qris_file_id,
caption=(
    "*PEMBAYARAN GROUP BOCIL*\n"
    "*────── . 👇🏻 . ──────*\n\n"

    "*📦 Paket*\n"
    f"*{package['nama']}*\n\n"

    "*💰 Nominal*\n"
    f"*{package['harga']}*\n\n"

    "*Scan kode QR diatas untuk melakukan pembayaran, bayar sesuai pilihan paket lalu kirim (screenshot/foto) transfer Anda disini sebagai bukti.*\n\n"

    "*✅ Pembayaran via*\n"
    "*(Ovo, Dana, Shopeepay, Gopay, TNG, Maybank, USDT)*\n\n"

    "*Terimakasih*"
),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📤 Saya Sudah Transfer",
                    callback_data=f"upload_bukti_{package_id}"
                )
            ]
        ])
    )
            
async def upload_bukti_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    username = f"@{user.username}" if user.username else "-"

    upload_waiting[user.id] = {
        "package_id": package["id"],
        "paket": package["nama"],
        "harga": package["harga"],
        "full_name": user.full_name,
        "username": username
    }

    await query.message.reply_text(
        "Silakan upload screenshot bukti transfer Anda.\n\n"
        "Pastikan:\n"
        "• Nominal transfer terlihat jelas.\n"
        "• Waktu transaksi terlihat.\n"
        "• Bukti tidak terpotong.\n\n"
        "Ketik /cancel untuk membatalkan."
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
    await query.edit_message_text(
        "➕ Tambah Paket\n\n"
        "Silakan masukkan nama paket baru.",
        reply_markup=keyboard
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
    await query.edit_message_text(
    f"{package['nama']}\n\n"
    f"💰 {package['harga']}",
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
                f"📦 {package['nama']}",
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

    await query.edit_message_text(
        "📦 Kelola Paket\n\n"
        "Pilih paket yang ingin dikelola:",
        reply_markup=InlineKeyboardMarkup(keyboard)

    )
    
async def adminvip_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📋 Order History",
                callback_data="payment_history"
            )
        ],
        [
            InlineKeyboardButton(
            "🖼 Edit QRIS",
            callback_data="payment_qris"
        )
    ],
        [
            InlineKeyboardButton(
            "🗑 Clear Order",
            callback_data="payment_clear"
        )
    ],
    [
            InlineKeyboardButton(
            "🔙 Menu Admin",
            callback_data="adminvip_back"
        )
    ]
    ])

    await query.edit_message_text(
        "💳 Pembayaran",
        reply_markup=keyboard
    )
   
async def payment_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:

        await query.message.delete()

    except:
        pass

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📋 Order History",
                callback_data="payment_history"
            )
        ],
        [
            InlineKeyboardButton(
                "🖼 Edit QRIS",
                callback_data="payment_qris"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Menu Admin",
                callback_data="adminvip_back"
            )
        ]
    ])
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="💳 Pembayaran",
        reply_markup=keyboard
    )
    
async def payment_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    history = read_order_history()

    if not history["orders"]:

        await query.edit_message_text(
            "📋 Order History\n\n"
            "Belum ada transaksi.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Pembayaran",
                        callback_data="adminvip_payment"
                    )
                ]
            ])
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

    await query.edit_message_text(
        "📋 Order History\n\n"

        f"💰 Total Pendapatan\n"
        f"Rp{total_pendapatan:,}".replace(",", ".") + "\n\n"

        f"📦 Total Order {total_order}\n\n"

        "📅 Pilih tanggal transaksi di bawah ini.",

        reply_markup=InlineKeyboardMarkup(keyboard)
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
    
async def adminvip_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{'🟢' if settings['join_vip_enabled'] else '🔴'} ORDER VIP : {'ON' if settings['join_vip_enabled'] else 'OFF'}",
                callback_data="adminvip_toggle_join"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'🟢' if settings['preview_approval_enabled'] else '🔴'} CEK PREVIEW : {'ON' if settings['preview_approval_enabled'] else 'OFF'}",
                callback_data="adminvip_toggle_preview"
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
        "⚙️ Pengaturan",
        reply_markup=keyboard
    )
    
async def adminvip_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📈 Lihat Statistik",
                callback_data="stats_view"
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 Reset Statistik",
                callback_data="stats_reset"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Menu Admin",
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
 
async def adminvip_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await clear_last_stats(
        query.message.chat_id,
        context.bot
    )
    await query.message.delete()

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="⚙️ Menu Admin VIP\n\n",
        reply_markup=build_adminvip_keyboard()
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

        await query.message.delete()

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

    await adminvip_settings_callback(update, context)
    
async def adminvip_toggle_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    settings = read_settings()
    settings["preview_approval_enabled"] = not settings["preview_approval_enabled"]
    save_settings(settings)

    await adminvip_settings_callback(update, context)
    
async def adminvip_name_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    admin_edit_waiting[query.from_user.id] = {
        "package_id": package_id,
        "field": "nama"
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data=f"adminvip_{package_id}"
            )
        ]
    ])
    await query.edit_message_text(
        f"📝 Edit Nama\n\n"
        f"Nama saat ini:\n"
        f"{package['nama']}\n\n"
        "Silakan update nama baru.",
        reply_markup=keyboard
    )
    
async def adminvip_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    admin_edit_waiting[query.from_user.id] = {
        "package_id": package_id,
        "field": "harga"
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data=f"adminvip_{package_id}"
            )
        ]
    ])
    await query.edit_message_text(
        f"💰 Edit Harga\n\n"
        f"Harga saat ini:\n"
        f"{package['harga']}\n\n"
        "Silakan update harga baru.",
        reply_markup=keyboard
    )
    
async def adminvip_desc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    admin_edit_waiting[query.from_user.id] = {
        "package_id": package_id,
        "field": "deskripsi"
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data=f"adminvip_{package_id}"
            )
        ]
    ])
    await query.edit_message_text(
        f"📄 Edit Deskripsi\n\n"
        f"Deskripsi saat ini:\n"
        f"{package['deskripsi']}\n\n"
        "Silakan update deskripsi baru.",
        reply_markup=keyboard
    )
    
async def adminvip_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    package_id = int(query.data.split("_")[2])
    package = get_package(package_id)

    admin_edit_waiting[query.from_user.id] = {
        "package_id": package_id,
        "field": "vip_link"
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Kembali",
                callback_data=f"adminvip_{package_id}"
            )
        ]
    ])
    await query.edit_message_text(
        f"🔗 Edit Link VIP\n\n"
        f"Link saat ini:\n"
        f"{package['vip_link']}\n\n"
        "Silakan kirim link VIP baru.\n\n"
        "Contoh:\nhttps://t.me/...",
        reply_markup=keyboard
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

    await query.edit_message_text(
        f"⚠️ Yakin ingin menghapus paket ini?\n\n"
        f"💎 {package['nama']}\n"
        f"💰 {package['harga']}",
        reply_markup=keyboard
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

    keyboard = []

    for package in packages["packages"]:

        keyboard.append([

            InlineKeyboardButton(

                package["nama"],

                callback_data=f"adminvip_{package['id']}"

            )

        ])

    keyboard.append([

        InlineKeyboardButton(

            "➕ Tambah Paket",

            callback_data="adminvip_add"

        )

    ])

    await query.edit_message_text(

        "⚙️ Admin VIP\n\nPilih paket yang ingin dikelola:",

        reply_markup=InlineKeyboardMarkup(keyboard)

    )
    
async def admin_edit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in admin_edit_waiting:
        return

    data = admin_edit_waiting.pop(user_id)

    packages = read_vip_packages()

    for package in packages["packages"]:
        if package["id"] == data["package_id"]:

            if data["field"] == "nama":
                package["nama"] = update.message.text.strip()

            elif data["field"] == "harga":
                package["harga"] = update.message.text.strip()

            elif data["field"] == "deskripsi":
                package["deskripsi"] = update.message.text

            elif data["field"] == "vip_link":
                package["vip_link"] = update.message.text.strip()

            save_vip_packages(packages)

            await update.message.reply_text(
                "✅ Data paket berhasil diperbarui."
            )
            return

async def show_add_preview(message, data):

    preview = (

        "📦 Preview Paket\n\n"

        f"💎 Nama\n{data['nama']}\n\n"

        f"💰 Harga\n{data['harga']}\n\n"

        f"📄 Deskripsi\n{data['deskripsi']}\n\n"

        f"🔗 Link\n{data['vip_link']}"

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

        reply_markup=keyboard

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
    await admin_edit_receive(update, context)
    await admin_add_receive(update, context)
  
        
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

    keyboard = []

    for package in packages["packages"]:
        keyboard.append([
            InlineKeyboardButton(
                package["nama"],
                callback_data=f"adminvip_{package['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "➕ Tambah Paket",
            callback_data="adminvip_add"
        )
    ])

    await query.edit_message_text(
        "✅ Paket berhasil ditambahkan.\n\n"
        "⚙️ Admin VIP\n\n"
        "Pilih paket yang ingin dikelola:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
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
    
def build_adminvip_keyboard():
    keyboard = []
    
    keyboard.append([
        InlineKeyboardButton(
            "📦 Kelola Paket",
            callback_data="adminvip_packages"
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            "📊 Statistik",
            callback_data="adminvip_stats"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "💳 Pembayaran",
            callback_data="adminvip_payment"
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            "⚙️ Pengaturan",
            callback_data="adminvip_settings"
        )
    ])

    return InlineKeyboardMarkup(keyboard)
    
async def adminvip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "⚙️ Menu Admin VIP\n\n",
        reply_markup=build_adminvip_keyboard()
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
            f"Total penggunaan `UB3A6P`: *{count}x*"
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

    if user_id in admin_qris_waiting:

        await admin_qris_receive(update, context)

        return

    await payment_receive(update, context)
    
async def payment_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in upload_waiting:

        return

    if not update.message.photo:

        await update.message.reply_text(

            "⚠️ Silakan kirim bukti transfer dalam bentuk foto."

        )

        return

    upload_waiting[user_id]["photo_file_id"] = update.message.photo[-1].file_id

    user = update.effective_user

    username = f"@{user.username}" if user.username else "-"

    await context.bot.send_photo(

        chat_id=ADMIN_ID,

        photo=upload_waiting[user_id]["photo_file_id"],

        caption=(

            "📥 Bukti Transfer Baru\n\n"

            f"👤 Nama : {user.full_name}\n"

            f"🔗 Username : {username}\n"

            f"🆔 User ID : {user.id}\n\n"

            f"📦 Paket : {upload_waiting[user_id]['paket']}\n"

            f"💰 Harga : {upload_waiting[user_id]['harga']}"

        )

    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Terima",
                callback_data=f"pay_ok|{user.id}"
            ),
            InlineKeyboardButton(
                "❌ Tolak",
                callback_data=f"pay_no|{user.id}"
            )
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "📋 Verifikasi Pembayaran\n\n"
            f"👤 {user.full_name}\n"
            f"📦 {upload_waiting[user_id]['paket']}\n"
            f"💰 {upload_waiting[user_id]['harga']}"
        ),
        reply_markup=keyboard
    )

    status_msg = await update.message.reply_text(
         "✅ Bukti transfer kamu sudah diterima.\n"
         "⏳ Estimasi waktu: 1–3 menit.\n\n"
         "Colek Admin: @BocilVIP89"
      )

    upload_waiting[user_id]["status_msg_id"] = status_msg.message_id

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
        action, uid = query.data.split("|", 1)
        user_id = int(uid)
    except Exception:
        return

    data = upload_waiting.get(user_id)

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

        upload_waiting.pop(user_id, None)

    elif action == "pay_no":
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ Bukti transfer ditolak.\n\n"
                "Silakan upload ulang bukti transfer."
            )
        )

        await query.edit_message_text(
            "❌ Pembayaran ditolak."
        )
        
async def getid_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    getid_waiting.discard(update.effective_user.id)
    await update.message.reply_text("❌ /getid dibatalkan.")
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

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable is not set.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("adminvip",   adminvip))
    app.add_handler(CommandHandler("stats",      stats))
    app.add_handler(CommandHandler("resetstats", resetstats))
    app.add_handler(CommandHandler("ban",        ban))
    app.add_handler(CommandHandler("unban",      unban))
    app.add_handler(CommandHandler("banned",     banned))
    app.add_handler(CommandHandler("getid",      getid_start))
    app.add_handler(CommandHandler("cancel",     getid_cancel))
    app.add_handler(CallbackQueryHandler(approval_callback, pattern=r"^(izin|tolak)\|"))
    app.add_handler(
    CallbackQueryHandler(
            payment_admin_callback,
            pattern=r"^(pay_ok|pay_no)\|"
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
        payment_history_detail_callback,
        pattern=r"^history_"
    ))
    app.add_handler(
    CallbackQueryHandler(
        payment_history_delete_callback,
        pattern=r"^history_delete_"
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
        adminvip_toggle_preview_callback,
        pattern=r"^adminvip_toggle_preview$"
    ))
    app.add_handler(
    CallbackQueryHandler(
        vip1_callback,
        pattern=r"^vip_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
    bayar1_callback,
    pattern=r"^bayar_\d+$"
    ))
    app.add_handler(
    CallbackQueryHandler(
            upload_bukti_callback,
            pattern=r"^upload_bukti_\d+$"
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