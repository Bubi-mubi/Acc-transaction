import os
import requests
import difflib

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
        return response.json()

    def update_status(self, record_id, status):
        url = f"{self.base_url}/{self.table_name}/{record_id}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "fields": {
                "STATUS": status
            }
        }
        response = requests.patch(url, json=data, headers=headers)
        if response.status_code != 200:
            print(f"Грешка при обновяване на {record_id}: {response.text}")

