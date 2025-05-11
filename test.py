import requests

API_KEY = "f95db6a609adf4c8dd19cf5d"
url = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/GBP"

response = requests.get(url)
print(response.status_code)
print(response.json())