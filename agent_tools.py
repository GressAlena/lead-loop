from langchain_core.tools import tool
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from datetime import datetime, timedelta
import pytz
from supabase import create_client
import os
import pickle
import uuid
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

SCOPES      = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
TIMEZONE    = "Asia/Almaty"

WORK_START = 10
WORK_END   = 18


def _calendar_service():
    creds = None
    base       = os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(base, "token.pickle")
    creds_path = os.path.join(base, "oauth_credentials.json")

    if os.path.exists(token_path):
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return build("calendar", "v3", credentials=creds)


@tool
def get_free_slots(days_ahead: int = 5) -> str:
    """
    Возвращает список свободных временных слотов для встречи на ближайшие дни.
    Вызывай когда клиент хочет узнать доступное время или готов записаться.
    Параметр days_ahead — сколько дней вперёд смотреть (по умолчанию 5).
    """
    try:
        service = _calendar_service()
        tz  = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)

        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days_ahead)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])

        busy = []
        for e in events:
            s  = e["start"].get("dateTime")
            en = e["end"].get("dateTime")
            if s and en:
                busy.append((datetime.fromisoformat(s), datetime.fromisoformat(en)))

        free   = []
        cursor = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

        while cursor < now + timedelta(days=days_ahead) and len(free) < 8:
            if cursor.weekday() < 5 and WORK_START <= cursor.hour < WORK_END:
                end     = cursor + timedelta(hours=1)
                overlap = any(not (end <= b[0] or cursor >= b[1]) for b in busy)
                if not overlap:
                    free.append(cursor)
            cursor += timedelta(hours=1)

        if not free:
            return "Свободных слотов на ближайшие дни нет. Попробую посмотреть позже."

        lines = ["Доступное время для встречи:"]
        for i, slot in enumerate(free, 1):
            lines.append(f"{i}. {slot.strftime('%d.%m (%A) %H:%M')}")
        lines.append("\nНапиши номер слота или удобное время.")
        return "\n".join(lines)

    except Exception as e:
        return f"Ошибка получения слотов: {e}"


@tool
def book_slot(datetime_str: str, lead_phone: str, lead_name: str,
              lead_company: str = "", lead_sphere: str = "") -> str:
    """
    Бронирует встречу в Google Calendar с Google Meet ссылкой и сохраняет данные клиента в базе.
    datetime_str — дата и время в формате 'DD.MM.YYYY HH:MM' (например: '15.07.2025 14:00').
    lead_phone   — телефон клиента (без +, только цифры).
    lead_name    — имя клиента.
    lead_company — компания (если назвал).
    lead_sphere  — сфера деятельности (если назвал).
    """
    try:
        service = _calendar_service()
        tz  = pytz.timezone(TIMEZONE)

        dt  = tz.localize(datetime.strptime(datetime_str, "%d.%m.%Y %H:%M"))
        end = dt + timedelta(hours=1)

        event = {
            "summary": f"Встреча: {lead_name}",
            "description": (
                f"Телефон: {lead_phone}\n"
                f"Компания: {lead_company}\n"
                f"Сфера: {lead_sphere}\n"
                f"Источник: WhatsApp-бот"
            ),
            "start": {"dateTime": dt.isoformat(),  "timeZone": TIMEZONE},
            "end":   {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
            "conferenceData": {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 60},
                    {"method": "email", "minutes": 1440},
                ],
            },
        }

        created = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event,
            conferenceDataVersion=1,
        ).execute()

        meet_link = ""
        for ep in created.get("conferenceData", {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break

        supabase.table("leads").update({
            "status":            "booked",
            "booked":            True,
            "meeting_time":      dt.isoformat(),
            "client_name":       lead_name,
            "lead_company":      lead_company,
            "lead_sphere":       lead_sphere,
            "calendar_event_id": created.get("id"),
            "meet_link":         meet_link,
        }).eq("phone", lead_phone).execute()

        reply = (
            f"✅ Встреча забронирована!\n"
            f"📅 {dt.strftime('%d.%m.%Y в %H:%M')} (Алматы)\n"
        )
        if meet_link:
            reply += f"🔗 Google Meet: {meet_link}\n"
        reply += "Напомним за 24 часа и за 1 час до встречи."

        return reply

    except ValueError:
        return "Не понял формат даты. Используй: DD.MM.YYYY HH:MM (например: 15.07.2025 14:00)"
    except Exception as e:
        import traceback
        print(f"[book_slot ERROR] {traceback.format_exc()}")
        return f"Ошибка бронирования: {e}"


@tool
def save_lead_info(phone: str, name: str = "",
                   company: str = "", sphere: str = "") -> str:
    """
    Сохраняет имя, компанию и сферу деятельности клиента в базу.
    Вызывай сразу как клиент назвал своё имя или компанию — не жди конца разговора.
    phone   — телефон клиента (без +, только цифры).
    name    — имя.
    company — компания.
    sphere  — сфера деятельности.
    """
    try:
        update = {}
        if name:    update["client_name"]  = name
        if company: update["lead_company"] = company
        if sphere:  update["lead_sphere"]  = sphere
        if update:
            supabase.table("leads").update(update).eq("phone", phone).execute()
        return f"Данные сохранены: {name or '—'}, {company or '—'}, {sphere or '—'}"
    except Exception as e:
        return f"Ошибка сохранения: {e}"


ALL_TOOLS = [get_free_slots, book_slot, save_lead_info]
