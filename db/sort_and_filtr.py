import logging
from utils.message_cleanup import cleanup_admin_messages
from db.database import Database
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import traceback
import re
from admin_notify import notify_admin
import messages_admin as MESSAGES_ADMIN


logger = logging.getLogger(__name__)


class SortAndFiltr:
    PAGE_SIZE_DEFAULT = 20

    async def start(self, update, context):
        # Очистим предыдущие админские сообщения
        try:
            await cleanup_admin_messages(context, bot=context.bot, logger_obj=logger)
        except Exception:
            logger.exception('SortAndFiltr.start: cleanup failed')
        # Также удалим сохранённые admin header/menu, если они остались
        try:
            for k in ('admin_header_message', 'admin_menu_message'):
                val = context.user_data.pop(k, None)
                if val and isinstance(val, (list, tuple)) and len(val) >= 2:
                    try:
                        await context.bot.delete_message(chat_id=val[0], message_id=val[1])
                    except Exception:
                        pass
        except Exception:
            logger.exception('SortAndFiltr.start: failed to cleanup admin header/menu')

        # Посылаем короткий заголовок и inline-клавиатуру с действиями (сортировать/фильтровать/выход)
        header = MESSAGES_ADMIN.SORT_ACTIONS_PROMPT.splitlines()[0] if isinstance(MESSAGES_ADMIN.SORT_ACTIONS_PROMPT, str) else MESSAGES_ADMIN.SORT_ACTIONS_PROMPT
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('1. Сортировать по', callback_data='sortfiltr:action:sort')],
            [InlineKeyboardButton('2. Фильтровать по', callback_data='sortfiltr:action:filter')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='sortfiltr:action:exit')]
        ])
        # Используем reply_text на Update.message или на callback.message при вызове через callback
        try:
            if getattr(update, 'message', None):
                sent = await update.message.reply_text(header, reply_markup=kb)
            else:
                # fallback: use callback_query.message
                cq = getattr(update, 'callback_query', None)
                if cq and getattr(cq, 'message', None):
                    sent = await cq.message.reply_text(header, reply_markup=kb)
                else:
                    # last resort
                    chat_id = getattr(update, 'effective_user', None).id if getattr(update, 'effective_user', None) else None
                    sent = await context.bot.send_message(chat_id=chat_id, text=header, reply_markup=kb)
        except Exception:
            logger.exception('SortAndFiltr.start: failed to send actions keyboard')
        context.user_data['sortfiltr_awaiting_action'] = True  # Ожидаем действие пользователя
        
    async def handle_action(self, update, context):
        # Удалим старые админские сообщения перед отправкой меню/результатов
        try:
            await cleanup_admin_messages(context, bot=context.bot, logger_obj=logger)
        except Exception:
            logger.exception('handle_action: cleanup failed')
        # Сохраняем выбор в context.user_data, чтобы не использовать глобальную переменную класса
        context.user_data['sortfiltr_choice'] = update.message.text.strip()
        # Сбрасываем параметры пагинации при новом выборе
        context.user_data['sortfiltr_page'] = 1
        context.user_data['sortfiltr_page_size'] = context.user_data.get('sortfiltr_page_size', self.PAGE_SIZE_DEFAULT)
        if context.user_data['sortfiltr_choice'] == '1':
            # Отправим inline-клавиатуру выбора поля для сортировки (тот же набор, что и для callback)
            try:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('1. По фамилии', callback_data='sortfiltr:sort:surname')],
                    [InlineKeyboardButton('2. По группе инвалидности', callback_data='sortfiltr:sort:gr1')],
                    [InlineKeyboardButton('3. По группам', callback_data='sortfiltr:sort:group')],
                    [InlineKeyboardButton('4. По полу', callback_data='sortfiltr:sort:floor')],
                    [InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='sortfiltr:sort:back'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='sortfiltr:sort:exit')]
                ])
                header = MESSAGES_ADMIN.SORT_FIELD_PROMPT.splitlines()[0] if isinstance(MESSAGES_ADMIN.SORT_FIELD_PROMPT, str) else MESSAGES_ADMIN.SORT_FIELD_PROMPT
                await update.message.reply_text(header, reply_markup=kb)
                context.user_data['sortfiltr_awaiting_sort_field'] = True
                context.user_data['sortfiltr_awaiting_action'] = False
            except Exception:
                logger.exception('handle_action: failed to send SORT_FIELD inline keyboard for text choice')
        elif context.user_data['sortfiltr_choice'] == '2':
            # Показать inline-кнопки для выбора поля фильтрации
            await self.send_filter_field_keyboard(update, context)
            context.user_data['sortfiltr_awaiting_action'] = False
        elif context.user_data['sortfiltr_choice'] == '0':
            # Выход из SortAndFiltr и возврат к admin_message
            await update.message.reply_text(MESSAGES_ADMIN.ADMIN_EXIT_TO_MENU)
            from bot import admin_message
            await admin_message(update, context)
            context.user_data['sortfiltr_awaiting_action'] = False
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        else:
            await update.message.reply_text(MESSAGES_ADMIN.SORT_CHOICE_PROMPT)
            await self.start(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False  # Сброс ожидания выбора поля сортировки

    async def handle_sort_field(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            context.user_data['sortfiltr_current_sort'] = 'surname'
            context.user_data['sortfiltr_page'] = 1
            await self.sort_surname(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text == '2':
            context.user_data['sortfiltr_current_sort'] = 'gr1'
            context.user_data['sortfiltr_page'] = 1
            await self.sort_gr1(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text == '3':
            context.user_data['sortfiltr_current_sort'] = 'group'
            context.user_data['sortfiltr_page'] = 1
            await self.sort_group(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text == '4':
            context.user_data['sortfiltr_current_sort'] = 'floor'
            context.user_data['sortfiltr_page'] = 1
            await self.sort_floor(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text == '0':
            # Возврат к начальному меню
            await self.start(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        else:
            await update.message.reply_text(MESSAGES_ADMIN.ENTER_FIELD_NUMBER)

    async def handle_filter_field(self, update, context):
        text = update.message.text.strip()
        mapping = {
            '1': ('surname', 'Фамилия'),
            '2': ('group_disability', 'Группа инвалидности'),
            '3': ('`group`', 'Группа'),
            '4': ('floor', 'Пол'),
            '5': ('area', 'Район'),
            '6': ('phone', 'Телефон'),
        }
        if text == '0':
            await self.start(update, context)
            context.user_data['sortfiltr_awaiting_filter_field'] = False
            return

        if text in mapping:
            db_field, pretty = mapping[text]
            context.user_data['sortfiltr_filter_field'] = db_field
            context.user_data['sortfiltr_page'] = 1
            # Спросим значение для фильтрации
            await update.message.reply_text(MESSAGES_ADMIN.FILTER_VALUE_PROMPT.format(field=pretty))
            context.user_data['sortfiltr_awaiting_filter_value'] = True
            context.user_data['sortfiltr_awaiting_filter_field'] = False
        else:
            await update.message.reply_text(MESSAGES_ADMIN.FILTER_INVALID_FIELD)

    async def send_filter_field_keyboard(self, update, context):
        """Отправляет inline-клавиатуру с полями для фильтрации (multi-filter builder)."""
        buttons = [
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_FIELD_SURNAME, callback_data='sortfiltr:filter:surname'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_FIELD_GROUP_DISABILITY, callback_data='sortfiltr:filter:group_disability')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_FIELD_GROUP, callback_data='sortfiltr:filter:`group`'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_FIELD_FLOOR, callback_data='sortfiltr:filter:floor')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_FIELD_AREA, callback_data='sortfiltr:filter:area'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_FIELD_PHONE, callback_data='sortfiltr:filter:phone')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_CANCEL, callback_data='sortfiltr:filter:cancel')],
            [InlineKeyboardButton('Применить', callback_data='sortfiltr:filter:apply'), InlineKeyboardButton('Очистить', callback_data='sortfiltr:filter:clear')]
        ]
        kb = InlineKeyboardMarkup(buttons)
        target = getattr(update, 'callback_query', None)
        if target and getattr(target, 'message', None):
            await target.message.reply_text(MESSAGES_ADMIN.FILTER_FIELD_PROMPT, reply_markup=kb)
        else:
            await update.message.reply_text(MESSAGES_ADMIN.FILTER_FIELD_PROMPT, reply_markup=kb)

    async def _show_filter_summary(self, message_obj, context):
        """Показывает краткое резюме текущих фильтров и кнопки управления (Добавить/Применить/Очистить)."""
        fl = context.user_data.get('sort_filters', []) or []
        if not fl:
            text = 'Текущие фильтры: (нет)'
        else:
            lines = []
            for i, f in enumerate(fl, 1):
                val = f.get('value') if f.get('value') is not None else ''
                lines.append(f"{i}. {f.get('pretty', f.get('field'))} {f.get('op')} {val}")
            text = 'Текущие фильтры:\n' + '\n'.join(lines)
        # Кнопки: Добавить ещё, Применить, Очистить
        kb_rows = [
            [InlineKeyboardButton('Добавить ещё', callback_data='sortfiltr:filter:back'), InlineKeyboardButton('Применить', callback_data='sortfiltr:filter:apply'), InlineKeyboardButton('Очистить', callback_data='sortfiltr:filter:clear')]
        ]
        # Кнопки удаления по индексам
        if fl:
            remove_row = []
            for i in range(len(fl)):
                remove_row.append(InlineKeyboardButton(f'❌{i+1}', callback_data=f'sortfiltr:filter:remove:{i}'))
            # разбиваем remove_row на подряды по 6 кнопок
            per = 6
            for i in range(0, len(remove_row), per):
                kb_rows.append(remove_row[i:i+per])
        kb_rows.append([InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='sortfiltr:filter:back'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='sortfiltr:filter:exit')])
        kb = InlineKeyboardMarkup(kb_rows)
        try:
            await message_obj.reply_text(text, reply_markup=kb)
        except Exception:
            try:
                await message_obj.reply_text(text)
            except Exception:
                pass

    def _build_pagination_markup(self, page: int, total: int) -> InlineKeyboardMarkup:
        buttons = []
        row = []
        if page > 1:
            row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_PAG_PREV, callback_data='sortfiltr:page:prev'))
        row.append(InlineKeyboardButton(f'{page}/{total}', callback_data='sortfiltr:page:info'))
        if page < total:
            row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_PAG_NEXT, callback_data='sortfiltr:page:next'))
        row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='sortfiltr:page:exit'))
        buttons.append(row)
        return InlineKeyboardMarkup(buttons)

    async def _cleanup_list_messages(self, context, delete_trigger_message=None):
        """
        Удаляет все сообщения списка и навигационное сообщение, если они сохранены в context.user_data.
        Если передан delete_trigger_message (telegram Message), попытается удалить и его.
        В конце очищает ключи из context.user_data.
        """
        try:
            for chat_id, msg_id in context.user_data.get('sortfiltr_list_messages', []) or []:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass
            nav = context.user_data.get('sortfiltr_nav_message')
            if nav and isinstance(nav, (list, tuple)) and len(nav) >= 2:
                try:
                    await context.bot.delete_message(chat_id=nav[0], message_id=nav[1])
                except Exception:
                    pass
        except Exception:
            try:
                logger.exception('_cleanup_list_messages: failed to delete list/nav messages')
            except Exception:
                pass
        # Удалим сообщение, где была нажата кнопка (если передано)
        if delete_trigger_message is not None:
            try:
                await delete_trigger_message.delete()
            except Exception:
                pass
        # Очистим трекинг
        context.user_data.pop('sortfiltr_list_messages', None)
        context.user_data.pop('sortfiltr_nav_message', None)
        # Удалим сообщение выбора поля сортировки при фильтрации, если есть
        try:
            sort_choice = context.user_data.pop('sortfiltr_sort_choice_message', None)
            if sort_choice and isinstance(sort_choice, (list, tuple)) and len(sort_choice) >= 2:
                try:
                    await context.bot.delete_message(chat_id=sort_choice[0], message_id=sort_choice[1])
                except Exception:
                    pass
        except Exception:
            pass

    def _build_where_from_filters(self, filters):
        """
        Собирает WHERE и параметры из списка фильтров (AND по умолчанию).
        filters: list of dicts {'field','op','value','pretty'}
        Возвращает (where_clause, params, count_sql, select_sql, order_field)
        """
        allowed = {'surname': 'surname', 'group_disability': 'group_disability', '`group`': '`group`', 'floor': 'floor', 'area': 'area', 'phone': 'phone'}
        parts = []
        params = []
        order_field = None
        for f in filters:
            field = f.get('field')
            op = f.get('op')
            val = f.get('value')
            if field not in allowed:
                continue
            if order_field is None:
                order_field = allowed[field]
            if op == 'equals':
                parts.append(f"{allowed[field]} = ?")
                params.append(val)
            elif op == 'contains':
                parts.append(f"LOWER({allowed[field]}) LIKE LOWER(?)")
                params.append(f"%{val}%")
            elif op == 'in':
                # разделяем по запятой
                vals = [s.strip() for s in (val or '').split(',') if s.strip()]
                if not vals:
                    continue
                placeholders = ','.join(['?'] * len(vals))
                parts.append(f"{allowed[field]} IN ({placeholders})")
                params.extend(vals)
            elif op == 'isnull':
                parts.append(f"{allowed[field]} IS NULL OR {allowed[field]} = ''")
            elif op == 'notnull':
                parts.append(f"({allowed[field]} IS NOT NULL AND {allowed[field]} <> '')")
            else:
                # unsupported op
                continue
        if not parts:
            return None, None, None, None, None
        where_clause = 'WHERE ' + ' AND '.join(parts)
        count_sql = f"SELECT COUNT(*) FROM members {where_clause}"
        # По умолчанию сортируем результаты по фамилии и отображаем указанные поля
        # Порядок отображения: surname, name, patronymic, group_disability, date_birth, address, phone, `group`
        select_sql = f"SELECT surname, name, patronymic, group_disability, date_birth, address, phone, `group` FROM members {where_clause} ORDER BY surname COLLATE NOCASE ASC"
        return where_clause, tuple(params), count_sql, select_sql, 'surname'

    async def sort_group(self, update, context):
        await self._paginate_query(
            update,
            context,
            select_sql='SELECT `group`, surname, name, patronymic FROM members ORDER BY `group` COLLATE NOCASE ASC',
            title='Список по группам',
            current_sort_key='group'
        )

    async def sort_floor(self, update, context):
        await self._paginate_query(
            update,
            context,
            select_sql='SELECT floor, surname, name, patronymic FROM members ORDER BY floor COLLATE NOCASE ASC',
            title='Список по полу',
            current_sort_key='floor'
        )

    async def sort_surname(self, update, context):
        await self._paginate_query(
            update,
            context,
            select_sql='SELECT surname, name, patronymic FROM members ORDER BY surname COLLATE NOCASE ASC',
            title='Список по фамилии',
            current_sort_key='surname'
        )

    async def sort_gr1(self, update, context):
        await self._paginate_query(
            update,
            context,
            select_sql='SELECT group_disability, surname, name, patronymic FROM members ORDER BY group_disability COLLATE NOCASE ASC',
            title='Список по группе инвалидности',
            current_sort_key='gr1'
        )

    async def _paginate_query(self, update, context, select_sql: str, title: str, current_sort_key: str):
        """
        Общая логика для пагинированного SELECT-запроса.
        select_sql: базовая часть запроса без LIMIT/OFFSET
        title: заголовок сообщения для пользователя
        current_sort_key: ключ для context.user_data['sortfiltr_current_sort']
        """
        # Перед отправкой страниц и сообщений обнулим старые админские сообщения
        try:
            await cleanup_admin_messages(context, bot=context.bot, logger_obj=logger)
        except Exception:
            logger.exception('_paginate_query: cleanup failed')
        db = Database()
        try:
            page = context.user_data.get('sortfiltr_page', 1)
            page_size = context.user_data.get('sortfiltr_page_size', self.PAGE_SIZE_DEFAULT)
            params = context.user_data.get('sortfiltr_query_params')
            count_sql = context.user_data.get('sortfiltr_count_sql')
            with db.get_cursor() as cursor:
                if count_sql:
                    cursor.execute(count_sql, params or ())
                    total = cursor.fetchone()[0]
                else:
                    cursor.execute('SELECT COUNT(*) FROM members')
                    total = cursor.fetchone()[0]
                if total == 0:
                    await update.message.reply_text(MESSAGES_ADMIN.DB_EMPTY)
                    return
                total_pages = (total + page_size - 1) // page_size
                if page < 1:
                    page = 1
                if page > total_pages:
                    page = total_pages
                offset = (page - 1) * page_size
                query = f"{select_sql} LIMIT ? OFFSET ?"
                # Передаём параметры WHERE (если есть) плюс пагинацию
                if params:
                    cursor.execute(query, tuple(params) + (page_size, offset))
                else:
                    cursor.execute(query, (page_size, offset))
                rows = cursor.fetchall()
                msg = MESSAGES_ADMIN.LIST_PAGE_TEMPLATE.format(title=title, page=page, total_pages=total_pages) + "\n"
                messages = []
                for idx, row in enumerate(rows, offset + 1):
                    # формируем строку из полей через ' | ' если есть первый столбец группы
                    if len(row) == 4:
                        line = f"{idx}. {row[0]} | {row[1]} {row[2]} {row[3]}\n"
                    else:
                        line = f"{idx}. {' '.join(map(str, row))}\n"
                    if len(msg) + len(line) > 4000:
                        messages.append(msg)
                        msg = ''
                    msg += line
                if msg:
                    messages.append(msg)
                # Построим клавиатуру с номерами всех страниц + row Назад/Выход
                page_buttons = []
                per_row = 8
                for i in range(1, total_pages + 1):
                    # Визуально выделяем текущую страницу и делаем её неактивной (callback -> info)
                    if i == page:
                        label = f'[{i}]'
                        page_buttons.append(InlineKeyboardButton(label, callback_data='sortfiltr:page:info'))
                    else:
                        page_buttons.append(InlineKeyboardButton(str(i), callback_data=f'sortfiltr:page:{i}'))
                # Разбиваем на ряды
                rows = [page_buttons[i:i+per_row] for i in range(0, len(page_buttons), per_row)]
                # Добавим последнюю строку с Назад/Выход
                rows.append([InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='sortfiltr:page:back'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='sortfiltr:page:exit')])
                kb_pages = InlineKeyboardMarkup(rows)
                sent_messages = []
                for m in messages:
                    try:
                        sent = await update.message.reply_text(m, reply_markup=kb_pages)
                        sent_messages.append((sent.chat.id, sent.message_id))
                    except Exception:
                        sent = await update.message.reply_text(m)
                        sent_messages.append((sent.chat.id, sent.message_id))
                context.user_data['sortfiltr_total_pages'] = total_pages
                context.user_data['sortfiltr_page'] = page
                context.user_data['sortfiltr_paginating'] = True
                context.user_data['sortfiltr_current_sort'] = current_sort_key
                # Отправляем inline-клавиатуру пагинации
                kb = self._build_pagination_markup(page, total_pages)
                try:
                    sent_nav = await update.message.reply_text(MESSAGES_ADMIN.PAGINATION_NAV_PROMPT, reply_markup=kb)
                    context.user_data['sortfiltr_nav_message'] = (sent_nav.chat.id, sent_nav.message_id)
                except Exception:
                    context.user_data.pop('sortfiltr_nav_message', None)
                # Если текущий режим - фильтрация, покажем клавиатуру выбора поля для сортировки результатов
                try:
                    if isinstance(current_sort_key, str) and current_sort_key.startswith('filter'):
                        sort_kb = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton('Фамилия', callback_data='sortfiltr:filter_sort:surname'),
                                InlineKeyboardButton('Группа инвалидности', callback_data='sortfiltr:filter_sort:group_disability'),
                                InlineKeyboardButton('Дата рождения', callback_data='sortfiltr:filter_sort:date_birth')
                            ],
                            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='sortfiltr:page:back'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='sortfiltr:page:exit')]
                        ])
                        try:
                            sent_sort_choice = await update.message.reply_text('Выберите поле для сортировки', reply_markup=sort_kb)
                            context.user_data['sortfiltr_sort_choice_message'] = (sent_sort_choice.chat.id, sent_sort_choice.message_id)
                        except Exception:
                            try:
                                sent_sort_choice = await update.message.reply_text('Выберите поле для сортировки')
                                context.user_data['sortfiltr_sort_choice_message'] = (sent_sort_choice.chat.id, sent_sort_choice.message_id)
                            except Exception:
                                pass
                except Exception:
                    try:
                        logger.exception('Failed to send filter sort-choice keyboard')
                    except Exception:
                        pass
                # Сохраним список отправленных сообщений, чтобы можно было их удалять при навигации
                context.user_data['sortfiltr_list_messages'] = sent_messages
            return
        except Exception as e:
            logger.exception('Ошибка при пагинации сортировки')
            try:
                await notify_admin(context, 'Ошибка при пагинации сортировки (sort_and_filtr)', traceback.format_exc())
            except Exception:
                pass
            await update.message.reply_text(MESSAGES_ADMIN.ERROR_SORTING.format(error=e))

    async def handle_filter_value(self, update, context):
        value = update.message.text.strip()
        # Если мы в режиме построения нескольких фильтров и ждём значения — накопим фильтр
        awaiting = context.user_data.pop('sortfiltr_awaiting_filter_value_for', None)
        if awaiting:
            field = awaiting.get('field')
            op = awaiting.get('op')
            pretty = awaiting.get('pretty')
            # Валидация значений в зависимости от оператора
            if op == 'in':
                vals = [s.strip() for s in (value or '').split(',') if s.strip()]
                if not vals:
                    # Попросим ввести снова список значений
                    prompt = MESSAGES_ADMIN.FILTER_VALUE_PROMPT_IN.format(field=pretty) if hasattr(MESSAGES_ADMIN, 'FILTER_VALUE_PROMPT_IN') else f'Введите значения через запятую для фильтрации по полю "{pretty}" (список):'
                    await update.message.reply_text(prompt)
                    # восстановим флаг ожидания
                    context.user_data['sortfiltr_awaiting_filter_value_for'] = awaiting
                    return
            elif op == 'equals':
                if not (value or '').strip():
                    prompt = MESSAGES_ADMIN.FILTER_VALUE_PROMPT_EQUALS.format(field=pretty) if hasattr(MESSAGES_ADMIN, 'FILTER_VALUE_PROMPT_EQUALS') else f'Введите значение для фильтрации по полю "{pretty}" (точное совпадение):'
                    await update.message.reply_text(prompt)
                    context.user_data['sortfiltr_awaiting_filter_value_for'] = awaiting
                    return

            fl = context.user_data.get('sort_filters', [])
            fl.append({'field': field, 'op': op, 'value': value, 'pretty': pretty})
            context.user_data['sort_filters'] = fl
            # Отвечаем кратким резюме и предлагаем действия
            await update.message.reply_text(f"Добавлен фильтр: {pretty} {op} {value}")
            await self._show_filter_summary(update.message, context)
            return

        # Старое поведение: одиночный фильтр (backward compatible)
        field = context.user_data.get('sortfiltr_filter_field')
        if not field:
            await update.message.reply_text(MESSAGES_ADMIN.FILTER_FIELD_PROMPT + ' ' + MESSAGES_ADMIN.ADMIN_EXIT_TO_MENU)
            await self.start(update, context)
            return
        # Подготовим SQL с WHERE и параметры (частичное совпадение)
        where_clause = f"WHERE LOWER({field}) LIKE LOWER(?)"
        # Всегда выбираем поля в порядке: surname, name, patronymic, group_disability, date_birth, address, phone, `group`
        select_sql = f"SELECT surname, name, patronymic, group_disability, date_birth, address, phone, `group` FROM members {where_clause} ORDER BY surname COLLATE NOCASE ASC"
        count_sql = f"SELECT COUNT(*) FROM members {where_clause}"
        context.user_data['sortfiltr_query_params'] = (f"%{value}%",)
        context.user_data['sortfiltr_count_sql'] = count_sql
        # Сохраним select_sql для повторной пагинации
        context.user_data['sortfiltr_select_sql'] = select_sql
        context.user_data['sortfiltr_awaiting_filter_value'] = False
        await self._paginate_query(update, context, select_sql=select_sql, title=f'Результаты фильтрации по {field}', current_sort_key=f'filter:{field}')
        context.user_data.pop('sortfiltr_query_params', None)
        context.user_data.pop('sortfiltr_count_sql', None)

    async def handle_action_without_set(self, update, context):
        choice = context.user_data.get('sortfiltr_choice')
        if choice == '1':
            await update.message.reply_text(MESSAGES_ADMIN.SORT_FIELD_PROMPT)
            context.user_data['sortfiltr_awaiting_sort_field'] = True
            context.user_data['sortfiltr_awaiting_action'] = False
        elif choice == '2':
            await update.message.reply_text(MESSAGES_ADMIN.FILTER_NOT_IMPLEMENTED)
            context.user_data['sortfiltr_awaiting_action'] = False
        else:
            await update.message.reply_text(MESSAGES_ADMIN.SORT_CHOICE_PROMPT)

    async def show_return_menu(self, update, context):
        await update.message.reply_text(MESSAGES_ADMIN.SORT_POST_ACTION_PROMPT)
        context.user_data['awaiting_return_menu'] = True  # Устанавливаем флаг ожидания выбора в меню возврата

    async def handle_return_menu_choice(self, update, context):
        user_reply = update.message.text.strip()
        if user_reply == '1':
            # Сохранить изменения (пример: коммит в БД, если требуется)
            # Здесь предполагается, что изменения уже внесены в БД, если нет — добавить нужную логику
            await update.message.reply_text(MESSAGES_ADMIN.CHANGES_SAVED)
            await self.start(update, context)
            context.user_data['awaiting_return_menu'] = False
            
        elif user_reply == '2':
            await update.message.reply_text(MESSAGES_ADMIN.CHANGES_NOT_SAVED)
            await self.start(update, context)
            context.user_data['awaiting_return_menu'] = False
            
        else:
            await update.message.reply_text(MESSAGES_ADMIN.RETURN_MENU_INVALID_CHOICE)

    async def process_state(self, update, context):
        """
        Универсальный обработчик состояний для SortAndFiltr.
        Если какой-либо из флагов состояния для SortAndFiltr установлен, вызывает
        соответствующий метод и возвращает True (чтобы бот не продолжал основную обработку).
        Возвращает False, если никаких флагов SortAndFiltr не установлено.
        """
        # Повтор или выход из SortAndFiltr
        if context.user_data.get('sortfiltr_repeat_or_exit'):
            await self.handle_repeat_or_exit(update, context)
            return True

        if context.user_data.get('sortfiltr_awaiting_action'):
            await self.handle_action(update, context)
            return True

        if context.user_data.get('sortfiltr_awaiting_sort_field'):
            await self.handle_sort_field(update, context)
            return True

        # Ожидание выбора поля для фильтрации
        if context.user_data.get('sortfiltr_awaiting_filter_field'):
            await self.handle_filter_field(update, context)
            return True

        # Ожидание ввода значения для выбранного поля фильтрации
        # Поддерживаем два флага: старый булевый 'sortfiltr_awaiting_filter_value'
        # (текстовый режим) и 'sortfiltr_awaiting_filter_value_for' (callback -> оператор -> ввод)
        if context.user_data.get('sortfiltr_awaiting_filter_value') or context.user_data.get('sortfiltr_awaiting_filter_value_for'):
            await self.handle_filter_value(update, context)
            return True

        if context.user_data.get('awaiting_return_menu'):
            await self.handle_return_menu_choice(update, context)
            return True

        # Пагинация
        if context.user_data.get('sortfiltr_paginating'):
            await self.handle_pagination(update, context)
            return True

        return False

    async def handle_pagination(self, update, context):
        """
        Обработка ввода пагинации: '>' - следующая страница, '<' - предыдущая, '0' - выход.
        После изменения страницы вызывает соответствующий метод сортировки для текущего типа.
        """
        text = update.message.text.strip()
        if text == '0':
            context.user_data['sortfiltr_paginating'] = False
            await update.message.reply_text(MESSAGES_ADMIN.PAGINATION_EXIT_PROMPT + ' ' + MESSAGES_ADMIN.ADMIN_EXIT_TO_MENU)
            await self.start(update, context)
            return

        page = context.user_data.get('sortfiltr_page', 1)
        total = context.user_data.get('sortfiltr_total_pages', 1)
        if text == '>':
            if page < total:
                page += 1
        elif text == '<':
            if page > 1:
                page -= 1
        else:
            await update.message.reply_text(MESSAGES_ADMIN.PAGINATION_INSTRUCTIONS)
            return

        context.user_data['sortfiltr_page'] = page
        # Повторно вызываем текущий сортирующий метод
        current = context.user_data.get('sortfiltr_current_sort')
        if current == 'surname':
            await self.sort_surname(update, context)
        elif current == 'gr1':
            await self.sort_gr1(update, context)
        elif current == 'group':
            await self.sort_group(update, context)
        elif current == 'floor':
            await self.sort_floor(update, context)
        else:
            await update.message.reply_text(MESSAGES_ADMIN.UNKNOWN_SORT_MODE)

    async def handle_repeat_or_exit(self, update, context):
        """
        Обрабатывает выбор пользователя при флаге повтор/выход.
        Ожидает ввод: '1' — повторить (возврат в меню SortAndFiltr), '2' — выйти в админ-меню.
        Если ввод некорректен, повторно запрашивает выбор.
        """
        text = update.message.text.strip()
        # Если флаг выставлен и это первый вызов — предложим пользователю выбор
        if text not in ('1', '2'):
            await update.message.reply_text(MESSAGES_ADMIN.SORT_REPEAT_EXIT)
            # Оставляем флаг активным, чтобы следующий ввод был обработан этим методом
            context.user_data['sortfiltr_repeat_or_exit'] = True
            return

        # Сбрасываем флаг — выбор будет обработан
        context.user_data['sortfiltr_repeat_or_exit'] = False
        if text == '1':
            # Повтор — просто вернём пользователя в начало SortAndFiltr
            await self.start(update, context)
            return
        elif text == '2':
            # Выход — вернуть в главное меню администратора
            from bot import admin_message
            await admin_message(update, context)
            return

    async def handle_callback(self, update, context):
        """Обработка CallbackQuery для фильтрации и пагинации."""
        query = update.callback_query
        data = query.data or ''
        await query.answer()

        # Формат данных: sortfiltr:action:arg
        parts = data.split(':')
        if len(parts) < 2 or parts[0] != 'sortfiltr':
            return
        action = parts[1]
        arg = parts[2] if len(parts) > 2 else None

        # Обработка выбора поля фильтрации / операций фильтра
        if action == 'filter':
            # arg может быть 'cancel' или имя поля, либо служебные команды
            if arg == 'cancel':
                await query.message.edit_text(MESSAGES_ADMIN.CANCELLED)
                await self.start(update, context)
                return
            if arg == 'apply':
                # Применить накопленные фильтры
                filters = context.user_data.get('sort_filters', []) or []
                if not filters:
                    await query.message.reply_text(MESSAGES_ADMIN.FILTER_NO_FILTERS if hasattr(MESSAGES_ADMIN, 'FILTER_NO_FILTERS') else 'Нет заданных фильтров')
                    return
                where_clause, params, count_sql, select_sql, order_field = self._build_where_from_filters(filters)
                if not where_clause:
                    await query.message.reply_text(MESSAGES_ADMIN.FILTER_INVALID if hasattr(MESSAGES_ADMIN, 'FILTER_INVALID') else 'Невозможно составить запрос из фильтров')
                    return
                # Сохраним параметры и вызовем пагинацию
                context.user_data['sortfiltr_query_params'] = params
                context.user_data['sortfiltr_count_sql'] = count_sql
                # Сохраним также select_sql для восстановления при пагинации
                context.user_data['sortfiltr_select_sql'] = select_sql
                context.user_data['sortfiltr_page'] = 1
                context.user_data['sortfiltr_current_sort'] = 'filter:multi'
                fake = type('F', (), {})()
                fake.message = query.message
                await self._paginate_query(fake, context, select_sql=select_sql, title='Результаты фильтрации', current_sort_key='filter:multi')
                # Очистка временных фильтров оставляем на усмотрение (пока сохраняем в контексте)
                return
            if arg == 'clear':
                context.user_data.pop('sort_filters', None)
                await query.message.edit_text('Фильтры очищены.')
                # предложим снова выбрать поле
                await self.send_filter_field_keyboard(update, context)
                return
            if arg and arg.startswith('remove:'):
                try:
                    idx = int(arg.split(':', 1)[1])
                    fl = context.user_data.get('sort_filters', [])
                    if 0 <= idx < len(fl):
                        fl.pop(idx)
                        context.user_data['sort_filters'] = fl
                        await query.message.edit_text('Фильтр удалён.')
                    else:
                        await query.message.answer('Индекс фильтра неверен')
                except Exception:
                    await query.message.answer('Не удалось удалить фильтр')
                # показать поле выбора снова
                await self.send_filter_field_keyboard(update, context)
                return
            # Если нажата кнопка 'Добавить ещё' (callback back) — показать выбор поля снова
            if arg == 'back':
                await self.send_filter_field_keyboard(update, context)
                return

            # Иначе — это имя поля: покажем клавиатуру операторов для выбранного поля
            field = arg
            # prettify
            pretty_map = {
                'surname': 'Фамилия',
                'group_disability': 'Группа инвалидности',
                '`group`': 'Группа',
                'floor': 'Пол',
                'area': 'Район',
                'phone': 'Телефон'
            }
            pretty = pretty_map.get(field, field)
            ops = [
                InlineKeyboardButton('Равно', callback_data=f"sortfiltr:filterop:{field}:equals"),
                InlineKeyboardButton('Содержит', callback_data=f"sortfiltr:filterop:{field}:contains"),
                InlineKeyboardButton('В списке', callback_data=f"sortfiltr:filterop:{field}:in"),
                InlineKeyboardButton('Пусто', callback_data=f"sortfiltr:filterop:{field}:isnull"),
                InlineKeyboardButton('Не пусто', callback_data=f"sortfiltr:filterop:{field}:notnull")
            ]
            ops.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='sortfiltr:filter:back'))
            ops.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='sortfiltr:filter:exit'))
            kb = InlineKeyboardMarkup([[b] for b in ops])
            await query.message.reply_text(MESSAGES_ADMIN.FILTER_CHOOSE_OP.format(field=pretty) if hasattr(MESSAGES_ADMIN, 'FILTER_CHOOSE_OP') else f'Выберите оператор для {pretty}:', reply_markup=kb)
            return

        if action == 'filterop':
            # parts: sortfiltr:filterop:<field>:<op>
            field = arg
            op = parts[3] if len(parts) > 3 else None
            pretty_map = {
                'surname': 'Фамилия',
                'group_disability': 'Группа инвалидности',
                '`group`': 'Группа',
                'floor': 'Пол',
                'area': 'Район',
                'phone': 'Телефон'
            }
            pretty = pretty_map.get(field, field)
            # операции без значения
            if op in ('isnull', 'notnull'):
                fl = context.user_data.get('sort_filters', [])
                fl.append({'field': field, 'op': op, 'value': None, 'pretty': pretty})
                context.user_data['sort_filters'] = fl
                await query.message.reply_text(f"Добавлен фильтр: {pretty} {op}")
                # показать текущие фильтры и опции
                await self._show_filter_summary(query.message, context)
                return
            # операции с вводом значения
            context.user_data['sortfiltr_awaiting_filter_value_for'] = {'field': field, 'op': op, 'pretty': pretty}
            # попросим ввести значение — сообщение зависит от оператора
            if op == 'equals':
                prompt = MESSAGES_ADMIN.FILTER_VALUE_PROMPT_EQUALS.format(field=pretty) if hasattr(MESSAGES_ADMIN, 'FILTER_VALUE_PROMPT_EQUALS') else f'Введите значение для фильтрации по полю "{pretty}" (точное совпадение):'
            elif op == 'contains':
                # частичное совпадение — стандартное сообщение
                prompt = MESSAGES_ADMIN.FILTER_VALUE_PROMPT.format(field=pretty)
            elif op == 'in':
                prompt = MESSAGES_ADMIN.FILTER_VALUE_PROMPT_IN.format(field=pretty) if hasattr(MESSAGES_ADMIN, 'FILTER_VALUE_PROMPT_IN') else f'Введите значения через запятую для фильтрации по полю "{pretty}" (список):'
            else:
                prompt = MESSAGES_ADMIN.FILTER_VALUE_PROMPT.format(field=pretty)
            await query.message.reply_text(prompt)
            return

        # Обработка начального меню действий (sort/filter/exit)
        if action == 'action':
            # arg может быть 'sort' / 'filter' / 'exit'
            if arg == 'sort':
                # Удалим сообщение с выбором действий и покажем inline-клавиатуру выбора поля для сортировки
                try:
                    await query.message.delete()
                except Exception:
                    pass
                try:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton('1. По фамилии', callback_data='sortfiltr:sort:surname')],
                        [InlineKeyboardButton('2. По группе инвалидности', callback_data='sortfiltr:sort:gr1')],
                        [InlineKeyboardButton('3. По группам', callback_data='sortfiltr:sort:group')],
                        [InlineKeyboardButton('4. По полу', callback_data='sortfiltr:sort:floor')],
                        [InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='sortfiltr:sort:back'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='sortfiltr:sort:exit')]
                    ])
                    # Отправим заголовок и клавиатуру
                    await query.message.reply_text(MESSAGES_ADMIN.SORT_FIELD_PROMPT.splitlines()[0], reply_markup=kb)
                    context.user_data['sortfiltr_awaiting_sort_field'] = True
                    context.user_data['sortfiltr_awaiting_action'] = False
                except Exception:
                    try:
                        logger.exception('handle_callback: failed to send SORT_FIELD inline keyboard')
                    except Exception:
                        pass
                return
            if arg == 'filter':
                try:
                    await query.message.delete()
                except Exception:
                    pass
                try:
                    # Покажем inline-клавиатуру для выбора поля фильтрации
                    await self.send_filter_field_keyboard(update, context)
                    context.user_data['sortfiltr_awaiting_action'] = False
                    return
                except Exception:
                    try:
                        logger.exception('handle_callback: failed to send filter field keyboard')
                    except Exception:
                        pass
                    return
            if arg == 'exit':
                try:
                    # удалить все старые сообщения списка/навигации прежде чем вернуть в админ-меню
                    await self._cleanup_list_messages(context, delete_trigger_message=query.message)
                    from bot import admin_message
                    fake = type('F', (), {})()
                    fake.callback_query = query
                    fake.message = query.message
                    await admin_message(fake, context)
                except Exception:
                    try:
                        logger.exception('handle_callback: failed to handle action:exit')
                    except Exception:
                        pass
                return

        # Пагинация
        if action == 'page':
            page = context.user_data.get('sortfiltr_page', 1)
            total = context.user_data.get('sortfiltr_total_pages', 1)
            # Числовой аргумент — прямая навигация на указанную страницу
            if arg == 'info':
                # Нажатие на текущую страницу — просто показать уведомление
                try:
                    await query.answer(text='Текущая страница', show_alert=False)
                except Exception:
                    pass
                return

            if arg and arg.isdigit():
                try:
                    target_page = int(arg)
                    if target_page < 1:
                        target_page = 1
                    context.user_data['sortfiltr_page'] = target_page
                    # Удалим предыдущие сообщения списка/навигацию и сообщение-триггер
                    await self._cleanup_list_messages(context, delete_trigger_message=query.message)
                    # Вызовем соответствующий сортирующий метод — используем fake.update с message = query.message
                    current = context.user_data.get('sortfiltr_current_sort')
                    fake = type('F', (), {})()
                    fake.message = query.message
                    if isinstance(current, str) and current.startswith('filter:'):
                        # При режиме фильтрации используем ранее сохранённые select/count в контексте
                        # Если их нет, соберём стандартный select с нужными полями и сортировкой по фамилии
                        select_sql = context.user_data.get('sortfiltr_select_sql') or (
                            "SELECT surname, name, patronymic, group_disability, date_birth, address, phone, `group` FROM members ORDER BY surname COLLATE NOCASE ASC"
                        )
                        await self._paginate_query(fake, context, select_sql=select_sql, title='Результаты фильтрации', current_sort_key=current)
                    else:
                        if current == 'surname':
                            await self.sort_surname(fake, context)
                        elif current == 'gr1':
                            await self.sort_gr1(fake, context)
                        elif current == 'group':
                            await self.sort_group(fake, context)
                        elif current == 'floor':
                            await self.sort_floor(fake, context)
                except Exception:
                    try:
                        logger.exception('handle_callback: failed to handle numeric page navigation')
                    except Exception:
                        pass
                return
            if arg == 'next':
                if page < total:
                    context.user_data['sortfiltr_page'] = page + 1
            elif arg == 'prev':
                if page > 1:
                    context.user_data['sortfiltr_page'] = page - 1
            elif arg == 'back':
                # Удалим все предыдущие сообщения списка/навигации и сообщение-триггер, затем покажем меню выбора поля для сортировки
                try:
                    await self._cleanup_list_messages(context, delete_trigger_message=query.message)
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton('1. По фамилии', callback_data='sortfiltr:sort:surname')],
                        [InlineKeyboardButton('2. По группе инвалидности', callback_data='sortfiltr:sort:gr1')],
                        [InlineKeyboardButton('3. По группам', callback_data='sortfiltr:sort:group')],
                        [InlineKeyboardButton('4. По полу', callback_data='sortfiltr:sort:floor')],
                        [InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='sortfiltr:sort:back'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data='sortfiltr:sort:exit')]
                    ])
                    await query.message.reply_text(MESSAGES_ADMIN.SORT_FIELD_PROMPT.splitlines()[0], reply_markup=kb)
                except Exception:
                    try:
                        logger.exception('handle_callback: failed to handle page:back')
                    except Exception:
                        pass
                return
            elif arg == 'exit':
                # Завершение — удалить все старые сообщения списка/навигации/текущий и вернуть в админ-меню
                try:
                    await self._cleanup_list_messages(context, delete_trigger_message=query.message)
                    from bot import admin_message
                    fake = type('F', (), {})()
                    fake.callback_query = query
                    fake.message = query.message
                    await admin_message(fake, context)
                except Exception:
                    try:
                        logger.exception('handle_callback: failed to handle page:exit')
                    except Exception:
                        pass
                return
            # Повторно показать текущую страницу
            current = context.user_data.get('sortfiltr_current_sort')
            fake = type('F', (), {})()
            fake.message = query.message
            # Если текущий режим — фильтр, сформируем select_sql из контекста
            if isinstance(current, str) and current.startswith('filter:'):
                # При режиме фильтрации используем ранее сохранённые select/count в контексте
                select_sql = context.user_data.get('sortfiltr_select_sql') or (
                    "SELECT surname, name, patronymic, group_disability, date_birth, address, phone, `group` FROM members ORDER BY surname COLLATE NOCASE ASC"
                )
                await self._paginate_query(fake, context, select_sql=select_sql, title='Результаты фильтрации', current_sort_key=current)
            else:
                if current == 'surname':
                    await self.sort_surname(fake, context)
                elif current == 'gr1':
                    await self.sort_gr1(fake, context)
                elif current == 'group':
                    await self.sort_group(fake, context)
                elif current == 'floor':
                    await self.sort_floor(fake, context)
            return

        # Обработка выбора поля сортировки после фильтрации (после вывода результатов)
        if action == 'filter_sort':
            # arg: surname | group_disability | date_birth
            # Нужно пересобрать SELECT с тем же WHERE, но другим ORDER BY
            field = arg
            col_map = {
                'surname': 'surname',
                'group_disability': 'group_disability',
                'date_birth': 'date_birth'
            }
            order_col = col_map.get(field)
            if not order_col:
                await query.message.answer('Некорректное поле сортировки')
                return
            try:
                # Удаляем текущие список/навигацию и триггер
                await self._cleanup_list_messages(context, delete_trigger_message=query.message)
            except Exception:
                pass
            # Попробуем взять WHERE/params из сохранённого состояния
            params = context.user_data.get('sortfiltr_query_params')
            count_sql = context.user_data.get('sortfiltr_count_sql')
            where_clause = None
            # Если есть сохранённый select_sql — используем его как базу и заменим ORDER BY
            stored_select = context.user_data.get('sortfiltr_select_sql')
            if stored_select:
                base = stored_select
                # Удалим случайно добавленные LIMIT/OFFSET (они добавляются только при выполнении)
                base = re.sub(r"\s+LIMIT\s+\?\s+OFFSET\s+\?\s*$", '', base, flags=re.IGNORECASE)
                # Заменим существующий ORDER BY на новый, либо добавим его
                if re.search(r'ORDER\s+BY', base, flags=re.IGNORECASE):
                    select_sql = re.sub(r'ORDER\s+BY[\s\S]*$', f'ORDER BY {order_col} COLLATE NOCASE ASC', base, flags=re.IGNORECASE)
                else:
                    select_sql = base + f' ORDER BY {order_col} COLLATE NOCASE ASC'
            else:
                if not count_sql or not params:
                    # Попробуем восстановить из sort_filters
                    filters = context.user_data.get('sort_filters', []) or []
                    where_clause, params_rec, count_sql_rec, select_sql_rec, _ = self._build_where_from_filters(filters)
                    params = params_rec
                    count_sql = count_sql_rec
                # Построим select_sql с нужным ORDER BY, учитывая where_clause
                if where_clause:
                    select_sql = f"SELECT surname, name, patronymic, group_disability, date_birth, address, phone, `group` FROM members {where_clause} ORDER BY {order_col} COLLATE NOCASE ASC"
                else:
                    select_sql = f"SELECT surname, name, patronymic, group_disability, date_birth, address, phone, `group` FROM members ORDER BY {order_col} COLLATE NOCASE ASC"
            # Сохраним в контексте и вызовем пагинацию
            context.user_data['sortfiltr_select_sql'] = select_sql
            context.user_data['sortfiltr_count_sql'] = count_sql
            context.user_data['sortfiltr_query_params'] = params
            context.user_data['sortfiltr_page'] = 1
            fake = type('F', (), {})()
            fake.message = query.message
            await self._paginate_query(fake, context, select_sql=select_sql, title='Результаты фильтрации', current_sort_key=f'filter:sorted:{field}')
            return

        # Обработка выбора поля для сортировки (inline-кнопки)
        if action == 'sort':
            # arg: surname | gr1 | group | floor | back | exit
            if arg in ('surname', 'gr1', 'group', 'floor'):
                try:
                    # удалим сообщение с inline-кнопками выбора поля
                    try:
                        await query.message.delete()
                    except Exception:
                        pass
                    # Построим fake update с message = query.message, чтобы сортирующие методы могли отвечать в тот же чат
                    fake = type('F', (), {})()
                    fake.message = query.message
                    # Сбросим страницу на 1
                    context.user_data['sortfiltr_page'] = 1
                    if arg == 'surname':
                        await self.sort_surname(fake, context)
                    elif arg == 'gr1':
                        await self.sort_gr1(fake, context)
                    elif arg == 'group':
                        await self.sort_group(fake, context)
                    elif arg == 'floor':
                        await self.sort_floor(fake, context)
                except Exception:
                    try:
                        logger.exception('handle_callback: failed to execute sort action')
                    except Exception:
                        pass
                return
            if arg == 'back':
                try:
                    # Удалим все старые сообщения списка/навигации и сообщение-триггер, затем вернёмся в start
                    await self._cleanup_list_messages(context, delete_trigger_message=query.message)
                    fake = type('F', (), {})()
                    fake.message = query.message
                    await self.start(fake, context)
                except Exception:
                    try:
                        logger.exception('handle_callback: failed to handle sort:back')
                    except Exception:
                        pass
                return
            if arg == 'exit':
                try:
                    try:
                        await query.message.delete()
                    except Exception:
                        pass
                    from bot import admin_message
                    fake = type('F', (), {})()
                    fake.callback_query = query
                    fake.message = query.message
                    await admin_message(fake, context)
                except Exception:
                    try:
                        logger.exception('handle_callback: failed to handle sort:exit')
                    except Exception:
                        pass
                return
