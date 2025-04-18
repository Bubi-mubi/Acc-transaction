# 🟩 bot.py

from telethon import TelegramClient, events
from dotenv import load_dotenv
from telethon.tl.custom import Button
import os
import re
from airtable_client import AirtableClient

load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)
airtable = AirtableClient()

bot_memory = {}
user_last_records = {}

# 🧠 Възможните колони с пари, по твоята Airtable таблица
VALID_AMOUNT_COLUMNS = [
    "INCOME £", "OUTCOME £", "DEPOSIT £", "WITHDRAW £",
    "INCOME BGN", "OUTCOME BGN", "DEPOSIT BGN", "WITHDRAW BGN",
    "INCOME EU", "OUTCOME EU", "DEPOSIT EU", "WITHDRAW EU"
]

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

@client.on(events.NewMessage)
async def smart_input_handler(event):
    if event.raw_text.startswith("/notes"):
        return

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

@client.on(events.CallbackQuery)
async def button_handler(event):
    data = event.data.decode("utf-8")
    parts = data.split("|")

    if len(parts) < 2:
        await event.answer("❌ Невалиден бутон.")
        return

    action = parts[0]
    user_id = str(parts[-1])

    if user_id not in bot_memory:
        await event.answer("❌ Няма активна операция.")
        return

    if len(parts) == 2:
        bot_memory[user_id]["action"] = action.upper()
        await event.edit("🟡 Какъв е статусът на трансакцията?",
            buttons=[
                [Button.inline("Pending", f"status|Pending|{user_id}".encode())],
                [Button.inline("Blocked", f"status|Blocked|{user_id}".encode())],
                [Button.inline("Arrived", f"status|Arrived|{user_id}".encode())]
            ])
        return

    if action == "status":
        status = parts[1].strip().title()
        bot_memory[user_id]["status"] = status
        await save_transfer(event, user_id)

async def save_transfer(event, user_id):
    data = bot_memory.get(user_id)
    action = data['action']
    currency = data['currency']
    col_base = f"{action} {currency}".upper()

    if col_base not in VALID_AMOUNT_COLUMNS:
        await event.respond(f"❌ Колона `{col_base}` не съществува. Провери дали има такава в Airtable.")
        return

    linked_accounts = airtable.get_linked_accounts_from_table("ВСИЧКИ АКАУНТИ")

    sender_id = receiver_id = None
    sender_label = receiver_label = ""

    for norm, (label, record_id) in linked_accounts.items():
        if all(kw in norm for kw in normalize(data['sender']).split()):
            sender_id = record_id
            sender_label = label
        if all(kw in norm for kw in normalize(data['receiver']).split()):
            receiver_id = record_id
            receiver_label = label

    if not sender_id or not receiver_id:
        await event.respond("⚠️ Не можах да открия и двете страни в акаунтите.")
        return

    fields_common = {
        "DATE": data["date"],
        "ТРАНЗАКЦИЯ СТАТУС": data.get("status", ""),
        "ЧИИ ПАРИ": "",
        "NOTES": ""
    }

    out_fields = {
        **fields_common,
        "БАНКА/БУКИ": [sender_id],
        col_base: -abs(data["amount"]),
    }

    in_fields = {
        **fields_common,
        "БАНКА/БУКИ": [receiver_id],
        col_base: abs(data["amount"]),
    }

    out_result = airtable.add_record_to_table("Acc Transaction", out_fields)
    in_result = airtable.add_record_to_table("Acc Transaction", in_fields)

    if 'id' in out_result and 'id' in in_result:
        await event.respond(f"✅ Записите са добавени успешно:\n❌ {sender_label}\n✅ {receiver_label}")
        user_last_records[user_id] = [out_result['id'], in_result['id']]
    else:
        await event.respond(f"⚠️ Грешка при запис:\nOUT: {out_result}\nIN: {in_result}")

    bot_memory.pop(user_id, None)
