
import asyncio
import os
import random
import sqlite3
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ---------- CONFIGURATION ----------

BOT_TOKEN = os.environ["BOT_TOKEN"]

BASE_DIR = Path(__file__).resolve().parent
WELCOME_IMAGE = BASE_DIR / "images" / "welcome.jpg"
RANDOM_IMAGE_DIR = BASE_DIR / "images" / "random"

# Render persistent disk mount path
DATA_DIR = Path(os.environ.get("DATA_DIR", "/var/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "bot.db"

INTERVAL_SECONDS = 2 * 60 * 60  # 2 hours

# First message: replace the placeholder with the exact Khmer welcome text.
WELCOME_CAPTION = """Welcome To G168-SPORT!

[PASTE YOUR ORIGINAL KHMER WELCOME TEXT HERE]"""

# Every scheduled message uses this same caption.
REPEAT_CAPTION = """Welcome To 855GOAL

855GOAL Update —

🌐 Website: <a href="https://heylink.me/855goal/">https://heylink.me/855goal/</a>
📢 Channel: <a href="https://t.me/GOALWIN855">https://t.me/GOALWIN855</a>
💬 Contact: <a href="https://t.me/Game855GOAL">https://t.me/Game855GOAL</a>

Send /stop to stop automatic messages."""

WELCOME_BUTTONS = InlineKeyboardMarkup([
    [InlineKeyboardButton(
        "💬 DM NOW", url="https://t.me/Game855GOAL"
    )],
    [InlineKeyboardButton(
        "🌐 WEBSITE", url="https://heylink.me/855goal/"
    )],
    [InlineKeyboardButton(
        "📢 CHANNEL UPDATE", url="https://t.me/GOALWIN855"
    )],
])


# ---------- DATABASE ----------

def connect_db():
    return sqlite3.connect(DB_PATH)


def init_db():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id INTEGER PRIMARY KEY,
                next_send_at REAL NOT NULL,
                last_image TEXT
            )
        """)


def subscribe(user_id):
    # A new /start begins a fresh 2-hour schedule.
    with connect_db() as db:
        db.execute("""
            INSERT INTO subscribers (user_id, next_send_at, last_image)
            VALUES (?, ?, NULL)
            ON CONFLICT(user_id) DO UPDATE SET
                next_send_at = excluded.next_send_at,
                last_image = NULL
        """, (user_id, time.time() + INTERVAL_SECONDS))


def unsubscribe(user_id):
    with connect_db() as db:
        db.execute(
            "DELETE FROM subscribers WHERE user_id = ?",
            (user_id,),
        )


def get_due_subscribers():
    with connect_db() as db:
        return db.execute("""
            SELECT user_id, last_image
            FROM subscribers
            WHERE next_send_at <= ?
        """, (time.time(),)).fetchall()


def schedule_next(user_id, image_path):
    with connect_db() as db:
        db.execute("""
            UPDATE subscribers
            SET next_send_at = ?, last_image = ?
            WHERE user_id = ?
        """, (time.time() + INTERVAL_SECONDS,
              str(image_path), user_id))


# ---------- IMAGES ----------

def get_random_image(last_image=None):
    images = [
        p for p in RANDOM_IMAGE_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ] if RANDOM_IMAGE_DIR.exists() else []

    if not images:
        return None

    # Avoid sending the same image twice in a row when possible.
    alternatives = [
        image for image in images
        if str(image) != last_image
    ]
    return random.choice(alternatives or images)


# ---------- COMMANDS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not user or not update.effective_message:
        return

    if not WELCOME_IMAGE.is_file():
        await update.effective_message.reply_text(
            "The welcome image is missing. Please contact the bot administrator."
        )
        return

    subscribe(user.id)

    await update.effective_message.reply_photo(
        photo=WELCOME_IMAGE.open("rb"),
        caption=WELCOME_CAPTION,
        reply_markup=WELCOME_BUTTONS,
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user:
        unsubscribe(user.id)
        await update.effective_message.reply_text(
            "Automatic messages have been stopped. Send /start to subscribe again."
        )


# ---------- REPEATING SCHEDULER ----------

async def scheduled_messages(application: Application):
    while True:
        try:
            for user_id, last_image in get_due_subscribers():
                image_path = get_random_image(last_image)

                if image_path is None:
                    # Try again in 10 minutes if no images are available.
                    with connect_db() as db:
                        db.execute("""
                            UPDATE subscribers
                            SET next_send_at = ?
                            WHERE user_id = ?
                        """, (time.time() + 600, user_id))
                    continue

                try:
                    with image_path.open("rb") as photo:
                        await application.bot.send_photo(
                            chat_id=user_id,
                            photo=photo,
                            caption=REPEAT_CAPTION,
                            parse_mode="HTML",
                        )

                    schedule_next(user_id, image_path)

                except TelegramError as error:
                    # Keep the subscription and retry in 10 minutes.
                    print(f"Could not message {user_id}: {error}")
                    with connect_db() as db:
                        db.execute("""
                            UPDATE subscribers
                            SET next_send_at = ?
                            WHERE user_id = ?
                        """, (time.time() + 600, user_id))

        except Exception as error:
            print(f"Scheduler error: {error}")

        # Check for due messages every 30 seconds.
        await asyncio.sleep(30)


async def post_init(application: Application):
    init_db()
    application.bot_data["scheduler_task"] = asyncio.create_task(
        scheduled_messages(application)
    )


async def post_shutdown(application: Application):
    task = application.bot_data.get("scheduler_task")

    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def main():
    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))

    print("855GOAL bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
