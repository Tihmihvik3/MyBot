from bot import admin_message
import messages_admin as MESSAGES_ADMIN
import logging
from db.database import Database
from utils.member_formatter import get_member_details_text
from db.edit_db import EditDB
from db.add_record import AddRecord
from db.del_record import DelRecord
from utils.admin_messenger import delete_tracked_messages

class WorkDB:
    def __init__(self):
        """
        Инициализация класса WorkDB, подключение к базе данных.
        """
        self.db = Database()
        self.logger = logging.getLogger(__name__)

    async def handle_admin_action(self, update, context):
        """
        Обрабатывает действия администратора, перенаправляет на соответствующий метод по выбору.
        """
        text = update.message.text.strip()
        # Обработка выбора пользователя из отсортированного списка
        if context.user_data.get('awaiting_member_detail_choice'):
            await self._handle_member_detail_choice(update, context, text)
            return
        # Обработка выбора действия над записью (редактировать/удалить/выйти)
        if context.user_data.get('awaiting_member_details_action'):
            await self.handle_member_details_action(update, context)
            return
        # Основное меню действий
        actions = {
            '1': self.show_sorted_by_surname,
            '2': self._handle_search_surname,
            '3': self._handle_edit_surname,
            '4': self._handle_add_record,
            '5': self._handle_delete_record,
        }
        action = actions.get(text)
        if action:
            await action(update, context)
        else:
            await update.message.reply_text(MESSAGES_ADMIN.WORKDB_INVALID_CHOICE)

    async def _handle_member_detail_choice(self, update, context, text):
        """
        Обрабатывает выбор пользователя для просмотра подробных данных по номеру записи.
        """
        context.user_data['awaiting_member_detail_choice'] = False
        if text == '0':
            await update.message.reply_text(MESSAGES_ADMIN.ADMIN_EXIT_TO_MENU)
            
            await admin_message(update, context)
            return
        try:
            idx = int(text)
        except Exception:
            await update.message.reply_text(MESSAGES_ADMIN.INVALID_NUMBER_TRY_AGAIN)
            return
        members_list = context.user_data.get('sorted_members_list', [])
        if 1 <= idx <= len(members_list):
            member_id = members_list[idx - 1]
            await self.show_member_details(update, context, member_id)
        else:
                await update.message.reply_text(MESSAGES_ADMIN.INVALID_NUMBER_TRY_AGAIN)

    async def _handle_search_surname(self, update, context):
        """
        Запрашивает у администратора фамилию для поиска пользователя.
        """
        await update.message.reply_text(MESSAGES_ADMIN.SEARCH_ENTER_SURNAME)
        context.user_data['awaiting_surname'] = True

    async def _handle_edit_surname(self, update, context):
        """
        Запускает процесс редактирования пользователя по фамилии.
        """
        edit_db = EditDB()
        await edit_db.search_and_show_fields(update, context)

    async def _handle_add_record(self, update, context):
        """
        Запускает процесс добавления новой записи пользователя.
        """
        add_record = AddRecord()
        await add_record.start_add(update, context)

    async def _handle_delete_record(self, update, context):
        """
        Запускает процесс удаления записи пользователя.
        """
        del_record = DelRecord()
        await del_record.start_delete(update, context)

    async def show_sorted_by_surname(self, update, context):
        """
        Выводит отсортированный по фамилии список пользователей (нумерация, Фамилия, Имя, Отчество),
        затем предлагает выбрать номер для подробного просмотра или 0 для выхода.
        """
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute('SELECT id, surname, name, patronymic FROM members ORDER BY surname COLLATE NOCASE ASC')
                rows = cursor.fetchall()
            self.logger.info(f"show_sorted_by_surname: fetched {len(rows)} rows from members")
            await self._send_user_list(update, context, rows)
        except Exception as e:
            try:
                self.logger.exception('Ошибка при сортировке (show_sorted_by_surname)')
            except Exception:
                pass
            # Попытка аккуратно уведомить пользователя
            try:
                text = MESSAGES_ADMIN.ERROR_SORTING.format(error=e)
                if getattr(update, 'message', None):
                    await update.message.reply_text(text)
                else:
                    chat_id = getattr(update, 'effective_user', None)
                    cid = chat_id.id if chat_id else getattr(update.callback_query.from_user, 'id', None)
                    if cid:
                        await context.bot.send_message(chat_id=cid, text=text)
            except Exception:
                try:
                    self.logger.exception('Не удалось уведомить пользователя об ошибке сортировки')
                except Exception:
                    pass

    async def _send_user_list(self, update, context, rows, page: int = 1):
        """
        Формирует и отправляет список пользователей, отсортированный по фамилии.
        """
        # Новая реализация: показываем список в виде inline-кнопок, по 10 на страницу,
        # с навигацией по страницам и кнопкой "Выход".
        if rows:
            # Сохраним полные результаты в context, чтобы обработчик callback'ов мог их использовать
            context.user_data['workdb_sorted_rows'] = rows
            # Также сохраним упорядоченный список id для совместимости с текстовым вводом (старый режим)
            try:
                context.user_data['sorted_members_list'] = [r[0] for r in rows]
            except Exception:
                context.user_data['sorted_members_list'] = []
            context.user_data['workdb_page_size'] = 10
            total = len(rows)
            total_pages = (total + context.user_data['workdb_page_size'] - 1) // context.user_data['workdb_page_size']
            context.user_data['workdb_total_pages'] = total_pages
            # Установим текущую страницу (по умолчанию передаётся 1)
            if page < 1:
                page = 1
            if page > total_pages:
                page = total_pages
            context.user_data['workdb_current_page'] = page

            header = MESSAGES_ADMIN.USER_LIST_HEADER + "\n" + MESSAGES_ADMIN.PAGE_INFO.format(page=page, total_pages=total_pages)
            # Отправим заголовок с клавиатурой для первой страницы
            # Перед отправкой удалим ранее отправленные сообщения списка (entries/pages), чтобы не мусорить чат
            # Если вызов пришёл из CallbackQuery (нажатие inline-кнопки администратора),
            # то удалим исходное сообщение с меню администратора (callback_query.message),
            # чтобы не оставлять старую кнопку "Выберите действие:" в чате.
            try:
                origin = None
                if getattr(update, 'callback_query', None):
                    origin = update.callback_query.message
                if origin:
                    try:
                        text = getattr(origin, 'text', '') or getattr(origin, 'caption', '') or ''
                        if not text.startswith('Добро пожаловать'):
                            await context.bot.delete_message(chat_id=origin.chat.id, message_id=origin.message_id)
                    except Exception:
                        # Игнорируем ошибки удаления — возможно сообщение уже удалено
                        pass
            except Exception:
                try:
                    self.logger.exception('Failed to cleanup admin origin message')
                except Exception:
                    pass
            # Попытаемся также удалить сохранённые admin header/menu сообщения, если они были сохранены
            try:
                for key in ('admin_header_message', 'admin_menu_message'):
                    val = context.user_data.pop(key, None)
                    if val and isinstance(val, (list, tuple)) and len(val) >= 2:
                        try:
                            # Не удаляем приветственное сообщение
                            # val -> (chat_id, message_id)
                            await context.bot.delete_message(chat_id=val[0], message_id=val[1])
                        except Exception:
                            pass
            except Exception:
                try:
                    self.logger.exception('Failed to cleanup saved admin header/menu messages')
                except Exception:
                    pass
            try:
                prev_entries = context.user_data.pop('workdb_entries_message', None)
                prev_pages = context.user_data.pop('workdb_pages_message', None)
                for msg in (prev_entries, prev_pages):
                    if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                        try:
                            # Не удаляем приветственное сообщение, если оно совпадает — но workdb сообщения обычно новые
                            await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                        except Exception:
                            pass
            except Exception:
                try:
                    self.logger.exception('Failed to cleanup old workdb messages')
                except Exception:
                    pass

            # Клавиатура записей (только записи текущей страницы)
            kb_entries = self._build_list_keyboard(rows, page=page, page_size=context.user_data['workdb_page_size'])
            # Клавиатура страниц (вторая строка сообщений)
            kb_pages = self._build_pages_keyboard(total_pages)
            try:
                # Отправляем два сообщения: 1) заголовок + клавиатура записей, 2) текст с номером страницы + клавиатура страниц
                if getattr(update, 'message', None):
                    sent_entries = await update.message.reply_text(header, reply_markup=kb_entries)
                    sent_pages = await update.message.reply_text(MESSAGES_ADMIN.PAGE_INFO.format(page=page, total_pages=total_pages), reply_markup=kb_pages)
                else:
                    # fallback: отправим через bot.send_message
                    user = getattr(update, 'effective_user', None)
                    chat_id = None
                    if user and getattr(user, 'id', None):
                        chat_id = user.id
                    elif getattr(update, 'callback_query', None) and getattr(update.callback_query, 'from_user', None):
                        chat_id = update.callback_query.from_user.id
                    if chat_id:
                        sent_entries = await context.bot.send_message(chat_id=chat_id, text=header, reply_markup=kb_entries)
                        sent_pages = await context.bot.send_message(chat_id=chat_id, text=MESSAGES_ADMIN.PAGE_INFO.format(page=page, total_pages=total_pages), reply_markup=kb_pages)
                    else:
                        raise RuntimeError('No chat_id available for sending user list')
                # Сохраним id сообщений, чтобы в callback'е можно было редактировать клавиатуры и текст
                context.user_data['workdb_entries_message'] = (sent_entries.chat.id, sent_entries.message_id)
                context.user_data['workdb_pages_message'] = (sent_pages.chat.id, sent_pages.message_id)
            except Exception:
                try:
                    self.logger.exception('_send_user_list: failed to send inline list')
                except Exception:
                    pass

            # Не переводим в режим ожидания ввода номера — теперь выбор придёт через callback'ы
            context.user_data.pop('awaiting_member_detail_choice', None)
            context.user_data['workdb_list_active'] = True
        else:
            try:
                if getattr(update, 'message', None):
                    await update.message.reply_text(MESSAGES_ADMIN.DB_EMPTY)
                else:
                    chat_id = getattr(update, 'effective_user', None)
                    cid = chat_id.id if chat_id else (getattr(update.callback_query.from_user, 'id', None) if getattr(update, 'callback_query', None) else None)
                    if cid:
                        await context.bot.send_message(chat_id=cid, text=MESSAGES_ADMIN.DB_EMPTY)
            except Exception:
                try:
                    self.logger.exception('_send_user_list: failed to report empty DB')
                except Exception:
                    pass

    def _build_list_keyboard(self, rows, page: int = 1, page_size: int = 10):
        """Построить InlineKeyboardMarkup для заданной страницы списка rows.
        Каждый пользователь — отдельная кнопка в своей строке. Ниже — строка с номерами страниц
        и отдельная строка с кнопкой 'Выход'."""
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        total = len(rows)
        total_pages = (total + page_size - 1) // page_size
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        start = (page - 1) * page_size
        end = min(start + page_size, total)
        buttons = []
        # Добавляем кнопки пользователей — по одной в строке
        for idx in range(start, end):
            rid, surname, name, patronymic = rows[idx][0], rows[idx][1], rows[idx][2], rows[idx][3]
            # Нумерация сквозная по всему списку: индекс +1
            number = idx + 1
            text = f"{number}. {surname} {name} {patronymic}".strip()
            cb = f'workdb:member:{rid}'
            buttons.append([InlineKeyboardButton(text, callback_data=cb)])

        # Строка с номерами страниц будет формироваться отдельно
        return InlineKeyboardMarkup(buttons)

    def _build_pages_keyboard(self, total_pages: int, per_row: int = 8):
        """Построить InlineKeyboardMarkup только с кнопками номеров страниц и кнопкой Выход.
        Разбиваем номера по строкам по per_row кнопок, чтобы все номера были видны."""
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        if total_pages <= 0:
            return InlineKeyboardMarkup([])
        row = []
        for p in range(1, total_pages + 1):
            row.append(InlineKeyboardButton(str(p), callback_data=f'workdb:list:page:{p}'))
            if len(row) >= per_row:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        # Добавим отдельную строку с кнопкой выхода
        buttons.append([InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='workdb:list:exit')])
        return InlineKeyboardMarkup(buttons)

    async def handle_callback(self, update, context):
        """Обработчик CallbackQuery для списка пользователей (workdb:...)
        Поддерживает:
         - workdb:member:<id> — показать детали записи
         - workdb:list:page:<n> — показать страницу n
         - workdb:list:exit — выйти из режима списка
        """
        query = update.callback_query
        data = getattr(query, 'data', '') or ''
        try:
            await query.answer()
        except Exception:
            pass

        parts = data.split(':')
        if len(parts) < 2:
            return
        kind = parts[1]

        # Перенаправим callback'ы editdb:* в EditDB
        if data.startswith('editdb:'):
            try:
                from db.edit_db import EditDB
                edit_db = EditDB()
                # Если пользователь выбрал одну из записей из результатов поиска — сразу перейти к редактированию
                if data.startswith('editdb:selected:'):
                    try:
                        parts_sel = data.split(':')
                        member_id = int(parts_sel[2]) if len(parts_sel) >= 3 else None
                    except Exception:
                        member_id = None
                    if member_id is None:
                        try:
                            await query.message.reply_text(MESSAGES_ADMIN.INVALID_RECORD_ID)
                        except Exception:
                            pass
                        return
                    # Удалим трекнутые админские сообщения (включая сообщение с результатами поиска),
                    # чтобы не оставлять старый список в чате, затем запустим edit flow
                    try:
                        await delete_tracked_messages(context, exclude_greeting=True)
                    except Exception:
                        try:
                            self.logger.exception('handle_callback: failed to delete tracked messages before edit start')
                        except Exception:
                            pass
                    try:
                        # Сформируем fake update с message=query.message
                        fake = type('F', (), {})()
                        fake.message = query.message
                        await edit_db.edit_member_by_id(fake, context, member_id)
                    except Exception:
                        try:
                            self.logger.exception('handle_callback: failed to start edit flow from selected search result')
                        except Exception:
                            pass
                    return

                # Route editdb callbacks: field selection, input controls, or cancel
                if data.startswith('editdb:field:'):
                    await edit_db.process_field_callback(update, context)
                elif data.startswith('editdb:input:'):
                    await edit_db.handle_input_callback(update, context)
                else:
                    await edit_db.handle_cancel_callback(update, context)
            except Exception:
                try:
                    self.logger.exception('handle_callback: failed to delegate editdb callback')
                except Exception:
                    pass
            return

        # Обработка callback'ов для AddRecord (workdb:add:cancel / workdb:add:back)
        if kind == 'add' and len(parts) >= 3:
            action = parts[2]
            # Новая обработка выбора по индексу для поля 'Пол': workdb:add:floor_idx:<i>
            if action == 'floor_idx' and len(parts) >= 4:
                try:
                    try:
                        idx = int(parts[3])
                    except Exception:
                        idx = None
                    try:
                        await query.message.delete()
                    except Exception:
                        pass
                    vals = context.user_data.get('add_record_floor_values', []) or []
                    value = None
                    if idx is not None and 0 <= idx < len(vals):
                        value = vals[idx]
                    if value is None:
                        return
                    try:
                        data = context.user_data.get('add_record_data', {}) or {}
                        # Подставляем в ключ 'floor'
                        data['floor'] = value
                        context.user_data['add_record_data'] = data
                    except Exception:
                        pass
                    try:
                        from db.add_record import AddRecord
                        ar = AddRecord()
                        fake = type('F', (), {})()
                        class M: pass
                        m = M()
                        m.text = value
                        m.chat = query.message.chat if getattr(query, 'message', None) and getattr(query.message, 'chat', None) else None
                        fake.message = m
                        await ar.handle_add_step(fake, context)
                    except Exception:
                        try:
                            self.logger.exception('handle_callback: failed to advance add_record after selecting floor by index')
                        except Exception:
                            pass
                    return
                except Exception:
                    try:
                        self.logger.exception('handle_callback: unexpected error handling add:floor_idx callback')
                    except Exception:
                        pass
                    return

            # Новая обработка выбора по индексу для общего поля 'Группа': workdb:add:group_idx:<i>
            if action == 'group_idx' and len(parts) >= 4:
                try:
                    try:
                        idx = int(parts[3])
                    except Exception:
                        idx = None
                    try:
                        await query.message.delete()
                    except Exception:
                        pass
                    vals = context.user_data.get('add_record_group_values', []) or []
                    value = None
                    if idx is not None and 0 <= idx < len(vals):
                        value = vals[idx]
                    if value is None:
                        return
                    try:
                        data = context.user_data.get('add_record_data', {}) or {}
                        step = context.user_data.get('add_record_step', None)
                        if step == 4:
                            key = 'group_disability'
                        elif step == 8:
                            key = '`group`'
                        else:
                            key = '`group`'
                        data[key] = value
                        context.user_data['add_record_data'] = data
                    except Exception:
                        pass
                    try:
                        from db.add_record import AddRecord
                        ar = AddRecord()
                        fake = type('F', (), {})()
                        class M: pass
                        m = M()
                        m.text = value
                        m.chat = query.message.chat if getattr(query, 'message', None) and getattr(query.message, 'chat', None) else None
                        fake.message = m
                        await ar.handle_add_step(fake, context)
                    except Exception:
                        try:
                            self.logger.exception('handle_callback: failed to advance add_record after selecting group by index')
                        except Exception:
                            pass
                    return
                except Exception:
                    try:
                        self.logger.exception('handle_callback: unexpected error handling add:group_idx callback')
                    except Exception:
                        pass
                    return
            # Специальная обработка выбора группы инвалидности: workdb:add:group:<encoded_value>
            if action == 'group' and len(parts) >= 4:
                try:
                    encoded = parts[3]
                    try:
                        await query.message.delete()
                    except Exception:
                        pass
                    # Декодируем значение и подставим его в данные карточки (старое поведение)
                    try:
                        from urllib.parse import unquote
                        value = unquote(encoded)
                    except Exception:
                        value = encoded
                    try:
                        data = context.user_data.get('add_record_data', {}) or {}
                        # По старой логике — записываем в ключ group_disability
                        data['group_disability'] = value
                        context.user_data['add_record_data'] = data
                    except Exception:
                        pass
                    # Вызовем обработчик шага как будто пользователь ввёл текст
                    try:
                        from db.add_record import AddRecord
                        ar = AddRecord()
                        fake = type('F', (), {})()
                        class M: pass
                        m = M()
                        m.text = value
                        m.chat = query.message.chat if getattr(query, 'message', None) and getattr(query.message, 'chat', None) else None
                        fake.message = m
                        await ar.handle_add_step(fake, context)
                    except Exception:
                        try:
                            self.logger.exception('handle_callback: failed to advance add_record after selecting group_disability')
                        except Exception:
                            pass
                    return
                except Exception:
                    try:
                        self.logger.exception('handle_callback: unexpected error handling add:group callback')
                    except Exception:
                        pass
                    return
            # Отмена добавления — вернуть в админ-меню, удалить prompt
            if action == 'cancel':
                try:
                    try:
                        await query.message.delete()
                    except Exception:
                        pass
                    # удалить сохранённый prompt, если есть
                    try:
                        prev = context.user_data.pop('add_record_prompt_message', None)
                        if prev and isinstance(prev, (list, tuple)) and len(prev) >= 2:
                            try:
                                await context.bot.delete_message(chat_id=prev[0], message_id=prev[1])
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # удалить заголовок 'Заполнение карточки', если есть
                    try:
                        hdr = context.user_data.pop('add_record_header_message', None)
                        if hdr and isinstance(hdr, (list, tuple)) and len(hdr) >= 2:
                            try:
                                await context.bot.delete_message(chat_id=hdr[0], message_id=hdr[1])
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # сбросим состояния add_record
                    context.user_data.pop('add_record_in_progress', None)
                    context.user_data.pop('add_record_step', None)
                    context.user_data.pop('add_record_data', None)
                    from bot import admin_message
                    fake = type('F', (), {})()
                    fake.callback_query = query
                    fake.message = query.message
                    await admin_message(fake, context)
                except Exception:
                    try:
                        self.logger.exception('handle_callback: failed to cancel add_record')
                    except Exception:
                        pass
                return

            # Назад — вернуться к предыдущему шагу ввода
            if action == 'back':
                try:
                    # удалим текущее сообщение-приглашение
                    try:
                        await query.message.delete()
                    except Exception:
                        pass
                    step = context.user_data.get('add_record_step', 0)
                    if step is None:
                        step = 0
                    # если мы на шаге >0 — вернёмся на предыдущий
                    if step > 0:
                        new_step = step - 1
                        # удалим ранее введённое значение для этого шага (если оно было)
                        try:
                            data = context.user_data.get('add_record_data', {}) or {}
                            db_fields = None
                            try:
                                from db.add_record import AddRecord as _AR
                                db_fields = _AR.db_fields
                            except Exception:
                                # fallback: try to read from current module's constant
                                db_fields = []
                            if db_fields and new_step < len(db_fields):
                                key = db_fields[new_step]
                                try:
                                    data.pop(key, None)
                                except Exception:
                                    pass
                            context.user_data['add_record_data'] = data
                            context.user_data['add_record_step'] = new_step
                        except Exception:
                            pass
                        # Показать prompt для предыдущего шага
                        try:
                            from db.add_record import AddRecord
                            ar = AddRecord()
                            fake = type('F', (), {})()
                            fake.message = query.message
                            fake.callback_query = query
                            await ar.ask_step(fake, context, new_step)
                        except Exception:
                            try:
                                self.logger.exception('handle_callback: failed to re-show add_record previous step')
                            except Exception:
                                pass
                    else:
                        # если нет предыдущего шага — вернём в админ-меню
                        # удалить заголовок карточки, если он есть
                        try:
                            hdr = context.user_data.pop('add_record_header_message', None)
                            if hdr and isinstance(hdr, (list, tuple)) and len(hdr) >= 2:
                                try:
                                    await context.bot.delete_message(chat_id=hdr[0], message_id=hdr[1])
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        from bot import admin_message
                        fake = type('F', (), {})()
                        fake.callback_query = query
                        fake.message = query.message
                        await admin_message(fake, context)
                except Exception:
                    try:
                        self.logger.exception('handle_callback: unexpected error handling add:back')
                    except Exception:
                        pass
                return

        # Обработка callback'ов подтверждения удаления delrec:yes:<id> / delrec:no:<id>
        if data.startswith('delrec:'):
            try:
                parts2 = data.split(':')
                if len(parts2) >= 3:
                    action = parts2[1]
                    member_id = None
                    try:
                        member_id = int(parts2[2])
                    except Exception:
                        member_id = None
                    # 'no' — просто удалить сообщение подтверждения
                    if action == 'no':
                        try:
                            # лог: получили callback no
                            try:
                                self.logger.info(f"delrec:no callback received for member_id={member_id}; query_message_id={getattr(query.message, 'message_id', None)}")
                            except Exception:
                                pass
                            # удаляем текущее сообщение (callback message)
                            deleted_query_msg = False
                            try:
                                await query.message.delete()
                                deleted_query_msg = True
                            except Exception as ex:
                                try:
                                    self.logger.debug(f"delrec:no: failed to delete query.message -> {ex}")
                                except Exception:
                                    pass
                                # fallback: попробуем убрать клавиатуру у сообщения, если удалить не удалось
                                try:
                                    await query.message.edit_reply_markup(reply_markup=None)
                                except Exception:
                                    pass
                            # также удалить сохранённое сообщение подтверждения, если есть
                            try:
                                conf = context.user_data.pop('delrec_confirm_message', None)
                                if conf and isinstance(conf, (list, tuple)) and len(conf) >= 2:
                                    try:
                                        try:
                                            await context.bot.delete_message(chat_id=conf[0], message_id=conf[1])
                                            try:
                                                self.logger.info(f"delrec:no: deleted stored confirm message {conf}")
                                            except Exception:
                                                pass
                                        except Exception as ex:
                                            try:
                                                self.logger.debug(f"delrec:no: failed to delete stored confirm message {conf} -> {ex}")
                                            except Exception:
                                                pass
                                            # fallback: попробуем убрать клавиатуру у сохранённого сообщения
                                            try:
                                                await context.bot.edit_message_reply_markup(chat_id=conf[0], message_id=conf[1], reply_markup=None)
                                            except Exception:
                                                pass
                                    except Exception:
                                        try:
                                            self.logger.debug(f"delrec:no: failed to delete stored confirm message {conf}")
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                        except Exception:
                            try:
                                self.logger.exception('delrec: failed to delete confirmation message')
                            except Exception:
                                pass
                        return
                    # 'yes' — удалить запись из БД, удалить подтверждение и сообщение с деталями, показать список
                    if action == 'yes' and member_id is not None:
                        try:
                            # архивируем и удалим запись через DelRecord helper
                            try:
                                from db.del_record import DelRecord
                                del_record = DelRecord()
                                fake = type('F', (), {})()
                                fake.message = query.message
                                archived_ok = await del_record.archive_and_delete_by_id(fake, context, member_id)
                                if not archived_ok:
                                    try:
                                        self.logger.exception('delrec: archive_and_delete failed')
                                    except Exception:
                                        pass
                            except Exception:
                                try:
                                    self.logger.exception('delrec: failed to archive and delete member')
                                except Exception:
                                    pass
                            # удалим подтверждение
                            try:
                                await query.message.delete()
                                try:
                                    self.logger.info(f"delrec:yes: deleted confirmation message for {member_id}")
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            # также удалить сохранённое сообщение подтверждения, если есть
                            try:
                                conf = context.user_data.pop('delrec_confirm_message', None)
                                if conf and isinstance(conf, (list, tuple)) and len(conf) >= 2:
                                    try:
                                        await context.bot.delete_message(chat_id=conf[0], message_id=conf[1])
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            # удалим сообщение с деталями, если сохранено
                            # удалить сообщения с деталями и с кнопками действий (если сохранены)
                            details_msg = context.user_data.pop('workdb_member_details_message', None)
                            actions_msg = context.user_data.pop('workdb_member_actions_message', None)
                            try:
                                for msg in (actions_msg, details_msg):
                                    if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                                        try:
                                            await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                            # Обновим/покажем список заново
                            rows = context.user_data.get('workdb_sorted_rows', None)
                            page = context.user_data.get('workdb_current_page', 1)
                            if rows:
                                # обновим локальный rows — удалим удалённую запись если present
                                try:
                                    rows = [r for r in rows if r[0] != member_id]
                                    context.user_data['workdb_sorted_rows'] = rows
                                except Exception:
                                    pass
                                fake = type('F', (), {})()
                                fake.callback_query = query
                                fake.message = query.message
                                await self._send_user_list(fake, context, rows, page=page)
                            else:
                                # если нет сохранённых rows — просто вернём в админ-меню
                                from bot import admin_message
                                fake = type('F', (), {})()
                                fake.callback_query = query
                                fake.message = query.message
                                await admin_message(fake, context)
                        except Exception:
                            try:
                                self.logger.exception('delrec: failed during confirmation handling')
                            except Exception:
                                pass
                        # сбросим состояния
                        context.user_data.pop('member_details_id', None)
                        context.user_data.pop('awaiting_member_details_action', None)
                        return
            except Exception:
                try:
                    self.logger.exception('handle_callback: unexpected error in delrec handling')
                except Exception:
                    pass

        # Обработка навигации по страницам и выхода
        if kind == 'list' and len(parts) >= 3:
            action = parts[2]
            # Показать страницу
            if action == 'page' and len(parts) >= 4:
                try:
                    page = int(parts[3])
                except Exception:
                    return
                rows = context.user_data.get('workdb_sorted_rows', [])
                page_size = context.user_data.get('workdb_page_size', 10)
                kb = self._build_list_keyboard(rows, page=page, page_size=page_size)
                try:
                    # Обновим клавиатуру записей и сообщение с номером страницы
                    total_pages = context.user_data.get('workdb_total_pages', 1)
                    # Обновим клавиатуру записей — редактируем сообщение entries
                    entries_msg = context.user_data.get('workdb_entries_message')
                    pages_msg = context.user_data.get('workdb_pages_message')
                    # Новые клавиатуры
                    new_kb_entries = self._build_list_keyboard(rows, page=page, page_size=page_size)
                    new_kb_pages = self._build_pages_keyboard(total_pages)
                    # Отредактируем сообщение с записями
                    if entries_msg:
                        await context.bot.edit_message_reply_markup(chat_id=entries_msg[0], message_id=entries_msg[1], reply_markup=new_kb_entries)
                    else:
                        # fallback: редактируем текущее сообщение
                        try:
                            await query.message.edit_reply_markup(reply_markup=new_kb_entries)
                        except Exception:
                            pass
                    # Обновим сообщение с номером страницы (текст и клавиатура)
                    header = MESSAGES_ADMIN.PAGE_INFO.format(page=page, total_pages=total_pages)
                    if pages_msg:
                        await context.bot.edit_message_text(chat_id=pages_msg[0], message_id=pages_msg[1], text=header, reply_markup=new_kb_pages)
                    else:
                        try:
                            # Если нет сохранённого message, отредактируем текущее
                            await query.message.edit_text(text=header, reply_markup=new_kb_pages)
                        except Exception:
                            pass
                    context.user_data['workdb_current_page'] = page
                except Exception:
                    try:
                        self.logger.exception('handle_callback: failed to edit message for page change')
                    except Exception:
                        pass
                return

            # Выход из режима списка
            if action == 'exit':
                try:
                    await query.message.edit_reply_markup(reply_markup=None)
                except Exception:
                    pass
                try:
                    from bot import admin_message
                    fake = type('F', (), {})()
                    # Передаём и query, и message: VerificationID.check_role ожидает
                    # либо update.callback_query (чтобы взять from_user), либо update.message
                    # Если передать только message, check_role может ошибочно взять
                    # wrong user (message.from_user) — поэтому передаём callback_query.
                    fake.callback_query = query
                    fake.message = query.message
                    await admin_message(fake, context)
                except Exception:
                    try:
                        self.logger.exception('handle_callback: failed to return to admin menu after exit')
                    except Exception:
                        pass
                # Сброс флагов
                context.user_data.pop('workdb_sorted_rows', None)
                context.user_data.pop('workdb_list_active', None)
                context.user_data.pop('workdb_current_page', None)
                context.user_data.pop('workdb_total_pages', None)
                return

        # Обработка выбора записи — строим fake-update с message=query.message
        if kind == 'member' and len(parts) >= 3:
            try:
                member_id = int(parts[2])
            except Exception:
                try:
                    await query.message.reply_text(MESSAGES_ADMIN.INVALID_RECORD_ID)
                except Exception:
                    pass
                return
            try:
                fake = type('F', (), {})()
                fake.message = query.message
                await self.show_member_details(fake, context, member_id)
            except Exception:
                try:
                    self.logger.exception('handle_callback: failed to show member details')
                except Exception:
                    pass
            return
        # Обработка действий detail (Редактировать / Удалить / Выход) из клавиатуры деталей записи
        if kind == 'detail' and len(parts) >= 3:
            action = parts[2]
            # Редактировать: перейти к меню редактирования для этой записи
            if action == 'edit' and len(parts) >= 4:
                try:
                    try:
                        details_msg = context.user_data.pop('workdb_member_details_message', None)
                        actions_msg = context.user_data.pop('workdb_member_actions_message', None)
                        for msg in (actions_msg, details_msg):
                            if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                                try:
                                    await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    member_id = int(parts[3])
                    from db.edit_db import EditDB
                    edit_db = EditDB()
                    fake = type('F', (), {})()
                    fake.message = query.message
                    await edit_db.edit_member_by_id(fake, context, member_id)
                except Exception:
                    try:
                        self.logger.exception('handle_callback: failed to start edit flow from detail')
                    except Exception:
                        pass
                # Сбросим состояние деталей
                context.user_data.pop('member_details_id', None)
                context.user_data.pop('awaiting_member_details_action', None)
                return

            # Удалить: перейти к подтверждению удаления для этой записи
            if action == 'delete' and len(parts) >= 4:
                try:
                    # При нажатии 'Удалить запись' не удаляем сообщение с деталями — оно должно оставаться
                    member_id = int(parts[3])
                    from db.del_record import DelRecord
                    del_record = DelRecord()
                    fake = type('F', (), {})()
                    fake.message = query.message
                    await del_record.delete_member_by_id(fake, context, member_id)
                except Exception:
                    try:
                        self.logger.exception('handle_callback: failed to start delete flow from detail')
                    except Exception:
                        pass
                # Не сбрасываем состояния здесь — детали остаются видимыми до подтверждения удаления
                return

            # Назад: удалить сообщения с деталями и клавиатурой, вернуть в режим списка
            if action == 'back':
                try:
                    details_msg = context.user_data.pop('workdb_member_details_message', None)
                    actions_msg = context.user_data.pop('workdb_member_actions_message', None)
                    for msg in (actions_msg, details_msg):
                        if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                            try:
                                await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                            except Exception:
                                pass
                    # Попробуем убрать клавиатуру у исходного сообщения списка
                    try:
                        await query.message.edit_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    # Попытаемся восстановить/показать список на той же странице
                    rows = context.user_data.get('workdb_sorted_rows', [])
                    page = context.user_data.get('workdb_current_page', 1)
                    if rows:
                        fake = type('F', (), {})()
                        fake.callback_query = query
                        fake.message = query.message
                        await self._send_user_list(fake, context, rows, page=page)
                    else:
                        # Если данных нет, вернём пользователя в главное админ-меню
                        from bot import admin_message
                        fake = type('F', (), {})()
                        fake.callback_query = query
                        fake.message = query.message
                        await admin_message(fake, context)
                except Exception:
                    try:
                        self.logger.exception('handle_callback: failed to return to list from detail back')
                    except Exception:
                        pass
                # Сбросим состояние
                context.user_data.pop('member_details_id', None)
                context.user_data.pop('awaiting_member_details_action', None)
                return
            # Выход из просмотра деталей: удалить сообщения с деталями и клавиатурой, вернуться в админ-меню
            if action == 'exit':
                try:
                    details_msg = context.user_data.pop('workdb_member_details_message', None)
                    actions_msg = context.user_data.pop('workdb_member_actions_message', None)
                    for msg in (actions_msg, details_msg):
                        if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                            try:
                                await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                            except Exception:
                                pass
                    # также попробуем убрать клавиатуру у исходного сообщения списка
                    try:
                        await query.message.edit_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    from bot import admin_message
                    fake = type('F', (), {})()
                    fake.callback_query = query
                    fake.message = query.message
                    await admin_message(fake, context)
                except Exception:
                    try:
                        self.logger.exception('handle_callback: failed to return to admin menu from detail exit')
                    except Exception:
                        pass
                # Сбросим состояние
                context.user_data.pop('member_details_id', None)
                context.user_data.pop('awaiting_member_details_action', None)
                return
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

    async def show_member_details(self, update, context, member_id):
        """
        Выводит подробные данные выбранной записи с пользовательскими названиями полей и предлагает действия над записью.
        """
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute('PRAGMA table_info(members)')
                columns = [col[1] for col in cursor.fetchall()]
                select_fields = [col for col in self.FIELD_MAP if col in columns]
                fields_sql = ', '.join([f'"{col}"' for col in select_fields])
                cursor.execute(f"SELECT {fields_sql} FROM members WHERE id = ?", (member_id,))
                result = cursor.fetchone()
                if result:
                    # Получим форматированные детали через helper
                    details = get_member_details_text(member_id, db_instance=self.db)
                    # Перед показом деталей удалим сообщения списка (entries/pages), чтобы не оставлять старый список в чате
                    try:
                        prev_entries = context.user_data.pop('workdb_entries_message', None)
                        prev_pages = context.user_data.pop('workdb_pages_message', None)
                        for msg in (prev_entries, prev_pages):
                            if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                                try:
                                    await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                                except Exception:
                                    pass
                    except Exception:
                        try:
                            self.logger.exception('show_member_details: failed to cleanup list messages')
                        except Exception:
                            pass

                    # Отправим текст с деталями и сохраним его id, чтобы можно было удалить при выходе
                    try:
                        sent_details = await update.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_HEADER + f"\n{details}")
                        try:
                            context.user_data['workdb_member_details_message'] = (sent_details.chat.id, sent_details.message_id)
                        except Exception:
                            pass
                    except Exception:
                        # Если отправка не удалась — постим без сохранения
                        await update.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_HEADER + f"\n{details}")

                    # Вместо текстового списка — отправим Inline-кнопки: Редактировать, Удалить, Выход
                    try:
                        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_EDIT, callback_data=f'workdb:detail:edit:{member_id}')],
                            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_DELETE, callback_data=f'workdb:detail:delete:{member_id}')],
                            [
                                InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data=f'workdb:detail:back:{member_id}'),
                                InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data=f'workdb:detail:exit')
                            ]
                        ])
                        sent_kb = await update.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_ACTION_PROMPT, reply_markup=kb)
                        # Сохраним сообщение клавиатуры на случай, если потребуется очистка
                        try:
                            context.user_data['workdb_member_actions_message'] = (sent_kb.chat.id, sent_kb.message_id)
                        except Exception:
                            pass
                    except Exception:
                        # fallback к старому текстовому варианту
                        await update.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_ACTION_FALLBACK)
                    # Сохраняем id выбранной записи и ожидаем ввод действия
                    context.user_data['member_details_id'] = member_id
                    context.user_data['awaiting_member_details_action'] = True
                else:
                    await update.message.reply_text(MESSAGES_ADMIN.RECORD_NOT_FOUND_SIMPLE)
        except Exception as e:
            await update.message.reply_text(MESSAGES_ADMIN.ERROR_SELECT.format(error=e))
    async def handle_member_details_action(self, update, context):
        """
        Обрабатывает выбор действия над записью: редактировать, удалить, выйти.
        """
        text = update.message.text.strip()
        member_id = context.user_data.get('member_details_id')
        context.user_data['awaiting_member_details_action'] = False
        if text == '0':
            await admin_message(update, context)
            return
        elif text == '1':
            from db.edit_db import EditDB
            edit_db = EditDB()
            await edit_db.edit_member_by_id(update, context, member_id)
            return
        elif text == '2':
            from db.del_record import DelRecord
            del_record = DelRecord()
            await del_record.delete_member_by_id(update, context, member_id)
            return
        else:
            await update.message.reply_text(MESSAGES_ADMIN.MEMBER_DETAILS_INVALID_CHOICE)
            context.user_data['awaiting_member_details_action'] = True

    async def search_by_second_field(self, update, context):
        """
        Поиск пользователей по фамилии (начало строки, без учёта регистра), выводит все найденные записи.
        """
        surname = update.message.text.strip()
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute('SELECT * FROM members WHERE LOWER(surname) LIKE LOWER(?) LIMIT 30', (surname + '%',))
                rows = cursor.fetchall()
                if rows:
                    msg = MESSAGES_ADMIN.SEARCH_RESULTS_HEADER + '\n'
                    messages = []
                    for idx, row in enumerate(rows, 1):
                        line = f"{idx} | " + ' | '.join(str(field) for field in row[1:]) + '\n'
                        if len(msg) + len(line) > 4000:
                            messages.append(msg)
                            msg = ''
                        msg += line
                    if msg:
                        messages.append(msg)
                    for m in messages:
                        await update.message.reply_text(m)
                else:
                    await update.message.reply_text(MESSAGES_ADMIN.SEARCH_NO_MATCH_SIMPLE)
        except Exception as e:
            await update.message.reply_text(MESSAGES_ADMIN.ERROR_SEARCH.format(error=e))
    # Здесь будут методы для работы с базой данных (позже)
