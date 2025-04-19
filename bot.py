from telethon import TelegramClient, events
from airtable_client import AirtableClient
from dotenv import load_dotenv
from telethon.tl.custom import Button
import os
import re
from datetime import datetime, timedelta

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
    "£": ["паунд", "паунда", "paund", "paunda", "gbp", "GBP", "gb"],
    "BGN": ["лв", "лева", "lv", "lw", "BGN", "bgn"],
    "EU": ["евро", "eur", "euro", "evro", "ewro", "EURO"],
    "USD": ["долар", "долара", "usd", "dolar", "dolara", "USD"]
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
airtable.get_linked_accounts()

@client.on(events.NewMessage)
async def smart_input_handler(event):
    match = re.search(
        r'(\d+(?:[.,]\d{1,2})?)\s*([а-яa-zA-Z.]+)\s+(?:от|ot)\s+(.+?)\s+(?:към|kum|kym|kam)\s+(.+)',
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

    await event.respond("📌 Въведена транзакция. Моля, изчакайте…")

    # Тригерваме обработката на бутона за OUT автоматично
    fake_event = type("Fake", (), {"data": f"out_trigger|{user_id}".encode(), "sender_id": event.sender_id, "get_sender": event.get_sender, "answer": event.answer, "edit": event.respond})()
    await button_handler(fake_event)

@client.on(events.CallbackQuery)
async def button_handler(event):
    data = event.data.decode("utf-8")

    if "|" not in data:
        return

    action, user_id = data.split("|")

    if user_id not in bot_memory:
        await event.answer("❌ Няма активна операция.")
        return

    if action == "out_trigger":
        payment = bot_memory[user_id]
        linked_accounts = airtable.get_linked_accounts()

        sender = await event.get_sender()
        entered_by = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or str(sender.id)

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

        bot_memory[event.sender_id] = {
            "common": payment,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "sender_label": sender_label,
            "receiver_label": receiver_label,
            "entered_by": entered_by,
            "step": "awaiting_out_type"
        }

        await event.edit(
            f"📌 Избери ВИД за акаунта със знак ❌ (OUT):",
            buttons=[
                [Button.inline("INCOME", b"out_type_INCOME"), Button.inline("OUTCOME", b"out_type_OUTCOME")],
                [Button.inline("DEPOSIT", b"out_type_DEPOSIT"), Button.inline("WITHDRAW", b"out_type_WITHDRAW")],
            ]
        )

@client.on(events.CallbackQuery(pattern=b'(out|in)_type_(INCOME|OUTCOME|DEPOSIT|WITHDRAW)'))
async def handle_type_selection(event):
    direction, tx_type = event.pattern_match.group(1).decode(), event.pattern_match.group(2).decode()
    user_id = event.sender_id

    memory = bot_memory.get(user_id)
    if not memory:
        await event.answer("⛔ Няма активна операция.")
        return

    currency = memory["common"]["currency"]
    amount = abs(memory["common"]["amount"])
    col = f"{tx_type} {currency}"

    if direction == "out":
        memory["out_fields"] = {
            "DATE": memory["common"]["date"],
            "БАНКА/БУКИ": [memory["sender_id"]],
            col: -amount,
            "STATUS": "Pending",
            "ЧИИ ПАРИ": "ФИРМА",
            "NOTES": f"{memory['sender_label']} ➡️ {memory['receiver_label']}",
            "Въвел транзакцията": memory["entered_by"],
            "ВИД": tx_type
        }
        memory["step"] = "awaiting_in_type"

        await event.edit(
            f"📌 Избери ВИД за акаунта със знак ✅ (IN):",
            buttons=[
                [Button.inline("INCOME", b"in_type_INCOME"), Button.inline("OUTCOME", b"in_type_OUTCOME")],
                [Button.inline("DEPOSIT", b"in_type_DEPOSIT"), Button.inline("WITHDRAW", b"in_type_WITHDRAW")],
            ]
        )

    elif direction == "in":
        memory["in_fields"] = {
            "DATE": memory["common"]["date"],
            "БАНКА/БУКИ": [memory["receiver_id"]],
            col: amount,
            "STATUS": "Pending",
            "ЧИИ ПАРИ": "ФИРМА",
            "NOTES": f"{memory['sender_label']} ➡️ {memory['receiver_label']}",
            "Въвел транзакцията": memory["entered_by"],
            "ВИД": tx_type
        }

        out_result = airtable.add_record(memory["out_fields"])
        in_result = airtable.add_record(memory["in_fields"])

        if 'id' in out_result and 'id' in in_result:
            bot_memory[user_id] = {
                'last_airtable_ids': [out_result['id'], in_result['id']]
            }

            await event.edit(
                "✅ И двата реда са записани успешно.\n\n📌 Избери статус:",
                buttons=[
                    [Button.inline("Pending", b"status_pending")],
                    [Button.inline("Arrived", b"status_arrived")],
                    [Button.inline("Blocked", b"status_blocked")],
                ]
            )
        else:
            await event.edit(f"⚠️ Грешка при запис:\nOUT: {out_result}\nIN: {in_result}")

        del bot_memory[user_id]

@client.on(events.CallbackQuery(pattern=b'status_(pending|arrived|blocked)'))
async def handle_status_selection(event):
    status_value = event.pattern_match.group(1)
    if isinstance(status_value, bytes):
        status_value = status_value.decode("utf-8")
    status_value = status_value.capitalize()

    user_id = event.sender_id
    last_ids = bot_memory.get(user_id, {}).get('last_airtable_ids', [])

    if not last_ids:
        await event.answer("❌ Няма запазени записи за обновяване.", alert=True)
        return

    for record_id in last_ids:
        airtable.update_status(record_id, status_value)

    await event.edit(f"📌 Статусът е зададен на: {status_value}")

client.run_until_disconnected()
