#!/usr/bin/env python3
import shutil, os, sqlite3
from datetime import datetime
from utils.date_utils import parse_date_strict

# Local duplicate of try_more_parsers
from datetime import datetime as _dt

def try_more_parsers(s: str):
    if not s:
        return None
    s = s.strip()
    if s.count('.') == 2 and len(s) >= 8 and s[0:4].isdigit() and s[4] == '.':
        cand = s.replace('.', '-')
        if parse_date_strict(cand):
            return parse_date_strict(cand)
    patterns = [
        "%Y.%m.%d",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%d-%m-%Y",
        "%d%m%Y",
        "%Y%m%d",
        "%Y %m %d",
    ]
    for p in patterns:
        try:
            dt = _dt.strptime(s, p)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            continue
    s2 = ''.join(ch for ch in s if ch.isdigit())
    if len(s2) == 8:
        try:
            dt = _dt.strptime(s2, "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            try:
                dt = _dt.strptime(s2, "%d%m%Y")
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
    return None

DB='db/members_vos.db'
if not os.path.exists(DB):
    raise SystemExit('DB not found')
# backup
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
bak = f"{DB}.bak.{ts}"
shutil.copy2(DB, bak)
print('Backup created:', bak)
conn = sqlite3.connect(DB)
cur = conn.cursor()
rows = cur.execute('select rowid, surname, name, patronymic, date_entry from members').fetchall()
updates = []
for row in rows:
    rowid, surname, name, patronymic, date_entry = row
    orig = date_entry or ''
    parsed = parse_date_strict(orig)
    if not parsed:
        parsed = try_more_parsers(orig)
    if parsed and parsed != orig:
        updates.append((parsed, rowid))

print('Will apply', len(updates), 'updates')
for parsed, rowid in updates:
    cur.execute('update members set date_entry = ? where rowid = ?', (parsed, rowid))
conn.commit()
print('Applied', len(updates))
conn.close()
