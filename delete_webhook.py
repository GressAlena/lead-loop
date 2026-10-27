import requests
import os
from dotenv import load_dotenv

load_dotenv()

headers = {
    "Authorization": f"Bearer {os.getenv('CALENDLY_TOKEN')}"
}

res = requests.get(
    "https://api.calendly.com/webhook_subscriptions",
    headers=headers,
    params={
        "organization": os.getenv("CALENDLY_ORG_URL"),
        "scope": "organization"
    }
)

webhooks = res.json().get("collection", [])

for wh in webhooks:
    print("URL:", wh["callback_url"])
    print("URI:", wh["uri"])
    print()

for wh in webhooks:
    uuid = wh["uri"].split("/")[-1]
    del_res = requests.delete(
        f"https://api.calendly.com/webhook_subscriptions/{uuid}",
        headers=headers
    )
    print(f"Удалён {uuid}: {del_res.status_code}")
