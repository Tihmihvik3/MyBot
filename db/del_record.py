import logging
from utils.admin_messenger import send_and_track, delete_tracked_messages

logger = logging.getLogger(__name__)


class DelRecord:
    db_fields = [
        "surname", "name", "patronymic", "date_birth", "group_disability", "phone", "address", "area", "`group`", "help_number", "date_issue", "validity_period", "pension_number", "ticket_number", "date_entry", "floor"
    ]

    async def start_delete(self, update, context):
        # Удалим предыдущие админские сообщения перед началом удаления
        try:
            await send_and_track(context, update.message, 'Введите фамилию для поиска (для удаления):')
        except Exception:
            logger.exception('start_delete: send_and_track failed; falling back')
            await update.message.reply_text('Введите фамилию для поиска (для удаления):')
        context.user_data['delrecord_awaiting_surname'] = True

    async def handle_surname_search(self, update, context):
        surname = update.message.text.strip()
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT rowid, ' + ', '.join(self.db_fields) + ' FROM members WHERE LOWER(surname) LIKE LOWER(?)', (surname + '%',))
                rows = cursor.fetchall()
                if not rows:
                    try:
                        await send_and_track(context, update.message, 'Совпадений не найдено. Повторить поиск? 1. Да 2. Выход')
                    except Exception:
                        await update.message.reply_text('Совпадений не найдено. Повторить поиск? 1. Да 2. Выход')
                    context.user_data['delrecord_repeat_or_exit'] = True
                    context.user_data['delrecord_awaiting_surname'] = False
                    return
                context.user_data['delrecord_search_results'] = rows
                if len(rows) == 1:
                    row = rows[0]
                    context.user_data['delrecord_selected_rowid'] = row[0]
                    try:
                        await send_and_track(context, update.message, f"Найдена запись: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}. Удалить? 1. Да 2. Нет")
                    except Exception:
                        await update.message.reply_text(f"Найдена запись: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}. Удалить? 1. Да 2. Нет")
                    context.user_data['delrecord_awaiting_confirm'] = True
                else:
                    msg = 'Результаты поиска:\n'
                    for idx, row in enumerate(rows, 1):
                        msg += f"{idx}. Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}\n"
                    msg += 'Введите номер нужной записи:'
                    try:
                        await send_and_track(context, update.message, msg)
                    except Exception:
                        await update.message.reply_text(msg)
                    context.user_data['delrecord_awaiting_choice'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при поиске: {e}')
        context.user_data['delrecord_awaiting_surname'] = False

    async def handle_choose_result(self, update, context):
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text('Введите номер из списка!')
            return
        idx = int(text)
        results = context.user_data.get('delrecord_search_results', [])
        if idx < 1 or idx > len(results):
            await update.message.reply_text('Некорректный номер!')
            return
        row = results[idx-1]
        context.user_data['delrecord_selected_rowid'] = row[0]
        try:
            await send_and_track(context, update.message, f"Вы выбрали: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}. Удалить? 1. Да 2. Нет")
        except Exception:
            await update.message.reply_text(f"Вы выбрали: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}. Удалить? 1. Да 2. Нет")
        context.user_data['delrecord_awaiting_choice'] = False
        context.user_data['delrecord_awaiting_confirm'] = True

    async def handle_confirm(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            # Удалить запись
            rowid = context.user_data.get('delrecord_selected_rowid')
            from db.database import Database
            db = Database()
            try:
                with db.get_cursor() as cursor:
                    # Сначала получим все поля записи
                    cursor.execute('SELECT rowid, ' + ', '.join(self.db_fields) + ' FROM members WHERE rowid = ?', (rowid,))
                    r = cursor.fetchone()
                    if not r:
                        await update.message.reply_text('Запись не найдена для удаления.')
                        context.user_data['delrecord_repeat_or_exit'] = True
                    else:
                        # r: (rowid, surname, name, ...)
                        # Подготовим вставку в members_archive; сопоставляем колонки явно
                        try:
                            cursor.execute('''
                                INSERT INTO members_archive (original_rowid, surname, name, patronymic, date_birth, group_disability, phone, address, area, "group", help_number, date_issue, validity_period, pension_number, ticket_number, date_entry, floor)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                r[0],
                                r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12], r[13], r[14], r[15], r[16]
                            ))
                        except Exception:
                            await update.message.reply_text('Ошибка при архивировании записи. Удаление отменено.')
                            context.user_data['delrecord_repeat_or_exit'] = True
                            return
                        # Если архивирование прошло успешно — удалить исходную запись
                        cursor.execute('DELETE FROM members WHERE rowid = ?', (rowid,))
                        try:
                            await send_and_track(context, update.message, 'Запись успешно удалена и перемещена в архив! Повторить удаление? 1. Да 2. Выход')
                        except Exception:
                            await update.message.reply_text('Запись успешно удалена и перемещена в архив! Повторить удаление? 1. Да 2. Выход')
                        context.user_data['delrecord_repeat_or_exit'] = True
            except Exception as e:
                await update.message.reply_text(f'Ошибка при удалении: {e}')
                context.user_data['delrecord_repeat_or_exit'] = True
        elif text == '2':
            # При отказе удалить — уберём сообщение с подтверждением удаления, если оно есть
            try:
                conf = context.user_data.pop('delrec_confirm_message', None)
                if conf and isinstance(conf, (list, tuple)) and len(conf) >= 2:
                    try:
                        await context.bot.delete_message(chat_id=conf[0], message_id=conf[1])
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                await send_and_track(context, update.message, '1. Повторить поиск\n2. Выход')
            except Exception:
                await update.message.reply_text('1. Повторить поиск\n2. Выход')
            context.user_data['delrecord_repeat_or_exit'] = True
        else:
            await update.message.reply_text('Введите 1 (Да) или 2 (Нет).')

        context.user_data['delrecord_awaiting_confirm'] = False

    async def handle_repeat_or_exit(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            # Повторить поиск
            await self.start_delete(update, context)
            context.user_data['delrecord_repeat_or_exit'] = False
        elif text == '2':
            # Выход — вернуться к меню администратора
            try:
                await send_and_track(context, update.message, 'Выберите действие администратора:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\nВведите номер действия:')
            except Exception:
                await update.message.reply_text('Выберите действие администратора:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\nВведите номер действия:')
            context.user_data['delrecord_repeat_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text('Введите 1 (повторить) или 2 (выход).')

    async def delete_member_by_id(self, update, context, member_id):
        """
        Начать удаление записи по id (вызов из callback'а).
        Сохранит выбранный rowid и предложит подтвердить удаление.
        """
        try:
            context.user_data['delrecord_selected_rowid'] = member_id
        except Exception:
            pass
        # Получим данные записи для показа пользователю
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT id, surname, name, patronymic FROM members WHERE id = ?', (member_id,))
                r = cursor.fetchone()
                if not r:
                    try:
                        await send_and_track(context, update.message, 'Запись не найдена для удаления.')
                    except Exception:
                        await update.message.reply_text('Запись не найдена для удаления.')
                    return

                # Формируем компактный текст: только значения полей (без названий)
                surname = r[1] if len(r) > 1 and r[1] is not None else ''
                name = r[2] if len(r) > 2 and r[2] is not None else ''
                patronymic = r[3] if len(r) > 3 and r[3] is not None else ''
                record_text = ' '.join(part for part in (surname, name, patronymic) if part)

                # Inline-подтверждение: Да / Нет
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Да', callback_data=f'delrec:yes:{member_id}'), InlineKeyboardButton('Нет', callback_data=f'delrec:no:{member_id}')]
                ])
                try:
                    sent = await update.message.reply_text(f'Запись:\n{record_text}\nУдалить?', reply_markup=kb)
                    try:
                        context.user_data['delrec_confirm_message'] = (sent.chat.id, sent.message_id)
                        try:
                            logger.info(f"delete_member_by_id: sent confirm message and saved delrec_confirm_message={(sent.chat.id, sent.message_id)} for member_id={member_id}")
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception:
                    # fallback
                    try:
                        await send_and_track(context, update.message, f'Запись:\n{record_text}\nУдалить?\n1. Да 2. Нет')
                    except Exception:
                        await update.message.reply_text(f'Запись:\n{record_text}\nУдалить?\n1. Да 2. Нет')
                    context.user_data['delrecord_awaiting_confirm'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при подготовке удаления: {e}')

    async def archive_and_delete_by_id(self, update, context, member_id):
        """
        Архивировать запись в members_archive и удалить из members.
        Возвращает True при успехе, False при ошибке.
        """
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                # Получим структуру таблицы members
                cursor.execute('PRAGMA table_info(members)')
                cols_info = cursor.fetchall()
                cols = [c[1] for c in cols_info]
                # Выберем все значения для этой записи
                sel_fields = ', '.join([f'"{c}"' for c in cols]) if cols else '*'
                cursor.execute(f'SELECT {sel_fields} FROM members WHERE id = ?', (member_id,))
                row = cursor.fetchone()
                if not row:
                    return False

                # Список полей для архива (кроме archive_id и archived_at)
                archive_fields = [
                    'original_rowid', 'surname', 'name', 'patronymic', 'date_birth', 'group_disability', 'phone', 'address', 'area', 'group', 'help_number', 'date_issue', 'validity_period', 'pension_number', 'ticket_number', 'date_entry', 'floor'
                ]

                # Соберём значения в том порядке, который ожидает members_archive
                values = [member_id]
                for af in archive_fields[1:]:
                    # В schema archive field name for "group" is "group" but in PRAGMA it may be group or `group`
                    colname = af
                    # special-case group field name
                    if af == 'group':
                        # try both group and `group`
                        candidates = ['group', '"group"', '`group`']
                    else:
                        candidates = [colname]
                    val = None
                    for cand in candidates:
                        if cand in cols:
                            idx = cols.index(cand)
                            val = row[idx]
                            break
                    values.append(val)

                # Выполним вставку в members_archive
                placeholders = ', '.join(['?'] * len(values))
                fields_sql = ', '.join(['original_rowid', 'surname', 'name', 'patronymic', 'date_birth', 'group_disability', 'phone', 'address', 'area', '"group"', 'help_number', 'date_issue', 'validity_period', 'pension_number', 'ticket_number', 'date_entry', 'floor'])
                try:
                    cursor.execute(f'INSERT INTO members_archive ({fields_sql}) VALUES ({placeholders})', tuple(values))
                except Exception:
                    # Если не удалось архивировать — отменяем удаление
                    return False

                # Удалим запись из members
                try:
                    cursor.execute('DELETE FROM members WHERE id = ?', (member_id,))
                except Exception:
                    return False
        except Exception:
            return False
        return True
    async def process_state(self, update, context):
        """
        Универсальный обработчик состояния для DelRecord.
        Возвращает True, если модуль обработал текущее сообщение.
        """
        if context.user_data.get('delrecord_repeat_or_exit'):
            await self.handle_repeat_or_exit(update, context)
            return True
        if context.user_data.get('delrecord_awaiting_surname'):
            await self.handle_surname_search(update, context)
            return True
        if context.user_data.get('delrecord_awaiting_choice'):
            await self.handle_choose_result(update, context)
            return True
        if context.user_data.get('delrecord_awaiting_confirm'):
            await self.handle_confirm(update, context)
            return True
        return False
