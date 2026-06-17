import asyncio
import logging
import sqlite3
import json
import random
from datetime import datetime
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                           InlineKeyboardButton, PreCheckoutQuery, LabeledPrice,
                           SuccessfulPayment, BotCommand, ReplyKeyboardMarkup,
                           KeyboardButton)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ButtonStyle, ParseMode
from aiogram.types import ChatMemberStatus
import os

# ---------- تنظیمات ----------
BOT_TOKEN = "8847898585:AAGl6_mi1pfQs2fGmWNa9um9mKdl-c2GhWQ"
ADMIN_ID = 8707765533  # عددی
CHANNEL_URL = "https://t.me/+AdMTlTiIm2NhOGVk"
REQUIRED_CHANNEL = ""  # پیش‌فرض خالی (ادمین تنظیم کنه)

# ---------- Flask App ----------
app = Flask(__name__)

# ---------- دیتابیس ----------
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  first_name TEXT,
                  username TEXT,
                  language TEXT DEFAULT 'en',
                  balance REAL DEFAULT 0,
                  referred_by INTEGER DEFAULT 0,
                  ref_count INTEGER DEFAULT 0,
                  registered_at TEXT,
                  is_active INTEGER DEFAULT 1,
                  casino_unlocked INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_enabled', 'True')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('color_scheme', 'blue')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('required_channel', '')")
    conn.commit()
    conn.close()

init_db()

def get_setting(key):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key, value):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def add_user(user_id, first_name, username, language='en'):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, first_name, username, language, registered_at) VALUES (?,?,?,?,?)",
              (user_id, first_name, username, language, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_user_balance(user_id, amount):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def get_user_balance(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def set_casino_unlocked(user_id, unlocked=1):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET casino_unlocked=? WHERE user_id=?", (unlocked, user_id))
    conn.commit()
    conn.close()

def get_casino_unlocked(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT casino_unlocked FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def add_referral(referrer_id, new_user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE users SET ref_count = ref_count + 1, balance = balance + 0.25 WHERE user_id=?", (referrer_id,))
    c.execute("UPDATE users SET referred_by = ? WHERE user_id=?", (referrer_id, new_user_id))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id, first_name, username, balance, ref_count FROM users ORDER BY registered_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_user_stats(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT balance, ref_count, casino_unlocked FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

# ---------- لاگ و بات ----------
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# ---------- وضعیت‌های FSM ----------
class AdminStates(StatesGroup):
    waiting_channel = State()
    waiting_color = State()

# ---------- توابع کمکی برای کیبورد رنگی ----------
def get_color_scheme():
    scheme = get_setting('color_scheme') or 'blue'
    colors = {
        'blue': {'primary': ButtonStyle.PRIMARY, 'success': ButtonStyle.SUCCESS, 'danger': ButtonStyle.DANGER},
        'red': {'primary': ButtonStyle.DANGER, 'success': ButtonStyle.SUCCESS, 'danger': ButtonStyle.PRIMARY},
        'green': {'primary': ButtonStyle.SUCCESS, 'success': ButtonStyle.PRIMARY, 'danger': ButtonStyle.DANGER},
        'dark': {'primary': ButtonStyle.PRIMARY, 'success': ButtonStyle.SUCCESS, 'danger': ButtonStyle.DANGER}
    }
    return colors.get(scheme, colors['blue'])

def get_main_menu(lang='en'):
    scheme = get_color_scheme()
    if lang == 'ru':
        text = {
            'pay': '🎰 Теди за 2 звезды',
            'ref': '👥 Теди через рефералов',
            'profile': '👤 Профиль',
            'ref_link': '🔗 Реферальная ссылка',
            'channel': '📢 Наш канал'
        }
    else:
        text = {
            'pay': '🎰 Tedi with 2 Stars',
            'ref': '👥 Tedi with Referral',
            'profile': '👤 Profile',
            'ref_link': '🔗 Referral Link',
            'channel': '📢 Our Channel'
        }
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text['pay'], callback_data='pay_entry', style=scheme['success'])],
        [InlineKeyboardButton(text=text['ref'], callback_data='ref_play', style=scheme['primary'])],
        [InlineKeyboardButton(text=text['profile'], callback_data='profile', style=scheme['primary']),
         InlineKeyboardButton(text=text['ref_link'], callback_data='ref_link', style=scheme['primary'])],
        [InlineKeyboardButton(text=text['channel'], callback_data='channel', style=scheme['danger'])]
    ])
    return keyboard

# ---------- بررسی عضویت اجباری ----------
async def check_subscription(user_id):
    channel = get_setting('required_channel')
    if not channel:
        return True
    try:
        member = await bot.get_chat_member(chat_id=f"@{channel}", user_id=user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except:
        return False

# ---------- تابع ارسال یا ویرایش ----------
async def send_or_delete(message: Message, text, reply_markup=None):
    try:
        await message.delete()
    except:
        pass
    await message.answer(text, reply_markup=reply_markup)

# ---------- هندلر استارت ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "User"
    username = message.from_user.username or ""
    add_user(user_id, first_name, username)
    
    # بررسی ریفرال
    if message.text and "ref_" in message.text:
        try:
            ref_id = int(message.text.split("_")[1])
            if ref_id != user_id:
                add_referral(ref_id, user_id)
                lang = 'ru' if message.from_user.language_code == 'ru' else 'en'
                await message.answer("✅ You were referred! The referrer got 0.25 Stars." if lang=='en' else "✅ Вы были приглашены! Пригласивший получил 0.25 звезд.")
        except:
            pass
    
    if get_setting('bot_enabled') != 'True':
        await message.answer("⛔ Bot is currently disabled. Please try later." if message.from_user.language_code != 'ru' else "⛔ Бот временно отключен. Попробуйте позже.")
        return
    
    if not await check_subscription(user_id):
        channel = get_setting('required_channel')
        if message.from_user.language_code == 'ru':
            text = f"🔒 Для использования бота, пожалуйста, подпишитесь на наш канал: @{channel}"
        else:
            text = f"🔒 Please subscribe to our channel to use the bot: @{channel}"
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться" if message.from_user.language_code == 'ru' else "📢 Subscribe", url=f"https://t.me/{channel}")],
            [InlineKeyboardButton(text="✅ Проверить" if message.from_user.language_code == 'ru' else "✅ Check", callback_data="check_sub")]
        ]))
        return
    
    lang = 'ru' if message.from_user.language_code == 'ru' else 'en'
    await send_or_delete(message, "🎰 Welcome to Tedi Stars Bot!\nChoose an option:" if lang=='en' else "🎰 Добро пожаловать в Tedi Stars Bot!\nВыберите опцию:", get_main_menu(lang))

