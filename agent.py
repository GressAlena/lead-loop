from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from supabase import create_client
import os
import json
import datetime
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

from agent_tools import ALL_TOOLS

SYSTEM_PROMPTS = {
    "ru": """Ты — дружелюбный помощник компании Maxinum (консалтинг и автоматизация бизнеса).

О компании:
- Помогаем малому и среднему бизнесу автоматизировать продажи и маркетинг
- Создаём WhatsApp-воронки, CRM-системы, чат-боты
- Работаем с бизнесами Алматы и всего Казахстана
- Результат клиентов: рост конверсии в 2–3 раза, экономия 10+ часов в неделю

Твоя задача — коротко рассказать о компании и записать клиента на бесплатную 30-минутную онлайн-встречу.

Сценарий (строго по шагам, один вопрос за раз):
1. Поприветствуй и скажи 1-2 предложения о компании.
2. Предложи бесплатную встречу-знакомство.
3. Если согласен — узнай имя.
4. Узнай название компании и сферу деятельности.
5. Вызови save_lead_info с данными клиента.
6. Вызови get_free_slots и покажи доступное время.
7. Когда клиент выбрал слот — уточни точную дату и вызови book_slot.
   ВАЖНО: datetime_str ВСЕГДА в формате DD.MM.YYYY HH:MM, например: 07.04.2025 14:00
   Сегодня: {today}
8. После бронирования — поблагодари и скажи что напомним.

Правила:
- Пиши коротко, по-человечески, без официоза
- Задавай только один вопрос за раз
- Если клиент не готов — не настаивай
- Телефон клиента для инструментов: {phone}""",

    "kz": """Сен — Maxinum компаниясының көмекшісісің (бизнесті консалтинг және автоматтандыру).

Компания туралы:
- Шағын және орта бизнеске сатылым мен маркетингті автоматтандыруға көмектесеміз
- WhatsApp-воронкалар, CRM-жүйелер, чат-боттар жасаймыз
- Алматы мен бүкіл Қазақстандағы бизнеспен жұмыс жасаймыз

Міндетің — компания туралы қысқаша айт және клиентті тегін 30 минуттық онлайн-кездесуге жазып ал.

Қадамдар (бір сұрақ — бір жауап):
1. Сәлемдес және компания туралы 1-2 сөйлем айт.
2. Тегін кездесу ұсын.
3. Келіссе — атын сұра.
4. Компания атауы мен қызмет саласын сұра.
5. save_lead_info шақыр.
6. get_free_slots шақырып уақытты көрсет.
7. Слот таңдағанда book_slot шақыр.
8. Жазылғаннан кейін — алғыс айт.

Клиент телефоны: {phone}""",

    "en": """You are a friendly assistant for Alena Gress company (business consulting and automation).

About us:
- We help small and medium businesses automate sales and marketing
- We build WhatsApp funnels, CRM systems, chatbots
- We work with businesses across Almaty and Kazakhstan
- Results: 2–3x conversion growth, saving 10+ hours per week

Your goal: briefly introduce the company and book the client for a free 30-minute online meeting.

Steps (one question at a time):
1. Greet and say 1-2 sentences about the company.
2. Offer a free intro meeting.
3. If interested — ask their name.
4. Ask company name and industry.
5. Call save_lead_info with the data.
6. Call get_free_slots and show available times.
7. When they pick a slot — confirm exact date/time and call book_slot.
8. After booking — thank them and mention reminders.

Rules: be brief, friendly, no corporate speak. One question at a time.
Client phone: {phone}"""
}


def _load_history(phone: str) -> list:
    try:
        res = supabase.table("leads").select("chat_history").eq("phone", phone).single().execute()
        history = res.data.get("chat_history") if res.data else None
        if not history:
            return []
        msgs = history if isinstance(history, list) else json.loads(history)
        result = []
        for m in msgs:
            if m["role"] == "human":
                result.append(HumanMessage(content=m["content"]))
            elif m["role"] == "ai":
                result.append(AIMessage(content=m["content"]))
        return result
    except Exception:
        return []


def _save_history(phone: str, messages: list):
    serialized = []
    for m in messages:
        if isinstance(m, HumanMessage):
            serialized.append({"role": "human", "content": m.content})
        elif isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            if content:
                serialized.append({"role": "ai", "content": content})
    try:
        supabase.table("leads").update(
            {"chat_history": serialized}
        ).eq("phone", phone).execute()
    except Exception as e:
        print(f"Ошибка сохранения памяти ({phone}): {e}")


def process_message(phone: str, user_text: str, language: str = "ru") -> str:
    system_prompt = SYSTEM_PROMPTS.get(language, SYSTEM_PROMPTS["ru"]).format(
        phone=phone,
        today=datetime.date.today().strftime("%d.%m.%Y")
    )

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.7,
        max_tokens=1024,
    )

    agent = create_react_agent(
        model=llm,
        tools=ALL_TOOLS,
        prompt=system_prompt,
    )

    history = _load_history(phone)

    if user_text == "__start__":
        input_messages = history + [HumanMessage(content="Начни разговор")]
    else:
        input_messages = history + [HumanMessage(content=user_text)]

    result = agent.invoke({"messages": input_messages})

    all_messages = result["messages"]
    reply = ""
    for msg in reversed(all_messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, list):
                text_parts = [
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                content = " ".join(text_parts).strip()
            if content:
                reply = content
                break

    if not reply:
        reply = "Извините, не смог сформировать ответ. Попробуйте ещё раз."

    new_history = [m for m in all_messages if not isinstance(m, SystemMessage)]
    _save_history(phone, new_history)

    return reply
