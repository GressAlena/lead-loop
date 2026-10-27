from supabase import create_client
import requests
import os
from dotenv import load_dotenv
import time

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

GREEN_API_ID    = os.getenv("GREEN_API_ID")
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")
INTRO_VIDEO_URL = os.getenv("INTRO_VIDEO_URL")


def send_video(chat_id):
    url = f"https://api.green-api.com/waInstance{GREEN_API_ID}/sendFileByUrl/{GREEN_API_TOKEN}"

    res = requests.post(url, json={
        "chatId":   chat_id,
        "urlFile":  INTRO_VIDEO_URL,
        "fileName": "video.mp4",
        "caption":  "Здравствуйте! Отправляю вам презентацию. Если интересно — ответьте на это сообщение"
    })

    return res.json()


response = supabase.table("leads") \
    .select("*") \
    .eq("status", "parsed") \
    .limit(50) \
    .execute()

leads = response.data

print(f"Найдено контактов: {len(leads)}")


for lead in leads:
    phone = lead.get("phone")

    if not phone:
        print("❌ Нет телефона")
        continue

    phone   = phone.replace("+", "")
    chat_id = f"{phone}@c.us"

    try:
        video_result = send_video(chat_id)

        print(f"🎥 VIDEO {phone} →", video_result)

        if "idMessage" not in video_result:
            print("⚠️ Видео не отправилось")
            continue

        supabase.table("leads") \
            .update({"status": "messaged"}) \
            .eq("id", lead["id"]) \
            .execute()

        print(f"✅ {phone} отправлено")

        time.sleep(3)

    except Exception as e:
        print("❌ Ошибка:", e)