# ---------- بررسی عضویت ----------
@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    await callback.answer()
    if await check_subscription(callback.from_user.id):
        lang = 'ru' if callback.from_user.language_code == 'ru' else 'en'
        await callback.message.delete()
        await callback.message.answer("✅ Subscription confirmed! Here is the menu:" if lang=='en' else "✅ Подписка подтверждена! Вот меню:", get_main_menu(lang))
    else:
        await callback.answer("❌ Still not subscribed. Please join first." if callback.from_user.language_code != 'ru' else "❌ Вы все еще не подписаны. Пожалуйста, подпишитесь.")

# ---------- پرداخت ----------
@dp.callback_query(F.data == "pay_entry")
async def pay_entry(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = 'ru' if callback.from_user.language_code == 'ru' else 'en'
    if get_setting('bot_enabled') != 'True':
        await callback.answer("Bot disabled." if lang=='en' else "Бот отключен.")
        return
    if not await check_subscription(user_id):
        await callback.answer("Please subscribe first." if lang=='en' else "Пожалуйста, подпишитесь сначала.")
        return
    await callback.message.delete()
    try:
        await bot.send_invoice(
            chat_id=user_id,
            title="🎰 Unlock Casino" if lang=='en' else "🎰 Открыть казино",
            description="Pay 2 Stars to unlock the casino slot machine!" if lang=='en' else "Заплатите 2 звезды, чтобы открыть слот-машину!",
            payload="casino_unlock",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="2 Stars", amount=2)],
            start_parameter="casino",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Pay" if lang=='en' else "💳 Оплатить", pay=True)]
            ])
        )
    except Exception as e:
        await callback.message.answer(f"Error: {e}")

@dp.pre_checkout_query()
async def pre_checkout_query_handler(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    user_id = message.from_user.id
    set_casino_unlocked(user_id, 1)
    lang = 'ru' if message.from_user.language_code == 'ru' else 'en'
    await message.answer(
        "🎉 Casino unlocked! Now you can play. Each spin costs 3 Stars." if lang=='en' else "🎉 Казино открыто! Теперь вы можете играть. Каждый спин стоит 3 звезды.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎰 Spin (3 Stars)" if lang=='en' else "🎰 Крутить (3 звезды)", callback_data="spin")]
        ])
    )

