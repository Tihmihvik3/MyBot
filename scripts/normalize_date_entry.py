#!/usr/bin/env python3
"""
Normalize `date_entry` values in `members` table to YYYY-MM-DD.

Usage:
  python scripts/normalize_date_entry.py --preview   # show changes, don't write
  python scripts/normalize_date_entry.py --apply     # create backup and apply updates

This script uses `utils.date_utils.parse_date_strict` first, and if that fails,
it tries several common date patterns (including YYYY.MM.DD) before giving up.
"""
import argparse
import shutil
import sqlite3
import os
from datetime import datetime
from utils.date_utils import parse_date_strict


def try_more_parsers(s: str):
    if not s:
        return None
    s = s.strip()
    # fast common replacement: dots -> dashes for YYYY.MM.DD
    if s.count('.') == 2 and len(s) >= 8 and s[0:4].isdigit() and s[4] == '.':
        cand = s.replace('.', '-')
        # now cand like YYYY-MM-DD
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
            dt = datetime.strptime(s, p)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            continue
    # try removing common non-digit separators
    s2 = ''.join(ch for ch in s if ch.isdigit())
    if len(s2) == 8:
        # try YYYYMMDD or DDMMYYYY
        try:
            # try YYYYMMDD
            dt = datetime.strptime(s2, "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            try:
                dt = datetime.strptime(s2, "%d%m%Y")
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
    return None


def backup_db(db_path: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = f"{db_path}.bak.{ts}"
    shutil.copy2(db_path, dest)
    return dest


def normalize(db_path: str, apply: bool = False, limit_preview: int = 20):
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute('select rowid, surname, name, patronymic, date_entry from members').fetchall()

    to_update = []
    failures = []

    for row in rows:
        rowid, surname, name, patronymic, date_entry = row
        orig = date_entry or ''
        parsed = parse_date_strict(orig)
        if not parsed:
            parsed = try_more_parsers(orig)
        if parsed:
            # ensure normalized format
            if parsed != orig:
                to_update.append((rowid, f"{surname} {name} {patronymic}".strip(), orig, parsed))
        else:
            # leave empty/null alone
            if orig and orig.strip():
                failures.append((rowid, f"{surname} {name} {patronymic}".strip(), orig))

    print(f"Checked {len(rows)} rows")
    print(f"Will update {len(to_update)} rows")
    print(f"Failed to parse {len(failures)} rows")

    if to_update:
        print("\nSample updates:")
        for r in to_update[:limit_preview]:
            print(r)

    if failures:
        print("\nSample failures:")
        for r in failures[:limit_preview]:
            print(r)

    if apply:
        print("\nApplying updates: creating backup and updating DB...")
        bak = backup_db(db_path)
        print("Backup created:", bak)
        updated = 0
        for rowid, fullname, orig, parsed in to_update:
            cur.execute('update members set date_entry = ? where rowid = ?', (parsed, rowid))
            updated += 1
        conn.commit()
        print(f"Applied {updated} updates")
        if failures:
            print("Rows that still could not be parsed (not changed):")
            for r in failures:
                print(r)
    else:
        print('\nPreview only — no changes were made. Use --apply to write.')

    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Apply updates to DB (creates backup).')
    parser.add_argument('--db', default='db/members_vos.db', help='Path to sqlite DB')
    args = parser.parse_args()

    normalize(args.db, apply=args.apply)


if __name__ == '__main__':
    main()
