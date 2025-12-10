import sqlite3, os

db_path = os.path.join(r'D:/Python/MyBot/db', 'members_vos.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT id, surname, name, patronymic, phone, telegram_id FROM members WHERE role = 'driver' AND telegram_id IS NOT NULL")
rows = cur.fetchall()
print('DRIVER_COUNT:', len(rows))
for r in rows:
    print(r)
conn.close()
