import requests
import os
from dotenv import load_dotenv

load_dotenv()

headers = {
    "Authorization": f"Bearer {os.getenv('CALENDLY_TOKEN')}",
    "Content-Type": "application/json"
}

payload = {
    "url": os.getenv("WEBHOOK_PUBLIC_URL"),
    "events": ["invitee.created"],
    "organization": os.getenv("CALENDLY_ORG_URL"),
    "scope": "organization"
}

res = requests.post(
    "https://api.calendly.com/webhook_subscriptions",
    json=payload,
    headers=headers
)

print(res.status_code)
print(res.json())
