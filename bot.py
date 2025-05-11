from telethon import TelegramClient, events
from airtable_client import AirtableClient
from dotenv import load_dotenv
from telethon.tl.custom import Button
import os
import re
from datetime import datetime, timedelta
import asyncio

load_dotenv()

bot_memory = {}

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

@client.on(events.NewMessage(pattern="/refresh"))
async def refresh_accounts(event):
    airtable.get_linked_accounts(force_refresh=True)
    await event.respond("🔄 Акаунтите са опреснени.")

async def refresh_accounts_periodically():
    while True:
        airtable.get_linked_accounts(force_refresh=True)
        print("🔁 Акаунтите са автоматично опреснени.")
        await asyncio.sleep(300)  # 5 минути

@client.on(events.NewMessage)
async def message_router(event):
    user_id = event.sender_id
    text = event.raw_text.strip()

    if bot_memory.get(user_id, {}).get("awaiting_note"):
        note_text = text
        record_ids = bot_memory[user_id].get("last_airtable_ids", [])
        if not record_ids:
            await event.respond("⚠️ Не са намерени записи.")
            return
        for record_id in record_ids:
            airtable.update_notes(record_id, note_text)
        await event.respond("✅ Бележката беше добавена успешно.")
        bot_memory[user_id]["awaiting_note"] = False
        return

    if text.startswith("/notes"):
        if user_id not in bot_memory or 'last_airtable_ids' not in bot_memory[user_id]:
            await event.respond("⚠️ Няма последни записи, към които да добавим бележка.")
            return
        bot_memory[user_id]['awaiting_note'] = True
        await event.respond("📝 Каква бележка искаш да добавим към последните два записа?")
        return

    if text.startswith("/delete"):
        username = event.sender.username or str(user_id)
        recent_records = airtable.get_recent_user_records(username)
        if not recent_records:
            await event.respond("ℹ️ Няма записи от последните 60 минути.")
            return
        bot_memory[user_id] = {"deletable_records": recent_records}
        message = "🗂️ Последни записи:\n\n"
        buttons = []
        for i, rec in enumerate(recent_records, start=1):
            date = rec["fields"].get("DATE", "—")
            amount = next((v for k, v in rec["fields"].items() if isinstance(v, (int, float))), "—")
            note = rec["fields"].get("NOTES", "—")
            message += f"{i}. 💸 {amount} | 📅 {date} | 📝 {note}\n"
            buttons.append(Button.inline(f"❌ Изтрий {i}", f"delete_{i}".encode()))
        await event.respond(message + "\n👇 Избери кой да изтрием:", buttons=buttons)
        return

    match = re.search(
        r'(\d+(?:[.,]\d{1,2})?)\s*([а-яa-zA-Z.]+)\s+(?:от|ot)\s+(.+?)\s+(?:към|kum|kym|kam)\s+(?:(лв|лева|leva|евро|evro|EUR|eur|usd|USD|dolara|долар|долара|паунд|paunda|paund|gbp|BGN|EUR|USD|GBP)\s+)?(.+)',
        text,
        re.IGNORECASE
    )
    if not match:
        return

    amount = float(match.group(1).replace(",", "."))
    currency_raw = match.group(2).strip()
    sender = match.group(3).strip()
    receiver_currency_raw = match.group(4)  # Може да е None
    receiver = match.group(5).strip()

    currency_key = get_currency_key(currency_raw)
    if not currency_key:
        await event.reply("❌ Неразпозната валута на изпращача.")
        return

    receiver_currency_key = get_currency_key(receiver_currency_raw) if receiver_currency_raw else currency_key
    if receiver_currency_raw and not receiver_currency_key:
        await event.reply("❌ Неразпозната валута на получателя.")
        return

    sender_obj = await event.get_sender()
    entered_by = f"{sender_obj.first_name or ''} {sender_obj.last_name or ''}".strip()
    if not entered_by:
        entered_by = str(user_id)

    linked_accounts = airtable.get_linked_accounts()

    sender_id = receiver_id = None
    sender_label = receiver_label = ""

    for norm, (label, record_id) in linked_accounts.items():
        if all(kw in norm for kw in normalize(sender).split()):
            sender_id = record_id
            sender_label = label
        if all(kw in norm for kw in normalize(receiver).split()):
            receiver_id = record_id
            receiver_label = label

    if not sender_id or not receiver_id:
        await event.reply("⚠️ Не можах да открия и двете страни в акаунтите.")
        return

    bot_memory[user_id] = {
        "base_data": {
            "amount": amount,
            "currency": currency_key,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "sender_label": sender_label,
            "receiver_label": receiver_label,
            "date": datetime.now().isoformat(),
            "entered_by": entered_by,
            "receiver_currency": receiver_currency_key
        },
        "step": "await_out_type"
    }

    await event.respond(
        "📌 Избери ВИД за акаунта със знак ❌ (OUT):",
        buttons=[
            [Button.inline("INCOME", b"type_out_income")],
            [Button.inline("OUTCOME", b"type_out_outcome")],
            [Button.inline("DEPOSIT", b"type_out_deposit")],
            [Button.inline("WITHDRAW", b"type_out_withdraw")],
        ]
    )

