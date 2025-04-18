from telethon import TelegramClient, events
from airtable_client import AirtableClient
from dotenv import load_dotenv
from telethon.tl.custom import Button
import os
import re

load_dotenv()

bot_memory = {}
user_last_records = {}

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

# 💬 Старт на нов запис
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

    await event.reply(
        f"📌 Разпознах: {amount} {currency_key} от *{sender}* към *{receiver}*.\nКакъв е видът на плащането?",
        buttons=[
            [Button.inline("INCOME", f"income|{user_id}".encode()),
             Button.inline("OUTCOME", f"outcome|{user_id}".encode())],
            [Button.inline("DEPOSIT", f"deposit|{user_id}".encode()),
             Button.inline("WITHDRAW", f"withdraw|{user_id}".encode())]
        ]
    )

# 🟡 Бутони: тип трансакция → статус → запис
@client.on(events.CallbackQuery)
async def button_handler(event):
    data = event.data.decode("utf-8")
    print("▶️ Callback data:", data)
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
                [Button.inline("🟡 Pending", f"status|🟡 Pending|{user_id}".encode())],
                [Button.inline("🔴 Blocked", f"status|🔴 Blocked|{user_id}".encode())],
                [Button.inline("🟢 Arrived", f"status|🟢 Arrived|{user_id}".encode())]
            ])
        return

    if action == "status":
        status = parts[1].strip()
        bot_memory[user_id]["status"] = status
        await save_transfer(event, user_id)

# ✅ Запис в Airtable
async def save_transfer(event, user_id):
    data = bot_memory.get(user_id)
    col_base = f"{data['action']} {data['currency']}".upper()
    linked_accounts = airtable.get_linked_accounts()

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
    status = data["status"]

    status_name = data.get("status", "").strip()
    status_options = airtable.get_status_options()

    if status_name not in status_options:
        await event.respond(f"⚠️ Статусът `{status_name}` не съществува в таблицата STATUS.")
        return

    status_record_id = status_options[status_name]

    # 🧠 Вземаме Record ID от таблицата STATUS
    status_text = data.get("status", "")
    status_id = None

    # Извличаме всички статуси от таблицата STATUS
    status_table = airtable.get_table("STATUS")
    for record in status_table:
        if record["fields"].get("STAT") == status_text:
            status_id = record["id"]
            break

    # Ако не е намерен, информираме потребителя
    if not status_id:
        await event.respond(f"⚠️ Статусът {status_text} не съществува в таблицата STATUS.")
        return

    fields_common = {
        "DATE": data["date"],
        "STATUS": [status_id],  # това вече е истински record ID
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

    out_result = airtable.add_record(out_fields)
    in_result = airtable.add_record(in_fields)

    if 'id' in out_result and 'id' in in_result:
        await event.respond(f"✅ Записите са добавени успешно:\n❌ {sender_label}\n✅ {receiver_label}")
        user_last_records[user_id] = [out_result['id'], in_result['id']]
    else:
        await event.respond(f"⚠️ Грешка при запис:\nOUT: {out_result}\nIN: {in_result}")

    # 🧹 Почистваме след това
    bot_memory.pop(user_id, None)

# 📝 Добавяне на бележка
@client.on(events.NewMessage(pattern=r'^/notes'))
async def handle_notes(event):
    user_id = str(event.sender_id)
    if user_id not in user_last_records:
        await event.reply("⚠️ Няма наскорошна трансакция, към която да добавя бележка.")
        return

    await event.reply("✍️ Моля, напиши бележката:")

    @client.on(events.NewMessage(from_users=event.sender_id))
    async def capture_note(note_event):
        note = note_event.raw_text
        record_ids = user_last_records[user_id]

        for record_id in record_ids:
            airtable.update_record(record_id, {"NOTES": note})

        await note_event.reply("📝 Бележката беше успешно записана към последната трансакция.")
        client.remove_event_handler(capture_note)

client.run_until_disconnected()
