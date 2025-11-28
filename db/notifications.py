"""Модуль для управления каналами уведомлений и получателями.

Предназначен для SQLite и использует Database из db.database.
"""
from datetime import datetime
import logging
from typing import List, Optional, Dict

from db.database import Database

logger = logging.getLogger(__name__)

# Используем экземпляр класса Database, как в проекте
_db = Database()


def ensure_channel(name: str, template: str = '', enabled: int = 1) -> int:
    """Создать канал если не существует и вернуть его id."""
    with _db.get_cursor() as cur:
        cur.execute('INSERT OR IGNORE INTO notification_channels (name, template, enabled) VALUES (?, ?, ?)', (name, template, enabled))
        cur.execute('SELECT id FROM notification_channels WHERE name = ?', (name,))
        row = cur.fetchone()
        return row[0] if row else None


def set_template(name: str, template: str, enabled: int = 1) -> int:
    with _db.get_cursor() as cur:
        cur.execute('INSERT OR IGNORE INTO notification_channels (name, template, enabled) VALUES (?, ?, ?)', (name, template, enabled))
        cur.execute('UPDATE notification_channels SET template = ?, enabled = ? WHERE name = ?', (template, enabled, name))
        cur.execute('SELECT id FROM notification_channels WHERE name = ?', (name,))
        row = cur.fetchone()
        return row[0] if row else None


def get_channel_by_name(name: str) -> Optional[Dict]:
    with _db.get_cursor() as cur:
        cur.execute('SELECT id, name, template, enabled FROM notification_channels WHERE name = ?', (name,))
        row = cur.fetchone()
        if not row:
            return None
        return {'id': row[0], 'name': row[1], 'template': row[2], 'enabled': bool(row[3])}


def add_target(channel_id: int, chat_id: str) -> int:
    with _db.get_cursor() as cur:
        cur.execute('INSERT INTO notification_targets (channel_id, chat_id) VALUES (?, ?)', (channel_id, str(chat_id)))
        cur.execute('SELECT id FROM notification_targets WHERE channel_id = ? AND chat_id = ?', (channel_id, str(chat_id)))
        row = cur.fetchone()
        return row[0] if row else None


def remove_target(channel_id: int, chat_id: str) -> bool:
    with _db.get_cursor() as cur:
        cur.execute('DELETE FROM notification_targets WHERE channel_id = ? AND chat_id = ?', (channel_id, str(chat_id)))
        return cur.rowcount > 0


def list_targets(channel_id: int) -> List[str]:
    with _db.get_cursor() as cur:
        cur.execute('SELECT chat_id FROM notification_targets WHERE channel_id = ?', (channel_id,))
        return [r[0] for r in cur.fetchall()]


def list_channels() -> List[Dict]:
    with _db.get_cursor() as cur:
        cur.execute('SELECT id, name, template, enabled FROM notification_channels ORDER BY name')
        return [{'id': r[0], 'name': r[1], 'template': r[2], 'enabled': bool(r[3])} for r in cur.fetchall()]


def create_admin_token(token: str) -> int:
    now = datetime.utcnow().isoformat()
    with _db.get_cursor() as cur:
        cur.execute('INSERT OR IGNORE INTO admin_tokens (token, created_at) VALUES (?, ?)', (token, now))
        cur.execute('SELECT id FROM admin_tokens WHERE token = ?', (token,))
        row = cur.fetchone()
        return row[0] if row else None


def get_admin_token() -> Optional[str]:
    with _db.get_cursor() as cur:
        cur.execute('SELECT token FROM admin_tokens ORDER BY id DESC LIMIT 1')
        row = cur.fetchone()
        return row[0] if row else None


