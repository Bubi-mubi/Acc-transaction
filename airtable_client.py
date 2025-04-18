import os
import requests
import difflib
from dotenv import load_dotenv

load_dotenv()

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
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def add_record_to_table(self, table_name, fields: dict):
        url = f"https://api.airtable.com/v0/{self.base_id}/{table_name}"
        data = {"fields": fields}
        response = requests.post(url, headers=self.headers, json=data)
        return response.json()

    def update_record_in_table(self, table_name, record_id: str, fields: dict):
        url = f"https://api.airtable.com/v0/{self.base_id}/{table_name}/{record_id}"
        data = {"fields": fields}
        response = requests.patch(url, headers=self.headers, json=data)
        return response.json()

    def get_linked_accounts_from_table(self, table_name):
        url = f"https://api.airtable.com/v0/{self.base_id}/{table_name}"
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
