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
from google import genai

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
SHEET_NAME = os.getenv("SHEET_NAME", "Учёт работ автомастерской")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not GEMINI_API_KEY:
    print("ОШИБКА: Не найден ключ GEMINI_API_KEY или GOOGLE_API_KEY")
else:
    print("Gemini ключ успешно загружен")

client = genai.Client(api_key=GEMINI_API_KEY)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_API_KEY)

user_data = {}

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gs = gspread.authorize(creds)
    return gs.open(SHEET_NAME).sheet1

yes_no_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Ja / Да"), KeyboardButton(text="Nein / Нет")]],
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

    if step == "mechaniker":
        user_data[user_id]["mechaniker"] = text
        user_data[user_id]["step"] = "datum"
        await message.answer(
            "Введите дату выполненных работ (ДД.ММ.ГГГГ) или напишите сегодня\n"
            "Bitte geben Sie das Datum ein (TT.MM.JJJJ) oder schreiben Sie heute:"
        )
        return

    if step == "datum":
        if text.lower() in ["сегодня", "heute", "today"]:
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

    if step == "fahrzeug":
        user_data[user_id]["fahrzeug"] = text
        user_data[user_id]["step"] = "ersatzteile"
        await message.answer(
            "Были ли использованы запасные части?\n"
            "Wurden Ersatzteile verwendet?",
            reply_markup=yes_no_kb
        )
        return

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

    if step == "verbrauch":
        if "ja" in text.lower() or "да" in text.lower():
            user_data[user_id]["verbrauch"] = "Ja"
        else:
            user_data[user_id]["verbrauch"] = "Nein"
        user_data[user_id]["step"] = "zeit"
        await message.answer(
            "Введите затраченное время в часах (например 1.5)\n"
            "Bitte geben Sie den Zeitaufwand in Stunden ein (z.B. 1.5):",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    if step == "zeit":
        user_data[user_id]["zeit"] = text.replace(",", ".")
        user_data[user_id]["step"] = "voice"
        await message.answer(
            "Теперь отправьте голосовое сообщение с описанием выполненных работ.\n"
            "Senden Sie jetzt eine Sprachnachricht mit der Arbeitsbeschreibung."
        )
        return

    if step == "confirm":
        lower_text = text.lower()

        if lower_text in ["да", "yes", "ja", "верно", "ок", "ok"]:
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
                await message.answer(
                    "Запись успешно добавлена в таблицу!\n\n"
                    "Чтобы сделать новую запись — нажмите /start или /new"
                )
            except Exception as e:
                await message.answer(f"Ошибка при записи в таблицу: {e}")
            user_data.pop(user_id, None)
            return

        if "заново" in lower_text or "голос" in lower_text or "описать" in lower_text:
            user_data[user_id]["step"] = "voice"
            await message.answer(
                "Отправьте новое голосовое сообщение с описанием работ.\n"
                "Senden Sie eine neue Sprachnachricht."
            )
            return

        if "отмен" in lower_text or "cancel" in lower_text or "нет" in lower_text or "nein" in lower_text:
            await message.answer(
                "Вся запись отменена.\n"
                "Чтобы начать заново — нажмите /start или /new"
            )
            user_data.pop(user_id, None)
            return

        await message.answer(
            "Пожалуйста, выберите:\n"
            "Да / Ja — сохранить\n"
            "Заново описать работу голосом\n"
            "Отменить всю запись"
        )
        return

@dp.message(F.voice)
async def handle_voice(message: Message):
    user_id = message.from_user.id

    if user_id not in user_data or user_data[user_id].get("step") != "voice":
        await message.answer("Сначала заполните все поля. Нажмите /start")
        return

    await message.answer("Слушаю и обрабатываю...")

    try:
        file = await bot.get_file(message.voice.file_id)
        voice_file = await bot.download_file(file.file_path)

        transcription = groq_client.audio.transcriptions.create(
            file=("voice.ogg", voice_file.read()),
            model="whisper-large-v3",
            language="ru"
        )
        raw_text = transcription.text

        prompt = (
            "Ты опытный переводчик технической документации немецкой автомастерской (KFZ / Nutzfahrzeuge / LKW).\n"
            "Переведи описание работ механика на правильный технический немецкий язык.\n\n"
            "Правила:\n"
            "- Отвечай ТОЛЬКО переводом, без пояснений, кавычек и лишнего текста.\n"
            "- Используй профессиональные термины немецкой автомеханики.\n"
            "- Для пневмоподушки подвески грузовика используй: Austausch der Luftfeder (Luftfederbalg)\n"
            "- Никогда не оставляй ответ пустым.\n\n"
            f"Текст механика: {raw_text}"
        )

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        beschreibung = response.text.strip()

        if not beschreibung:
            beschreibung = raw_text

        user_data[user_id]["beschreibung"] = beschreibung
        user_data[user_id]["step"] = "confirm"

        data = user_data[user_id]

        confirm_text = "Проверьте данные / Bitte pruefen:\n\n"
        confirm_text += f"Mechaniker: {data['mechaniker']}\n"
        confirm_text += f"Datum: {data['datum']}\n"
        confirm_text += f"Fahrzeug-Nr.: {data['fahrzeug']}\n"
        confirm_text += f"Arbeitsbeschreibung: {beschreibung}\n"
        confirm_text += f"Ersatzteile: {data['ersatzteile']}\n"
        confirm_text += f"Verbrauchsmaterial: {data['verbrauch']}\n"
        confirm_text += f"Zeitaufwand: {data['zeit']} h\n\n"
        confirm_text += "Всё верно? Напишите Да или Нет\n"
        confirm_text += "Alles korrekt? Schreiben Sie Ja oder Nein"

        await message.answer(confirm_text)

    except Exception as e:
        await message.answer(f"Ошибка обработки: {e}")

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
