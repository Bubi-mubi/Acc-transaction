import requests
import os

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

        mapping = {}  # {normalized string: (full name, record_id)}

        for record in data.get("records", []):
            full_name = record["fields"].get("REG")
            if full_name:
                normalized = full_name.lower().replace("-", "").replace("  ", " ").strip()
                mapping[normalized] = (full_name, record["id"])

        return mapping

    def find_matching_account(user_input, account_dict):
    input_keywords = user_input.lower().split()

    for normalized_name, (original, record_id) in account_dict.items():
        if all(keyword in normalized_name for keyword in input_keywords):
            return record_id  # return record ID of best match

    return None


    def add_record(self, fields: dict):
        data = {
            "fields": fields
        }
        response = requests.post(self.endpoint, headers=self.headers, json=data)
        return response.json()

