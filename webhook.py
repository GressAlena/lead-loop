from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import os
import threading
import time
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)
CORS(app)

GREEN_API_ID    = os.getenv("GREEN_API_ID")
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")
INTRO_VIDEO_URL = os.getenv("INTRO_VIDEO_URL")

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

SEND_URL = f"https://api.green-api.com/waInstance{GREEN_API_ID}/sendMessage/{GREEN_API_TOKEN}"


parse_state = {"status": "idle", "log": "", "count": 0, "error": ""}
send_state  = {"status": "idle", "sent": 0, "total": 0}


def run_parser(city, segment, limit, phone_only):
    global parse_state
    parse_state = {"status": "running", "log": f"Старт: {city} / {segment}", "count": 0, "error": ""}

    CITY_SLUGS = {
        "алматы":  "almaty",
        "астана":  "astana",
        "шымкент": "shymkent",
        "актобе":  "aktobe",
        "атырау":  "atyrau",
        "almaty":  "almaty",
        "astana":  "astana",
    }

    def normalize_phone(raw):
        digits = re.sub(r'\D', '', raw)
        if len(digits) == 10:
            digits = "7" + digits
        elif len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        return digits

    def save_to_db(company):
        if not company.get("phone"):
            return False
        try:
            supabase.table("leads").upsert({
                "phone":        company["phone"],
                "company_name": company["name"],
                "address":      company["address"],
                "category":     segment,
                "source_url":   company["url"],
                "city":         city,
                "segment":      segment,
                "status":       "parsed"
            }).execute()
            return True
        except Exception as e:
            parse_state["log"] = f"Ошибка БД: {e}"
            return False

    try:
        from playwright.sync_api import sync_playwright
        from urllib.parse import quote

        city_slug  = CITY_SLUGS.get(city.lower(), city.lower().replace(" ", "_"))
        query_enc  = quote(segment)
        search_url = f"https://2gis.kz/{city_slug}/search/{query_enc}"
        parse_state["log"] = f"Открываем: {search_url}"

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="ru-RU"
            )
            page = ctx.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,webp,svg,mp4,woff2}", lambda r: r.abort())
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            try:
                page.wait_for_selector('[data-key]', timeout=15000)
            except:
                parse_state["log"] = "Ожидание результатов..."
                time.sleep(5)

            parse_state["log"] = "Прокрутка для подгрузки карточек..."
            for _ in range(8):
                page.keyboard.press("End")
                time.sleep(1.5)
                page.mouse.wheel(0, 2000)
                time.sleep(1)

            links = set()
            for el in page.query_selector_all('a[data-key]'):
                href = el.get_attribute("href")
                if href and "/firm/" in href:
                    links.add(("https://2gis.kz" + href) if href.startswith("/") else href)

            if len(links) < 3:
                for el in page.query_selector_all('a[href*="/firm/"]'):
                    href = el.get_attribute("href")
                    if href:
                        links.add(("https://2gis.kz" + href) if href.startswith("/") else href)

            if len(links) < 3:
                for el in page.query_selector_all('a[class*="cardView"], a[class*="card_"]'):
                    href = el.get_attribute("href")
                    if href and "/firm/" in href:
                        links.add(("https://2gis.kz" + href) if href.startswith("/") else href)

            links = list(links)[:limit]
            parse_state["log"] = f"Найдено {len(links)} карточек, начинаем обход..."

            if not links:
                html_snippet = page.content()[:500]
                parse_state["log"] = f"Карточки не найдены. Фрагмент: {html_snippet}"
                parse_state["status"] = "done"
                parse_state["count"]  = 0
                browser.close()
                return

            added = 0
            for i, url in enumerate(links):
                if parse_state["status"] == "stopped":
                    break
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    try:
                        page.wait_for_selector("h1", timeout=8000)
                    except:
                        pass

                    name_el = page.query_selector("h1")
                    name    = name_el.inner_text().strip() if name_el else ""

                    address = ""
                    for sel in ['[class*="address"]', '[itemprop="address"]', '[class*="Address"]']:
                        addr_el = page.query_selector(sel)
                        if addr_el:
                            address = addr_el.inner_text().strip()
                            break

                    for btn_text in ["Показать телефон", "Показать номер", "Позвонить"]:
                        btn = page.query_selector(f'button:has-text("{btn_text}")')
                        if btn:
                            btn.click()
                            time.sleep(1.2)
                            break

                    phone = ""
                    phone_el = page.query_selector('a[href^="tel:"]')
                    if phone_el:
                        raw   = phone_el.get_attribute("href").replace("tel:", "")
                        phone = normalize_phone(raw)
                    else:
                        phone_text_el = page.query_selector('[class*="phone"], [class*="Phone"]')
                        if phone_text_el:
                            phone = normalize_phone(phone_text_el.inner_text())

                    if phone_only and not phone:
                        parse_state["log"] = f"[{i+1}/{len(links)}] Нет телефона, пропускаем"
                        continue

                    if save_to_db({"name": name, "address": address, "phone": phone, "url": url}):
                        added += 1
                        parse_state["log"] = f"✅ [{i+1}/{len(links)}] {name} — {phone}"
                    else:
                        parse_state["log"] = f"[{i+1}/{len(links)}] Дубль: {name}"

                    parse_state["count"] = added
                    time.sleep(2)

                except Exception as e:
                    parse_state["log"] = f"Ошибка [{i+1}]: {e}"

            browser.close()

        parse_state["status"] = "done"
        parse_state["count"]  = added
        parse_state["log"]    = f"Парсинг завершён. Добавлено: {added} лидов."

    except Exception as e:
        parse_state["status"] = "error"
        parse_state["error"]  = str(e)


