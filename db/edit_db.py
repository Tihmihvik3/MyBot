import logging
import asyncio
from utils.admin_messenger import send_and_track, delete_tracked_messages
import messages_admin as MESSAGES_ADMIN
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from utils.member_formatter import get_member_details_text

logger = logging.getLogger(__name__)


class EditDB:
    fields = [
        "Фамилия", "Имя", "Отчество", "Дата рождения", "Группа инвалидности", "Телефон", "Адрес", "Район", "Группа", "Справка МСЭ", "Дата выдачи справки МСЭ", "Срок действия справки MСЭ", "Пенсионное удостоверение", "Номер членского билета", "Дата вступления", "Пол"
    ]
    db_fields = [
        "surname", "name", "patronymic", "date_birth", "group_disability", "phone", "address", "area", "`group`", "help_number", "date_issue", "validity_period", "pension_number", "ticket_number", "date_entry", "floor"
    ]

    # Копия маппинга полей для отображения деталей (используется при показе деталей из EditDB)
    FIELD_MAP = {  # Сопоставление полей базы данных с пользовательскими названиями
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

    async def search_and_show_fields(self, update, context):
        # Отправим приглашение через send_and_track (он удалит старые сообщения перед отправкой)
        try:
            await send_and_track(context, update.message, MESSAGES_ADMIN.SEARCH_ENTER_SURNAME)
        except Exception:
            logger.exception('search_and_show_fields: send_and_track failed; falling back')
            await update.message.reply_text(MESSAGES_ADMIN.SEARCH_ENTER_SURNAME)
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
                        await send_and_track(context, update.message, MESSAGES_ADMIN.SEARCH_NO_MATCH_SIMPLE)
                    except Exception:
                        await update.message.reply_text(MESSAGES_ADMIN.SEARCH_NO_MATCH_SIMPLE)
                    context.user_data['editdb_awaiting_surname'] = False
                    return
                context.user_data['editdb_search_results'] = rows
                if len(rows) == 1:
                    row = rows[0]
                    try:
                        await send_and_track(context, update.message, MESSAGES_ADMIN.SELECTED_RECORD_TEMPLATE.format(surname=row[1], name=row[2], patronymic=row[3]))
                    except Exception:
                        await update.message.reply_text(MESSAGES_ADMIN.SELECTED_RECORD_TEMPLATE.format(surname=row[1], name=row[2], patronymic=row[3]))
                    context.user_data['editdb_selected_rowid'] = row[0]
                    await self.show_edit_menu(update, context)
                else:
                    # Формируем Inline-клавиатуру с результатами поиска
                    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                    buttons = []
                    for idx, row in enumerate(rows, 1):
                        text = f"{idx}. {row[1]} {row[2]} {row[3]}".strip()
                        cb = f'editdb:selected:{row[0]}'
                        buttons.append([InlineKeyboardButton(text, callback_data=cb)])
                    # Добавим кнопку отмены
                    buttons.append([InlineKeyboardButton(MESSAGES_ADMIN.BTN_CANCEL, callback_data='editdb:cancel')])
                    kb = InlineKeyboardMarkup(buttons)
                    try:
                        await send_and_track(context, update.message, MESSAGES_ADMIN.SEARCH_RESULTS_HEADER, reply_markup=kb)
                    except Exception:
                        try:
                            await update.message.reply_text(MESSAGES_ADMIN.SEARCH_RESULTS_HEADER, reply_markup=kb)
                        except Exception:
                            # fallback: отправим простым текстом
                            msg = 'Результаты поиска:\n'
                            for idx, row in enumerate(rows, 1):
                                msg += f"{idx}. Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}\n"
                            msg += MESSAGES_ADMIN.SEARCH_RESULTS_PROMPT
                            await update.message.reply_text(msg)
                    # Сохраним результаты для совместимости с текстовым вводом
                    context.user_data['editdb_search_results'] = rows
                    # Ожидание теперь будет приходить через callback'ы, сбросим флаг текстового выбора
                    context.user_data.pop('editdb_awaiting_choice', None)
        except Exception as e:
            await update.message.reply_text(MESSAGES_ADMIN.ERROR_SEARCH.format(error=e))
        context.user_data['editdb_awaiting_surname'] = False

    async def handle_choose_result(self, update, context):
        # Обработка выбора результата поиска
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text(MESSAGES_ADMIN.ENTER_NUMBER_FROM_LIST)
            return
        idx = int(text)
        results = context.user_data.get('editdb_search_results', [])
        if idx < 1 or idx > len(results):
            await update.message.reply_text(MESSAGES_ADMIN.INVALID_NUMBER)
            return
        row = results[idx-1]
        await update.message.reply_text(MESSAGES_ADMIN.SELECTED_RECORD_TEMPLATE.format(surname=row[1], name=row[2], patronymic=row[3]))
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
        # Очистим возможные флаги из других модулей (например, control_room), чтобы
        # они не перехватывали дальнейшие текстовые вводы в процессе редактирования.
        try:
            # Удаляем все ключи, начинающиеся с 'control_room_' из user_data
            keys_to_remove = [k for k in list(context.user_data.keys()) if k.startswith('control_room_')]
            for k in keys_to_remove:
                try:
                    context.user_data.pop(k, None)
                except Exception:
                    pass
        except Exception:
            pass
        # Сразу показать меню редактирования (оно использует send_and_track)
        await self.show_edit_menu(update, context)

    async def show_edit_menu(self, update, context):
        # Показать меню редактирования как Inline-клавиатуру (callback-driven)
        selected_rowid = context.user_data.get('editdb_selected_rowid')
        if not selected_rowid:
            try:
                await send_and_track(context, update.message, MESSAGES_ADMIN.NO_ID_SELECTED)
            except Exception:
                await update.message.reply_text(MESSAGES_ADMIN.NO_ID_SELECTED)
            return

        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        for idx, col in enumerate(self.fields, 1):
            cb = f'editdb:field:{idx}:{selected_rowid}'
            buttons.append([InlineKeyboardButton(f'{idx}. {col}', callback_data=cb)])
        # Добавим кнопку отмены
        buttons.append([InlineKeyboardButton(MESSAGES_ADMIN.BTN_CANCEL, callback_data='editdb:cancel')])
        kb = InlineKeyboardMarkup(buttons)

        # Удалим старые admin сообщения и отправим клавиатуру
        try:
            if getattr(update, 'message', None):
                sent = await update.message.reply_text(MESSAGES_ADMIN.EDIT_MENU_PROMPT, reply_markup=kb)
            else:
                user = getattr(update, 'effective_user', None)
                chat_id = user.id if user and getattr(user, 'id', None) else (getattr(update.callback_query.from_user, 'id', None) if getattr(update, 'callback_query', None) else None)
                if chat_id:
                    sent = await context.bot.send_message(chat_id=chat_id, text=MESSAGES_ADMIN.EDIT_MENU_PROMPT, reply_markup=kb)
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
            await update.message.reply_text(MESSAGES_ADMIN.ENTER_FIELD_NUMBER)
            return
        idx = int(text)
        if idx < 1 or idx > len(self.fields):
            await update.message.reply_text(MESSAGES_ADMIN.INVALID_FIELD_NUMBER)
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
                await send_and_track(context, update.message, MESSAGES_ADMIN.FIELD_CURRENT_PROMPT.format(field_name=field_name, display=display_val))
            except Exception:
                await update.message.reply_text(MESSAGES_ADMIN.FIELD_CURRENT_PROMPT.format(field_name=field_name, display=display_val))
            context.user_data['editdb_awaiting_new_value'] = {'field': db_field, 'rowid': row[0], 'field_name': field_name}
            context.user_data['editdb_awaiting_field'] = False  # <--- Сброс ожидания выбора поля
        else:
            await update.message.reply_text(MESSAGES_ADMIN.ERROR_SELECT.format(error='не удалось получить запись для редактирования'))

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
            # Перед уведомлением — удалим приглашение ввода, если оно было сохранено
            try:
                pm = context.user_data.pop('editdb_input_prompt_message', None)
                if pm and isinstance(pm, (list, tuple)) and len(pm) >= 2:
                    try:
                        await context.bot.delete_message(chat_id=pm[0], message_id=pm[1])
                    except Exception:
                        pass
            except Exception:
                pass

            # Уведомим о сохранении и запланируем автоматическое удаление через 5 секунд
            sent_success = None
            try:
                sent_success = await send_and_track(context, update.message, MESSAGES_ADMIN.SAVE_SUCCESS.format(field_name=field_name, new_value=new_value))
            except Exception:
                try:
                    sent_success = await update.message.reply_text(MESSAGES_ADMIN.SAVE_SUCCESS.format(field_name=field_name, new_value=new_value))
                except Exception:
                    sent_success = None

            # Если сообщение сохранено — удалить его через 5 секунд (не блокируя поток)
            if sent_success and getattr(sent_success, 'chat', None):
                try:
                    async def _del_after(delay, bot, cid, mid):
                        try:
                            await asyncio.sleep(delay)
                        except Exception:
                            return
                        try:
                            await bot.delete_message(chat_id=cid, message_id=mid)
                        except Exception:
                            pass
                    asyncio.create_task(_del_after(5, context.bot, sent_success.chat.id, sent_success.message_id))
                except Exception:
                    pass
            # После сохранения показываем обновлённые детали записи
            # Получим форматированные детали через общий helper (поддерживает id и rowid)
            try:
                from db.database import Database
                db2 = Database()
                details = get_member_details_text(rowid, db_instance=db2)
            except Exception as e:
                details = MESSAGES_ADMIN.ERROR_SELECT.format(error=e)

            # Отправим детали и кнопки действий (edit/delete/back/exit) — callback'ы оформлены для WorkDB
            try:
                sent_details = await update.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_HEADER + f"\n{details}")
                try:
                    context.user_data['workdb_member_details_message'] = (sent_details.chat.id, sent_details.message_id)
                except Exception:
                    pass
            except Exception:
                try:
                    await update.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_HEADER + f"\n{details}")
                except Exception:
                    pass

            try:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(MESSAGES_ADMIN.BTN_EDIT, callback_data=f'workdb:detail:edit:{rowid}')],
                    [InlineKeyboardButton(MESSAGES_ADMIN.BTN_DELETE, callback_data=f'workdb:detail:delete:{rowid}')],
                    [InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data=f'workdb:detail:back:{rowid}'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data=f'workdb:detail:exit')]
                ])
                sent_kb = await update.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_ACTION_PROMPT, reply_markup=kb)
                try:
                    context.user_data['workdb_member_actions_message'] = (sent_kb.chat.id, sent_kb.message_id)
                except Exception:
                    pass
            except Exception:
                try:
                    await update.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_ACTION_FALLBACK)
                except Exception:
                    pass
        except Exception as e:
            await update.message.reply_text(MESSAGES_ADMIN.ERROR_SELECT.format(error=e))
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
        # Отправить приглашение к вводу нового значения с inline-кнопками "Назад" и "Отмена"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data=f'editdb:input:back:{rowid}'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_CANCEL, callback_data=f'editdb:input:cancel:{rowid}')]  
        ])
        try:
            sent_prompt = await query.message.reply_text(MESSAGES_ADMIN.ENTER_NEW_VALUE_PROMPT.format(field_name=field_name), reply_markup=kb)
            try:
                # save prompt message id so it can be deleted when user enters the value
                context.user_data['editdb_input_prompt_message'] = (sent_prompt.chat.id, sent_prompt.message_id)
            except Exception:
                pass
        except Exception:
            try:
                user_id = getattr(query.from_user, 'id', None)
                if user_id:
                    await context.bot.send_message(chat_id=user_id, text=MESSAGES_ADMIN.ENTER_NEW_VALUE_PROMPT.format(field_name=field_name), reply_markup=kb)
            except Exception:
                pass
        # Флаг, что ожидаем текстовый ввод
        context.user_data['editdb_waiting_text'] = True

    async def handle_input_callback(self, update, context):
        """
        Обработка inline-кнопок, показанных при вводе нового значения (Назад / Отмена).
        Формат callback_data: editdb:input:<action>:<rowid>
        action: back | cancel
        """
        query = update.callback_query
        data = getattr(query, 'data', '') or ''
        try:
            await query.answer()
        except Exception:
            pass
        parts = data.split(':')
        action = parts[2] if len(parts) > 2 else None
        member_id = None
        if len(parts) > 3:
            try:
                member_id = int(parts[3])
            except Exception:
                member_id = None

        # Если нажали "Назад" — показать заново меню выбора поля
        if action == 'back':
            try:
                # удалим текущее сообщение-приглашение с кнопками
                try:
                    await query.message.delete()
                except Exception:
                    pass
                # Показать меню полей
                fake = type('F', (), {})()
                fake.message = query.message
                await self.show_edit_menu(fake, context)
            except Exception:
                try:
                    logger.exception('handle_input_callback: failed to handle back')
                except Exception:
                    pass
            return

        # Если нажали "Отмена" — показать детали выбранной записи (обновлённые)
        if action == 'cancel':
            try:
                # удалим приглашение
                try:
                    await query.message.delete()
                except Exception:
                    pass
                # member_id: если не передан, попробуем взять из состояния
                mid = member_id or context.user_data.get('editdb_selected_rowid') or context.user_data.get('editdb_awaiting_new_value', {}).get('rowid') if context.user_data.get('editdb_awaiting_new_value') else None
                if not mid:
                    # ничего — вернём в админ-меню
                    from bot import admin_message
                    fake = type('F', (), {})()
                    fake.message = query.message
                    await admin_message(fake, context)
                    return

                # Показать детали записи (локальная реализация, подобная WorkDB.show_member_details)
                # Reuse the common formatter which handles id/rowid
                try:
                    details = get_member_details_text(mid)
                except Exception as e:
                    details = MESSAGES_ADMIN.ERROR_SELECT.format(error=e)

                # Отправим текст с деталями и inline-кнопки действий (редактировать/удалить/назад/выход)
                try:
                    sent_details = await query.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_HEADER + f"\n{details}")
                    try:
                        context.user_data['workdb_member_details_message'] = (sent_details.chat.id, sent_details.message_id)
                    except Exception:
                        pass
                except Exception:
                    try:
                        await query.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_HEADER + f"\n{details}")
                    except Exception:
                        pass

                # Кнопки действий — используем callback'ы workdb:detail:... чтобы обработать далее в WorkDB
                try:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(MESSAGES_ADMIN.BTN_EDIT, callback_data=f'workdb:detail:edit:{mid}')],
                        [InlineKeyboardButton(MESSAGES_ADMIN.BTN_DELETE, callback_data=f'workdb:detail:delete:{mid}')],
                        [InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data=f'workdb:detail:back:{mid}'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data=f'workdb:detail:exit')]
                    ])
                    sent_kb = await query.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_ACTION_PROMPT, reply_markup=kb)
                    try:
                        context.user_data['workdb_member_actions_message'] = (sent_kb.chat.id, sent_kb.message_id)
                    except Exception:
                        pass
                except Exception:
                    try:
                        await query.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_ACTION_FALLBACK)
                    except Exception:
                        pass

                # Установим состояние, что ожидаем действия над записью
                context.user_data['member_details_id'] = mid
                context.user_data['awaiting_member_details_action'] = True
            except Exception:
                try:
                    logger.exception('handle_input_callback: failed to show member details on cancel')
                except Exception:
                    pass
            return

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
        # Также удалим приглашение к вводу, если оно есть, и сбросим состояние editdb
        try:
            pm = context.user_data.pop('editdb_input_prompt_message', None)
            if pm and isinstance(pm, (list, tuple)) and len(pm) >= 2:
                try:
                    await context.bot.delete_message(chat_id=pm[0], message_id=pm[1])
                except Exception:
                    pass
        except Exception:
            pass
        # Очистим состояние модуля редактирования
        try:
            for k in ('editdb_awaiting_new_value', 'editdb_awaiting_field', 'editdb_waiting_text', 'editdb_selected_rowid', 'editdb_search_results', 'editdb_awaiting_surname'):
                try:
                    context.user_data.pop(k, None)
                except Exception:
                    pass
        except Exception:
            pass

        # Уведомим пользователя и вернём в админ-меню
        try:
            await query.message.reply_text(MESSAGES_ADMIN.EDITING_CANCELLED)
        except Exception:
            pass
        try:
            # Возврат в меню администратора — используем локальный import, как в других модулях
            from bot import admin_message
            fake = type('F', (), {})()
            fake.callback_query = query
            fake.message = query.message
            await admin_message(fake, context)
        except Exception:
            try:
                logger.exception('handle_cancel_callback: failed to return to admin menu')
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
            await update.message.reply_text(MESSAGES_ADMIN.ADMIN_MAIN_MENU)
            context.user_data['editdb_continue_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text(MESSAGES_ADMIN.ENTER_1_OR_2)

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
