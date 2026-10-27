from agent_tools import book_slot
import os
from dotenv import load_dotenv
load_dotenv()

result = book_slot.invoke({
    "datetime_str": "07.04.2025 16:00",
    "lead_phone": "77065177883",
    "lead_name": "Тест",
    "lead_company": "Тест компания",
    "lead_sphere": "тест"
})
print(result)
