import os
import uuid
import sqlite3
from fastapi import FastAPI, Request
from yookassa import Configuration, Payment
import vk_api

app = FastAPI()

# =============================
# Переменные окружения
# =============================

VK_TOKEN = os.getenv("VK_TOKEN")
SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
VK_CONFIRMATION_TOKEN = os.getenv("VK_CONFIRMATION_TOKEN")

Configuration.account_id = SHOP_ID
Configuration.secret_key = SECRET_KEY

vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()


# =============================
# Работа с БД
# =============================

def get_course(course_id):
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, price, pdf_path FROM courses WHERE id=?", (course_id,))
    course = cursor.fetchone()
    conn.close()
    return course


def save_payment(user_id, course_id, payment_id):
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO payments (user_id, course_id, payment_id, status) VALUES (?, ?, ?, ?)",
        (user_id, course_id, payment_id, "pending")
    )
    conn.commit()
    conn.close()


def update_payment_status(payment_id, status):
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE payments SET status=? WHERE payment_id=?",
        (status, payment_id)
    )
    conn.commit()
    conn.close()


# =============================
# VK Callback
# =============================

from fastapi.responses import PlainTextResponse

@app.post("/vk")
async def vk_webhook(request: Request):
    data = await request.json()

    if data["type"] == "confirmation":
        return PlainTextResponse(VK_CONFIRMATION_TOKEN)

    if data["type"] == "message_new":
        user_id = data["object"]["message"]["from_id"]
        text = data["object"]["message"]["text"]

        if text.startswith("Купить"):
            course_id = int(text.split()[-1])
            course = get_course(course_id)

            payment = Payment.create({
                "amount": {
                    "value": str(course[2]),
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": "https://vk.com"
                },
                "capture": True,
                "description": f"Покупка курса {course[1]}"
            }, uuid.uuid4())

            save_payment(user_id, course_id, payment.id)

            vk.messages.send(
                user_id=user_id,
                message=f"Оплатите курс по ссылке:\n{payment.confirmation.confirmation_url}",
                random_id=0
            )

        return "ok"

    return "ok"


# =============================
# ЮKassa webhook
# =============================

@app.post("/yookassa")
async def yookassa_webhook(request: Request):
    data = await request.json()

    if data["event"] == "payment.succeeded":
        payment_id = data["object"]["id"]

        update_payment_status(payment_id, "succeeded")

        # тут позже добавим выдачу PDF

    return {"status": "ok"}

