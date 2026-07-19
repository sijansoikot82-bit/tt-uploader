#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import csv
import html
import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from pyrogram import Client as PyroClient
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================================
# CONFIG
# =========================================================
BOT_TOKEN = "8069267100:AAG2hMn2B05NNOLqsYO5lNIcwh3_jlCjkvw"
OWNER_ID = 6741820113

# Required for Pyrogram
PYRO_API_ID = 39137783
PYRO_API_HASH = "9c88a76da31f95e28a7e440f8e75395a"

BASE_DIR = Path("data")
APPROVALS_FILE = BASE_DIR / "approvals.json"
COOKIES_FILE = BASE_DIR / "cookies.txt"

BOT_TITLE = "TT : XPEOM UPLOADER"
BOT_SUBTITLE = "Premium TikTok publishing panel"

METHOD_UPLOAD_URL = "https://method.itzcrih.it/upload"
METHOD_DOWNLOAD_BASE = "https://method.itzcrih.it/download"

if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE":
    raise SystemExit("BOT_TOKEN is missing")
if OWNER_ID <= 0:
    raise SystemExit("OWNER_ID is missing or invalid")
if not PYRO_API_ID or PYRO_API_ID == 123456:
    raise SystemExit("PYRO_API_ID is missing or invalid")
if not PYRO_API_HASH or PYRO_API_HASH == "PASTE_YOUR_API_HASH_HERE":
    raise SystemExit("PYRO_API_HASH is missing")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("xpeom-uploader")

# =========================================================
# FILE HELPERS
# =========================================================
def ensure_dirs() -> None:
    BASE_DIR.mkdir(exist_ok=True)
    if not COOKIES_FILE.exists():
        COOKIES_FILE.write_text("", encoding="utf-8")


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default.copy()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default.copy()


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def approvals_data() -> Dict[str, Any]:
    data = load_json(APPROVALS_FILE, {"allowed_users": [OWNER_ID]})
    data.setdefault("allowed_users", [])
    if OWNER_ID not in data["allowed_users"]:
        data["allowed_users"].append(OWNER_ID)
    return data


def save_approvals(data: Dict[str, Any]) -> None:
    data.setdefault("allowed_users", [])
    if OWNER_ID not in data["allowed_users"]:
        data["allowed_users"].append(OWNER_ID)
    save_json(APPROVALS_FILE, data)


def load_cookie_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not COOKIES_FILE.exists():
        return rows

    with COOKIES_FILE.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="|")
        for row in reader:
            if not row:
                continue
            while len(row) < 4:
                row.append("")
            rows.append(
                {
                    "telegram_id": row[0].strip(),
                    "zernio_api_key": row[1].strip(),
                    "tiktok_account_id": row[2].strip(),
                    "timezone": row[3].strip() or "Asia/Dhaka",
                }
            )
    return rows


def save_cookie_rows(rows: list[dict[str, str]]) -> None:
    with COOKIES_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="|")
        for row in rows:
            writer.writerow(
                [
                    row.get("telegram_id", ""),
                    row.get("zernio_api_key", ""),
                    row.get("tiktok_account_id", ""),
                    row.get("timezone", "Asia/Dhaka"),
                ]
            )


def ensure_user_row(user_id: int) -> dict[str, str]:
    rows = load_cookie_rows()
    for row in rows:
        if row.get("telegram_id") == str(user_id):
            row.setdefault("timezone", "Asia/Dhaka")
            save_cookie_rows(rows)
            return row

    row = {
        "telegram_id": str(user_id),
        "zernio_api_key": "",
        "tiktok_account_id": "",
        "timezone": "Asia/Dhaka",
    }
    rows.append(row)
    save_cookie_rows(rows)
    return row


def get_user_record(user_id: int) -> Dict[str, str]:
    rows = load_cookie_rows()
    for row in rows:
        if row.get("telegram_id") == str(user_id):
            row.setdefault("timezone", "Asia/Dhaka")
            return row
    return {
        "telegram_id": str(user_id),
        "zernio_api_key": "",
        "tiktok_account_id": "",
        "timezone": "Asia/Dhaka",
    }


def set_user_field(user_id: int, field: str, value: str) -> Dict[str, str]:
    rows = load_cookie_rows()
    found = False
    for row in rows:
        if row.get("telegram_id") == str(user_id):
            row[field] = value
            row.setdefault("timezone", "Asia/Dhaka")
            found = True
            break

    if not found:
        row = {
            "telegram_id": str(user_id),
            "zernio_api_key": "",
            "tiktok_account_id": "",
            "timezone": "Asia/Dhaka",
        }
        row[field] = value
        rows.append(row)

    save_cookie_rows(rows)
    return get_user_record(user_id)


def make_temp_work_dir(user_id: int) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"xpeom_{user_id}_"))


def cleanup_path(path: Optional[Path]) -> None:
    if not path:
        return
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)
    except Exception:
        pass