# ---------- اسپین ----------
@dp.callback_query(F.data == "spin")
async def spin_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = 'ru' if callback.from_user.language_code == 'ru' else 'en'
    if not await check_subscription(user_id):
        await callback.answer("Subscribe first." if lang=='en' else "Подпишитесь сначала.")
        return
    if not get_casino_unlocked(user_id):
        await callback.answer("You need to unlock casino first! Click on 'Tedi with 2 Stars'." if lang=='en' else "Сначала откройте казино! Нажмите 'Теди за 2 звезды'.")
        return
    balance = get_user_balance(user_id)
    if balance < 3:
        await callback.answer(f"Insufficient balance! You have {balance} Stars. Need 3." if lang=='en' else f"Недостаточно звезд! У вас {balance} звезд. Нужно 3.")
        return
    update_user_balance(user_id, -3)
    result = random.randint(1, 100)
    if result == 77:
        reward = 10
        update_user_balance(user_id, reward)
        text = f"🎉🎉🎉 JACKPOT! You won {reward} Stars! 🎉🎉🎉\n\nContact admin to claim: @A1S2IR" if lang=='en' else f"🎉🎉🎉 ДЖЕКПОТ! Вы выиграли {reward} звезд! 🎉🎉🎉\n\nСвяжитесь с админом: @A1S2IR"
        await bot.send_message(ADMIN_ID, f"User {callback.from_user.id} won JACKPOT! Reward {reward} Stars.")
        try:
            await bot.set_message_reaction(chat_id=callback.message.chat.id, message_id=callback.message.message_id, reaction=[types.ReactionTypeEmoji(emoji='🎉')])
        except:
            pass
    else:
        text = "❌ You lost. Try again!" if lang=='en' else "❌ Вы проиграли. Попробуйте снова!"
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Spin Again (3 Stars)" if lang=='en' else "🎰 Крутить снова (3 звезды)", callback_data="spin")]
    ]))
    # ---------- پروفایل ----------
@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = 'ru' if callback.from_user.language_code == 'ru' else 'en'
    stats = get_user_stats(user_id)
    if stats:
        balance, ref_count, unlocked = stats
        text = f"👤 Profile\nBalance: {balance} Stars\nReferrals: {ref_count}\nCasino: {'✅ Unlocked' if unlocked else '❌ Locked'}" if lang=='en' else f"👤 Профиль\nБаланс: {balance} звезд\nРефералы: {ref_count}\nКазино: {'✅ Открыто' if unlocked else '❌ Закрыто'}"
    else:
        text = "User not found."
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=get_main_menu(lang))

# ---------- لینک ارجاع ----------
@dp.callback_query(F.data == "ref_link")
async def ref_link_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = 'ru' if callback.from_user.language_code == 'ru' else 'en'
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    text = f"🔗 Your referral link:\n{ref_link}\n\nShare this link with your friends! Each referral gives you 0.25 Stars." if lang=='en' else f"🔗 Ваша реферальная ссылка:\n{ref_link}\n\nПоделитесь этой ссылкой с друзьями! Каждый реферал дает вам 0.25 звезд."
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=get_main_menu(lang))

# ---------- بازی با زیرمجموعه ----------
@dp.callback_query(F.data == "ref_play")
async def ref_play_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = 'ru' if callback.from_user.language_code == 'ru' else 'en'
    text = ("🎰 You can earn Stars by inviting friends.\n"
            "Each referral = 0.25 Stars.\n"
            "Use your Stars to spin the slot (3 Stars per spin).\n"
            "Click the button below to play." if lang=='en' else
            "🎰 Вы можете зарабатывать звезды, приглашая друзей.\n"
            "Каждый реферал = 0.25 звезд.\n"
            "Используйте свои звезды для кручения слота (3 звезды за спин).\n"
            "Нажмите кнопку ниже, чтобы играть.")
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Spin (3 Stars)" if lang=='en' else "🎰 Крутить (3 звезды)", callback_data="spin")]
    ]))

