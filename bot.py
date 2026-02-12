import os
import uuid
import sqlite3
from fastapi import FastAPI, Request
from yookassa import Configuration, Payment
import vk_api
import requests
import base64

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

def create_payment(user_id, amount, description):
    shop_id = os.getenv("YOOKASSA_SHOP_ID")
    secret_key = os.getenv("YOOKASSA_SECRET_KEY")

    auth = base64.b64encode(f"{shop_id}:{secret_key}".encode()).decode()

    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
        "Idempotence-Key": str(user_id)
    }

    data = {
        "amount": {
            "value": f"{amount}.00",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": "https://vk.com"
        },
        "capture": True,
        "description": description,
        "metadata": {
            "user_id": user_id
        }
    }

    response = requests.post(
        "https://api.yookassa.ru/v3/payments",
        json=data,
        headers=headers
    )

    return response.json()

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

    if text.lower() == "купить":
    payment = create_payment(
        user_id=user_id,
        amount=1990,
        description="Курс Киберслед"
    )

    confirmation_url = payment["confirmation"]["confirmation_url"]

    send_message(user_id, f"Для оплаты перейдите по ссылке:\n{confirmation_url}")


    return Response(content="ok", media_type="text/plain")



# =============================
# ЮKassa webhook
# =============================

@app.post("/yookassa")
async def yookassa_webhook(request: Request):
    data = await request.json()

    if data["event"] == "payment.succeeded":
        payment_object = data["object"]
        user_id = payment_object["metadata"]["user_id"]

        pdf_path = "cybertrail.pdf"  # твой файл

        upload = VkUpload(vk_session)
        doc = upload.document_message(pdf_path, peer_id=user_id)

        attachment = f"doc{doc['doc']['owner_id']}_{doc['doc']['id']}"

        send_message(user_id, "Оплата прошла успешно! Вот ваш курс:", attachment=attachment)

    return PlainTextResponse("ok")





