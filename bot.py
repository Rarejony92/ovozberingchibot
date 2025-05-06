import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramBadRequest
from typing import List, Dict, Set, Optional
from datetime import datetime

# Muhit o'zgaruvchilarini o'qish
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
CHANNELS = os.getenv("CHANNELS", "").split(",")

# Bot konfiguratsiyasi
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())

# Kanalga a'zolikni tekshirish
async def check_channel_subscription(user_id: int) -> bool:
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except Exception as e:
            logging.error(f"Kanalga a'zolikni tekshirishda xato: {e}")
            return False
    return True

# Holatlar (States)
class PollState(StatesGroup):
    waiting_for_title = State()
    waiting_for_image = State()
    waiting_for_options = State()

class AdminState(StatesGroup):
    waiting_for_new_admin_id = State()
    waiting_for_remove_admin_id = State()

class ChannelState(StatesGroup):
    waiting_for_new_channel = State()
    waiting_for_remove_channel = State()

class AnnouncementState(StatesGroup):
    waiting_for_announcement = State()

# Ma'lumotlar bazasi (vaqtincha)
polls: Dict[str, Dict] = {}
votes: Dict[str, Set[int]] = {}
user_polls: Dict[int, List[str]] = {}
users: Set[int] = set()

# Admin paneli tugmalari
admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Yangi So'rovnoma", callback_data="new_poll")],
    [InlineKeyboardButton(text="Mening So'rovnomalarim", callback_data="my_polls")],
    [
        InlineKeyboardButton(text="Adminlar", callback_data="admins"),
        InlineKeyboardButton(text="Kanallar", callback_data="channels")
    ],
    [
        InlineKeyboardButton(text="Xabarnoma", callback_data="announcement"),
        InlineKeyboardButton(text="Statistika", callback_data="stats")
    ]
])

# Start komandasi
@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    users.add(user_id)
    
    # Kanalga a'zolikni tekshirish
    is_subscribed = await check_channel_subscription(user_id)
    if not is_subscribed:
        join_buttons = []
        for channel in CHANNELS:
            join_buttons.append([InlineKeyboardButton(
                text=f"🔔 {channel} kanaliga obuna bo'lish", 
                url=f"https://t.me/{channel.strip('@')}"
            )])
        await message.answer(
            "Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo'ling:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=join_buttons)
        )
        return
    
    # Admin yoki oddiy foydalanuvchi tekshiruvi
    if user_id in ADMIN_IDS:
        await message.answer("Admin paneliga xush kelibsiz!", reply_markup=admin_keyboard)
    else:
        active_polls = {pid: p for pid, p in polls.items() if p.get('is_active', True)}
        if not active_polls:
            await message.answer("Hozircha faol so'rovnomalar mavjud emas.")
        else:
            kb = InlineKeyboardBuilder()
            for poll_id, poll in active_polls.items():
                kb.button(text=poll['title'], callback_data=f"vote_{poll_id}")
            await message.answer("Faol so'rovnomalar:", reply_markup=kb.as_markup())

# Yangi so'rovnoma yaratish
@dp.callback_query(F.data == "new_poll")
async def create_poll_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    await call.message.answer("So'rovnoma sarlavhasini kiriting:")
    await state.set_state(PollState.waiting_for_title)
    await call.answer()

@dp.message(PollState.waiting_for_title)
async def get_title(message: Message, state: FSMContext):
    if len(message.text) > 200:
        await message.answer("Sarlavha juda uzun. Iltimos, 200 belgidan kamroq kiriting.")
        return
    
    await state.update_data(title=message.text)
    await message.answer("Rasm yuboring (agar rasm kerak bo'lmasa, 'skip' deb yozing):")
    await state.set_state(PollState.waiting_for_image)

@dp.message(PollState.waiting_for_image, F.photo)
async def get_image_with_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(image=file_id)
    await message.answer("Variantlarni vergul bilan ajratib kiriting (masalan: Ali, Vali, Sami):")
    await state.set_state(PollState.waiting_for_options)

