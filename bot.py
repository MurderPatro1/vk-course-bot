import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlencode

import vk_api
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from vk_api.upload import VkUpload

app = FastAPI()

# =============================
# Переменные окружения
# =============================

VK_TOKEN = os.getenv("VK_TOKEN", "")
VK_CONFIRMATION_TOKEN = os.getenv("VK_CONFIRMATION_TOKEN", "")

# ЮMoney (Quickpay + HTTP-уведомления)
YOOMONEY_RECEIVER = os.getenv("YOOMONEY_RECEIVER", "")
YOOMONEY_NOTIFICATION_SECRET = os.getenv("YOOMONEY_NOTIFICATION_SECRET", "")

vk_session = vk_api.VkApi(token=VK_TOKEN) if VK_TOKEN else None
vk = vk_session.get_api() if vk_session else None


# =============================
# Работа с БД
# =============================


def get_course(course_id: int):
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, description, price, pdf_path FROM courses WHERE id=?", (course_id,))
    course = cursor.fetchone()
    conn.close()
    return course


def get_courses():
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, description, price FROM courses ORDER BY id")
    courses = cursor.fetchall()
    conn.close()
    return courses


def save_payment(user_id: int, course_id: int, payment_label: str):
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO payments (user_id, course_id, payment_id, status) VALUES (?, ?, ?, ?)",
        (user_id, course_id, payment_label, "pending"),
    )
    conn.commit()
    conn.close()


def get_payment(payment_label: str):
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, user_id, course_id, payment_id, status FROM payments WHERE payment_id=? ORDER BY id DESC LIMIT 1",
        (payment_label,),
    )
    payment = cursor.fetchone()
    conn.close()
    return payment


def update_payment_status(payment_label: str, status: str):
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE payments SET status=? WHERE payment_id=?", (status, payment_label))
    conn.commit()
    conn.close()


# =============================
# VK helpers
# =============================


def send_message(user_id: int, message: str, keyboard: dict | None = None, attachment: str | None = None):
    if not vk:
        return

    params = {
        "user_id": user_id,
        "random_id": uuid.uuid4().int & 0x7FFFFFFF,
        "message": message,
    }
    if attachment:
        params["attachment"] = attachment
    if keyboard:
        params["keyboard"] = json.dumps(keyboard, ensure_ascii=False)

    vk.messages.send(**params)


def make_main_keyboard() -> dict:
    return {
        "one_time": False,
        "buttons": [
            [{"action": {"type": "text", "label": "Каталог", "payload": '{"cmd":"catalog"}'}, "color": "primary"}],
            [{"action": {"type": "text", "label": "Помощь", "payload": '{"cmd":"help"}'}, "color": "secondary"}],
        ],
    }


def make_courses_keyboard() -> dict:
    buttons = []
    row = []
    for course_id, title, _description, _price in get_courses():
        row.append(
            {
                "action": {
                    "type": "text",
                    "label": f"Купить: {title[:24]}",
                    "payload": json.dumps({"cmd": "buy", "course_id": course_id}, ensure_ascii=False),
                },
                "color": "positive",
            }
        )
        if len(row) == 1:
            buttons.append(row)
            row = []
    return {"one_time": False, "buttons": buttons or [[{"action": {"type": "text", "label": "Каталог", "payload": '{"cmd":"catalog"}'}, "color": "primary"}]]}


def format_courses_message() -> str:
    courses = get_courses()
    if not courses:
        return "Сейчас нет активных курсов."

    lines = ["📚 Доступные курсы:"]
    for course_id, title, description, price in courses:
        short_desc = (description or "").strip().split("\n")[0]
        lines.append(f"{course_id}. {title} — {price} ₽")
        if short_desc:
            lines.append(f"   {short_desc[:90]}")
    lines.append("\nВыберите курс кнопкой ниже.")
    return "\n".join(lines)


# =============================
# ЮMoney helpers
# =============================


def create_yoomoney_payment_url(user_id: int, course_id: int, amount: int, title: str) -> tuple[str, str]:
    payment_label = f"{user_id}:{course_id}:{uuid.uuid4().hex}"
    params = {
        "receiver": YOOMONEY_RECEIVER,
        "quickpay-form": "shop",
        "targets": f"Покупка курса: {title}",
        "paymentType": "SB",
        "sum": str(amount),
        "label": payment_label,
        "successURL": "https://vk.com",
    }
    url = f"https://yoomoney.ru/quickpay/confirm.xml?{urlencode(params)}"
    return payment_label, url


