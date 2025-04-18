from telethon import TelegramClient, events
from airtable_client import AirtableClient
from dotenv import load_dotenv
from telethon.tl.custom import Button
import os
import datetime
import re

load_dotenv()

# Памет за временни данни от потребители
bot_memory = {}

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

@client.on(events.NewMessage(pattern=r'^Добави:'))
async def handler(event):
    try:
        text = event.raw_text.replace("Добави:", "").strip()
        parts = [p.strip() for p in text.split("|")]

        # 🔍 Взимаме акаунти и търсим по ключови думи
        linked_accounts = airtable.get_linked_accounts()
        record_id = find_matching_account(parts[1], linked_accounts)

        print("🔎 Ключови думи:", parts[1])
        print("📦 Заредени акаунти от Airtable:")
        for norm, (full, rid) in linked_accounts.items():
            print(f"- {full} ➜ {rid} (нормализирано: {norm})")

        if not record_id:
            await event.reply("⚠️ Не можах да открия акаунта по подадените ключови думи.")
            return

        # ✅ Подготвяме запис
        fields = {
            "DATE": event.message.date.date().isoformat(),
            "БАНКА/БУКИ": [record_id],
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
        print("Airtable Response:", result)
        if 'id' in result:
            await event.reply("✅ Записът беше добавен успешно в Airtable!")
        else:
            await event.reply(f"⚠️ Airtable не прие заявката:\n{result}")

    except Exception as e:
        await event.reply(f"⚠️ Грешка: {e}")

# 💬 Разпознаване на изречение като: "100 паунда от X към Y"
@client.on(events.NewMessage)
async def smart_input_handler(event):
    match = re.search(
        r'(\d+(?:[.,]\d{1,2})?)\s*([а-яa-zA-Z.]+)\s+(?:от|ot)\s+(.+?)\s+(?:към|kum|kym)\s+(.+)',
        event.raw_text,
        re.IGNORECASE
    )
    if not match:
        print("❌ Не съвпада с шаблона:", event.raw_text)
        return

    amount = float(match.group(1).replace(",", "."))
    currency_raw = match.group(2).strip()
    sender = match.group(3).strip()
    receiver = match.group(4).strip()

    currency_key = get_currency_key(currency_raw)

    if not currency_key:
        await event.reply("❌ Не мога да разбера валутата. Моля, използвай: лв, lv, паунд, eur, долар и т.н.")
        return

    user_id = event.sender_id
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
            [Button.inline("INCOME", b"income"), Button.inline("OUTCOME", b"outcome")],
            [Button.inline("DEPOSIT", b"deposit"), Button.inline("WITHDRAW", b"withdraw")]
        ]
    )
    
# 👆 Обработка на избрания тип плащане
@client.on(events.CallbackQuery)
async def button_handler(event):
    user_id = event.sender_id
    if user_id not in bot_memory:
        await event.answer("❌ Няма активна операция.")
        return

    action = event.data.decode("utf-8").upper()
    payment = bot_memory.pop(user_id)

    # 🗂️ Генерираме името на колоната според валутата
    col_base = f"{action} {payment['currency']}"  # напр. INCOME BGN

    # Взимаме акаунтите от Airtable
    linked_accounts = airtable.get_linked_accounts()
    print("🔁 Търся по ключови думи:")
    print("🔍 Sender:", payment["sender"])
    print("🔍 Receiver:", payment["receiver"])
    print("📦 Linked accounts:")
    for norm, (full, id_) in linked_accounts.items():
        print(f"➡️ {norm} → {full} ({id_})")

    print("📦 NORMALIZED REG от Airtable:")
    for norm, (original, rid) in linked_accounts.items():
        print(f"- {norm}  →  {original}")

    # 🔍 Търсим акаунти чрез метода от класа AirtableClient
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

    # ❌ OUT запис (от sender)
    out_fields = {
        "DATE": payment["date"],
        "БАНКА/БУКИ": [sender_id],
        col_base: -abs(payment["amount"]),  # винаги отрицателно
        "STATUS": "Pending",
        "ЧИИ ПАРИ": "ФИРМА",
        "NOTES": f"{sender_label} ➡️ {receiver_label}"
    }

    # ✅ IN запис (в receiver)
    in_fields = {
        "DATE": payment["date"],
        "БАНКА/БУКИ": [receiver_id],
        col_base: abs(payment["amount"]),
        "STATUS": "Pending",
        "ЧИИ ПАРИ": "ФИРМА",
        "NOTES": f"{sender_label} ➡️ {receiver_label}"
    }

    # Записваме и двата реда
    out_result = airtable.add_record(out_fields)
    in_result = airtable.add_record(in_fields)

    if 'id' in out_result and 'id' in in_result:
       await event.edit(
    f"✅ Два записа бяха добавени успешно:\n\n❌ - {sender_label}\n✅ + {receiver_label}"
)
    else:
        await event.edit(f"⚠️ Грешка при запис:\nOUT: {out_result}\nIN: {in_result}")

client.run_until_disconnected()