@dp.message(PollState.waiting_for_image, F.text.lower() == "skip")
async def skip_image(message: Message, state: FSMContext):
    await state.update_data(image=None)
    await message.answer("Variantlarni vergul bilan ajratib kiriting (masalan: Ali, Vali, Sami):")
    await state.set_state(PollState.waiting_for_options)

@dp.message(PollState.waiting_for_options)
async def get_options(message: Message, state: FSMContext):
    options = [opt.strip() for opt in message.text.split(",") if opt.strip()]
    
    if len(options) < 2:
        await message.answer("Kamida 2 ta variant kiriting!")
        return
    
    if len(options) > 10:
        await message.answer("Variantlar soni 10 tadan ko'p bo'lmasligi kerak!")
        return
    
    data = await state.get_data()
    poll_id = str(len(polls) + 1)
    creator_id = message.from_user.id
    
    polls[poll_id] = {
        'title': data['title'],
        'image': data.get('image'),
        'options': options,
        'votes': {opt: 0 for opt in options},
        'creator': creator_id,
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'is_active': True
    }
    votes[poll_id] = set()
    
    if creator_id not in user_polls:
        user_polls[creator_id] = []
    user_polls[creator_id].append(poll_id)
    
    await message.answer(f"So'rovnoma muvaffaqiyatli yaratildi! ID: {poll_id}")
    await state.clear()

# So'rovnomada ovoz berish
@dp.callback_query(F.data.startswith("vote_"))
async def vote_handler(call: CallbackQuery):
    poll_id = call.data.split("_")[1]
    user_id = call.from_user.id
    
    is_subscribed = await check_channel_subscription(user_id)
    if not is_subscribed:
        await call.answer("Avval kanal(lar)ga obuna bo'ling!", show_alert=True)
        return
    
    if user_id in votes.get(poll_id, set()):
        await call.answer("Siz allaqachon ovoz bergansiz!", show_alert=True)
        return
    
    poll = polls.get(poll_id)
    if not poll or not poll.get('is_active', True):
        await call.answer("So'rovnoma topilmadi yoki yakunlangan", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    for opt in poll['options']:
        kb.button(text=opt, callback_data=f"select_{poll_id}_{opt}")
    kb.adjust(1)
    
    if poll.get('image'):
        await call.message.answer_photo(
            photo=poll['image'],
            caption=poll['title'],
            reply_markup=kb.as_markup()
        )
    else:
        await call.message.answer(
            poll['title'],
            reply_markup=kb.as_markup()
        )
    await call.answer()

@dp.callback_query(F.data.startswith("select_"))
async def select_option(call: CallbackQuery):
    _, poll_id, selected = call.data.split("_", 2)
    user_id = call.from_user.id
    
    if user_id in votes.get(poll_id, set()):
        await call.answer("Siz allaqachon ovoz bergansiz!", show_alert=True)
        return
    
    poll = polls.get(poll_id)
    if not poll or not poll.get('is_active', True):
        await call.answer("So'rovnoma topilmadi yoki yakunlangan", show_alert=True)
        return
    
    poll['votes'][selected] += 1
    votes[poll_id].add(user_id)
    
    await call.answer(f"Siz {selected} uchun ovoz berdingiz!", show_alert=True)
    
    if call.from_user.id not in ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"Yangi ovoz: {call.from_user.full_name} ({call.from_user.id})\n"
                    f"So'rovnoma: {poll['title']}\n"
                    f"Tanlov: {selected}"
                )
            except Exception as e:
                logging.error(f"Adminga xabar yuborishda xato: {e}")

