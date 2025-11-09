from bot import admin_message
import logging
from db.database import Database
from db.edit_db import EditDB
from db.add_record import AddRecord
from db.del_record import DelRecord

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
            await update.message.reply_text("Некорректный выбор. Введите номер действия от 1 до 5.")

    async def _handle_member_detail_choice(self, update, context, text):
        """
        Обрабатывает выбор пользователя для просмотра подробных данных по номеру записи.
        """
        context.user_data['awaiting_member_detail_choice'] = False
        if text == '0':
            await update.message.reply_text('Выход в меню администратора.')
            
            await admin_message(update, context)
            return
        try:
            idx = int(text)
        except Exception:
            await update.message.reply_text('Некорректный номер. Попробуйте снова.')
            return
        members_list = context.user_data.get('sorted_members_list', [])
        if 1 <= idx <= len(members_list):
            member_id = members_list[idx - 1]
            await self.show_member_details(update, context, member_id)
        else:
            await update.message.reply_text('Некорректный номер. Попробуйте снова.')

    async def _handle_search_surname(self, update, context):
        """
        Запрашивает у администратора фамилию для поиска пользователя.
        """
        await update.message.reply_text("Введите фамилию для поиска:")
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
                if getattr(update, 'message', None):
                    await update.message.reply_text(f'Ошибка при сортировке: {e}')
                else:
                    chat_id = getattr(update, 'effective_user', None)
                    cid = chat_id.id if chat_id else getattr(update.callback_query.from_user, 'id', None)
                    if cid:
                        await context.bot.send_message(chat_id=cid, text=f'Ошибка при сортировке: {e}')
            except Exception:
                self.logger.exception('Не удалось уведомить пользователя об ошибке сортировки')

    async def _send_user_list(self, update, context, rows):
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
            context.user_data['workdb_current_page'] = 1

            header = f'Список пользователей (отсортировано по фамилии):\nСтраница 1 из {total_pages}'
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
            kb_entries = self._build_list_keyboard(rows, page=1, page_size=context.user_data['workdb_page_size'])
            # Клавиатура страниц (вторая строка сообщений)
            kb_pages = self._build_pages_keyboard(total_pages)
            try:
                # Отправляем два сообщения: 1) заголовок + клавиатура записей, 2) текст с номером страницы + клавиатура страниц
                if getattr(update, 'message', None):
                    sent_entries = await update.message.reply_text(header, reply_markup=kb_entries)
                    sent_pages = await update.message.reply_text(f'Страница 1 из {total_pages}', reply_markup=kb_pages)
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
                        sent_pages = await context.bot.send_message(chat_id=chat_id, text=f'Страница 1 из {total_pages}', reply_markup=kb_pages)
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
                    await update.message.reply_text('В базе нет данных.')
                else:
                    chat_id = getattr(update, 'effective_user', None)
                    cid = chat_id.id if chat_id else (getattr(update.callback_query.from_user, 'id', None) if getattr(update, 'callback_query', None) else None)
                    if cid:
                        await context.bot.send_message(chat_id=cid, text='В базе нет данных.')
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
        buttons.append([InlineKeyboardButton('Выход', callback_data='workdb:list:exit')])
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
                    header = f'Страница {page} из {total_pages}'
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
                    await query.message.reply_text('Некорректный идентификатор записи.')
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
                    details = '\n'.join(f"{self.FIELD_MAP.get(field, field)}: {value}" for field, value in zip(select_fields, result))
                    await update.message.reply_text(f'Данные выбранной записи:\n{details}')
                    await update.message.reply_text(
                        'Выберите действие для этой записи:\n1. Редактировать данные\n2. Удалить запись\n0. Выйти'
                    )
                    # Сохраняем id выбранной записи и ожидаем ввод действия
                    context.user_data['member_details_id'] = member_id
                    context.user_data['awaiting_member_details_action'] = True
                else:
                    await update.message.reply_text('Запись не найдена.')
        except Exception as e:
            await update.message.reply_text(f'Ошибка при выборе записи: {e}')
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
            await update.message.reply_text('Некорректный выбор. Введите 1, 2 или 0.')
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
                    msg = 'Результаты поиска:\n'
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
                    await update.message.reply_text('Совпадений не найдено.')
        except Exception as e:
            await update.message.reply_text(f'Ошибка при поиске: {e}')
    # Здесь будут методы для работы с базой данных (позже)
