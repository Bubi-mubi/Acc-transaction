from telethon import TelegramClient, events
from airtable_client import AirtableClient
from dotenv import load_dotenv
from telethon.tl.custom import Button
import os
import re

load_dotenv()

# 📦 Памет за временни данни от потребители
bot_memory = {}

# 🔁 Нормализация на текст
def normalize(text):
    return (
        text.lower()
        .replace("-", " ")
        .replace("_", " ")
        .replace("–", " ")
        .replace("—", " ")
        .replace("  ", " ")
        .strip()
    )

CURRENCY_SYNONYMS = {
    "£": ["паунд", "паунда", "paund", "paunda", "gbp", "gb"],
    "BGN": ["лв", "лева", "lv", "lw"],
    "EU": ["евро", "eur", "euro", "evro", "ewro"],
    "USD": ["долар", "долара", "usd", "dolar", "dolara"]
}

def get_currency_key(word):
    word = word.lower().strip()
    for key, synonyms in CURRENCY_SYNONYMS.items():
        if word in synonyms:
            return key
    return None

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)
airtable = AirtableClient()

# 💬 Основно съобщение тип "100 lv ot A kum B"
@client.on(events.NewMessage)
async def smart_input_handler(event):
    match = re.search(
        r'(\d+(?:[.,]\d{1,2})?)\s*([а-яa-zA-Z.]+)\s+(?:от|ot)\s+(.+?)\s+(?:към|kum|kym)\s+(.+)',
        event.raw_text,
        re.IGNORECASE
    )
    if not match:
        return

    amount = float(match.group(1).replace(",", "."))
    currency_raw = match.group(2).strip()
    sender = match.group(3).strip()
    receiver = match.group(4).strip()

    currency_key = get_currency_key(currency_raw)
    if not currency_key:
        await event.reply("❌ Неразпозната валута.")
        return

    user_id = str(event.sender_id)
    bot_memory[user_id] = {
        "amount": amount,
        "currency": currency_key,
        "sender": sender,
        "receiver": receiver,
        "date": event.message.date.date().isoformat()
    }

    await event.respond(
        f"📌 Разпознах: {amount} {currency_key} от *{sender}* към *{receiver}*.\nКакъв е видът на плащането?",
        buttons=[
            [Button.inline("INCOME", f"income|{user_id}".encode()),
             Button.inline("OUTCOME", f"outcome|{user_id}".encode())],
            [Button.inline("DEPOSIT", f"deposit|{user_id}".encode()),
             Button.inline("WITHDRAW", f"withdraw|{user_id}".encode())]
        ]
    )

# 👆 Обработка на бутони
@client.on(events.CallbackQuery)
async def button_handler(event):
    data = event.data.decode("utf-8")
    action, user_id = data.split("|")

    if user_id not in bot_memory:
        await event.answer("❌ Няма активна операция.")
        return

    payment = bot_memory.pop(user_id)
    col_base = f"{action} {payment['currency']}"
    linked_accounts = airtable.get_linked_accounts()

    sender_id = receiver_id = None
    sender_label = receiver_label = ""

    for norm, (label, record_id) in linked_accounts.items():
        if all(kw in norm for kw in normalize(payment['sender']).split()):
            sender_id = record_id
            sender_label = label
        if all(kw in norm for kw in normalize(payment['receiver']).split()):
            receiver_id = record_id
            receiver_label = label

    if not sender_id or not receiver_id:
        await event.edit("⚠️ Не можах да открия и двете страни в акаунтите.")
        return

    out_fields = {
        "DATE": payment["date"],
        "БАНКА/БУКИ": [sender_id],
        col_base: -abs(payment["amount"]),
        "STATUS": "Pending",
        "ЧИИ ПАРИ": "ФИРМА",
        "NOTES": f"{sender_label} ➡️ {receiver_label}"
    }

    in_fields = {
        "DATE": payment["date"],
        "БАНКА/БУКИ": [receiver_id],
        col_base: abs(payment["amount"]),
        "STATUS": "Pending",
        "ЧИИ ПАРИ": "ФИРМА",
        "NOTES": f"{sender_label} ➡️ {receiver_label}"
    }

    out_result = airtable.add_record(out_fields)
    in_result = airtable.add_record(in_fields)

    if 'id' in out_result and 'id' in in_result:
        await event.edit(f"✅ Два записа добавени успешно:\n\n❌ - {sender_label}\n✅ + {receiver_label}")
    else:
        await event.edit(f"⚠️ Грешка при запис:\nOUT: {out_result}\nIN: {in_result}")

client.run_until_disconnected()