def render_template_safe(template: str, values: Dict[str, str], escape_func=lambda s: s) -> str:
    """Простая и безопасная подстановка только для разрешённых токенов.

    escape_func — функция экранирования значений (например, escape_html из control_room).
    """
    allowed = ['id', 'date', 'where_from', 'departure_time', 'where', 'arrival_time', 'customer', 'phone']
    result = template
    for k in allowed:
        v = values.get(k, '') or ''
        try:
            esc = escape_func(str(v))
        except Exception:
            esc = str(v)
        result = result.replace('{' + k + '}', esc)
    return result


## Helpers for birthday notifications
from datetime import date, timedelta, datetime
def get_admin_telegram_ids() -> list:
    """Return list of telegram_id (as strings) for members with admin roles.

    NOTE: selection restricted to roles 'admin' and 'super_admin' (underscore) per requirements.
    """
    with _db.get_cursor() as cur:
        cur.execute("""
            SELECT DISTINCT telegram_id FROM members
            WHERE (role = 'admin' OR role = 'super_admin') AND telegram_id IS NOT NULL
        """)
        rows = cur.fetchall()
    return [r[0] for r in rows if r and r[0]]


def get_birthdays_for_days_before(days_before: int) -> list:
    """Return list of rows for members whose birthday falls in days_before days from today.

    Each returned row is a dict with keys: id, surname, name, patronymic, group, phone, date_birth
    date_birth is returned as stored in DB (ISO YYYY-MM-DD if available).
    """
    target = (date.today() + timedelta(days=days_before)).strftime('%m-%d')
    with _db.get_cursor() as cur:
        cur.execute(
            """
            SELECT id, surname, name, patronymic, "group", phone, date_birth
            FROM members
            WHERE date_birth IS NOT NULL AND date_birth <> '' AND strftime('%m-%d', date_birth) = ?
            ORDER BY date_birth ASC
            """,
            (target,)
        )
        rows = cur.fetchall()
    results = []
    for r in rows:
        results.append({
            'id': r[0],
            'surname': r[1] or '',
            'name': r[2] or '',
            'patronymic': r[3] or '',
            'group': r[4] or '',
            'phone': r[5] or '',
            'date_birth': r[6] or ''
        })
    return results


def build_birthday_message(rows: list, days_before: int) -> str:
    """Build human-readable message for given birthday rows and offset days_before."""
    if not rows:
        return ''
    header = ''
    if days_before == 0:
        header = 'Сегодня дни рождения членов ВОС:'
    else:
        header = f'Напоминание: через {days_before} дня(ей) — дни рождения членов ВОС:'
    lines = [header, '']
    for i, r in enumerate(rows, start=1):
        try:
            db = r.get('date_birth')
            dob = datetime.strptime(db, '%Y-%m-%d').strftime('%d.%m.%Y') if db else ''
        except Exception:
            dob = r.get('date_birth') or ''
        fullname = ' '.join(p for p in (r.get('surname'), r.get('name'), r.get('patronymic')) if p).strip()
        grp = r.get('group') or ''
        phone = r.get('phone') or ''
        lines.append(f"{i}) {dob} — {fullname} — Группа: {grp} — Тел: {phone}")
    return '\n'.join(lines)


async def send_birthday_notifications(bot, days_before: int) -> int:
    """Async helper to send birthday notifications to all admin telegram ids.

    Returns number of messages attempted (admins count) or 0 if nothing to send.
    """
    admins = get_admin_telegram_ids()
    # include ADMIN_CHAT_ID from settings if configured
    try:
        import settings
        admin_chat = getattr(settings, 'ADMIN_CHAT_ID', None)
        if admin_chat:
            # ensure included as string and avoid duplicates
            if str(admin_chat) not in [str(a) for a in admins]:
                admins.append(str(admin_chat))
    except Exception:
        pass
    rows = get_birthdays_for_days_before(days_before)
    if not rows or not admins:
        return 0
    text = build_birthday_message(rows, days_before)
    sent = 0
    for a in admins:
        try:
            await bot.send_message(chat_id=int(a), text=text)
            sent += 1
        except Exception:
            logger.exception('Failed to send birthday notification to %s', a)
    return sent
