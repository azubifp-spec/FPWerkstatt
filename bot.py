import os
import json
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from groq import Groq
import gspread
from google.oauth2.service_account import Credentials

# === Настройки (будут браться из переменных окружения) ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
SHEET_NAME = os.getenv("SHEET_NAME", "Учёт работ автомастерской")

# Инициализация
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_API_KEY)

# Хранилище временных данных пользователей
user_data = {}

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Здравствуйте!\n\n"
        "Я бот для учёта выполненных работ.\n"
        "Напишите ваше имя и фамилию одним сообщением.\n"
        "Например: Крупчан Сергей"
    )
    user_data[message.from_user.id] = {"step": "waiting_name"}

@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id not in user_data:
        await message.answer("Нажмите /start чтобы начать.")
        return

    if user_data[user_id].get("step") == "waiting_name":
        user_data[user_id]["name"] = text
        user_data[user_id]["step"] = "ready"
        await message.answer(
            f"Отлично, {text}!\n\n"
            "Теперь просто отправьте голосовое сообщение о выполненной работе.\n"
            "Говорите на русском."
        )
        return

    if user_data[user_id].get("step") == "confirm":
        if text.lower() in ["да", "yes", "верно", "ок", "ok"]:
            try:
                sheet = get_sheet()
                data = user_data[user_id]["pending"]
                sheet.append_row([
                    data["mechaniker"],
                    data["datum"],
                    data["fahrzeug"],
                    data["beschreibung"],
                    data["ersatzteile"],
                    data["verbrauch"],
                    data["zeit"]
                ])
                await message.answer("✅ Запись успешно добавлена в таблицу!")
            except Exception as e:
                await message.answer(f"Ошибка при записи: {e}")
            user_data[user_id]["step"] = "ready"
            user_data[user_id].pop("pending", None)
        else:
            await message.answer("Запись отменена. Отправьте новое голосовое сообщение.")
            user_data[user_id]["step"] = "ready"
        return

@dp.message(F.voice)
async def handle_voice(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or user_data[user_id].get("step") != "ready":
        await message.answer("Сначала нажмите /start и укажите своё имя.")
        return

    await message.answer("Слушаю... Обрабатываю голосовое сообщение.")

    # Скачиваем голосовое
    file = await bot.get_file(message.voice.file_id)
    file_path = file.file_path
    voice_bytes = await bot.download_file(file_path)

    # Распознаём речь через Groq Whisper
    try:
        transcription = groq_client.audio.transcriptions.create(
            file=("voice.ogg", voice_bytes.read()),
            model="whisper-large-v3",
            language="ru"
        )
        text = transcription.text
    except Exception as e:
        await message.answer(f"Не удалось распознать речь: {e}")
        return

    # Отправляем в LLM для извлечения данных
    prompt = f"""
Ты помощник автомастерской в Германии.
Из русского текста извлеки данные и верни ТОЛЬКО валидный JSON без пояснений:

{{
  "mechaniker": "имя механика (оставь как есть)",
  "datum": "дата в формате ДД.ММ.ГГГГ (если не указана — сегодня {datetime.now().strftime('%d.%m.%Y')})",
  "fahrzeug": "номер автомобиля",
  "beschreibung": "описание работ на правильном техническом немецком (KFZ)",
  "ersatzteile": "Ja или Nein",
  "verbrauch": "Ja или Nein",
  "zeit": "время в часах числом (например 1.5)"
}}

Текст механика: {text}
Имя механика: {user_data[user_id].get('name', '')}
"""

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        response_text = completion.choices[0].message.content.strip()
        # Убираем возможные ```json
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        data = json.loads(response_text)
    except Exception as e:
        await message.answer(f"Ошибка обработки: {e}\nРаспознанный текст: {text}")
        return

    # Показываем подтверждение
    confirm_text = (
        f"Проверьте данные:\n\n"
        f"Mechaniker: {data.get('mechaniker')}\n"
        f"Datum: {data.get('datum')}\n"
        f"Fahrzeug-Nr.: {data.get('fahrzeug')}\n"
        f"Arbeitsbeschreibung: {data.get('beschreibung')}\n"
        f"Ersatzteile: {data.get('ersatzteile')}\n"
        f"Verbrauchsmaterial: {data.get('verbrauch')}\n"
        f"Zeitaufwand: {data.get('zeit')} h\n\n"
        f"Всё верно? Напишите «Да» или «Нет»"
    )
    user_data[user_id]["pending"] = data
    user_data[user_id]["step"] = "confirm"
    await message.answer(confirm_text)

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
