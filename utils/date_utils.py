"""Утилиты для разбора и нормализации дат.

Функции возвращают строку в формате ISO YYYY-MM-DD при успешном разборе,
или None при некорректном вводе.
"""
from datetime import datetime
from typing import Optional


def parse_date_strict(text: str) -> Optional[str]:
    """Попытаться распарсить дату в одном из поддерживаемых форматов.

    Поддерживаемые входы:
    - DD.MM.YYYY   -> возвращает YYYY-MM-DD
    - DDMMYYYY     -> возвращает YYYY-MM-DD
    - YYYY-MM-DD   -> возвращает YYYY-MM-DD (пасс-тру)

    Если парсинг не удался, возвращает None.
    """
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    # ISO
    try:
        if len(s) == 10 and s[4] == '-' and s[7] == '-':
            # YYYY-MM-DD
            dt = datetime.strptime(s, '%Y-%m-%d')
            return dt.date().isoformat()
    except Exception:
        pass

    # YYYY.MM.DD (common in DB exports) or YYYY/MM/DD
    try:
        if len(s) == 10 and s[4] == '.' and s[7] == '.':
            dt = datetime.strptime(s, '%Y.%m.%d')
            return dt.date().isoformat()
        if len(s) == 10 and s[4] == '/' and s[7] == '/':
            dt = datetime.strptime(s, '%Y/%m/%d')
            return dt.date().isoformat()
    except Exception:
        pass

    # DD.MM.YYYY
    try:
        if len(s) == 10 and s[2] == '.' and s[5] == '.':
            dt = datetime.strptime(s, '%d.%m.%Y')
            return dt.date().isoformat()
    except Exception:
        pass

    # DDMMYYYY
    try:
        if len(s) == 8 and s.isdigit():
            day = s[0:2]
            mon = s[2:4]
            year = s[4:8]
            dt = datetime.strptime(f"{day}.{mon}.{year}", '%d.%m.%Y')
            return dt.date().isoformat()
    except Exception:
        pass

    return None
