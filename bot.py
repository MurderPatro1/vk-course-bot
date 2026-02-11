import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import sqlite3
import random
import os

TOKEN = os.getenv("VK_TOKEN")


ADMINS = [695637048]  # твой ID

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)


# =========================
# Работа с БД
# =========================

def get_courses():
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, price, description, pdf_path FROM courses")
    courses = cursor.fetchall()
    conn.close()
    return courses


def update_price(course_id, new_price):
    conn = sqlite3.connect("courses.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE courses SET price = ? WHERE id = ?",
        (new_price, course_id)
    )
    conn.commit()
    conn.close()


# =========================
# Клавиатуры
# =========================

def main_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("📚 Каталог", VkKeyboardColor.PRIMARY)
    return keyboard


def catalog_keyboard(courses):
    keyboard = VkKeyboard(one_time=False)

    for course in courses:
        keyboard.add_button(f"{course[1]}", VkKeyboardColor.PRIMARY)
        keyboard.add_line()

    keyboard.add_button("🏠 В меню", VkKeyboardColor.SECONDARY)
    return keyboard


def course_keyboard(course_id):
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button(f"🛒 Купить {course_id}", VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button("⬅ Назад", VkKeyboardColor.SECONDARY)
    return keyboard


def admin_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("✏ Изменить цену", VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("🏠 В меню", VkKeyboardColor.SECONDARY)
    return keyboard


# =========================
# Бот
# =========================

print("Бот запущен")

for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:

        user_id = event.user_id
        text = event.text.strip()

        # =========================
        # Главное меню
        # =========================

        if text.lower() in ["начать", "start", "🏠 в меню"]:
            vk.messages.send(
                user_id=user_id,
                message="Добро пожаловать!",
                keyboard=main_keyboard().get_keyboard(),
                random_id=random.randint(1, 999999)
            )

        # =========================
        # Каталог
        # =========================

        elif text == "📚 Каталог":
            courses = get_courses()

            vk.messages.send(
                user_id=user_id,
                message="📚 Наши курсы:",
                keyboard=catalog_keyboard(courses).get_keyboard(),
                random_id=random.randint(1, 999999)
            )

        # =========================
        # Назад
        # =========================

        elif text == "⬅ Назад":
            courses = get_courses()

            vk.messages.send(
                user_id=user_id,
                message="📚 Каталог:",
                keyboard=catalog_keyboard(courses).get_keyboard(),
                random_id=random.randint(1, 999999)
            )

        # =========================
        # Админ вход
        # =========================

        elif text.lower() == "/admin":
            if user_id in ADMINS:
                vk.messages.send(
                    user_id=user_id,
                    message="🔐 Админ-панель",
                    keyboard=admin_keyboard().get_keyboard(),
                    random_id=random.randint(1, 999999)
                )
            else:
                vk.messages.send(
                    user_id=user_id,
                    message="Нет доступа",
                    random_id=random.randint(1, 999999)
                )

        # =========================
        # Изменение цены (кнопка)
        # =========================

        elif text == "✏ Изменить цену":
            if user_id in ADMINS:
                vk.messages.send(
                    user_id=user_id,
                    message="Введите: Цена ID Новая_цена\nПример: Цена 1 2990",
                    random_id=random.randint(1, 999999)
                )

        # =========================
        # Команда смены цены
        # =========================

        elif text.startswith("Цена"):
            if user_id in ADMINS:
                try:
                    parts = text.split()
                    course_id = int(parts[1])
                    new_price = int(parts[2])

                    update_price(course_id, new_price)

                    vk.messages.send(
                        user_id=user_id,
                        message="✅ Цена обновлена",
                        random_id=random.randint(1, 999999)
                    )
                except:
                    vk.messages.send(
                        user_id=user_id,
                        message="Ошибка формата",
                        random_id=random.randint(1, 999999)
                    )

        # =========================
        # Открытие курса
        # =========================

        else:
            courses = get_courses()
            found = False

            for course in courses:
                if text == course[1]:
                    found = True
                    message = f"📘 {course[1]}\n\n💰 Цена: {course[2]} руб.\n\n{course[3]}"

                    vk.messages.send(
                        user_id=user_id,
                        message=message,
                        keyboard=course_keyboard(course[0]).get_keyboard(),
                        random_id=random.randint(1, 999999)
                    )
                    break

            # =========================
            # Покупка
            # =========================

            if text.startswith("🛒 Купить"):
                try:
                    course_id = int(text.split()[-1])

                    for course in courses:
                        if course[0] == course_id:
                            pdf_path = course[4]

                            upload = vk_api.VkUpload(vk_session)
                            doc = upload.document_message(pdf_path, peer_id=user_id)

                            attachment = f"doc{doc['doc']['owner_id']}_{doc['doc']['id']}"

                            vk.messages.send(
                                user_id=user_id,
                                message="Спасибо за покупку!",
                                attachment=attachment,
                                random_id=random.randint(1, 999999)
                            )
                            break
                except Exception as e:
                    print("Ошибка покупки:", e)
