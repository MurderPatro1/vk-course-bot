import hashlib
import json
import logging
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
logger = logging.getLogger("vk_sales_bot")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

VK_TOKEN = os.getenv("VK_TOKEN", "")
VK_CONFIRMATION_TOKEN = os.getenv("VK_CONFIRMATION_TOKEN", "")
VK_CALLBACK_SECRET = os.getenv("VK_CALLBACK_SECRET", "")

YOOMONEY_RECEIVER = os.getenv("YOOMONEY_RECEIVER", "")
YOOMONEY_NOTIFICATION_SECRET = os.getenv("YOOMONEY_NOTIFICATION_SECRET", "")

vk_session = vk_api.VkApi(token=VK_TOKEN) if VK_TOKEN else None
vk = vk_session.get_api() if vk_session else None


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


def send_message(peer_id: int, message: str, keyboard: dict | None = None, attachment: str | None = None):
    if not vk:
        logger.warning("VK_TOKEN is not set, cannot send message")
        return

    params = {
        "peer_id": peer_id,
        "random_id": uuid.uuid4().int & 0x7FFFFFFF,
        "message": message,
    }
    if attachment:
        params["attachment"] = attachment
    if keyboard:
        params["keyboard"] = json.dumps(keyboard, ensure_ascii=False)

    try:
        vk.messages.send(**params)
    except Exception:
        logger.exception("Failed to send VK message to peer_id=%s", peer_id)


def make_main_keyboard() -> dict:
    return {
        "one_time": False,
        "buttons": [[{"action": {"type": "text", "label": "Каталог", "payload": '{"cmd":"catalog"}'}, "color": "primary"}]],
    }


def make_catalog_keyboard() -> dict:
    courses = get_courses()
    buttons = []

    for course_id, title, _description, _price in courses:
        buttons.append(
            [
                {
                    "action": {
                        "type": "text",
                        "label": f"Купить: {title[:28]}",
                        "payload": json.dumps({"cmd": "buy", "course_id": course_id}, ensure_ascii=False),
                    },
                    "color": "positive",
                }
            ]
        )

    buttons.append([
        {"action": {"type": "text", "label": "Назад", "payload": '{"cmd":"back"}'}, "color": "secondary"}
    ])

    return {
        "one_time": False,
        "buttons": buttons,
    }


def build_catalog_text() -> str:
    courses = get_courses()
    if not courses:
        return "Сейчас в каталоге пока нет курсов."

    lines = ["📚 Каталог курсов:"]
    for _course_id, title, description, price in courses:
        short_description = (description or "").strip()
        if len(short_description) > 180:
            short_description = f"{short_description[:177]}..."
        lines.append(f"\n• {title}\n{short_description}\nЦена: {price} ₽")

    lines.append("\nВыберите курс кнопкой ниже 👇")
    return "\n".join(lines)


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
    return payment_label, f"https://yoomoney.ru/quickpay/confirm.xml?{urlencode(params)}"


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
    return hashlib.sha1(check_string.encode()).hexdigest() == form["sha1_hash"]


def deliver_course(user_id: int, course_id: int):
    course = get_course(course_id)
    if not course:
        return

    _, title, _description, _price, pdf_path = course
    file_path = Path(pdf_path)

    try:
        if vk_session and file_path.exists():
            upload = VkUpload(vk_session)
            doc = upload.document_message(str(file_path), peer_id=user_id)
            attachment = f"doc{doc['doc']['owner_id']}_{doc['doc']['id']}"
            send_message(user_id, f"✅ Оплата прошла успешно! Отправляю курс: {title}", attachment=attachment)
        else:
            send_message(user_id, f"✅ Оплата прошла успешно! Курс '{title}' будет отправлен менеджером.")
    except Exception:
        logger.exception("Failed to deliver course_id=%s to user_id=%s", course_id, user_id)


def parse_payload(payload_raw):
    if not payload_raw:
        return {}
    if isinstance(payload_raw, dict):
        return payload_raw
    if isinstance(payload_raw, str):
        try:
            return json.loads(payload_raw)
        except json.JSONDecodeError:
            logger.warning("Invalid VK payload JSON: %s", payload_raw)
            return {}
    return {}


@app.get("/")
async def healthcheck():
    return {"status": "ok"}


