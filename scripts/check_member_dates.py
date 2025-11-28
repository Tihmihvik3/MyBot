import os
import sys
# Ensure project root on path
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.date_utils import parse_date_strict
from db.config import Config
import sqlite3

db_path = os.path.join(os.path.dirname(ROOT), 'MyBot', 'db', Config.DB_NAME) if False else os.path.join(os.path.dirname(__file__), '..', 'db', Config.DB_NAME)
# The above expression is awkward when run from different cwd; construct robustly:
db_path = os.path.join(ROOT, 'db', Config.DB_NAME)

if not os.path.exists(db_path):
    print('Database not found at', db_path)
    sys.exit(2)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("PRAGMA table_info(members)")
cols = [r[1] for r in cur.fetchall()]
if not cols:
    print('Table members not found or has no columns')
    conn.close()
    sys.exit(1)

# Columns existence
for fld in ('date_birth','date_entry'):
    if fld not in cols:
        print(f"Warning: column {fld} not present in members table")

cur.execute('SELECT rowid, surname, name, patronymic, date_birth, date_entry FROM members')
rows = cur.fetchall()

invalid_birth = []
invalid_entry = []

for r in rows:
    rowid, surname, name, patronymic, date_birth, date_entry = r
    fullname = ' '.join([p for p in (surname, name, patronymic) if p])
    # check date_birth
    if date_birth is not None and str(date_birth).strip() != '':
        parsed = parse_date_strict(str(date_birth))
        if not parsed:
            invalid_birth.append((rowid, fullname, date_birth))
    # check date_entry
    if date_entry is not None and str(date_entry).strip() != '':
        parsed = parse_date_strict(str(date_entry))
        if not parsed:
            invalid_entry.append((rowid, fullname, date_entry))

print('Checked', len(rows), 'members')
print('\nInvalid date_birth entries:')
for it in invalid_birth:
    print(it)
print('\nInvalid date_entry entries:')
for it in invalid_entry:
    print(it)

conn.close()

if invalid_birth or invalid_entry:
    sys.exit(3)
else:
    print('\nAll checked dates look valid (or empty).')
    sys.exit(0)
