import os
import json
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from groq import Groq
import gspread
from google.oauth2.service_account import Credentials

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
SHEET_NAME = os.getenv("SHEET_NAME", "Учёт работ автомастерской")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_API_KEY)

# Временное хранилище данных пользователей
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

# Клавиатура Да/Нет
yes_no_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Ja / Да"), KeyboardButton(text="Nein / Нет")]
    ],
    resize_keyboard=True
)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    user_data[user_id] = {"step": "mechaniker"}
    await message.answer(
        "Введите Ваше Имя и Фамилию\n"
        "Bitte geben Sie Ihren Vor- und Nachnamen ein:",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(Command("new"))
async def cmd_new(message: Message):
    await cmd_start(message)

@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id not in user_data:
        await message.answer("Нажмите /start чтобы начать новую запись.")
        return

    step = user_data[user_id].get("step")

    # --- Шаг 1: Имя ---
    if step == "mechaniker":
        user_data[user_id]["mechaniker"] = text
        user_data[user_id]["step"] = "datum"
        await message.answer(
            "Введите дату выполненных работ (ДД.ММ.ГГГГ)\n"
            "или напишите «сегодня»\n\n"
            "Bitte geben Sie das Datum ein (TT.MM.JJJJ)\n"
            "oder schreiben Sie «heute»:"
        )
        return

    # --- Шаг 2: Дата ---
    if step == "datum":
        if text.lower() in ["сегодня", "heute", "сегодняшняя", "today"]:
            date_str = datetime.now().strftime("%d.%m.%Y")
        else:
            date_str = text
        user_data[user_id]["datum"] = date_str
        user_data[user_id]["step"] = "fahrzeug"
        await message.answer(
            "Введите номер транспортного средства\n"
            "Bitte geben Sie die Fahrzeug-Nr. ein:"
        )
        return

    # --- Шаг 3: Номер ТС ---
    if step == "fahrzeug":
        user_data[user_id]["fahrzeug"] = text
        user_data[user_id]["step"] = "ersatzteile"
        await message.answer(
            "Были ли использованы запасные части?\n"
            "Wurden Ersatzteile verwendet?",
            reply_markup=yes_no_kb
        )
        return

    # --- Шаг 4: Запчасти ---
    if step == "ersatzteile":
        if "ja" in text.lower() or "да" in text.lower():
            user_data[user_id]["ersatzteile"] = "Ja"
        else:
            user_data[user_id]["ersatzteile"] = "Nein"
        user_data[user_id]["step"] = "verbrauch"
        await message.answer(
            "Были ли использованы расходные материалы?\n"
            "Wurde Verbrauchsmaterial verwendet?",
            reply_markup=yes_no_kb
        )
        return

    # --- Шаг 5: Расходники ---
    if step == "verbrauch":
        if "ja" in text.lower() or "да" in text.lower():
            user_data[user_id]["verbrauch"] = "Ja"
        else:
            user_data[user_id]["verbrauch"] = "Nein"
        user_data[user_id]["step"] = "zeit"
        await message.answer(
            "Введите затраченное время в часах (например: 1.5)\n"
            "Bitte geben Sie den Zeitaufwand in Stunden ein (z.B. 1.5):",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    # --- Шаг 6: Время ---
    if step == "zeit":
        user_data[user_id]["zeit"] = text.replace(",", ".")
        user_data[user_id]["step"] = "voice"
        await message.answer(
            "Теперь отправьте голосовое сообщение с описанием выполненных работ.\n"
            "Senden Sie jetzt eine Sprachnachricht mit der Arbeitsbeschreibung."
        )
        return

    # --- Подтверждение ---
    if step == "confirm":
        if text.lower() in ["да", "yes", "ja", "верно", "ок", "ok"]:
            try:
                sheet = get_sheet()
                data = user_data[user_id]
                sheet.append_row([
                    data["mechaniker"],
                    data["datum"],
                    data["fahrzeug"],
                    data["beschreibung"],
                    data["ersatzteile"],
                    data["verbrauch"],
                    data["zeit"]
                ])
                await message.answer("✅ Запись успешно добавлена в таблицу!\n\nЧтобы сделать новую запись — нажмите /start или /new")
            except Exception as e:
                await message.answer(f"Ошибка при записи в таблицу: {e}")
            user_data.pop(user_id, None)
        else:
            await message.answer("Запись отменена. Нажмите /start чтобы начать заново.")
            user_data.pop(user_id, None)
        return

@dp.message(F.voice)
async def handle_voice(message: Message):
    user_id = message.from_user.id

    if user_id not in user_data or user_data[user_id].get("step") != "voice":
        await message.answer("Сначала заполните все поля. Нажмите /start")
        return

    await message.answer("Слушаю и обрабатываю голосовое сообщение...")

    try:
        file = await bot.get_file(message.voice.file_id)
        voice_bytes = await bot.download_file(file.file_path)

        # Распознавание речи
        transcription = groq_client.audio.transcriptions.create(
            file=("voice.ogg", voice_bytes.read()),
            model="whisper-large-v3",
            language="ru"
        )
        raw_text = transcription.text

        # Перевод на технический немецкий
        prompt = f"""
Ты — помощник немецкой автомастерской.
Переведи описание работ механика на правильный технический немецкий язык (KFZ-Fachsprache).
Ответ должен быть только переводом, без пояснений и кавычек.

Текст механика: {raw_text}
"""

        completion = groq_client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        beschreibung = completion.choices[0].message.content.strip()

        user_data[user_id]["beschreibung"] = beschreibung
        user_data[user_id]["step"] = "confirm"

        data = user_data[user_id]
        confirm_text = (
            f"Проверьте данные / Bitte prüfen:\n\n"
            f"Mechaniker: {data['mechaniker']}\n"
            f"Datum: {data['datum']}\n"
            f"Fahrzeug-Nr.: {data['fahrzeug']}\n"
            f"Arbeitsbeschreibung: {beschreibung}\n"
            f"Ersatzteile: {data['ersatzteile']}\n"
            f"Verbrauchsmaterial: {data['verbrauch']}\n"
            f"Zeitaufwand: {data['zeit']} h\n\n"
            f"Всё верно? Напишите «Да» или «Нет»\n"
            f"Alles korrekt? Schreiben Sie «Ja» oder 
