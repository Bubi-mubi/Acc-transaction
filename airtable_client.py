import os
import requests
import difflib
from dotenv import load_dotenv

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
        load_dotenv()
        self.token = os.getenv("AIRTABLE_PAT")
        self.base_id = os.getenv("AIRTABLE_BASE_ID")

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        self.endpoint = f"https://api.airtable.com/v0/{self.base_id}/AccTransaction"

    def add_record(self, fields: dict):
        """Добавя нов запис в AccTransaction."""
        data = {"fields": fields}
        response = requests.post(self.endpoint, headers=self.headers, json=data)
        return response.json()

    def update_record(self, record_id: str, fields: dict):
        """Обновява съществуващ запис по ID."""
        url = f"{self.endpoint}/{record_id}"
        data = {"fields": fields}
        response = requests.patch(url, headers=self.headers, json=data)
        return response.json()

    def get_linked_accounts(self):
        """Връща нормализирана карта на акаунти от таблица ВСИЧКИ АКАУНТИ."""
        url = f"https://api.airtable.com/v0/{self.base_id}/ВСИЧКИ%20АКАУНТИ"
        mapping = {}
        offset = None

        while True:
            full_url = url
            if offset:
                full_url += f"?offset={offset}"

            response = requests.get(full_url, headers=self.headers)
            data = response.json()

            for record in data.get("records", []):
                full_name = record["fields"].get("REG")
                if full_name:
                    normalized = normalize(full_name)
                    mapping[normalized] = (full_name, record["id"])

            offset = data.get("offset")
            if not offset:
                break

        return mapping

    def find_matching_account(self, user_input, account_dict=None):
        """Извършва fuzzy match на акаунт по име."""
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

    def get_status_records(self):
        """Връща статуси от таблица STATUS, като STAT → record ID."""
        url = f"https://api.airtable.com/v0/{self.base_id}/STATUS"
        response = requests.get(url, headers=self.headers)

        if response.status_code != 200:
            print("❌ Грешка при зареждане на статуси:", response.status_code, response.text)
            return {}

        records = response.json().get("records", [])
        return {
            record["fields"]["STAT"]: record["id"]
            for record in records
            if "STAT" in record["fields"]
        }