@app.post("/vk")
async def vk_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        logger.exception("Invalid JSON in /vk webhook")
        return PlainTextResponse("ok")

    if data.get("type") == "confirmation":
        return PlainTextResponse(VK_CONFIRMATION_TOKEN)

    #if VK_CALLBACK_SECRET and data.get("secret") != VK_CALLBACK_SECRET:
       # logger.warning("VK callback secret mismatch")
       # return PlainTextResponse("ok")

    if data.get("type") != "message_new":
        return PlainTextResponse("ok")

    try:
        obj = data.get("object") or {}
        message = obj.get("message") if isinstance(obj, dict) else None
        if not message and isinstance(obj, dict):
            message = obj
        if not isinstance(message, dict):
            message = {}

        peer_id = message.get("peer_id") or message.get("from_id") or message.get("user_id")
        user_id = message.get("from_id") or message.get("user_id") or peer_id

        if not peer_id:
            logger.warning("Cannot detect peer_id in VK payload: %s", data)
            return PlainTextResponse("ok")

        payload_raw = message.get("payload") or obj.get("payload")
        text = (message.get("text") or "").strip().lower()

        payload = parse_payload(payload_raw)
        cmd = payload.get("cmd")
        course_id = payload.get("course_id")

        if cmd == "back":
            send_message(peer_id, "Главное меню", keyboard=make_main_keyboard())
            return PlainTextResponse("ok")

        if cmd == "catalog" or text in {"каталог", "старт", "начать", "меню", "привет", "hello", "hi"}:
            if not get_courses():
                send_message(peer_id, "Каталог пока пуст. Обратитесь к менеджеру.", keyboard=make_main_keyboard())
                return PlainTextResponse("ok")

            send_message(peer_id, build_catalog_text(), keyboard=make_catalog_keyboard())
            return PlainTextResponse("ok")

        if cmd == "buy":
            try:
                selected_course_id = int(course_id)
            except (TypeError, ValueError):
                send_message(peer_id, "Не удалось определить курс. Откройте каталог и нажмите кнопку покупки снова.", keyboard=make_catalog_keyboard())
                return PlainTextResponse("ok")

            course = get_course(selected_course_id)
            if not course:
                send_message(peer_id, "Курс не найден. Откройте каталог и выберите актуальный курс.", keyboard=make_catalog_keyboard())
                return PlainTextResponse("ok")

            if not YOOMONEY_RECEIVER:
                send_message(peer_id, "Оплата временно недоступна: не настроен кошелёк ЮMoney.", keyboard=make_main_keyboard())
                return PlainTextResponse("ok")

            c_id, title, _description, price, _ = course
            payment_label, payment_url = create_yoomoney_payment_url(user_id=user_id, course_id=c_id, amount=price, title=title)
            save_payment(user_id=user_id, course_id=c_id, payment_label=payment_label)

            pay_keyboard = {
                "one_time": False,
                "buttons": [
                    [{"action": {"type": "open_link", "label": "💳 Оплатить", "link": payment_url}}],
                    [{"action": {"type": "text", "label": "Назад", "payload": '{"cmd":"back"}'}, "color": "secondary"}],
                ],
            }
            send_message(peer_id, f"Вы выбрали курс '{title}' за {price} ₽. Нажмите 'Оплатить'.", keyboard=pay_keyboard)
            return PlainTextResponse("ok")

        send_message(peer_id, "Нажмите кнопку 'Каталог'.", keyboard=make_main_keyboard())
        return PlainTextResponse("ok")
    except Exception:
        logger.exception("Unhandled error in /vk webhook")
        return PlainTextResponse("ok")


@app.post("/yoomoney")
async def yoomoney_webhook(request: Request):
    form = dict(await request.form())

    if not verify_yoomoney_notification(form):
        logger.warning("Invalid YuMoney notification: %s", form)
        return PlainTextResponse("invalid", status_code=400)

    payment_label = form.get("label", "")
    payment = get_payment(payment_label)
    if not payment:
        return PlainTextResponse("ok")

    _row_id, user_id, course_id, _payment_id, status = payment
    if status == "paid":
        return PlainTextResponse("ok")

    update_payment_status(payment_label, "paid")
    deliver_course(user_id=int(user_id), course_id=int(course_id))
    return PlainTextResponse("ok")

