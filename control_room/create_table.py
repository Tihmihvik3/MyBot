from db.database import Database
from datetime import date, timedelta
import logging
import re
from typing import Optional
import traceback
import asyncio
from admin_notify import notify_admin
from control_room.messages import NO_REQUESTS, CREATE_INSTRUCTION


async def ensure_chart_table(db: Database, update, context, logger: logging.Logger) -> bool:
    """Убедиться, что таблица chart существует; если нет — создать и уведомить пользователя.

    Возвращает True если таблица не существовала и была создана (в этом случае вызовчик должен сделать return),
    иначе False и можно продолжать работу.
    """
    try:
        logger.debug('ensure_chart_table: entering, проверяем существование таблицы chart')
        with db.get_cursor() as cursor:
            def _ensure_addresses_and_customer_tables(cur, logger):
                """Внутренняя утилита: убедиться, что таблицы addresses и customer_addresse существуют."""
                try:
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='addresses'")
                    if not cur.fetchone():
                        cur.execute('''
                        CREATE TABLE addresses (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            address TEXT
                        )
                        ''')
                        logger.info('Создана таблица addresses')
                except Exception:
                    logger.exception('Ошибка при создании таблицы addresses')
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(notify_admin(context, 'Ошибка при создании таблицы addresses (create_table)', traceback.format_exc()))
                    except Exception:
                        pass
                try:
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customer_addresse'")
                    if not cur.fetchone():
                        cur.execute('''
                        CREATE TABLE customer_addresse (
                            customer_id INTEGER,
                            addresse_id INTEGER,
                            direction TEXT,
                            rating INTEGER,
                            FOREIGN KEY(customer_id) REFERENCES members(id),
                            FOREIGN KEY(addresse_id) REFERENCES addresses(id)
                        )
                        ''')
                        logger.info('Создана таблица customer_addresse')
                except Exception:
                    logger.exception('Ошибка при создании таблицы customer_addresse')
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(notify_admin(context, 'Ошибка при создании таблицы customer_addresse (create_table)', traceback.format_exc()))
                    except Exception:
                        pass
                # Создадим уникальный индекс по (customer_id, addresse_id, direction)
                try:
                    cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_addresse_unique ON customer_addresse(customer_id, addresse_id, direction)')
                except Exception:
                    logger.exception('Не удалось создать уникальный индекс для customer_addresse')
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(notify_admin(context, 'Не удалось создать уникальный индекс для customer_addresse (create_table)', traceback.format_exc()))
                    except Exception:
                        pass
                # Создание таблицы customers_rating (customer_id, rating)
                try:
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customers_rating'")
                    if not cur.fetchone():
                        cur.execute('''
                        CREATE TABLE customers_rating (
                            customer_id INTEGER,
                            rating INTEGER,
                            FOREIGN KEY(customer_id) REFERENCES members(id)
                        )
                        ''')
                        logger.info('Создана таблица customers_rating')
                        try:
                            # Создаём уникальный индекс по customer_id, чтобы обеспечить одну запись на заказчика
                            cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_rating_customer_unique ON customers_rating(customer_id)')
                        except Exception:
                            logger.exception('Не удалось создать уникальный индекс для customers_rating')
                            try:
                                loop = asyncio.get_running_loop()
                                loop.create_task(notify_admin(context, 'Не удалось создать уникальный индекс для customers_rating (create_table)', traceback.format_exc()))
                            except Exception:
                                pass
                except Exception:
                    logger.exception('Ошибка при создании таблицы customers_rating')
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(notify_admin(context, 'Ошибка при создании таблицы customers_rating (create_table)', traceback.format_exc()))
                    except Exception:
                        pass

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
                # Создадим связанные таблицы addresses и customer_addresse, если их нет
                _ensure_addresses_and_customer_tables(cursor, logger)
                await msg.reply_text(f'{NO_REQUESTS} {CREATE_INSTRUCTION}')
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
                        loop = asyncio.get_running_loop()
                        loop.create_task(notify_admin(context, 'Не удалось заполнить departure_datetime для существующих записей (create_table)', traceback.format_exc()))
                    except Exception:
                        pass
                try:
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chart_departure_datetime ON chart(departure_datetime)')
                except Exception:
                    logger.exception('Не удалось создать индекс idx_chart_departure_datetime')
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(notify_admin(context, 'Не удалось создать индекс idx_chart_departure_datetime (create_table)', traceback.format_exc()))
                    except Exception:
                        pass
            else:
                logger.debug('ensure_chart_table: поле departure_datetime уже присутствует')
            # Убедимся в наличии таблиц addresses и customer_addresse
            _ensure_addresses_and_customer_tables(cursor, logger)
            # Убедимся в наличии таблицы архива заявок chart_archive
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chart_archive'")
                if not cursor.fetchone():
                    cursor.execute('''
                    CREATE TABLE chart_archive (
                        archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        original_id INTEGER,
                        date TEXT,
                        where_from TEXT,
                        departure_time TEXT,
                        "where" TEXT,
                        arrival_time TEXT,
                        departure_datetime TEXT,
                        customer TEXT,
                        phone TEXT,
                        archived_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    ''')
                    logger.info('Создана таблица chart_archive')
            except Exception:
                logger.exception('Ошибка при создании таблицы chart_archive')
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(notify_admin(context, 'Ошибка при создании таблицы chart_archive (create_table)', traceback.format_exc()))
                except Exception:
                    pass
            # Убедимся в наличии таблицы архива для членов members_archive
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='members_archive'")
                if not cursor.fetchone():
                    cursor.execute('''
                    CREATE TABLE members_archive (
                        archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        original_rowid INTEGER,
                        surname TEXT,
                        name TEXT,
                        patronymic TEXT,
                        date_birth TEXT,
                        group_disability TEXT,
                        phone TEXT,
                        address TEXT,
                        area TEXT,
                        "group" TEXT,
                        help_number TEXT,
                        date_issue TEXT,
                        validity_period TEXT,
                        pension_number TEXT,
                        ticket_number TEXT,
                        date_entry TEXT,
                        floor TEXT,
                        archived_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    ''')
                    logger.info('Создана таблица members_archive')
            except Exception:
                logger.exception('Ошибка при создании таблицы members_archive')
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(notify_admin(context, 'Ошибка при создании таблицы members_archive (create_table)', traceback.format_exc()))
                except Exception:
                    pass
    except Exception:
        msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
        logger.exception('Ошибка доступа к базе данных при обеспечении таблицы chart')
        try:
            await notify_admin(context, 'Ошибка доступа к базе данных при ensure_chart_table (create_table)', traceback.format_exc())
        except Exception:
            pass
        await msg.reply_text('Ошибка доступа к базе данных при проверке таблицы chart.')
    return False
