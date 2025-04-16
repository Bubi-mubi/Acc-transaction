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

    def add_record(self, fields: dict):
        data = {
            "fields": fields
        }
        response = requests.post(self.endpoint, headers=self.headers, json=data)
        return response.json()

