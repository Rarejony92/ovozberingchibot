import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

# ✅ Muhim sozlamalar (qo‘lda kiritilgan)
TOKEN = "7693988010:AAFTqOCaIkXcadrgRYqMrxOjwCqbuGpiJGU"  # Bot tokeni
ADMIN_ID = "7915183548"  # Admin ID
CHANNEL_USERNAME = "kosonsoytezkor"  # Kanal username (@siz)

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

# ✅ Holatlar
class UploadImage(StatesGroup):
    waiting_for_image = State()
    waiting_for_name = State()

# ✅ Ma'lumotlarni saqlash
images = {}  # {image_id: {"file_id": file_id, "name": name, "votes": 0}}
votes = {}  # {user_id: image_id}

# ✅ Obuna tekshirish
async def check_subscription(user_id):
    chat_member = await bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
    return chat_member.status in ["member", "administrator", "creator"]

# ✅ Start komandasi
@dp.message_handler(commands=["start"])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    args = message.get_args()
    
    if not await check_subscription(user_id):
        btn = InlineKeyboardMarkup().add(InlineKeyboardButton("🔔 Obuna bo‘lish", url=f"https://t.me/{CHANNEL_USERNAME}"))
        await message.answer("📢 Ovoz berishdan oldin kanalimizga obuna bo‘ling!", reply_markup=btn)
        return
    
    if args.startswith("vote_"):
        image_id = int(args.split("_")[1])
        if user_id in votes:
            await message.answer("❌ Siz allaqachon ovoz bergansiz.")
        else:
            votes[user_id] = image_id
            images[image_id]["votes"] += 1
            await message.answer("✅ Ovoz berildi!")
    else:
        await message.answer("✅ Siz kanalga obuna bo‘lgansiz. Ovoz berish uchun /vote buyrug‘ini ishlating.")

# ✅ Rasm yuklash (admin)
@dp.message_handler(commands=["upload"])
async def upload_image_command(message: types.Message):
    if str(message.from_user.id) != ADMIN_ID:
        return
    await message.answer("📸 Rasmni yuboring:")
    await UploadImage.waiting_for_image.set()

@dp.message_handler(content_types=types.ContentType.PHOTO, state=UploadImage.waiting_for_image)
async def process_image(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(file_id=file_id)
    await message.answer("ℹ️ Ism va familiyani kiriting:")
    await UploadImage.waiting_for_name.set()

@dp.message_handler(state=UploadImage.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    image_id = len(images) + 1
    images[image_id] = {"file_id": data["file_id"], "name": message.text, "votes": 0}
    await message.answer(f"✅ Rasm saqlandi! ID: {image_id}")
    await state.finish()

# ✅ Ovoz berish
@dp.message_handler(commands=["vote"])
async def vote_command(message: types.Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        btn = InlineKeyboardMarkup().add(InlineKeyboardButton("🔔 Obuna bo‘lish", url=f"https://t.me/{CHANNEL_USERNAME}"))
        await message.answer("📢 Ovoz berishdan oldin kanalimizga obuna bo‘ling!", reply_markup=btn)
        return
    
    if user_id in votes:
        await message.answer("❌ Siz allaqachon ovoz bergansiz.")
        return
    
    if not images:
        await message.answer("⚠️ Hozircha rasmlar yuklanmagan.")
        return
    
    markup = InlineKeyboardMarkup()
    for image_id, data in images.items():
        markup.add(InlineKeyboardButton(text=data["name"], callback_data=f"vote_{image_id}"))
    
    await message.answer("🗳 Ovoz berish uchun rasm tanlang:", reply_markup=markup)

@dp.callback_query_handler(lambda c: c.data.startswith("vote_"))
async def process_vote(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    image_id = int(callback_query.data.split("_")[1])
    
    if user_id in votes:
        await callback_query.answer("❌ Siz allaqachon ovoz bergansiz.", show_alert=True)
        return
    
    votes[user_id] = image_id
    images[image_id]["votes"] += 1
    await callback_query.answer("✅ Ovoz berildi!")
    await bot.send_message(ADMIN_ID, f"🗳 {callback_query.from_user.full_name} #{image_id}-rasmga ovoz berdi.")

# ✅ Kanalga joylash (admin)
@dp.message_handler(commands=["post"])
async def post_image(message: types.Message):
    if str(message.from_user.id) != ADMIN_ID:
        return
    if not images:
        await message.answer("⚠️ Hozircha rasmlar yuklanmagan.")
        return

    for image_id, data in images.items():
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton("🗳 Ovoz berish", url=f"https://t.me/{bot.username}?start=vote_{image_id}")
        )
        caption = f"📸 {data['name']}\n🗳 {data['votes']} ta ovoz"
        await bot.send_photo(f"@{CHANNEL_USERNAME}", photo=data["file_id"], caption=caption, reply_markup=markup)
    
    await message.answer("✅ Barcha rasmlar kanalga yuborildi!")

# ✅ Botni ishga tushirish
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