# Mening so'rovnomalarim
@dp.callback_query(F.data == "my_polls")
async def show_my_polls(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    creator_id = call.from_user.id
    if creator_id not in user_polls or not user_polls[creator_id]:
        await call.answer("Siz hali so'rovnoma yaratmadingiz!", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    for poll_id in user_polls[creator_id]:
        if poll_id in polls:
            poll = polls[poll_id]
            status = "✅ Faol" if poll.get('is_active', True) else "❌ Yakunlangan"
            kb.button(text=f"{poll['title']} ({status})", callback_data=f"manage_{poll_id}")
    kb.adjust(1)
    
    await call.message.answer("Sizning so'rovnomalaringiz:", reply_markup=kb.as_markup())
    await call.answer()

# So'rovnomani boshqarish
@dp.callback_query(F.data.startswith("manage_"))
async def manage_poll(call: CallbackQuery):
    poll_id = call.data.split("_")[1]
    poll = polls.get(poll_id)
    
    if not poll:
        await call.answer("So'rovnoma topilmadi")
        return
    
    if call.from_user.id not in ADMIN_IDS and call.from_user.id != poll.get('creator'):
        await call.answer("Bu sizning so'rovnomaningiz emas!", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Statistikani ko'rish", callback_data=f"stats_{poll_id}")
    if poll.get('is_active', True):
        kb.button(text="🚫 Yakunlash", callback_data=f"deactivate_{poll_id}")
    else:
        kb.button(text="✅ Faollashtirish", callback_data=f"activate_{poll_id}")
    kb.button(text="🗑 So'rovnomani o'chirish", callback_data=f"delete_{poll_id}")
    kb.adjust(1)
    
    status = "✅ Faol" if poll.get('is_active', True) else "❌ Yakunlangan"
    unknown_text = "Noma'lum"
    text_parts = [
        f"So'rovnoma: {poll['title']}",
        f"Holati: {status}",
        f"Yaratilgan: {poll.get('created_at', unknown_text)}",
        f"Ovozlar soni: {len(votes.get(poll_id, set()))}"
    ]
    await call.message.answer("\n".join(text_parts), reply_markup=kb.as_markup())
    await call.answer()

# So'rovnomani o'chirish/yakunlash/faollashtirish
@dp.callback_query(F.data.startswith("deactivate_"))
async def deactivate_poll(call: CallbackQuery):
    poll_id = call.data.split("_")[1]
    poll = polls.get(poll_id)
    
    if not poll:
        await call.answer("So'rovnoma topilmadi")
        return
    
    if call.from_user.id not in ADMIN_IDS and call.from_user.id != poll.get('creator'):
        await call.answer("Bu sizning so'rovnomaningiz emas!", show_alert=True)
        return
    
    poll['is_active'] = False
    await call.answer("So'rovnoma yakunlandi!", show_alert=True)
    await call.message.delete()

@dp.callback_query(F.data.startswith("activate_"))
async def activate_poll(call: CallbackQuery):
    poll_id = call.data.split("_")[1]
    poll = polls.get(poll_id)
    
    if not poll:
        await call.answer("So'rovnoma topilmadi")
        return
    
    if call.from_user.id not in ADMIN_IDS and call.from_user.id != poll.get('creator'):
        await call.answer("Bu sizning so'rovnomaningiz emas!", show_alert=True)
        return
    
    poll['is_active'] = True
    await call.answer("So'rovnoma qayta faollashtirildi!", show_alert=True)
    await call.message.delete()

@dp.callback_query(F.data.startswith("delete_"))
async def delete_poll(call: CallbackQuery):
    poll_id = call.data.split("_")[1]
    poll = polls.get(poll_id)
    
    if not poll:
        await call.answer("So'rovnoma topilmadi")
        return
    
    if call.from_user.id not in ADMIN_IDS and call.from_user.id != poll.get('creator'):
        await call.answer("Bu sizning so'rovnomaningiz emas!", show_alert=True)
        return
    
    creator_id = poll.get('creator')
    if creator_id in user_polls and poll_id in user_polls[creator_id]:
        user_polls[creator_id].remove(poll_id)
    
    del polls[poll_id]
    if poll_id in votes:
        del votes[poll_id]
    
    await call.answer("So'rovnoma muvaffaqiyatli o'chirildi!", show_alert=True)
    await call.message.delete()

# So'rovnoma statistikasi
@dp.callback_query(F.data.startswith("stats_"))
async def show_poll_stats(call: CallbackQuery):
    poll_id = call.data.split("_")[1]
    poll = polls.get(poll_id)
    
    if not poll:
        await call.answer("So'rovnoma topilmadi")
        return
    
    if call.from_user.id not in ADMIN_IDS and call.from_user.id != poll.get('creator'):
        await call.answer("Bu sizning so'rovnomaningiz emas!", show_alert=True)
        return
    
    total_votes = sum(poll['votes'].values())
    status = "✅ Faol" if poll.get('is_active', True) else "❌ Yakunlangan"
    unknown_text = "Noma'lum"
    
    stats_text = [
        f"📊 {poll['title']} - Natijalar:",
        f"Holati: {status}",
        f"Yaratilgan: {poll.get('created_at', unknown_text)}",
        "Natijalar:"
    ]
    
    for option, count in poll['votes'].items():
        percentage = (count / total_votes * 100) if total_votes > 0 else 0
        stats_text.append(f"{option}: {count} ovoz ({percentage:.1f}%)")
    
    stats_text.append(f"Jami ovozlar: {total_votes}")
    
    if poll.get('image'):
        await call.message.answer_photo(
            photo=poll['image'],
            caption="\n".join(stats_text)
        )
    else:
        await call.message.answer("\n".join(stats_text))
    
    await call.answer()

# Adminlarni boshqarish
@dp.callback_query(F.data == "admins")
async def manage_admins(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    kb.button(text="Admin qo'shish", callback_data="add_admin")
    kb.button(text="Admin o'chirish", callback_data="remove_admin")
    kb.button(text="Adminlar ro'yxati", callback_data="list_admins")
    kb.adjust(1)
    
    await call.message.answer("Adminlarni boshqarish:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data == "add_admin")
async def add_admin_prompt(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Yangi admin ID sini kiriting:")
    await state.set_state(AdminState.waiting_for_new_admin_id)
    await call.answer()

@dp.message(AdminState.waiting_for_new_admin_id)
async def add_admin(message: Message, state: FSMContext):
    try:
        new_id = int(message.text.strip())
        if new_id not in ADMIN_IDS:
            ADMIN_IDS.append(new_id)
            await message.answer(f"Admin (ID: {new_id}) muvaffaqiyatli qo'shildi.")
        else:
            await message.answer("Bu ID allaqachon adminlar ro'yxatida.")
    except ValueError:
        await message.answer("Noto'g'ri ID format. Faqat raqam kiriting.")
    await state.clear()

@dp.callback_query(F.data == "remove_admin")
async def remove_admin_prompt(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    if not ADMIN_IDS:
        await call.answer("Adminlar ro'yxati bo'sh", show_alert=True)
        return
    
    await call.message.answer("O'chirish uchun admin ID sini kiriting:")
    await state.set_state(AdminState.waiting_for_remove_admin_id)
    await call.answer()

@dp.message(AdminState.waiting_for_remove_admin_id)
async def remove_admin(message: Message, state: FSMContext):
    try:
        remove_id = int(message.text.strip())
        if remove_id in ADMIN_IDS:
            if remove_id == message.from_user.id:
                await message.answer("O'zingizni adminlikdan o'chira olmaysiz!")
            else:
                ADMIN_IDS.remove(remove_id)
                await message.answer(f"Admin (ID: {remove_id}) muvaffaqiyatli o'chirildi.")
        else:
            await message.answer("Bu ID adminlar ro'yxatida mavjud emas.")
    except ValueError:
        await message.answer("Noto'g'ri ID format. Faqat raqam kiriting.")
    await state.clear()

@dp.callback_query(F.data == "list_admins")
async def list_admins(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    if not ADMIN_IDS:
        await call.answer("Adminlar ro'yxati bo'sh", show_alert=True)
        return
    
    admins_list = "\n".join(str(admin_id) for admin_id in ADMIN_IDS)
    await call.message.answer(f"Adminlar ro'yxati:\n{admins_list}")
    await call.answer()

# Kanallarni boshqarish
@dp.callback_query(F.data == "channels")
async def manage_channels(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    kb.button(text="Kanal qo'shish", callback_data="add_channel")
    kb.button(text="Kanal o'chirish", callback_data="remove_channel")
    kb.button(text="Kanallar ro'yxati", callback_data="list_channels")
    kb.adjust(1)
    
    await call.message.answer("Kanallarni boshqarish:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data == "add_channel")
async def add_channel_prompt(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Yangi kanal usernameni kiriting (@ belgisi bilan):")
    await state.set_state(ChannelState.waiting_for_new_channel)
    await call.answer()

@dp.message(ChannelState.waiting_for_new_channel)
async def add_channel(message: Message, state: FSMContext):
    channel = message.text.strip()
    if not channel.startswith("@"):
        channel = "@" + channel
    
    if channel not in CHANNELS:
        CHANNELS.append(channel)
        await message.answer(f"Kanal {channel} qo'shildi.")
    else:
        await message.answer("Bu kanal allaqachon ro'yxatda.")
    await state.clear()

@dp.callback_query(F.data == "remove_channel")
async def remove_channel_prompt(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    if not CHANNELS:
        await call.answer("Kanallar ro'yxati bo'sh", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    for channel in CHANNELS:
        kb.button(text=channel, callback_data=f"remove_ch_{channel}")
    kb.adjust(1)
    
    await call.message.answer("O'chirish uchun kanalni tanlang:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("remove_ch_"))
async def remove_channel(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    channel = call.data.split("_", 2)[-1]
    if channel in CHANNELS:
        CHANNELS.remove(channel)
        await call.answer(f"{channel} kanali ro'yxatdan o'chirildi!", show_alert=True)
        await call.message.delete()
    else:
        await call.answer("Bu kanal ro'yxatda mavjud emas!", show_alert=True)

@dp.callback_query(F.data == "list_channels")
async def list_channels(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    if not CHANNELS:
        await call.answer("Kanallar ro'yxati bo'sh", show_alert=True)
        return
    
    channels_list = "\n".join(CHANNELS)
    await call.message.answer(f"Obuna bo'lish kerak bo'lgan kanallar:\n{channels_list}")
    await call.answer()

# Xabarnoma yuborish
@dp.callback_query(F.data == "announcement")
async def start_announcement(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    await call.message.answer(
        "Xabarnoma yuborish uchun xabarni yuboring (matn, rasm, video, etc.):\n"
        "Bekor qilish uchun /cancel buyrug'ini yuboring."
    )
    await state.set_state(AnnouncementState.waiting_for_announcement)
    await call.answer()

@dp.message(AnnouncementState.waiting_for_announcement, F.text == "/cancel")
async def cancel_announcement(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Xabarnoma bekor qilindi.")

@dp.message(AnnouncementState.waiting_for_announcement)
async def send_announcement(message: Message, state: FSMContext):
    total_users = len(users)
    if total_users == 0:
        await message.answer("Hozircha obunachilar mavjud emas.")
        await state.clear()
        return
    
    success = 0
    failed = 0
    
    await message.answer(f"Xabarnoma {total_users} ta foydalanuvchiga yuborilmoqda...")
    
    for user_id in users:
        try:
            await message.send_copy(user_id)
            success += 1
        except Exception as e:
            logging.error(f"Xabarnomani {user_id} ga yuborishda xato: {e}")
            failed += 1
        await asyncio.sleep(0.1)
    
    await message.answer(
        f"Xabarnoma yuborildi!\n"
        f"Muvaffaqiyatli: {success}\n"
        f"Muvaffaqiyatsiz: {failed}"
    )
    await state.clear()

# Bot statistikasi
@dp.callback_query(F.data == "stats")
async def show_bot_stats(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Faqat adminlar uchun!", show_alert=True)
        return
    
    active_polls = sum(1 for p in polls.values() if p.get('is_active', True))
    inactive_polls = len(polls) - active_polls
    total_votes = sum(len(v) for v in votes.values())
    
    stats_text = [
        "📊 Bot statistikasi:",
        f"Jami foydalanuvchilar: {len(users)}",
        f"Jami so'rovnomalar: {len(polls)}",
        f"Faol so'rovnomalar: {active_polls}",
        f"Yakunlangan so'rovnomalar: {inactive_polls}",
        f"Jami ovozlar: {total_votes}",
        "So'rovnomalar ro'yxati:"
    ]
    
    for poll_id, poll in polls.items():
        status = "✅ Faol" if poll.get('is_active', True) else "❌ Yakunlangan"
        stats_text.append(
            f"- {poll['title']} ({status}): {len(votes.get(poll_id, set()))} ovoz"
        )
    
    await call.message.answer("\n".join(stats_text))
    await call.answer()

# Botni ishga tushirish
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())