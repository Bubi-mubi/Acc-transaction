from telethon import TelegramClient, events
from airtable_client import AirtableClient
from dotenv import load_dotenv
import os
import datetime

load_dotenv()

bot_token = os.getenv("BOT_TOKEN")

# Стартираме само с bot_token – без API_ID и API_HASH
client = TelegramClient('bot_session', api_id=None, api_hash=None).start(bot_token=bot_token)
airtable = AirtableClient()

