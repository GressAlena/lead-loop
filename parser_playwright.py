from playwright.sync_api import sync_playwright
from supabase import create_client
from dotenv import load_dotenv
import os
import time
import re

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

QUERY = "кафе алматы"


def normalize_phone(phone):
    phone = re.sub(r'\D', '', phone)
    return phone


def save_to_db(company):
    if not company.get("phone"):
        return

    try:
        supabase.table("leads").upsert({
            "phone": company["phone"],
            "company_name": company["name"],
            "address": company["address"],
            "category": QUERY,
            "source_url": company["url"],
            "city": "Almaty",
            "segment": QUERY,
            "status": "parsed"
        }).execute()

        print("✅ Добавлено:", company["phone"])

    except Exception as e:
        print("Ошибка БД:", e)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    page.goto(f"https://2gis.kz/almaty/search/{QUERY}")
    time.sleep(5)

    for _ in range(5):
        page.mouse.wheel(0, 3000)
        time.sleep(2)

    cards = page.query_selector_all('a._1rehek')
    links = []

    for card in cards:
        href = card.get_attribute("href")
        if href:
            links.append("https://2gis.kz" + href)

    print("Собрано ссылок:", len(links))

    for url in links[:20]:
        try:
            page.goto(url)
            time.sleep(3)

            name_el = page.query_selector("h1")
            name = name_el.inner_text() if name_el else ""

            address_el = page.query_selector('[class*="address"]')
            address = address_el.inner_text() if address_el else ""

            btn = page.query_selector('button:has-text("Показать телефон")')
            if btn:
                btn.click()
                time.sleep(1)

            phone_el = page.query_selector('a[href^="tel:"]')

            if not phone_el:
                print("❌ Нет телефона")
                continue

            phone = phone_el.inner_text()
            phone = normalize_phone(phone)

            print("📞", phone)

            company = {
                "name": name,
                "address": address,
                "phone": phone,
                "url": url
            }

            save_to_db(company)

            time.sleep(2)

        except Exception as e:
            print("Ошибка:", e)

    browser.close()