ensure_dirs()
approvals = approvals_data()
save_approvals(approvals)
ensure_user_row(OWNER_ID)

# =========================================================
# PYROGRAM CLIENT
# =========================================================
pyro_client = PyroClient(
    "xpeom_helper",
    api_id=PYRO_API_ID,
    api_hash=PYRO_API_HASH,
    bot_token=BOT_TOKEN,
)


async def pyro_post_init(app: Application) -> None:
    await pyro_client.start()


async def pyro_post_shutdown(app: Application) -> None:
    try:
        await pyro_client.stop()
    except Exception:
        pass

# =========================================================
# AUTH
# =========================================================
def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def is_allowed(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in set(approvals.get("allowed_users", []))


async def safe_delete_message(message: Optional[Message]) -> None:
    if not message:
        return
    try:
        await message.delete()
    except Exception:
        pass


async def notify_owner_access_request(context: ContextTypes.DEFAULT_TYPE, update: Update) -> None:
    user = update.effective_user
    if not user:
        return

    username = f"@{user.username}" if user.username else "(no username)"
    text = (
        f"🔐 <b>Access request</b>\n\n"
        f"User ID: <code>{user.id}</code>\n"
        f"Name: {html.escape(user.full_name)}\n"
        f"Username: {html.escape(username)}\n\n"
        f"Approve this user?"
    )
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{user.id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"deny:{user.id}"),
            ]
        ]
    )
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )

# =========================================================
# MENU HELPERS
# =========================================================
def current_menu(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("current_menu", "main")


def set_current_menu(context: ContextTypes.DEFAULT_TYPE, menu: str) -> None:
    context.user_data["current_menu"] = menu


def push_menu(context: ContextTypes.DEFAULT_TYPE, menu: str) -> None:
    stack = context.user_data.setdefault("menu_stack", [])
    cur = current_menu(context)
    if cur and cur != menu:
        stack.append(cur)


def pop_menu(context: ContextTypes.DEFAULT_TYPE) -> str:
    stack = context.user_data.setdefault("menu_stack", [])
    if stack:
        return stack.pop()
    return "main"


def clear_navigation(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["menu_stack"] = []


def set_pending(context: ContextTypes.DEFAULT_TYPE, action: str, **kwargs: Any) -> None:
    data = {"type": action}
    data.update(kwargs)
    context.user_data["pending_action"] = data


def get_pending(context: ContextTypes.DEFAULT_TYPE) -> Optional[Dict[str, Any]]:
    return context.user_data.get("pending_action")


def clear_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("pending_action", None)


def clear_upload(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("upload_state", None)


def clear_prompt_refs(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("media_prompt_message_id", None)
    context.user_data.pop("caption_prompt_message_id", None)


def clear_workflow(context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_pending(context)
    clear_upload(context)


def main_menu_keyboard(is_owner_user: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📤 Upload", callback_data="nav:upload")],
        [InlineKeyboardButton("🔧 Manage API", callback_data="nav:manage_api")],
        [InlineKeyboardButton("ℹ️ Status", callback_data="nav:status")],
        [InlineKeyboardButton("❓ Help", callback_data="nav:help")],
    ]
    if is_owner_user:
        rows.append([InlineKeyboardButton("🛠 Owner Panel", callback_data="nav:admin")])
    return InlineKeyboardMarkup(rows)


def upload_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🖼 Photo", callback_data="nav:upload_photo")],
            [InlineKeyboardButton("🎥 Video", callback_data="nav:upload_video")],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="nav:back"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="nav:main"),
            ],
        ]
    )


def manage_api_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Set API Key", callback_data="nav:api_setkey")],
            [InlineKeyboardButton("➖ Remove API Key", callback_data="nav:api_rmkey")],
            [InlineKeyboardButton("🎯 Set Account ID", callback_data="nav:api_setaccount")],
            [InlineKeyboardButton("🧹 Remove Account ID", callback_data="nav:api_rmaccount")],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="nav:back"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="nav:main"),
            ],
        ]
    )


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👥 Users List", callback_data="nav:admin_users")],
            [InlineKeyboardButton("⚙️ Show Config", callback_data="nav:admin_status")],
            [InlineKeyboardButton("➕ Allow User", callback_data="nav:admin_allow")],
            [InlineKeyboardButton("➖ Deny User", callback_data="nav:admin_deny")],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="nav:back"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="nav:main"),
            ],
        ]
    )


def caption_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏭ Skip Caption", callback_data="nav:skip_caption")],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="nav:back"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="nav:main"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="nav:cancel")],
        ]
    )


