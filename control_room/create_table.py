from db.database import Database
from datetime import date, timedelta
import logging
import re
from typing import Optional


async def ensure_chart_table(db: Database, update, context, logger: logging.Logger) -> bool:
    """Убедиться, что таблица chart существует; если нет — создать и уведомить пользователя.

    Возвращает True если таблица не существовала и была создана (в этом случае вызовчик должен сделать return),
    иначе False и можно продолжать работу.
    """
    try:
        logger.debug('ensure_chart_table: entering, проверяем существование таблицы chart')
        with db.get_cursor() as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chart'")
            found = cursor.fetchone()
            if not found:
                cursor.execute('''
                CREATE TABLE chart (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    where_from TEXT,
                    departure_time TEXT,
                    "where" TEXT,
                    arrival_time TEXT,
                    departure_datetime TEXT,
                    customer TEXT,
                    phone TEXT
                )
                ''')
                msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
                await msg.reply_text('Таблица "chart" не была обнаружена и была создана.')
                await msg.reply_text('Заявок нет. Наберите 0 чтобы создать заявку.')
                context.user_data['control_room_wait_create'] = True
                return True

            # Выполнить возможную миграцию departure_datetime
            try:
                cursor.execute("PRAGMA table_info(chart)")
                cols = [r[1] for r in cursor.fetchall()]
            except Exception:
                cols = []
            if 'departure_datetime' not in cols:
                try:
                    cursor.execute("ALTER TABLE chart ADD COLUMN departure_datetime TEXT")
                except Exception:
                    # Игнорируем, если ALTER TABLE не поддерживается
                    pass
                try:
                    cursor.execute("SELECT id, date, departure_time FROM chart")
                    all_rows = cursor.fetchall()
                    for rr in all_rows:
                        rid, dval, tval = rr[0], rr[1], rr[2]
                        if dval and tval:
                            dt_comb = None
                            try:
                                # Попытаться нормализовать время в HH:MM
                                m = re.match(r'^(\d{1,2}):(?P<min>\d{1,2})(?::\d{1,2})?$', str(tval).strip())
                                tnorm = None
                                if m:
                                    h = int(m.group(0).split(':')[0])
                                    mi = int(m.group(0).split(':')[1])
                                    if 0 <= h < 24 and 0 <= mi < 60:
                                        tnorm = f"{h:02d}:{mi:02d}"
                                if tnorm:
                                    dt_comb = f"{dval} {tnorm}:00"
                            except Exception:
                                dt_comb = None
                            if dt_comb:
                                cursor.execute('UPDATE chart SET departure_datetime = ? WHERE id = ?', (dt_comb, rid))
                except Exception:
                    logger.exception('Не удалось заполнить departure_datetime для существующих записей')
                try:
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chart_departure_datetime ON chart(departure_datetime)')
                except Exception:
                    logger.exception('Не удалось создать индекс idx_chart_departure_datetime')
            else:
                logger.debug('ensure_chart_table: поле departure_datetime уже присутствует')
    except Exception:
        msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
        logger.exception('Ошибка доступа к базе данных при обеспечении таблицы chart')
        await msg.reply_text('Ошибка доступа к базе данных при проверке таблицы chart.')
    return False
