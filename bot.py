from telethon import TelegramClient, events
from airtable_client import AirtableClient
from dotenv import load_dotenv
import os
import datetime

load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)
airtable = AirtableClient()

@client.on(events.NewMessage(pattern=r'^Добави:'))
async def handler(event):
    try:
        text = event.raw_text.replace("Добави:", "").strip()
        parts = [p.strip() for p in text.split("|")]

        fields = {
            "Data": datetime.datetime.strptime(parts[0], "%d.%m.%Y").date().isoformat(),
            "БАНКА/БУКИ": [parts[1]],
            "INCOME £": float(parts[2]),
            "OUTCOME £": float(parts[3]),
            "DEPOSIT £": float(parts[4]),
            "WITHDRAW £": float(parts[5]),
            "INCOME BGN": float(parts[6]),
            "OUTCOME BGN": float(parts[7]),
            "DEPOSIT BGN": float(parts[8]),
            "WITHDRAW BGN": float(parts[9]),
            "STATUS": parts[10],
            "ЧИИ ПАРИ": parts[11],
            "NOTES": parts[12] if len(parts) > 12 else ""
        }

        result = airtable.add_record(fields)
        await event.reply("✅ Записът беше добавен успешно в Airtable!")

    except Exception as e:
        await event.reply(f"⚠️ Грешка: {e}")

client.run_until_disconnected()
