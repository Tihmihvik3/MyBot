#!/usr/bin/env python3
"""Replace date_entry values in format YYYY.MM.DD with YYYY-MM-DD.

Creates a timestamped backup of the DB, updates only exact matches of
four digits '.' two digits '.' two digits (e.g. 2022.06.16) and reports
how many rows were changed.
"""
import re
import shutil
import sqlite3
import os
from datetime import datetime

DB = 'db/members_vos.db'

def backup(db_path):
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = f"{db_path}.bak.{ts}"
    shutil.copy2(db_path, dest)
    return dest

def run():
    print('DB:', DB)
    bak = backup(DB)
    print('Backup created:', bak)

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    rows = cur.execute('select rowid, date_entry from members where date_entry is not null').fetchall()
    pattern = re.compile(r'^\d{4}\.\d{2}\.\d{2}$')
    to_update = []
    for rowid, val in rows:
        if val and pattern.match(val.strip()):
            new = val.strip().replace('.', '-')
            to_update.append((new, rowid, val))

    print('Matches to update:', len(to_update))
    for new, rowid, orig in to_update:
        cur.execute('update members set date_entry = ? where rowid = ?', (new, rowid))

    conn.commit()
    conn.close()
    print('Applied updates')

if __name__ == '__main__':
    run()
