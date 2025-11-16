from db.database import Database
import messages_admin as MESSAGES_ADMIN

# Локальная карта полей для отображения в деталях (русские названия)
FIELD_MAP = {
    'surname': 'Фамилия',
    'name': 'Имя',
    'patronymic': 'Отчество',
    'date_birth': 'Дата рождения',
    'group_disability': 'Группа инвалидности',
    'phone': 'Телефон',
    'address': 'Адрес',
    'area': 'Район',
    'group': 'Группа',
    'help_number': 'Справка МСЭ',
    'date_issue': 'Дата выдачи справки МСЭ',
    'validity_period': 'Срок действия справки MСЭ',
    'pension_number': 'Пенсионное удостоверение',
    'ticket_number': 'Номер членского билета',
    'date_entry': 'Дата вступления',
    'floor': 'Пол',
}


def get_member_details_text(member_id, db_instance: Database = None) -> str:
    """Возвращает форматированную строку с деталями записи member_id.

    Если передан db_instance (объект Database), он будет использован, иначе внутри
    функции создаётся свой Database.

    Возвращает строку с деталями или сообщение об ошибке из messages_admin.
    """
    try:
        own_db = False
        if db_instance is None:
            db_instance = Database()
            own_db = True
        with db_instance.get_cursor() as cursor:
            cursor.execute('PRAGMA table_info(members)')
            columns = [col[1] for col in cursor.fetchall()]
            select_fields = [col for col in FIELD_MAP.keys() if col in columns]
            if select_fields:
                fields_sql = ', '.join([f'"{col}"' for col in select_fields])
            else:
                fields_sql = '*'
            # Try to find by explicit id column first; if not found, try rowid.
            # Some parts of the code use `id`, others used SQLite ROWID. Support both.
            cursor.execute(f"SELECT {fields_sql} FROM members WHERE id = ?", (member_id,))
            result = cursor.fetchone()
            if not result:
                try:
                    cursor.execute(f"SELECT {fields_sql} FROM members WHERE rowid = ?", (member_id,))
                    result = cursor.fetchone()
                except Exception:
                    result = None
            if result:
                details_lines = [f"{FIELD_MAP.get(field, field)}: {value}" for field, value in zip(select_fields, result)]
                details = '\n'.join(details_lines)
            else:
                details = MESSAGES_ADMIN.RECORD_NOT_FOUND_SIMPLE
        return details
    except Exception as e:
        return MESSAGES_ADMIN.ERROR_SELECT.format(error=e)
