import os
import requests
import difflib

CURRENCY_SYNONYMS = {
    "£": ["паунд", "паунда", "paund", "paunda", "gbp", "GBP", "gb"],
    "BGN": ["лв", "лева", "lv", "lw", "BGN", "bgn"],
    "EU": ["евро", "eur", "euro", "evro", "ewro", "EURO"],
    "USD": ["долар", "долара", "usd", "dolar", "dolara", "USD"]
}

def normalize_currency(currency):
    """Нормализира валутата към стандартен формат (BGN, USD, GBP, EU)."""
    currency = currency.lower().strip()
    for key, synonyms in CURRENCY_SYNONYMS.items():
        if currency in synonyms:
            return key
    return None  # Ако валутата не е разпозната

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

class AirtableClient:
    def __init__(self):
        self.token = os.getenv("AIRTABLE_PAT")
        self.base_id = os.getenv("AIRTABLE_BASE_ID")
        self.table_name = os.getenv("AIRTABLE_TABLE_NAME")
        self.endpoint = f"https://api.airtable.com/v0/{self.base_id}/{self.table_name}"
        self.base_url = f"https://api.airtable.com/v0/{self.base_id}"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self.cached_accounts = None  # Кеширан списък с акаунти

    def get_exchange_rate(self, from_currency, to_currency):
        from_currency = normalize_currency(from_currency)
        to_currency = normalize_currency(to_currency)

        if not from_currency or not to_currency:
            print(f"❌ Неразпозната валута: {from_currency} или {to_currency}")
            return None

        API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")
        url = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/{from_currency}"

        try:
            response = requests.get(url)
            response.raise_for_status()  # Ще хвърли грешка, ако статус кодът не е 200
            data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Грешка при заявката към API: {e}")
            return None

        if data.get("result") == "success":
            rate = data["conversion_rates"].get(to_currency)
            if rate:
                print(f"📈 Търсен курс: 1 {from_currency} → {to_currency} = {rate}")
                return rate

        print("❌ Грешка: result != success или липсва валутен курс.")
        return None

    def update_notes(self, record_id, note):  # ⬅️ напълно отделна функция, със същия отстъп като всички методи
        url = f"{self.base_url}/{self.table_name}/{record_id}"
        data = {
            "fields": {
                "NOTES": note
            }
        }

        response = requests.patch(url, json=data, headers=self.headers, params={"typecast": "true"})
        print(f"📝 Обновен NOTES за {record_id}: {response.status_code} – {response.text}")

        if response.status_code != 200:
            print(f"❌ Грешка при обновяване на NOTES за {record_id}: {response.text}")
            return False
        return True

    def get_linked_accounts(self, force_refresh=False):
        if hasattr(self, 'cached_accounts') and self.cached_accounts and not force_refresh:
            return self.cached_accounts

        url = f"https://api.airtable.com/v0/{self.base_id}/ВСИЧКИ%20АКАУНТИ"
        mapping = {}
        offset = None

        while True:
            full_url = url
            if offset:
                full_url += f"?offset={offset}"

            response = requests.get(full_url, headers=self.headers)
            if response.status_code != 200:
                print(f"❌ Грешка при извличане на акаунти: {response.status_code} – {response.text}")
                return {}

            data = response.json()

            for record in data.get("records", []):
                full_name = record["fields"].get("REG")
                if full_name:
                    normalized = normalize(full_name)
                    mapping[normalized] = (full_name, record["id"])

            offset = data.get("offset")
            if not offset:
                break

        self.cached_accounts = mapping
        return self.cached_accounts


    def find_matching_account(self, user_input, account_dict=None):
        if account_dict is None:
            account_dict = self.get_linked_accounts()

        user_input_norm = normalize(user_input)
        print(f"\n🔍 Търсим fuzzy: '{user_input}' → '{user_input_norm}'")

        possible_matches = list(account_dict.keys())
        best = difflib.get_close_matches(user_input_norm, possible_matches, n=1, cutoff=0.5)

        if best:
            matched_key = best[0]
            original, record_id = account_dict[matched_key]
            print(f"✅ Най-близък fuzzy match: {original} ({record_id})")
            return record_id

        print("❌ Няма близко съвпадение.")
        return None

    def add_record(self, fields: dict):
        data = {"fields": fields}
        response = requests.post(self.endpoint, headers=self.headers, json=data)
        if response.status_code != 200:
            print(f"❌ Грешка при добавяне на запис: {response.status_code} – {response.text}")
            return None
        return response.json()

    def update_status(self, record_id, status):
        print(f"➡️ Обновяване на запис: {record_id} със STATUS: {status}")

        url = f"{self.base_url}/{self.table_name}/{record_id}"
        data = {
            "fields": {
                "STATUS": status
            }
        }

        response = requests.patch(url, json=data, headers=self.headers, params={"typecast": "true"})

        print("⬅️ Отговор от Airtable:", response.status_code, response.text)

        if response.status_code != 200:
            print(f"❌ Грешка при обновяване на {record_id}: {response.text}")

        from datetime import datetime, timedelta

    def get_recent_user_records(self, user_filter_text, within_minutes=60):
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=within_minutes)
        cutoff_iso = cutoff.isoformat()

        filter_formula = f"AND(IS_AFTER(DATE, '{cutoff_iso}'), FIND('{user_filter_text}', {{NOTES}}))"
        url = f"{self.endpoint}?filterByFormula={filter_formula}"

        response = requests.get(url, headers=self.headers)
        data = response.json()

        return data.get("records", [])

    def delete_record(self, record_id):
        url = f"{self.base_url}/{self.table_name}/{record_id}"
        response = requests.delete(url, headers=self.headers)
        print(f"🗑️ Изтриване на запис {record_id}: {response.status_code}")
        if response.status_code != 200:
            print(f"❌ Грешка при изтриване на запис {record_id}: {response.text}")
            return False
        return True