@app.route("/parse", methods=["POST"])
def start_parse():
    global parse_state
    if parse_state["status"] == "running":
        return jsonify({"error": "Парсинг уже запущен"}), 409

    data       = request.json or {}
    city       = data.get("city",       "Алматы")
    segment    = data.get("segment",    "кафе")
    limit      = int(data.get("limit",  50))
    phone_only = bool(data.get("phone_only", True))

    t = threading.Thread(target=run_parser, args=(city, segment, limit, phone_only), daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/parse/status", methods=["GET"])
def parse_status():
    return jsonify(parse_state)


@app.route("/parse/stop", methods=["POST"])
def stop_parse():
    parse_state["status"] = "stopped"
    return jsonify({"ok": True})


def send_video(chat_id):
    url = f"https://api.green-api.com/waInstance{GREEN_API_ID}/sendFileByUrl/{GREEN_API_TOKEN}"
    res = requests.post(url, json={
        "chatId":   chat_id,
        "urlFile":  INTRO_VIDEO_URL,
        "fileName": "video.mp4",
        "caption":  "Здравствуйте! Отправляю вам презентацию. Если интересно — ответьте на это сообщение"
    })
    return res.json()


def run_send(status_filter, segment_filter, city_filter, limit):
    global send_state
    send_state = {"status": "running", "sent": 0, "total": 0}

    try:
        query = supabase.table("leads").select("*").eq("status", status_filter)
        if segment_filter:
            query = query.eq("segment", segment_filter)
        if city_filter:
            query = query.eq("city", city_filter)

        leads = query.limit(limit).execute().data
        send_state["total"] = len(leads)

        sent = 0
        for lead in leads:
            phone = lead.get("phone", "").replace("+", "")
            if not phone:
                continue
            chat_id = f"{phone}@c.us"
            result  = send_video(chat_id)
            if "idMessage" in result:
                supabase.table("leads").update({"status": "messaged"}).eq("id", lead["id"]).execute()
                sent += 1
                send_state["sent"] = sent
            time.sleep(3)

        send_state["status"] = "done"
        send_state["sent"]   = sent

    except Exception as e:
        send_state["status"] = "error"
        send_state["error"]  = str(e)


@app.route("/send", methods=["POST"])
def start_send():
    global send_state
    if send_state["status"] == "running":
        return jsonify({"error": "Рассылка уже запущена"}), 409

    data    = request.json or {}
    status  = data.get("status",  "parsed")
    segment = data.get("segment", "")
    city    = data.get("city",    "")
    limit   = int(data.get("limit", 50))

    t = threading.Thread(target=run_send, args=(status, segment, city, limit), daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/send/status", methods=["GET"])
def send_status_route():
    return jsonify(send_state)


def send_message(chat_id, text):
    try:
        requests.post(SEND_URL, json={"chatId": chat_id, "message": text})
    except Exception as e:
        print("Ошибка отправки:", e)


def get_lead(phone):
    res = supabase.table("leads").select("*").eq("phone", phone).execute()
    return res.data[0] if res.data else None


def handle_with_agent(phone, chat_id, message, language):
    try:
        from agent import process_message
        reply = process_message(phone=phone, user_text=message, language=language)
        send_message(chat_id, reply)
    except Exception as e:
        print(f"Ошибка агента ({phone}): {e}")
        send_message(chat_id, "Извините, произошла ошибка. Попробуйте написать ещё раз.")


@app.route("/", methods=["POST"])
def webhook():
    data = request.json
    try:
        if data.get("typeWebhook") != "incomingMessageReceived":
            return "ok"

        message_data = data.get("messageData", {})
        sender_data  = data.get("senderData", {})

        if message_data.get("typeMessage") != "textMessage":
            return "ok"

        message = message_data.get("textMessageData", {}).get("textMessage", "").strip()
        chat_id = sender_data.get("chatId", "")

        if not message or not chat_id:
            return "ok"

        phone = chat_id.replace("@c.us", "")
        lead  = get_lead(phone)

        if not lead:
            return "ok"

        status = lead.get("status")

        if status == "messaged":
            supabase.table("leads").update({
                "language": "ru",
                "status":   "agent"
            }).eq("phone", phone).execute()

            t = threading.Thread(
                target=handle_with_agent,
                args=(phone, chat_id, "__start__", "ru"),
                daemon=True
            )
            t.start()

        elif status == "agent":
            language = lead.get("language", "ru")
            t = threading.Thread(
                target=handle_with_agent,
                args=(phone, chat_id, message, language),
                daemon=True
            )
            t.start()

        elif status == "booked":
            language = lead.get("language", "ru")
            t = threading.Thread(
                target=handle_with_agent,
                args=(phone, chat_id, message, language),
                daemon=True
            )
            t.start()

    except Exception as e:
        print("Ошибка webhook:", e)

    return "ok"


@app.route("/calendly", methods=["POST"])
def calendly_webhook():
    data    = request.json
    payload = data.get("payload", {})

    name       = payload.get("name")
    email      = payload.get("email")
    start_time = payload["scheduled_event"]["start_time"]

    dt        = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    almaty    = dt + timedelta(hours=5)
    formatted = almaty.strftime("%d.%m.%Y в %H:%M")

    phone = None
    for qa in payload.get("questions_and_answers", []):
        cleaned = re.sub(r'\D', '', qa.get("answer", ""))
        if len(cleaned) >= 10:
            phone = cleaned[-10:]
            break

    if not phone:
        return "ok"

    res  = supabase.table("leads").select("*").ilike("phone", f"%{phone}%").execute()
    lead = res.data[0] if res.data else None
    if not lead:
        return "ok"

    language = lead.get("language", "ru")
    chat_id  = f"{lead['phone']}@c.us"

    supabase.table("leads").update({
        "status":       "booked",
        "booked":       True,
        "meeting_time": start_time,
        "client_name":  name,
        "email":        email
    }).eq("id", lead["id"]).execute()

    messages = {
        "ru": f"✅ Вы записались на встречу!\n📅 {formatted} (Алматы)\nДо встречи, {name}!",
        "kz": f"✅ Кездесуге жазылдыңыз!\n📅 {formatted} (Алматы)\nКездескенше, {name}!",
        "en": f"✅ You're booked!\n📅 {formatted} (Almaty)\nSee you soon, {name}!",
    }
    send_message(chat_id, messages.get(language, messages["ru"]))
    return "ok"


if __name__ == "__main__":
    app.run(port=5000, debug=False)
