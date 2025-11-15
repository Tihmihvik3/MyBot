import logging
from utils.admin_messenger import send_and_track, delete_tracked_messages

logger = logging.getLogger(__name__)


class EditDB:
    fields = [
        "Фамилия", "Имя", "Отчество", "Дата рождения", "Группа инвалидности", "Телефон", "Адрес", "Район", "Группа", "Справка МСЭ", "Дата выдачи справки МСЭ", "Срок действия справки MСЭ", "Пенсионное удостоверение", "Номер членского билета", "Дата вступления", "Пол"
    ]
    db_fields = [
        "surname", "name", "patronymic", "date_birth", "group_disability", "phone", "address", "area", "`group`", "help_number", "date_issue", "validity_period", "pension_number", "ticket_number", "date_entry", "floor"
    ]

    async def search_and_show_fields(self, update, context):
        # Отправим приглашение через send_and_track (он удалит старые сообщения перед отправкой)
        try:
            await send_and_track(context, update.message, 'Введите фамилию для поиска:')
        except Exception:
            logger.exception('search_and_show_fields: send_and_track failed; falling back')
            await update.message.reply_text('Введите фамилию для поиска:')
        context.user_data['editdb_awaiting_surname'] = True

    async def handle_surname_search(self, update, context):
        # Обработка поиска по фамилии (LIKE, без учёта регистра) и вывод Фамилия, Имя, Отчество с нумерацией
        surname = update.message.text.strip()
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT rowid, ' + ', '.join(self.db_fields) + ' FROM members WHERE LOWER(surname) LIKE LOWER(?)', (surname + '%',))
                rows = cursor.fetchall()
                if not rows:
                    try:
                        await send_and_track(context, update.message, 'Совпадений не найдено.')
                    except Exception:
                        await update.message.reply_text('Совпадений не найдено.')
                    context.user_data['editdb_awaiting_surname'] = False
                    return
                context.user_data['editdb_search_results'] = rows
                if len(rows) == 1:
                    row = rows[0]
                    try:
                        await send_and_track(context, update.message, f"Вы выбрали: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}")
                    except Exception:
                        await update.message.reply_text(f"Вы выбрали: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}")
                    context.user_data['editdb_selected_rowid'] = row[0]
                    await self.show_edit_menu(update, context)
                else:
                    msg = 'Результаты поиска:\n'
                    for idx, row in enumerate(rows, 1):
                        msg += f"{idx}. Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}\n"
                    msg += 'Введите номер нужной записи:'
                    try:
                        await send_and_track(context, update.message, msg)
                    except Exception:
                        await update.message.reply_text(msg)
                    context.user_data['editdb_awaiting_choice'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при поиске: {e}')
        context.user_data['editdb_awaiting_surname'] = False

    async def handle_choose_result(self, update, context):
        # Обработка выбора результата поиска
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text('Введите номер из списка!')
            return
        idx = int(text)
        results = context.user_data.get('editdb_search_results', [])
        if idx < 1 or idx > len(results):
            await update.message.reply_text('Некорректный номер!')
            return
        row = results[idx-1]
        await update.message.reply_text(f"Вы выбрали: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}")
        context.user_data['editdb_selected_rowid'] = row[0]
        await self.show_edit_menu(update, context)
        context.user_data['editdb_awaiting_choice'] = False

    async def edit_member_by_id(self, update, context, member_id):
        """
        Начать редактирование конкретной записи по id (вызывается из callback'а).
        Устанавливает выбранный rowid в context и показывает меню выбора поля.
        """
        # Сохраним выбранный rowid в состоянии модуля
        try:
            context.user_data['editdb_selected_rowid'] = member_id
        except Exception:
            pass
        # Сразу показать меню редактирования (оно использует send_and_track)
        await self.show_edit_menu(update, context)

    async def show_edit_menu(self, update, context):
        # Показать меню редактирования как Inline-клавиатуру (callback-driven)
        selected_rowid = context.user_data.get('editdb_selected_rowid')
        if not selected_rowid:
            try:
                await send_and_track(context, update.message, 'Ошибка: не выбран идентификатор записи для редактирования.')
            except Exception:
                await update.message.reply_text('Ошибка: не выбран идентификатор записи для редактирования.')
            return

        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        for idx, col in enumerate(self.fields, 1):
            cb = f'editdb:field:{idx}:{selected_rowid}'
            buttons.append([InlineKeyboardButton(f'{idx}. {col}', callback_data=cb)])
        # Добавим кнопку отмены
        buttons.append([InlineKeyboardButton('Отмена', callback_data='editdb:cancel')])
        kb = InlineKeyboardMarkup(buttons)

        # Удалим старые admin сообщения и отправим клавиатуру
        try:
            if getattr(update, 'message', None):
                sent = await update.message.reply_text('Выберите поле для редактирования:', reply_markup=kb)
            else:
                user = getattr(update, 'effective_user', None)
                chat_id = user.id if user and getattr(user, 'id', None) else (getattr(update.callback_query.from_user, 'id', None) if getattr(update, 'callback_query', None) else None)
                if chat_id:
                    sent = await context.bot.send_message(chat_id=chat_id, text='Выберите поле для редактирования:', reply_markup=kb)
                else:
                    raise RuntimeError('No chat_id to send edit menu')
            try:
                context.user_data['editdb_menu_message'] = (sent.chat.id, sent.message_id)
            except Exception:
                pass
        except Exception:
            logger.exception('show_edit_menu: failed to send edit menu')
        # меню теперь ожидает callback'а, не текст
        context.user_data.pop('editdb_awaiting_field', None)

    async def handle_field_edit(self, update, context):
        # Обработка выбора поля для редактирования
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text('Введите номер поля!')
            return
        idx = int(text)
        if idx < 1 or idx > len(self.fields):
            await update.message.reply_text('Некорректный номер поля!')
            return
        field_name = self.fields[idx-1]
        db_field = self.db_fields[idx-1]
        # Получаем выбранную запись
        results = context.user_data.get('editdb_search_results', [])
        selected_rowid = context.user_data.get('editdb_selected_rowid')
        row = None
        if selected_rowid and results:
            for r in results:
                if r[0] == selected_rowid:
                    row = r
                    break
        elif results:
            row = results[0]
        if row:
            # Форматирование даты в виде DD.MM.YYYY для полей с датами
            display_val = ''
            try:
                display_val = row[idx] if row[idx] is not None else ''
            except Exception:
                display_val = ''
            if display_val and 'Дата' in field_name:
                try:
                    from datetime import datetime
                    dt = datetime.strptime(display_val, '%Y-%m-%d')
                    display_val = dt.strftime('%d.%m.%Y')
                except Exception:
                    pass
            try:
                await send_and_track(context, update.message, f'Текущее значение поля "{field_name}": {display_val}\nВведите новое значение:')
            except Exception:
                await update.message.reply_text(f'Текущее значение поля "{field_name}": {display_val}\nВведите новое значение:')
            context.user_data['editdb_awaiting_new_value'] = {'field': db_field, 'rowid': row[0], 'field_name': field_name}
            context.user_data['editdb_awaiting_field'] = False  # <--- Сброс ожидания выбора поля
        else:
            await update.message.reply_text('Ошибка: не удалось получить запись для редактирования.')

    async def handle_new_value(self, update, context):
        # Сохраняем новое значение и показываем пользователю, затем предлагаем продолжить или выйти
        data = context.user_data.get('editdb_awaiting_new_value')
        if not data:
            await update.message.reply_text('Нет данных для обновления.')
            return
        # Перед уведомлением о сохранении используем send_and_track
        new_value = update.message.text.strip()
        field = data['field']
        rowid = data['rowid']
        field_name = data['field_name']
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                # Очищаем ячейку (ставим пустое значение)
                cursor.execute(f'UPDATE members SET {field} = NULL WHERE rowid = ?', (rowid,))
                # Вносим новое значение
                cursor.execute(f'UPDATE members SET {field} = ? WHERE rowid = ?', (new_value, rowid))
            try:
                await send_and_track(context, update.message, f'Новое значение поля "{field_name}": {new_value} успешно сохранено!')
            except Exception:
                await update.message.reply_text(f'Новое значение поля "{field_name}": {new_value} успешно сохранено!')
            # Предложить продолжить или выйти
            try:
                await send_and_track(context, update.message, 'Выберите действие:\n1. Продолжить редактирование\n2. Выход')
            except Exception:
                await update.message.reply_text('Выберите действие:\n1. Продолжить редактирование\n2. Выход')
            context.user_data['editdb_continue_or_exit'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сохранении: {e}')
        context.user_data['editdb_awaiting_new_value'] = None

    async def process_field_callback(self, update, context):
        """
        Обработка нажатия на поле в Inline-клавиатуре выбора поля.
        Устанавливает состояние ожидания нового значения и просит ввести текст.
        Callback data: editdb:field:<idx>:<rowid>
        """
        query = update.callback_query
        data = getattr(query, 'data', '') or ''
        try:
            await query.answer()
        except Exception:
            pass
        parts = data.split(':')
        if len(parts) < 4:
            try:
                await query.message.reply_text('Некорректные данные callback.')
            except Exception:
                pass
            return
        try:
            idx = int(parts[2])
            rowid = int(parts[3])
        except Exception:
            try:
                await query.message.reply_text('Некорректный идентификатор поля или записи.')
            except Exception:
                pass
            return
        if idx < 1 or idx > len(self.fields):
            try:
                await query.message.reply_text('Некорректный номер поля.')
            except Exception:
                pass
            return
        field_name = self.fields[idx-1]
        db_field = self.db_fields[idx-1]

        # Удалим меню выбора поля
        try:
            menu_msg = context.user_data.pop('editdb_menu_message', None)
            if menu_msg and isinstance(menu_msg, (list, tuple)) and len(menu_msg) >= 2:
                try:
                    await context.bot.delete_message(chat_id=menu_msg[0], message_id=menu_msg[1])
                except Exception:
                    pass
        except Exception:
            pass

        # Сохраняем ожидание нового значения
        context.user_data['editdb_awaiting_new_value'] = {'field': db_field, 'rowid': rowid, 'field_name': field_name}

        # Попросим ввести новое значение (текстовое). Это единственная текстовая точка ввода.
        try:
            await query.message.reply_text(f'Введите новое значение для поля "{field_name}":')
        except Exception:
            try:
                user_id = getattr(query.from_user, 'id', None)
                if user_id:
                    await context.bot.send_message(chat_id=user_id, text=f'Введите новое значение для поля "{field_name}":')
            except Exception:
                pass
        # Флаг, что ожидаем текстовый ввод
        context.user_data['editdb_waiting_text'] = True

    async def handle_cancel_callback(self, update, context):
        query = update.callback_query
        try:
            await query.answer()
        except Exception:
            pass
        # Удалим меню
        try:
            menu_msg = context.user_data.pop('editdb_menu_message', None)
            if menu_msg and isinstance(menu_msg, (list, tuple)) and len(menu_msg) >= 2:
                try:
                    await context.bot.delete_message(chat_id=menu_msg[0], message_id=menu_msg[1])
                except Exception:
                    pass
        except Exception:
            pass
        try:
            await query.message.reply_text('Редактирование отменено.')
        except Exception:
            pass

    async def handle_continue_or_exit(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            # Продолжить редактирование — снова показать меню выбора поля
            await self.show_edit_menu(update, context)
            context.user_data['editdb_continue_or_exit'] = False
        elif text == '2':
            # Выход — перейти к меню выбора действия администратора (WorkDB)
            await update.message.reply_text('Выберите действие администратора:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\nВведите номер действия:')
            context.user_data['editdb_continue_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text('Введите 1 (продолжить) или 2 (выход).')

    async def process_state(self, update, context):
        """
        Универсальная обработка состояний для EditDB.
        Возвращает True если сообщение обработано модулем.
        """
        if context.user_data.get('editdb_continue_or_exit'):
            await self.handle_continue_or_exit(update, context)
            return True
        if context.user_data.get('editdb_awaiting_surname'):
            await self.handle_surname_search(update, context)
            return True
        if context.user_data.get('editdb_awaiting_choice'):
            await self.handle_choose_result(update, context)
            return True
        if context.user_data.get('editdb_awaiting_field'):
            await self.handle_field_edit(update, context)
            return True
        if context.user_data.get('editdb_awaiting_new_value'):
            await self.handle_new_value(update, context)
            return True
        return False
