import sqlite3

conn = sqlite3.connect("courses.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    description TEXT,
    price INTEGER,
    pdf_path TEXT
)
""")

cursor.execute("""
INSERT INTO courses (title, description, price, pdf_path)
VALUES (?, ?, ?, ?)
""", (
    "Python с нуля",
    "Полный курс по Python для новичков.\n\n"
    "Вы изучите:\n"
    "- основы синтаксиса\n"
    "- переменные и функции\n"
    "- работу с файлами\n"
    "- создание ботов\n\n"
    "Подойдёт для абсолютных новичков.",
    1990,
    "files/course1.pdf"
))

conn.commit()
conn.close()

print("База обновлена")