# ---------- کانال ----------
@dp.callback_query(F.data == "channel")
async def channel_callback(callback: CallbackQuery):
    await callback.message.delete()
    lang = 'ru' if callback.from_user.language_code == 'ru' else 'en'
    await callback.message.answer(f"📢 {lang=='en' and 'Our Channel' or 'Наш канал'}: {CHANNEL_URL}", reply_markup=get_main_menu(lang))

# ---------- پنل ادمین ----------
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Unauthorized.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔛 Enable/Disable Bot", callback_data="admin_toggle")],
        [InlineKeyboardButton(text="🎨 Change Button Colors", callback_data="admin_colors")],
        [InlineKeyboardButton(text="📢 Set Required Channel", callback_data="admin_channel")],
        [InlineKeyboardButton(text="👥 View Users", callback_data="admin_users")],
        [InlineKeyboardButton(text="📊 Stats", callback_data="admin_stats")]
    ])
    await message.answer("🛠 Admin Panel:", reply_markup=keyboard)

@dp.callback_query(F.data == "admin_toggle")
async def admin_toggle(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Unauthorized.")
        return
    current = get_setting('bot_enabled')
    new = 'False' if current == 'True' else 'True'
    set_setting('bot_enabled', new)
    await callback.answer(f"Bot is now {'enabled' if new=='True' else 'disabled'}.", show_alert=True)
    await callback.message.delete()
    await admin_panel(callback.message)

@dp.callback_query(F.data == "admin_colors")
async def admin_colors(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Unauthorized.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔵 Blue", callback_data=f"color_blue", style=ButtonStyle.PRIMARY),
         InlineKeyboardButton(text=f"🔴 Red", callback_data=f"color_red", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text=f"🟢 Green", callback_data=f"color_green", style=ButtonStyle.SUCCESS),
         InlineKeyboardButton(text=f"⚫ Dark", callback_data=f"color_dark", style=ButtonStyle.PRIMARY)]
    ])
    await callback.message.delete()
    await callback.message.answer("Choose a color scheme:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("color_"))
async def set_color(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Unauthorized.")
        return
    color = callback.data.split("_")[1]
    set_setting('color_scheme', color)
    await callback.answer(f"Color scheme set to {color}.", show_alert=True)
    await callback.message.delete()
    await admin_panel(callback.message)

@dp.callback_query(F.data == "admin_channel")
async def admin_channel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Unauthorized.")
        return
    await callback.message.delete()
    await callback.message.answer("Send the channel username (without @) or 'none' to remove.")
    await state.set_state(AdminStates.waiting_channel)

@dp.message(StateFilter(AdminStates.waiting_channel))
async def set_channel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    channel = message.text.strip()
    if channel.lower() == 'none':
        set_setting('required_channel', '')
        await message.answer("✅ Required channel removed.")
    else:
        set_setting('required_channel', channel)
        await message.answer(f"✅ Required channel set to @{channel}")
    await state.clear()
    await admin_panel(message)

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Unauthorized.")
        return
    users = get_all_users()
    text = "👥 Users:\n"
    for u in users[:20]:
        text += f"ID: {u[0]}, Name: {u[1]}, Balance: {u[3]}, Referrals: {u[4]}\n"
    if len(users) > 20:
        text += f"... and {len(users)-20} more."
    await callback.message.delete()
    await callback.message.answer(text)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Unauthorized.")
        return
    users = get_all_users()
    total = len(users)
    total_balance = sum(u[3] for u in users)
    text = f"📊 Stats:\nTotal Users: {total}\nTotal Stars in circulation: {total_balance}"
    await callback.message.delete()
    await callback.message.answer(text)

# ---------- تنظیم وب‌هوک برای Render ----------
async def set_webhook():
    webhook_url = os.environ.get('RENDER_EXTERNAL_URL')
    if not webhook_url:
        # برای اجرای محلی (آزمایشی)
        return
    await bot.set_webhook(url=f"{webhook_url}/webhook")
    logging.info(f"Webhook set to {webhook_url}/webhook")

# ---------- مسیر وب‌هوک برای Flask ----------
@app.route('/webhook', methods=['POST'])
async def webhook():
    update = types.Update(**request.json)
    await dp.process_update(update)
    return jsonify({"ok": True})

@app.route('/', methods=['GET'])
def index():
    return "Bot is running!"

# ---------- اجرا ----------
async def on_startup():
    await set_webhook()
    logging.info("Bot started!")

if __name__ == '__main__':
    # اجرا با Flask برای Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)