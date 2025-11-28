import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'db', 'members_vos.db')

def main():
    db = os.path.abspath(DB_PATH)
    if not os.path.exists(db):
        print('DB not found:', db)
        return
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT id, surname, name, patronymic, role, telegram_id FROM members WHERE role IN ('admin','super_admin')")
    rows = cur.fetchall()
    if not rows:
        print('No admin/super_admin rows found')
    else:
        print('Found', len(rows), 'admin(s):')
        for r in rows:
            print('id={:d} | {} {} {} | role={} | telegram_id={}'.format(r[0], r[1], r[2], r[3] or '', r[4], r[5] or ''))
    conn.close()

if __name__ == '__main__':
    main()