def render_menu(menu: str, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[str, InlineKeyboardMarkup]:
    is_owner_user = is_owner(user_id)
    ucfg = get_user_record(user_id)
    display_name = html.escape(context.user_data.get("display_name", "User"))

    if menu == "main":
        text = (
            f"🤖 <b>TT : XPEOM UPLOADER</b>\n\n"
            f"Welcome, <b>{display_name}</b>. 🤍✨\n\n"
            f"Choose an option below.\n"
            f"Use the buttons only — everything is arranged inside the panel.\n\n"
            f"Developer : @Soikat69x ✅"
        )
        return text, main_menu_keyboard(is_owner_user)

    if menu == "upload":
        text = (
            f"📤 <b>Upload Panel</b>\n\n"
            f"Choose Photo or Video first.\n"
            f"You can send the selected file as normal media or as a document.\n\n"
            f"The bot will then ask for the caption."
        )
        return text, upload_menu_keyboard()

    if menu == "manage_api":
        text = (
            f"🔧 <b>Manage API</b>\n\n"
            f"API Key: {'✅ set' if ucfg.get('zernio_api_key') else '❌ missing'}\n"
            f"Account ID: {'✅ set' if ucfg.get('tiktok_account_id') else '❌ missing'}\n\n"
            f"Use the buttons below to add or remove your own data."
        )
        return text, manage_api_keyboard()

    if menu == "status":
        if is_owner_user:
            text = (
                f"ℹ️ <b>Status</b>\n\n"
                f"Telegram ID: <code>{user_id}</code>\n"
                f"API Key: {'✅ set' if ucfg.get('zernio_api_key') else '❌ missing'}\n"
                f"Account ID: {'✅ set' if ucfg.get('tiktok_account_id') else '❌ missing'}\n"
                f"Timezone: <code>{html.escape(ucfg.get('timezone', 'Asia/Dhaka'))}</code>\n"
                f"Approved Users: <code>{len(set(approvals.get('allowed_users', [])))}</code>"
            )
        else:
            text = (
                f"ℹ️ <b>Status</b>\n\n"
                f"Telegram ID: <code>{user_id}</code>\n"
                f"API Key: {'✅ set' if ucfg.get('zernio_api_key') else '❌ missing'}\n"
                f"Account ID: {'✅ set' if ucfg.get('tiktok_account_id') else '❌ missing'}\n"
                f"Timezone: <code>{html.escape(ucfg.get('timezone', 'Asia/Dhaka'))}</code>"
            )
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="nav:main")]])

    if menu == "help":
        text = (
            f"❓ <b>Help</b>\n\n"
            f"1) Open Upload\n"
            f"2) Pick Photo or Video\n"
            f"3) Send the media\n"
            f"4) Send caption or skip it\n"
            f"5) The bot publishes through Zernio\n\n"
            f"Use Back or Main Menu anytime."
        )
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="nav:main")]])

    if menu == "admin":
        text = (
            f"🛠 <b>Owner Panel</b>\n\n"
            f"Visible only to the owner.\n"
            f"You can manage access from here."
        )
        return text, admin_menu_keyboard()

    if menu == "admin_users":
        ids = sorted(set(approvals.get("allowed_users", [])))
        rows = load_cookie_rows()
        row_map = {r["telegram_id"]: r for r in rows}
        lines = []
        for uid in ids:
            rec = row_map.get(
                str(uid),
                {"zernio_api_key": "", "tiktok_account_id": "", "timezone": "Asia/Dhaka"},
            )
            lines.append(
                f"• <code>{uid}</code> | key: {'yes' if rec.get('zernio_api_key') else 'no'} | acct: {'yes' if rec.get('tiktok_account_id') else 'no'}"
            )
        if not lines:
            lines = ["No approved users."]
        text = "👥 <b>Approved Users</b>\n\n" + "\n".join(lines)
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="nav:main")]])

    if menu == "admin_status":
        text = (
            f"⚙️ <b>Owner Config</b>\n\n"
            f"Your Telegram ID: <code>{OWNER_ID}</code>\n"
            f"API Key: {'✅ set' if ucfg.get('zernio_api_key') else '❌ missing'}\n"
            f"Account ID: {'✅ set' if ucfg.get('tiktok_account_id') else '❌ missing'}\n"
            f"Timezone: <code>{html.escape(ucfg.get('timezone', 'Asia/Dhaka'))}</code>\n"
            f"Total Approved Users: <code>{len(set(approvals.get('allowed_users', [])))}</code>"
        )
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="nav:main")]])

    if menu == "api_wait_key":
        return "🔑 <b>Set API Key</b>\n\nSend your Zernio API key now.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="nav:cancel")]]
        )

    if menu == "api_wait_account":
        return "🎯 <b>Set Account ID</b>\n\nSend your Zernio/TikTok account ID now.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="nav:cancel")]]
        )

    if menu == "upload_wait_media":
        expected = context.user_data.get("upload_state", {}).get("expected_kind", "media")
        text = (
            f"📎 <b>Waiting for {html.escape(str(expected))}</b>\n\n"
            f"Send your file now.\n"
            f"If you chose Photo or Video, a document is also accepted.\n\n"
            f"You can cancel anytime."
        )
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="nav:cancel")]])

    if menu == "upload_wait_caption":
        text = (
            f"✍️ <b>Caption</b>\n\n"
            f"Now send the caption for this post.\n"
            f"You can also skip caption and publish directly."
        )
        return text, caption_keyboard()

    if menu == "admin_wait_allow":
        return "➕ <b>Allow User</b>\n\nSend the Telegram numeric user ID you want to approve.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="nav:cancel")]]
        )

    if menu == "admin_wait_deny":
        return "➖ <b>Deny User</b>\n\nSend the Telegram numeric user ID you want to remove.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="nav:cancel")]]
        )

    return render_menu("main", user_id, context)