@client.on(events.CallbackQuery(pattern=b"type_(out|in)_(.+)"))
async def handle_type_selection(event):
    user_id = event.sender_id
    match = event.pattern_match
    direction = match.group(1).decode("utf-8")
    tx_type = match.group(2).decode("utf-8").upper()

    memory = bot_memory.get(user_id)
    if not memory:
        await event.answer("⛔ Няма активна операция.")
        return

    base = memory["base_data"]
    col_base = f"{tx_type} {base['currency'].upper()}"

    if direction == "out":
        memory["out_fields"] = {
            "DATE": base["date"],
            "БАНКА/БУКИ": [base["sender_id"]],
            col_base: -abs(base["amount"]),
            "STATUS": "Pending",
            "Въвел транзакцията": base["entered_by"]
        }
        memory["step"] = "await_in_type"
        await event.edit(
            "📌 Избери ВИД за акаунта със знак ✅ (IN):",
            buttons=[
                [Button.inline("INCOME", b"type_in_income")],
                [Button.inline("OUTCOME", b"type_in_outcome")],
                [Button.inline("DEPOSIT", b"type_in_deposit")],
                [Button.inline("WITHDRAW", b"type_in_withdraw")],
            ]
        )

    elif direction == "in":
        out_currency = base["currency"]  # оригинална валута от изпращача
        in_currency = base["receiver_currency"] # валута на получателя

        converted_amount = base["amount"]

        # Проверка дали трябва да превалутираме
        if out_currency != in_currency:
            # Извличаме курса от airtable_client
            rate = airtable.get_exchange_rate(out_currency, in_currency)
            if not rate:
                await event.edit("⚠️ Грешка при извличане на валутен курс.")
                return
            # изчисляваме сумата по новия курс
            converted_amount = round(base["amount"] * rate, 2)

        # записваме входящия ред в Airtable с конвертираната валута
        memory["in_fields"] = {
            "DATE": base["date"],
            "БАНКА/БУКИ": [base["receiver_id"]],
            f"{tx_type} {in_currency.upper()}": abs(converted_amount),
            "STATUS": "Pending",
            "Въвел транзакцията": base["entered_by"]
        }

        # записваме изходящия и входящия ред
        out_result = airtable.add_record(memory["out_fields"])
        in_result = airtable.add_record(memory["in_fields"])

        # проверка дали записът е успешен
        if 'id' in out_result and 'id' in in_result:
            bot_memory[user_id] = {
                'last_airtable_ids': [out_result['id'], in_result['id']]
            }
            await event.edit(
                "✅ Въведена транзакция с превалутиране. 📌 Избери статус:",
                buttons=[
                    [Button.inline("Pending", b"status_pending")],
                    [Button.inline("Arrived", b"status_arrived")],
                    [Button.inline("Blocked", b"status_blocked")]
                ]
            )
        else:
            await event.edit("⚠️ Грешка при запис.")

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
    bot_memory[user_id]["deletable_records"] = []

@client.on(events.CallbackQuery(pattern=b'status_(pending|arrived|blocked)'))
async def handle_status_selection(event):
    status_value = event.pattern_match.group(1).decode("utf-8").capitalize()
    user_id = event.sender_id
    last_ids = bot_memory.get(user_id, {}).get('last_airtable_ids', [])

    if not last_ids:
        await event.answer("❌ Няма запазени записи за обновяване.", alert=True)
        return

    for record_id in last_ids:
        airtable.update_status(record_id, status_value)

    await event.edit(f"📌 Статусът е зададен на: {status_value}")

loop = asyncio.get_event_loop()
loop.create_task(refresh_accounts_periodically())
client.run_until_disconnected()
