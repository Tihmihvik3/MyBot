#!/usr/bin/env python3
"""Скрипт для нормализации поля date_birth в таблице members.

Поддерживаемые входные форматы:
- DD-MM-YY  (например, 31-12-85)
- DD.MM.YYYY (например, 31.12.1985)

Нормализуем в формат YYYY-MM-DD.

Правило для двухзначного года: если yy <= 25 -> 2000+yy, иначе 1900+yy.
Если это не подходит — поправьте логику в функции normalize_year.
"""
import re
import sys
from datetime import date

from db.database import Database


DATE_RE = re.compile(r"^\s*(\d{1,2})[.\-](\d{1,2})[.\-](\d{2,4})\s*$")
ALPHA_DATE_RE = re.compile(r"^\s*(\d{1,2})[.\-]([A-Za-zА-Яа-яёЁ]+)[.\-](\d{2,4})\s*$")

# Карта русских сокращённых/полных названий месяцев -> номер
RU_MONTHS = {
    'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'май': 5, 'мая': 5, 'июн': 6, 'июл': 7,
    'авг': 8, 'сен': 9, 'сент': 9, 'окт': 10, 'ноя': 11, 'дек': 12,
    'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4, 'июнь': 6, 'июль': 7,
    'август': 8, 'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12
}


def normalize_year(y_str: str) -> int:
    # y_str может быть '85' или '1985'
    y = int(y_str)
    if len(y_str) == 2:
        # Правило: 00..25 -> 2000..2025, иначе 1900..1999
        if 0 <= y <= 25:
            return 2000 + y
        return 1900 + y
    return y


def normalize_date_value(val: str):
    if not val or not isinstance(val, str):
        return None
    # сначала пробуем числовой формат DD.MM.YYYY или DD-MM-YY
    m = DATE_RE.match(val)
    if m:
        day_s, mon_s, year_s = m.groups()
        try:
            d0 = int(day_s)
            m0 = int(mon_s)
            y0 = int(year_s)
            # Если первый компонент > 31, вероятно формат YYYY-MM-DD
            if d0 > 31:
                # формат скорее всего YYYY-MM-DD: d0=year, m0=month, y0=day
                yr = d0
                mth = m0
                d = y0
            else:
                d = d0
                mth = m0
                yr = normalize_year(year_s)
            dt = date(yr, mth, d)
            return dt.isoformat()
        except Exception:
            return None

    # затем пробуем формат с названием месяца (русские/англ.)
    m = ALPHA_DATE_RE.match(val)
    if m:
        day_s, mon_s, year_s = m.groups()
        mon_key = mon_s.strip().lower()
        # укоротим до первых 3 букв для попытки сопоставления
        mon3 = mon_key[:3]
        mth = None
        if mon3 in RU_MONTHS:
            mth = RU_MONTHS[mon3]
        elif mon_key in RU_MONTHS:
            mth = RU_MONTHS[mon_key]
        else:
            # попробуем английские аббревиатуры
            en_map = {
                'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12
            }
            if mon3 in en_map:
                mth = en_map[mon3]
        if mth is None:
            return None
        try:
            d = int(day_s)
            yr = normalize_year(year_s)
            dt = date(yr, mth, d)
            return dt.isoformat()
        except Exception:
            return None

    return None


def main():
    db = Database()
    if db.connection is None:
        print('Не удалось подключиться к БД; проверьте db/config.py и наличие файла БД.')
        sys.exit(1)

    updated = 0
    failed = []
    total = 0
    with db.get_cursor() as cursor:
        try:
            cursor.execute('SELECT rowid, surname, date_birth FROM members')
        except Exception as e:
            print('Ошибка при чтении таблицы members:', e)
            return
        rows = cursor.fetchall()
        for row in rows:
            total += 1
            rowid, surname, dob = row[0], row[1], row[2]
            new = normalize_date_value(dob)
            if new and new != dob:
                try:
                    cursor.execute('UPDATE members SET date_birth = ? WHERE rowid = ?', (new, rowid))
                    updated += 1
                    print(f'[{rowid}] {surname}: {dob} -> {new}')
                except Exception as e:
                    failed.append((rowid, dob, str(e)))
            else:
                # либо не удалось нормализовать, либо уже в нужном формате
                if new is None and dob:
                    failed.append((rowid, dob, 'parse_failed'))

    print(f'Обработано записей: {total}, обновлено: {updated}, не удалось нормализовать: {len(failed)}')
    if failed:
        print('Список неуспешных записей (rowid, original_value, reason):')
        for f in failed:
            print(f)


if __name__ == '__main__':
    main()
