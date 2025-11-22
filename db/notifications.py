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
