import os
import requests

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
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def get_linked_accounts(self):
        url = f"https://api.airtable.com/v0/{self.base_id}/ВСИЧКИ%20АКАУНТИ"
        response = requests.get(url, headers=self.headers)
        data = response.json()

        mapping = {}
        for record in data.get("records", []):
            full_name = record["fields"].get("REG")
            if full_name:
                normalized = normalize(full_name)
                mapping[normalized] = (full_name, record["id"])

        return mapping

    def find_matching_account(self, user_input, account_dict=None):
    if account_dict is None:
        account_dict = self.get_linked_accounts()

    input_keywords = normalize(user_input).split()
    print(f"\n🔍 Търсим за: '{user_input}' → ключови думи: {input_keywords}\n")

    for normalized_name, (original, record_id) in account_dict.items():
        print(f"🔎 Сравняваме с: {normalized_name}")
        if all(keyword in normalized_name for keyword in input_keywords):
            print(f"✅ НАМЕРЕНО: {original} (ID: {record_id})")
            return record_id

    print("❌ Нищо не съвпадна.")
    return None

    def add_record(self, fields: dict):
        data = {
            "fields": fields
        }
        response = requests.post(self.endpoint, headers=self.headers, json=data)
        return response.json()
