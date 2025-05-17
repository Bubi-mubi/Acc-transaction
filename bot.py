from telethon import TelegramClient, events
from airtable_client import AirtableClient
from dotenv import load_dotenv
from telethon.tl.custom import Button
import os
import re
from datetime import datetime, timedelta
import asyncio
import requests

load_dotenv()

bot_memory = {}
cached_rates = {}

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

def get_cached_exchange_rate(from_currency, to_currency):
    if (from_currency, to_currency) not in cached_rates:
        rate = airtable.get_exchange_rate(from_currency, to_currency)
        if rate:
            cached_rates[(from_currency, to_currency)] = rate
    return cached_rates.get((from_currency, to_currency))

class AirtableClient:
    def __init__(self):
        self.exchange_rate_cache = {}

    def get_exchange_rate(self, from_currency, to_currency):
        # Проверка за валидни кодове на валути
        valid_currencies = ["GBP", "BGN", "USD", "EUR"]
        if from_currency not in valid_currencies or to_currency not in valid_currencies:
            print(f"❌ Невалиден код на валута: {from_currency} или {to_currency}")
            return None

        # Проверка за кеширани курсове
        cache_key = f"{from_currency}_{to_currency}"
        if cache_key in self.exchange_rate_cache:
            cached_rate, timestamp = self.exchange_rate_cache[cache_key]
            if (datetime.utcnow() - timestamp).seconds < 3600:  # Кешът е валиден за 1 час
                print(f"📥 Използване на кеширан курс: 1 {from_currency} → {to_currency} = {cached_rate}")
                return cached_rate

        # Ако няма кеш, извличаме курса от API
        API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")
        url = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/{from_currency}"

        try:
            response = requests.get(url)
            if response.status_code != 200:
                print(f"❌ Грешка при заявката: status {response.status_code}")
                print("Сървър върна:", response.text)
                return None

            data = response.json()
            print("📊 Пълен отговор от API:", data)
        except Exception as e:
            print(f"❌ Изключение при получаване на курс: {e}")
            return None

        if data.get("result") == "success":
            rate = data["conversion_rates"].get(to_currency)
            if rate:
                print(f"📈 Търсен курс: 1 {from_currency} → {to_currency} = {rate}")
                # Запазване на курса в кеша
                self.exchange_rate_cache[cache_key] = (rate, datetime.utcnow())
                return rate

        print("❌ Грешка: result != success или липсва валутен курс.")
        return None

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)
airtable = AirtableClient()
airtable.get_linked_accounts()

# Тест с валидни валути
rate = airtable.get_exchange_rate("GBP", "BGN")
print(f"Курс GBP → BGN: {rate}")

# Тест с невалидна валута
rate = airtable.get_exchange_rate("INVALID", "BGN")
print(f"Курс INVALID → BGN: {rate}")

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

    # Регулярен израз за разпознаване на съобщения
    match = re.search(
        r'(\d+(?:[.,]\d{1,2})?)\s*([а-яa-zA-Z.]+)\s+(?:от|ot)\s+(.+?)\s+(?:към|kum|kym|kam)\s+(?:(лв|лева|leva|евро|evro|EUR|eur|usd|USD|dolara|долар|долара|паунд|paunda|paund|gbp|BGN|EUR|USD|GBP)\s+)?(.+)',
        text,
        re.IGNORECASE
    )
    if not match:
        return

    # Извличане на данни от съобщението
    amount = float(match.group(1).replace(",", "."))
    currency_raw = match.group(2).strip()
    sender = match.group(3).strip()
    receiver_currency_raw = match.group(4)  # Може да е None
    receiver = match.group(5).strip()

    # Разпознаване на валутите
    currency_key = get_currency_key(currency_raw)
    if not currency_key:
        await event.reply("❌ Неразпозната валута на изпращача.")
        return

    receiver_currency_key = get_currency_key(receiver_currency_raw) if receiver_currency_raw else currency_key
    if receiver_currency_raw and not receiver_currency_key:
        await event.reply("❌ Неразпозната валута на получателя.")
        return

    # Извличане на акаунти
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

    # Превалутиране, ако е необходимо
    converted_amount = amount
    if currency_key != receiver_currency_key:
        rate = get_cached_exchange_rate(currency_key, receiver_currency_key)
        if not rate:
            await event.reply("⚠️ Грешка при извличане на валутен курс.")
            return
        converted_amount = round(amount * rate, 2)

    # Запис в Airtable
    out_record = {
        "DATE": datetime.now().isoformat(),
        "БАНКА/БУКИ": [sender_id],
        f"OUT {currency_key.upper()}": -abs(amount),
        "STATUS": "Pending",
        "Въвел транзакцията": f"{event.sender.first_name or ''} {event.sender.last_name or ''}".strip()
    }
    in_record = {
        "DATE": datetime.now().isoformat(),
        "БАНКА/БУКИ": [receiver_id],
        f"IN {receiver_currency_key.upper()}": abs(converted_amount),
        "STATUS": "Pending",
        "Въвел транзакцията": f"{event.sender.first_name or ''} {event.sender.last_name or ''}".strip()
    }

    out_result = airtable.add_record(out_record)
    in_result = airtable.add_record(in_record)

    if 'id' in out_result and 'id' in in_result:
        bot_memory[user_id] = {
            'last_airtable_ids': [out_result['id'], in_result['id']]
        }
        await event.reply(
            "✅ Транзакцията е записана успешно с превалутиране.",
            buttons=[
                [Button.inline("Pending", b"status_pending")],
                [Button.inline("Arrived", b"status_arrived")],
                [Button.inline("Blocked", b"status_blocked")]
            ]
        )
    else:
        await event.reply("⚠️ Грешка при запис в Airtable.")

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
            rate = get_cached_exchange_rate(out_currency, in_currency)
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