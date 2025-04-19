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
    "£": ["паунд", "паунда", "paund", "paunda", "gbp", "GBP" "gb"],
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
airtable.get_linked_accounts()  # 🔄 предварително зареждане и кеширане на акаунти


@client.on(events.NewMessage)
async def note_input_handler(event):
    user_id = event.sender_id
    if user_id not in bot_memory:
        return

    if not bot_memory[user_id].get("awaiting_note"):
        return  # не чакаме бележка

    note_text = event.raw_text.strip()
    record_ids = bot_memory[user_id].get("last_airtable_ids", [])

    if not record_ids:
        await event.respond("⚠️ Не са намерени записи.")
        return

    for record_id in record_ids:
        airtable.update_notes(record_id, note_text)

    await event.respond("✅ Бележката беше добавена успешно.")
    bot_memory[user_id]["awaiting_note"] = False


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
    await event.answer("⏳ Момент...")

    data = event.data.decode("utf-8")

    if "|" not in data:
        return  # игнорира бутони без | (например статус бутоните)

    action, user_id = data.split("|")

    if user_id not in bot_memory:
        await event.answer("❌ Няма активна операция.")
        return

    payment = bot_memory.pop(user_id)
    action = action.upper()
    col_base = f"{action} {payment['currency'].upper()}"
    linked_accounts = airtable.get_linked_accounts()

    # 🔽 Вземаме пълното име на потребителя
    sender = await event.get_sender()
    entered_by = f"{sender.first_name or ''} {sender.last_name or ''}".strip()
    if not entered_by:
        entered_by = str(sender.id)  # fallback


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
        "NOTES": f"{sender_label} ➡️ {receiver_label}",
        "Въвел транзакцията": entered_by
    }

    in_fields = {
        "DATE": payment["date"],
        "БАНКА/БУКИ": [receiver_id],
        col_base: abs(payment["amount"]),
        "STATUS": "Pending",
        "ЧИИ ПАРИ": "ФИРМА",
        "NOTES": f"{sender_label} ➡️ {receiver_label}",
        "Въвел транзакцията": entered_by
    }

    bot_memory[event.sender_id] = {
        "out_fields": out_fields,
        "in_fields": in_fields,
        "awaiting_type": "OUT"
    }

    await event.edit(
        f"📌 Избери ВИД за акаунта със знак ❌ (OUT):",
        buttons=[
            [Button.inline("INCOME", b"type_income")],
            [Button.inline("OUTCOME", b"type_outcome")],
            [Button.inline("DEPOSIT", b"type_deposit")],
            [Button.inline("WITHDRAW", b"type_withdraw")],
        ]
    )

    @client.on(events.CallbackQuery(pattern=b'type_(.+)'))
    async def handle_dual_type_selection(event):
        user_id = event.sender_id
        type_selected = event.pattern_match.group(1).decode("utf-8").upper()

        memory = bot_memory.get(user_id)
        if not memory:
            await event.answer("⛔ Няма активна операция.")
            return

        if memory["awaiting_type"] == "OUT":
            memory["out_fields"]["ВИД"] = type_selected
            memory["awaiting_type"] = "IN"

            await event.edit(
                f"📌 Избери ВИД за акаунта със знак ✅ (IN):",
                buttons=[
                    [Button.inline("INCOME", b"type_income")],
                    [Button.inline("OUTCOME", b"type_outcome")],
                    [Button.inline("DEPOSIT", b"type_deposit")],
                    [Button.inline("WITHDRAW", b"type_withdraw")],
                ]
            )

        elif memory["awaiting_type"] == "IN":
            memory["in_fields"]["ВИД"] = type_selected

            out_result = airtable.add_record(memory["out_fields"])
            in_result = airtable.add_record(memory["in_fields"])

            if 'id' in out_result and 'id' in in_result:
                bot_memory[user_id] = {
                    'last_airtable_ids': [out_result['id'], in_result['id']]
                }

        await event.edit(
            f"✅ Два записа добавени успешно:\n\n❌ - {sender_label}\n✅ + {receiver_label}\n\n📌 Избери статус:",
            buttons=[
                [Button.inline("Pending", b"status_pending")],
                [Button.inline("Arrived", b"status_arrived")],
                [Button.inline("Blocked", b"status_blocked")]
            ]
        )
    else:
        await event.edit(f"⚠️ Грешка при запис:\nOUT: {out_result}\nIN: {in_result}")


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


@client.on(events.NewMessage(pattern="/notes"))
async def notes_command_handler(event):
    user_id = event.sender_id
    if user_id not in bot_memory or 'last_airtable_ids' not in bot_memory[user_id]:
        await event.respond("⚠️ Няма последни записи, към които да добавим бележка.")
        return

    bot_memory[user_id]['awaiting_note'] = True
    await event.respond("📝 Каква бележка искаш да добавим към последните два записа?")

    from telethon.tl.custom import Button
    from datetime import datetime, timedelta

    @client.on(events.NewMessage(pattern="/delete"))
    async def delete_with_buttons(event):
        user_id = event.sender_id
        username = event.sender.username or str(user_id)

        recent_records = airtable.get_recent_user_records(username)
        if not recent_records:
            await event.respond("ℹ️ Няма записи от последните 60 минути.")
            return

        # Записваме целите записи временно
        bot_memory[user_id] = {
            "deletable_records": recent_records
        }

        message = "🗂️ Последни записи:\n\n"
        buttons = []

        for i, rec in enumerate(recent_records, start=1):
            date = rec["fields"].get("DATE", "—")
            amount = next((v for k, v in rec["fields"].items() if isinstance(v, (int, float))), "—")
            note = rec["fields"].get("NOTES", "—")
            message += f"{i}. 💸 {amount} | 📅 {date} | 📝 {note}\n"
            buttons.append(Button.inline(f"❌ Изтрий {i}", f"delete_{i}".encode()))

        await event.respond(message + "\n👇 Избери кой да изтрием:", buttons=buttons)


    @client.on(events.CallbackQuery(pattern=b"delete_([0-9]+)"))
    async def handle_delete_button(event):
        user_id = event.sender_id
        index = int(event.pattern_match.group(1)) - 1

        records = bot_memory.get(user_id, {}).get("deletable_records", [])
        if index < 0 or index >= len(records):
            await event.answer("❌ Невалиден запис.", alert=True)
            return

        record = records[index]
        record_id = record["id"]
        note = record["fields"].get("NOTES", "—")

        success = airtable.delete_record(record_id)
        if success:
            await event.edit(f"🗑️ Записът „{note}“ беше изтрит успешно.")
        else:
            await event.edit("⚠️ Възникна грешка при изтриването.")

        # Почисти временната памет
        bot_memory[user_id]["deletable_records"] = []

client.run_until_disconnected()