async def present_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, menu: str, *, edit: bool = False) -> Optional[Message]:
    user = update.effective_user
    if not user:
        return None

    text, kb = render_menu(menu, user.id, context)

    if edit and update.callback_query:
        message = await update.callback_query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    else:
        message = await context.bot.send_message(
            chat_id=user.id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    set_current_menu(context, menu)
    return message

# =========================================================
# TELEGRAM FILE HELPERS
# =========================================================
def build_public_media_url(file_path: str) -> str:
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"


def telegram_get_file(file_id: str) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile"
    r = requests.get(url, params={"file_id": file_id}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getFile failed: {data}")
    return data["result"]


def fetch_url_size(url: str) -> int:
    total = 0
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                total += len(chunk)
    return total


def resolve_photo_public_url(file_id: str) -> Tuple[str, int]:
    result = telegram_get_file(file_id)
    file_path = result["file_path"]
    file_url = build_public_media_url(file_path)
    file_size = result.get("file_size")
    if file_size is None or int(file_size) <= 0:
        file_size = fetch_url_size(file_url)
    else:
        file_size = int(file_size)
    return file_url, file_size

# =========================================================
# MEDIA PARSING
# =========================================================
def media_from_message(update: Update, expected_kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    msg = update.effective_message
    if not msg:
        return None

    if msg.photo:
        photo = msg.photo[-1]
        return {
            "kind": "photo",
            "file_id": photo.file_id,
            "filename": "photo.jpg",
            "mime_type": "image/jpeg",
            "file_size": int(photo.file_size or 0),
        }

    if msg.video:
        video = msg.video
        return {
            "kind": "video",
            "file_id": video.file_id,
            "filename": video.file_name or "video.mp4",
            "mime_type": video.mime_type or "video/mp4",
            "file_size": int(video.file_size or 0),
        }

    if msg.document:
        doc = msg.document
        doc_mime = (doc.mime_type or "").lower()
        if expected_kind == "photo":
            kind = "photo"
            mime = doc_mime if doc_mime.startswith("image/") else "image/jpeg"
            filename = doc.file_name or "photo.jpg"
        elif expected_kind == "video":
            kind = "video"
            mime = doc_mime if doc_mime.startswith("video/") else "video/mp4"
            filename = doc.file_name or "video.mp4"
        else:
            if doc_mime.startswith("image/"):
                kind = "photo"
            elif doc_mime.startswith("video/"):
                kind = "video"
            else:
                kind = "document"
            mime = doc.mime_type or "application/octet-stream"
            filename = doc.file_name or "file.bin"

        return {
            "kind": kind,
            "file_id": doc.file_id,
            "filename": filename,
            "mime_type": mime,
            "file_size": int(doc.file_size or 0),
        }

    return None

# =========================================================
# METHOD.UPLOAD / DOWNLOAD
# =========================================================
METHOD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
    "Origin": "https://method.itzcrih.it",
    "Referer": "https://method.itzcrih.it/",
}


def method_upload_video(input_path: Path) -> str:
    with input_path.open("rb") as f:
        r = requests.post(
            METHOD_UPLOAD_URL,
            headers=METHOD_HEADERS,
            files={"video": (input_path.name, f, "video/mp4")},
            data={"encoding": "false"},
            timeout=300,
        )

    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"Method upload failed: {data}")

    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(f"Method upload did not return task_id: {data}")

    return str(task_id)


def method_download_video(task_id: str, out_path: Path) -> Path:
    url = f"{METHOD_DOWNLOAD_BASE}/{task_id}"
    headers = {
        "User-Agent": METHOD_HEADERS["User-Agent"],
        "Referer": "https://method.itzcrih.it/",
        "Accept-Encoding": "identity",
    }

    with requests.get(url, headers=headers, stream=True, timeout=300) as r:
        r.raise_for_status()
        with out_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return out_path


async def pyro_download_media(file_id: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = await pyro_client.download_media(file_id, file_name=str(out_path))
    if not downloaded:
        raise RuntimeError("Pyrogram failed to download media")
    return Path(downloaded)

# =========================================================
# MEDIA PREPARATION
# =========================================================
async def prepare_media_via_method(media: Dict[str, Any], work_dir: Path) -> Dict[str, Any]:
    """
    Photo:
      - direct Telegram public file URL (no processing)
    Video:
      - download using Pyrogram (supports big files)
      - upload to method.itzcrih.it
      - download processed output locally
      - use method download URL directly for Zernio
    """
    if media["kind"] != "video":
        file_url, file_size = resolve_photo_public_url(media["file_id"])
        media["file_url"] = file_url
        media["file_size"] = int(file_size)
        media["mime_type"] = media.get("mime_type") or "image/jpeg"
        return media

    input_path = work_dir / f"in_{media['file_id']}_{media['filename']}"
    processed_path = work_dir / f"method_{media['file_id']}.mp4"

    downloaded = await pyro_download_media(media["file_id"], input_path)
    task_id = await asyncio.to_thread(method_upload_video, downloaded)
    await asyncio.to_thread(method_download_video, task_id, processed_path)

    media["file_url"] = f"{METHOD_DOWNLOAD_BASE}/{task_id}"
    media["local_path"] = str(processed_path)
    media["filename"] = processed_path.name
    media["mime_type"] = "video/mp4"
    media["file_size"] = processed_path.stat().st_size
    media["method_task_id"] = task_id
    return media

# =========================================================
# ZERNIO
# =========================================================
def zernio_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://zernio.com",
        "Referer": "https://zernio.com/dashboard/posts-all",
    }


def publish_to_zernio(
    api_key: str,
    account_id: str,
    caption: str,
    media_url: str,
    filename: str,
    mime_type: str,
    media_kind: str,
    file_size: int,
    timezone_name: str,
) -> Dict[str, Any]:
    if not isinstance(file_size, int) or file_size <= 0:
        raise ValueError("file_size must be a positive integer")

    post_url = "https://zernio.com/api/v1/posts"
    tiktok_media_type = "photo" if media_kind == "photo" else "video"
    media_item_type = "image" if tiktok_media_type == "photo" else "video"

    payload = {
        "content": caption,
        "scheduledFor": datetime.now(timezone.utc).isoformat(),
        "publishNow": True,
        "isDraft": False,
        "timezone": timezone_name,
        "mediaItems": [
            {
                "type": media_item_type,
                "url": media_url,
                "filename": filename,
                "size": file_size,
                "mimeType": mime_type,
            }
        ],
        "tags": [],
        "hashtags": [],
        "mentions": [],
        "visibility": "public",
        "crosspostingEnabled": True,
        "platforms": [
            {
                "platform": "tiktok",
                "accountId": account_id,
                "customContent": caption,
                "customMedia": [],
                "platformSpecificData": {
                    "tiktokSettings": {
                        "privacy_level": "PUBLIC_TO_EVERYONE",
                        "allow_comment": True,
                        "allow_duet": True,
                        "allow_stitch": True,
                        "commercial_content_type": "none",
                        "brand_partner_promote": False,
                        "is_brand_organic_post": False,
                        "content_preview_confirmed": True,
                        "express_consent_given": True,
                        "media_type": tiktok_media_type,
                        "auto_add_music": False,
                        "description": caption,
                        "draft": False,
                    }
                },
            }
        ],
    }

    r = requests.post(post_url, headers=zernio_headers(api_key), json=payload, timeout=120)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    if r.status_code >= 400:
        raise RuntimeError(f"Zernio error {r.status_code}: {data}")

    return data

# =========================================================
# MENU ACTIONS
# =========================================================
async def show_main(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    clear_workflow(context)
    clear_navigation(context)
    set_current_menu(context, "main")
    await present_menu(update, context, "main", edit=edit)


async def show_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    clear_workflow(context)
    push_menu(context, "upload")
    set_current_menu(context, "upload")
    await present_menu(update, context, "upload", edit=edit)


async def show_manage_api(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    clear_workflow(context)
    push_menu(context, "manage_api")
    set_current_menu(context, "manage_api")
    await present_menu(update, context, "manage_api", edit=edit)


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    clear_workflow(context)
    push_menu(context, "status")
    set_current_menu(context, "status")
    await present_menu(update, context, "status", edit=edit)


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    clear_workflow(context)
    push_menu(context, "help")
    set_current_menu(context, "help")
    await present_menu(update, context, "help", edit=edit)


async def show_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    clear_workflow(context)
    push_menu(context, "admin")
    set_current_menu(context, "admin")
    await present_menu(update, context, "admin", edit=edit)


async def show_admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    clear_workflow(context)
    push_menu(context, "admin_users")
    set_current_menu(context, "admin_users")
    await present_menu(update, context, "admin_users", edit=edit)


async def show_admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    clear_workflow(context)
    push_menu(context, "admin_status")
    set_current_menu(context, "admin_status")
    await present_menu(update, context, "admin_status", edit=edit)


async def prompt_api_input(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, *, edit: bool = False) -> None:
    clear_upload(context)
    set_pending(context, kind)
    menu_name = {
        "await_api_key": "api_wait_key",
        "await_account_id": "api_wait_account",
        "await_allow_user": "admin_wait_allow",
        "await_deny_user": "admin_wait_deny",
    }[kind]
    push_menu(context, menu_name)
    set_current_menu(context, menu_name)
    await present_menu(update, context, menu_name, edit=edit)


async def prompt_upload_media(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, *, edit: bool = False) -> None:
    clear_workflow(context)
    context.user_data["upload_state"] = {"expected_kind": kind, "media": None}
    set_pending(context, "await_media", expected_kind=kind)
    push_menu(context, "upload_wait_media")
    set_current_menu(context, "upload_wait_media")
    msg = await present_menu(update, context, "upload_wait_media", edit=edit)
    if msg:
        context.user_data["media_prompt_message_id"] = msg.message_id


async def prompt_upload_caption(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    set_pending(context, "await_caption")
    push_menu(context, "upload_wait_caption")
    set_current_menu(context, "upload_wait_caption")
    msg = await present_menu(update, context, "upload_wait_caption", edit=edit)
    if msg:
        context.user_data["caption_prompt_message_id"] = msg.message_id


async def delete_media_prompt(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    mid = context.user_data.pop("media_prompt_message_id", None)
    if mid:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=int(mid))
        except Exception:
            pass


async def delete_caption_prompt(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    mid = context.user_data.pop("caption_prompt_message_id", None)
    if mid:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=int(mid))
        except Exception:
            pass


async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_workflow(context)
    prev = pop_menu(context)
    set_current_menu(context, prev)
    await present_menu(update, context, prev, edit=True)


async def go_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_workflow(context)
    clear_navigation(context)
    set_current_menu(context, "main")
    await present_menu(update, context, "main", edit=True)


async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    clear_workflow(context)
    clear_navigation(context)
    clear_prompt_refs(context)
    set_current_menu(context, "main")
    if user:
        await delete_media_prompt(context, user.id)
        await delete_caption_prompt(context, user.id)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text("🛑 Cancelled.")
        except Exception:
            pass
    await show_main(update, context, edit=False)

# =========================================================
# PUBLISH FLOW
# =========================================================
async def publish_current_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, caption: str) -> None:
    user = update.effective_user
    if not user:
        return

    up = context.user_data.get("upload_state", {})
    media = up.get("media")
    if not media:
        clear_workflow(context)
        clear_navigation(context)
        await context.bot.send_message(chat_id=user.id, text="Session expired. Use /start again.")
        await show_main(update, context, edit=False)
        return

    ucfg = get_user_record(user.id)
    api_key = ucfg.get("zernio_api_key", "").strip()
    account_id = ucfg.get("tiktok_account_id", "").strip()
    timezone_name = ucfg.get("timezone", "Asia/Dhaka")

    progress_msg = None
    temp_dir: Optional[Path] = None
    try:
        progress_msg = await context.bot.send_message(
            chat_id=user.id,
            text="⏳ Processing media...\n🔄 Preparing the file",
        )

        temp_dir = make_temp_work_dir(user.id)
        prepared = await prepare_media_via_method(media, temp_dir)

        try:
            await progress_msg.edit_text("⏳ Publishing to Zernio...\n🚀 Please wait.")
        except Exception:
            pass

        result = await asyncio.to_thread(
            publish_to_zernio,
            api_key,
            account_id,
            caption,
            prepared["file_url"],
            prepared["filename"],
            prepared["mime_type"],
            prepared["kind"],
            int(prepared["file_size"]),
            timezone_name,
        )

        post = result.get("post", {})
        post_id = post.get("_id", "unknown")
        status = post.get("status", "unknown")

        clear_workflow(context)
        clear_navigation(context)
        clear_prompt_refs(context)

        await safe_delete_message(progress_msg)

        await context.bot.send_message(
            chat_id=user.id,
            text=(
                f"✅ <b>Published successfully</b>\n\n"
                f"Post ID: <code>{html.escape(str(post_id))}</code>\n"
                f"Status: <code>{html.escape(str(status))}</code>"
            ),
            parse_mode=ParseMode.HTML,
        )
        await show_main(update, context, edit=False)

    except Exception as e:
        log.exception("Publish failed")
        clear_workflow(context)
        clear_navigation(context)
        clear_prompt_refs(context)

        await safe_delete_message(progress_msg)

        await context.bot.send_message(chat_id=user.id, text=f"❌ Failed: {e}")
        await show_main(update, context, edit=False)

    finally:
        cleanup_path(temp_dir)

# =========================================================
# BUTTON ROUTER
# =========================================================
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return

    await q.answer()
    user = q.from_user
    if not user:
        return

    context.user_data["display_name"] = user.full_name
    data = q.data or ""

    if data.startswith("approve:") or data.startswith("deny:"):
        if not is_owner(user.id):
            await q.edit_message_text("Owner only.")
            return

        action, uid_str = data.split(":", 1)
        uid = int(uid_str)
        approvals.setdefault("allowed_users", [])

        if action == "approve":
            if uid not in approvals["allowed_users"]:
                approvals["allowed_users"].append(uid)
                save_approvals(approvals)
            ensure_user_row(uid)
            await q.edit_message_text(f"✅ Approved user <code>{uid}</code>", parse_mode=ParseMode.HTML)
            try:
                await context.bot.send_message(chat_id=uid, text="✅ Your access request has been approved.")
            except Exception:
                pass
            return

        if action == "deny":
            approvals["allowed_users"] = [x for x in approvals["allowed_users"] if x != uid]
            save_approvals(approvals)
            await q.edit_message_text(f"❌ Denied user <code>{uid}</code>", parse_mode=ParseMode.HTML)
            try:
                await context.bot.send_message(chat_id=uid, text="❌ Your access request was denied.")
            except Exception:
                pass
            return

    if not is_allowed(user.id):
        await q.edit_message_text("You are not allowed to use this bot.")
        return

    if data == "nav:main":
        await go_main(update, context)
        return

    if data == "nav:back":
        await go_back(update, context)
        return

    if data == "nav:cancel":
        await cancel_flow(update, context)
        return

    if data == "nav:skip_caption":
        pending = get_pending(context)
        if pending and pending.get("type") == "await_caption":
            await delete_caption_prompt(context, user.id)
            await publish_current_upload(update, context, caption="")
            return
        await q.edit_message_text("Nothing to skip.")
        return

    if data == "nav:upload":
        await show_upload(update, context, edit=True)
        return

    if data == "nav:manage_api":
        await show_manage_api(update, context, edit=True)
        return

    if data == "nav:status":
        await show_status(update, context, edit=True)
        return

    if data == "nav:help":
        await show_help(update, context, edit=True)
        return

    if data == "nav:admin":
        if not is_owner(user.id):
            await q.edit_message_text("Owner only.")
            return
        await show_admin(update, context, edit=True)
        return

    if data == "nav:upload_photo":
        await prompt_upload_media(update, context, "photo", edit=True)
        return

    if data == "nav:upload_video":
        await prompt_upload_media(update, context, "video", edit=True)
        return

    if data == "nav:api_setkey":
        await prompt_api_input(update, context, "await_api_key", edit=True)
        return

    if data == "nav:api_rmkey":
        set_user_field(user.id, "zernio_api_key", "")
        await show_manage_api(update, context, edit=True)
        return

    if data == "nav:api_setaccount":
        await prompt_api_input(update, context, "await_account_id", edit=True)
        return

    if data == "nav:api_rmaccount":
        set_user_field(user.id, "tiktok_account_id", "")
        await show_manage_api(update, context, edit=True)
        return

    if data == "nav:admin_users":
        if not is_owner(user.id):
            await q.edit_message_text("Owner only.")
            return
        await show_admin_users(update, context, edit=True)
        return

    if data == "nav:admin_status":
        if not is_owner(user.id):
            await q.edit_message_text("Owner only.")
            return
        await show_admin_status(update, context, edit=True)
        return

    if data == "nav:admin_allow":
        if not is_owner(user.id):
            await q.edit_message_text("Owner only.")
            return
        await prompt_api_input(update, context, "await_allow_user", edit=True)
        return

    if data == "nav:admin_deny":
        if not is_owner(user.id):
            await q.edit_message_text("Owner only.")
            return
        await prompt_api_input(update, context, "await_deny_user", edit=True)
        return

    await q.edit_message_text("Unknown action.")

# =========================================================
# TEXT HANDLER
# =========================================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    context.user_data["display_name"] = user.full_name

    if not is_allowed(user.id):
        await msg.reply_text("You are not approved to use this bot.")
        await notify_owner_access_request(context, update)
        return

    pending = get_pending(context)
    text = (msg.text or "").strip()

    if not pending:
        if text.startswith("/"):
            return
        await msg.reply_text("Use /start to open the menu.")
        return

    ptype = pending.get("type")

    if ptype == "await_api_key":
        if not text:
            await msg.reply_text("Send a valid API key.")
            return
        set_user_field(user.id, "zernio_api_key", text)
        ensure_user_row(user.id)
        clear_workflow(context)
        clear_navigation(context)
        await msg.reply_text("✅ API key saved.")
        await show_manage_api(update, context, edit=False)
        return

    if ptype == "await_account_id":
        if not text:
            await msg.reply_text("Send a valid account ID.")
            return
        set_user_field(user.id, "tiktok_account_id", text)
        ensure_user_row(user.id)
        clear_workflow(context)
        clear_navigation(context)
        await msg.reply_text("✅ Account ID saved.")
        await show_manage_api(update, context, edit=False)
        return

    if ptype == "await_allow_user":
        if not text.isdigit():
            await msg.reply_text("Send a numeric Telegram user ID.")
            return
        uid = int(text)
        approvals.setdefault("allowed_users", [])
        if uid not in approvals["allowed_users"]:
            approvals["allowed_users"].append(uid)
            save_approvals(approvals)
        ensure_user_row(uid)
        clear_workflow(context)
        clear_navigation(context)
        await msg.reply_text(f"✅ Allowed user <code>{uid}</code>.", parse_mode=ParseMode.HTML)
        await show_admin(update, context, edit=False)
        return

    if ptype == "await_deny_user":
        if not text.isdigit():
            await msg.reply_text("Send a numeric Telegram user ID.")
            return
        uid = int(text)
        approvals.setdefault("allowed_users", [])
        approvals["allowed_users"] = [x for x in approvals["allowed_users"] if x != uid]
        save_approvals(approvals)
        clear_workflow(context)
        clear_navigation(context)
        await msg.reply_text(f"✅ Denied user <code>{uid}</code>.", parse_mode=ParseMode.HTML)
        await show_admin(update, context, edit=False)
        return

    if ptype == "await_caption":
        await delete_caption_prompt(context, user.id)
        await publish_current_upload(update, context, caption=text)
        return

# =========================================================
# MEDIA HANDLER
# =========================================================
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    context.user_data["display_name"] = user.full_name

    if not is_allowed(user.id):
        await msg.reply_text("You are not approved to use this bot.")
        await notify_owner_access_request(context, update)
        return

    pending = get_pending(context)
    if not pending or pending.get("type") != "await_media":
        return

    expected_kind = pending.get("expected_kind", "photo")
    media = media_from_message(update, expected_kind=expected_kind)

    if not media:
        await msg.reply_text("Please send photo, video, or document.")
        return

    if msg.document and expected_kind in ("photo", "video"):
        media["kind"] = expected_kind
        media["mime_type"] = "image/jpeg" if expected_kind == "photo" else "video/mp4"
        if expected_kind == "photo" and not media["filename"].lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            media["filename"] = media["filename"] or "photo.jpg"
        if expected_kind == "video" and not media["filename"].lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
            media["filename"] = media["filename"] or "video.mp4"

    try:
        media["file_size"] = int(media.get("file_size") or 0)
        context.user_data["upload_state"] = {
            "expected_kind": expected_kind,
            "media": media,
        }

        clear_pending(context)

        await delete_media_prompt(context, user.id)
        await prompt_upload_caption(update, context, edit=False)
    except Exception as e:
        clear_workflow(context)
        clear_navigation(context)
        await msg.reply_text(f"❌ Media processing failed: {e}")
        await show_main(update, context, edit=False)

# =========================================================
# COMMANDS
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return

    context.user_data["display_name"] = user.full_name

    if not is_allowed(user.id):
        await update.message.reply_text("You are not approved yet. Your request has been sent to the owner.")
        await notify_owner_access_request(context, update)
        return

    clear_workflow(context)
    clear_navigation(context)
    clear_prompt_refs(context)
    set_current_menu(context, "main")
    await present_menu(update, context, "main", edit=False)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return

    clear_workflow(context)
    clear_navigation(context)
    clear_prompt_refs(context)
    set_current_menu(context, "main")
    await update.message.reply_text("🛑 Cancelled.")
    await present_menu(update, context, "main", edit=False)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_allowed(update.effective_user.id):
        return
    context.user_data["display_name"] = update.effective_user.full_name
    clear_workflow(context)
    clear_navigation(context)
    set_current_menu(context, "help")
    await present_menu(update, context, "help", edit=False)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_allowed(update.effective_user.id):
        return
    context.user_data["display_name"] = update.effective_user.full_name
    clear_workflow(context)
    clear_navigation(context)
    set_current_menu(context, "status")
    await present_menu(update, context, "status", edit=False)


async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_owner(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /allow <telegram_user_id>")
        return
    uid = int(context.args[0])
    approvals.setdefault("allowed_users", [])
    if uid not in approvals["allowed_users"]:
        approvals["allowed_users"].append(uid)
        save_approvals(approvals)
    ensure_user_row(uid)
    await update.message.reply_text(f"✅ Allowed user {uid}")


async def deny_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_owner(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /deny <telegram_user_id>")
        return
    uid = int(context.args[0])
    approvals.setdefault("allowed_users", [])
    approvals["allowed_users"] = [x for x in approvals["allowed_users"] if x != uid]
    save_approvals(approvals)
    await update.message.reply_text(f"✅ Denied user {uid}")

# =========================================================
# MAIN
# =========================================================
def build_app() -> Application:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(pyro_post_init)
        .post_shutdown(pyro_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("allow", allow_cmd))
    app.add_handler(CommandHandler("deny", deny_cmd))

    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_media))

    return app


if __name__ == "__main__":
    ensure_dirs()
    save_approvals(approvals)
    ensure_user_row(OWNER_ID)

    app = build_app()
    log.info("Bot started")
    app.run_polling(close_loop=False)