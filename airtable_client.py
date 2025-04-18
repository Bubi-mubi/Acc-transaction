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
        self.table_name = os.getenv("AIRTABLE_TABLE", "AccTransactions")

        self.endpoint = f"https://api.airtable.com/v0/{self.base_id}/{self.table_name}"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def get_table(self, table_name):
        url = f"https://api.airtable.com/v0/{self.base_id}/{table_name}"
        response = requests.get(url, headers=self.headers)
        return response.json().get("records", [])

    def get_status_options(self):
        url = f"https://api.airtable.com/v0/{self.base_id}/STATUS"
        response = requests.get(url, headers=self.headers)
        records = response.json().get("records", [])
        return {record["fields"]["STAT"]: record["id"] for record in records if "STAT" in record["fields"]}

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

    def add_record(self, fields: dict):
        data = {"fields": fields}
        response = requests.post(self.endpoint, headers=self.headers, json=data)
        return response.json()

    def update_record(self, record_id, fields: dict):
        url = f"{self.endpoint}/{record_id}"
        data = {"fields": fields}
        response = requests.patch(url, headers=self.headers, json=data)
        return response.json()
