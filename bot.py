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

from fastapi.responses import Response

@app.post("/vk")
async def vk_webhook(request: Request):
    data = await request.json()

    # Подтверждение сервера VK
    if data.get("type") == "confirmation":
        return Response(
            content="5bb3d654",
            media_type="text/plain"
        )

    # Новое сообщение
    if data.get("type") == "message_new":
        return Response(content="ok", media_type="text/plain")

    return Response(content="ok", media_type="text/plain")



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