def verify_yoomoney_notification(form: dict) -> bool:
    required = [
        "notification_type",
        "operation_id",
        "amount",
        "currency",
        "datetime",
        "sender",
        "codepro",
        "label",
        "sha1_hash",
    ]
    if not all(key in form for key in required):
        return False

    check_string = "&".join(
        [
            form["notification_type"],
            form["operation_id"],
            form["amount"],
            form["currency"],
            form["datetime"],
            form["sender"],
            form["codepro"],
            YOOMONEY_NOTIFICATION_SECRET,
            form["label"],
        ]
    )
    expected_hash = hashlib.sha1(check_string.encode()).hexdigest()
    return expected_hash == form["sha1_hash"]


def deliver_course(user_id: int, course_id: int):
    course = get_course(course_id)
    if not course:
        return

    _, title, _description, _price, pdf_path = course
    file_path = Path(pdf_path)

    if vk_session and file_path.exists():
        upload = VkUpload(vk_session)
        doc = upload.document_message(str(file_path), peer_id=user_id)
        attachment = f"doc{doc['doc']['owner_id']}_{doc['doc']['id']}"
        send_message(user_id, f"✅ Оплата прошла успешно! Отправляю курс: {title}", attachment=attachment)
    else:
        send_message(user_id, f"✅ Оплата прошла успешно! Курс '{title}' будет отправлен менеджером.")


# =============================
# VK Callback
# =============================


@app.get("/")
async def healthcheck():
    return {"status": "ok"}


@app.post("/vk")
async def vk_webhook(request: Request):
    data = await request.json()

    if data.get("type") == "confirmation":
        return PlainTextResponse(VK_CONFIRMATION_TOKEN)

    if data.get("type") != "message_new":
        return PlainTextResponse("ok")

    message = data.get("object", {}).get("message", {})
    user_id = message.get("from_id")
    if not user_id:
        return PlainTextResponse("ok")

    payload_raw = message.get("payload")
    text = (message.get("text") or "").strip().lower()

    cmd = None
    course_id = None
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
            cmd = payload.get("cmd")
            course_id = payload.get("course_id")
        except json.JSONDecodeError:
            cmd = None

    if cmd == "buy" and course_id:
        course = get_course(int(course_id))
        if not course:
            send_message(user_id, "Курс не найден.", keyboard=make_main_keyboard())
            return PlainTextResponse("ok")

        c_id, title, _description, price, _pdf_path = course

        if not YOOMONEY_RECEIVER:
            send_message(user_id, "Оплата временно недоступна. Не настроен кошелёк ЮMoney.", keyboard=make_main_keyboard())
            return PlainTextResponse("ok")

        payment_label, payment_url = create_yoomoney_payment_url(user_id=user_id, course_id=c_id, amount=price, title=title)
        save_payment(user_id=user_id, course_id=c_id, payment_label=payment_label)

        pay_keyboard = {
            "one_time": False,
            "buttons": [
                [{"action": {"type": "open_link", "label": "💳 Оплатить", "link": payment_url}}],
                [{"action": {"type": "text", "label": "Каталог", "payload": '{"cmd":"catalog"}'}, "color": "primary"}],
            ],
        }
        send_message(
            user_id,
            f"Вы выбрали курс '{title}' за {price} ₽. Нажмите кнопку ниже для оплаты. После оплаты курс придёт автоматически.",
            keyboard=pay_keyboard,
        )
        return PlainTextResponse("ok")

    if cmd == "catalog" or text in {"каталог", "старт", "начать", "меню"}:
        send_message(user_id, format_courses_message(), keyboard=make_courses_keyboard())
        return PlainTextResponse("ok")

    if cmd == "help" or text in {"помощь", "help"}:
        send_message(
            user_id,
            "Это бот продаж курсов. Всё работает кнопками:\n"
            "1) Нажмите 'Каталог'\n"
            "2) Нажмите кнопку 'Купить' у нужного курса\n"
            "3) Оплатите в ЮMoney — курс придёт автоматически.",
            keyboard=make_main_keyboard(),
        )
        return PlainTextResponse("ok")

    send_message(user_id, "Добро пожаловать! Нажмите кнопку ниже.", keyboard=make_main_keyboard())
    return PlainTextResponse("ok")


# =============================
# ЮMoney webhook
# =============================


@app.post("/yoomoney")
async def yoomoney_webhook(request: Request):
    form = dict(await request.form())

    if not verify_yoomoney_notification(form):
        return PlainTextResponse("invalid", status_code=400)

    payment_label = form.get("label", "")
    payment = get_payment(payment_label)

    if not payment:
        return PlainTextResponse("ok")

    _payment_row_id, user_id, course_id, _payment_id, status = payment

    if status == "paid":
        return PlainTextResponse("ok")

    update_payment_status(payment_label, "paid")
    deliver_course(user_id=int(user_id), course_id=int(course_id))

    return PlainTextResponse("ok")
