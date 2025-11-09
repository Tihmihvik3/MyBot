import logging
from utils.message_cleanup import cleanup_admin_messages
from db.database import Database
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import traceback
from admin_notify import notify_admin


logger = logging.getLogger(__name__)


class SortAndFiltr:
    PAGE_SIZE_DEFAULT = 20

    async def start(self, update, context):
        # Очистим предыдущие админские сообщения
        try:
            await cleanup_admin_messages(context, bot=context.bot, logger_obj=logger)
        except Exception:
            logger.exception('SortAndFiltr.start: cleanup failed')
        await update.message.reply_text('Выберите действие:\n1. Сортировать по\n2. Фильтровать по\n0. Выйти')
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
            await update.message.reply_text('Выберите поле для сортировки:\n1. По фамилии\n2. По группе инвалидности\n3. По группам\n4. По полу\n0. выйти')
            context.user_data['sortfiltr_awaiting_sort_field'] = True  # Ожидаем выбор поля для сортировки
            context.user_data['sortfiltr_awaiting_action'] = False  # Ожидаем, что пользователь выберет поле для сортировки
        elif context.user_data['sortfiltr_choice'] == '2':
            # Показать inline-кнопки для выбора поля фильтрации
            await self.send_filter_field_keyboard(update, context)
            context.user_data['sortfiltr_awaiting_action'] = False
        elif context.user_data['sortfiltr_choice'] == '0':
            # Выход из SortAndFiltr и возврат к admin_message
            await update.message.reply_text('Возврат в главное меню администратора.')
            from bot import admin_message
            await admin_message(update, context)
            context.user_data['sortfiltr_awaiting_action'] = False
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        else:
            await update.message.reply_text('Введите 1 (сортировать) или 2 (фильтровать).')
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
            await update.message.reply_text('Введите номер поля из списка.')

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
            await update.message.reply_text(f'Введите значение для фильтрации по полю "{pretty}" (частичное совпадение):')
            context.user_data['sortfiltr_awaiting_filter_value'] = True
            context.user_data['sortfiltr_awaiting_filter_field'] = False
        else:
            await update.message.reply_text('Выберите корректный номер поля для фильтрации.')

    async def send_filter_field_keyboard(self, update, context):
        """Отправляет inline-клавиатуру с полями для фильтрации."""
        buttons = [
            [InlineKeyboardButton('Фамилия', callback_data='sortfiltr:filter:surname'), InlineKeyboardButton('Группа инвалидности', callback_data='sortfiltr:filter:group_disability')],
            [InlineKeyboardButton('Группа', callback_data='sortfiltr:filter:`group`'), InlineKeyboardButton('Пол', callback_data='sortfiltr:filter:floor')],
            [InlineKeyboardButton('Район', callback_data='sortfiltr:filter:area'), InlineKeyboardButton('Телефон', callback_data='sortfiltr:filter:phone')],
            [InlineKeyboardButton('Отмена', callback_data='sortfiltr:filter:cancel')]
        ]
        kb = InlineKeyboardMarkup(buttons)
        # При CallbackQuery используем .message, иначе .message от Update
        target = getattr(update, 'callback_query', None)
        if target:
            await target.message.reply_text('Выберите поле для фильтрации:', reply_markup=kb)
        else:
            await update.message.reply_text('Выберите поле для фильтрации:', reply_markup=kb)

    def _build_pagination_markup(self, page: int, total: int) -> InlineKeyboardMarkup:
        buttons = []
        row = []
        if page > 1:
            row.append(InlineKeyboardButton('◀', callback_data='sortfiltr:page:prev'))
        row.append(InlineKeyboardButton(f'{page}/{total}', callback_data='sortfiltr:page:info'))
        if page < total:
            row.append(InlineKeyboardButton('▶', callback_data='sortfiltr:page:next'))
        row.append(InlineKeyboardButton('Выход', callback_data='sortfiltr:page:exit'))
        buttons.append(row)
        return InlineKeyboardMarkup(buttons)

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
                    await update.message.reply_text('В базе нет данных.')
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
                msg = f"{title} (страница {page}/{total_pages}):\n"
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
                for m in messages:
                    await update.message.reply_text(m)
                context.user_data['sortfiltr_total_pages'] = total_pages
                context.user_data['sortfiltr_page'] = page
                context.user_data['sortfiltr_paginating'] = True
                context.user_data['sortfiltr_current_sort'] = current_sort_key
                # Отправляем inline-клавиатуру пагинации
                kb = self._build_pagination_markup(page, total_pages)
                await update.message.reply_text('Навигация по страницам:', reply_markup=kb)
            return
        except Exception as e:
            logger.exception('Ошибка при пагинации сортировки')
            try:
                await notify_admin(context, 'Ошибка при пагинации сортировки (sort_and_filtr)', traceback.format_exc())
            except Exception:
                pass
            await update.message.reply_text(f'Ошибка при сортировке: {e}')

    async def handle_filter_value(self, update, context):
        value = update.message.text.strip()
        field = context.user_data.get('sortfiltr_filter_field')
        if not field:
            await update.message.reply_text('Поле для фильтрации не выбрано. Вернитесь в меню фильтрации.')
            await self.start(update, context)
            return
        # Подготовим SQL с WHERE и параметры
        # Используем частичное совпадение (LIKE %value%)
        where_clause = f"WHERE LOWER({field}) LIKE LOWER(?)"
        # Выбор отображаемых столбцов — сначала поле фильтрации, затем ФИО
        select_sql = f"SELECT {field}, surname, name, patronymic FROM members {where_clause} ORDER BY {field} COLLATE NOCASE ASC"
        count_sql = f"SELECT COUNT(*) FROM members {where_clause}"
        # Сохраним параметры в context, чтобы _paginate_query мог их использовать
        context.user_data['sortfiltr_query_params'] = (f"%{value}%",)
        context.user_data['sortfiltr_count_sql'] = count_sql
        # Сбросим флаги ожидания
        context.user_data['sortfiltr_awaiting_filter_value'] = False
        # Переиспользуем _paginate_query, задав current_sort_key как фильтр-field
        await self._paginate_query(update, context, select_sql=select_sql, title=f'Результаты фильтрации по {field}', current_sort_key=f'filter:{field}')
        # Очистим временные параметры после выполнения
        context.user_data.pop('sortfiltr_query_params', None)
        context.user_data.pop('sortfiltr_count_sql', None)

    async def handle_action_without_set(self, update, context):
        choice = context.user_data.get('sortfiltr_choice')
        if choice == '1':
            await update.message.reply_text('Выберите поле для сортировки:\n1. По фамилии\n2. По группе инвалидности\n3. По группам\n4. По полу')
            context.user_data['sortfiltr_awaiting_sort_field'] = True
            context.user_data['sortfiltr_awaiting_action'] = False
        elif choice == '2':
            await update.message.reply_text('Фильтрация по выбранному полю пока не реализована.')
            context.user_data['sortfiltr_awaiting_action'] = False
        else:
            await update.message.reply_text('Введите 1 (сортировать) или 2 (фильтровать).')

    async def show_return_menu(self, update, context):
        menu_text = "\nВыберите действие после сортировки:\n1. Сохранить изменения\n2. Не сохранять изменения"
        await update.message.reply_text(menu_text)
        context.user_data['awaiting_return_menu'] = True  # Устанавливаем флаг ожидания выбора в меню возврата

    async def handle_return_menu_choice(self, update, context):
        user_reply = update.message.text.strip()
        if user_reply == '1':
            # Сохранить изменения (пример: коммит в БД, если требуется)
            # Здесь предполагается, что изменения уже внесены в БД, если нет — добавить нужную логику
            await update.message.reply_text('Изменения сохранены.')
            await self.start(update, context)
            context.user_data['awaiting_return_menu'] = False
            
        elif user_reply == '2':
            await update.message.reply_text('Изменения не сохранены.')
            await self.start(update, context)
            context.user_data['awaiting_return_menu'] = False
            
        else:
            await update.message.reply_text('Пожалуйста, выберите 1 (сохранить) или 2 (не сохранять).')

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
        if context.user_data.get('sortfiltr_awaiting_filter_value'):
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
            await update.message.reply_text('Выход из режима пагинации. Возврат в меню сортировки.')
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
            await update.message.reply_text("Введите '>' или '<' для навигации, или 0 для выхода.")
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
            await update.message.reply_text('Неизвестный режим сортировки.')

    async def handle_repeat_or_exit(self, update, context):
        """
        Обрабатывает выбор пользователя при флаге повтор/выход.
        Ожидает ввод: '1' — повторить (возврат в меню SortAndFiltr), '2' — выйти в админ-меню.
        Если ввод некорректен, повторно запрашивает выбор.
        """
        text = update.message.text.strip()
        # Если флаг выставлен и это первый вызов — предложим пользователю выбор
        if text not in ('1', '2'):
            await update.message.reply_text('Повтор или выход?\n1. Повторить\n2. Выйти')
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

        # Обработка выбора поля фильтрации
        if action == 'filter':
            if arg == 'cancel':
                await query.message.edit_text('Отменено')
                await self.start(update, context)
                return
            # Сохраним выбор и попросим ввести значение
            context.user_data['sortfiltr_filter_field'] = arg
            context.user_data['sortfiltr_awaiting_filter_value'] = True
            await query.message.edit_text(f'Выбрано поле для фильтрации: {arg}. Введите значение (частичное совпадение):')
            return

        # Пагинация
        if action == 'page':
            page = context.user_data.get('sortfiltr_page', 1)
            total = context.user_data.get('sortfiltr_total_pages', 1)
            if arg == 'next':
                if page < total:
                    context.user_data['sortfiltr_page'] = page + 1
            elif arg == 'prev':
                if page > 1:
                    context.user_data['sortfiltr_page'] = page - 1
            elif arg == 'exit':
                context.user_data['sortfiltr_paginating'] = False
                await query.message.edit_text('Выход из режима пагинации.')
                await self.start(update, context)
                return
            # Повторно показать текущую страницу
            current = context.user_data.get('sortfiltr_current_sort')
            # Если текущий режим — фильтр, сформируем select_sql из контекста
            if isinstance(current, str) and current.startswith('filter:'):
                field = current.split(':', 1)[1]
                # Если фильтр — это специальный режим, восстановим предыдущие параметры
                # Параметры должны быть в sortfiltr_query_params и sortfiltr_count_sql
                select_sql = f"SELECT {field}, surname, name, patronymic FROM members ORDER BY {field} COLLATE NOCASE ASC"
                await self._paginate_query(update, context, select_sql=select_sql, title=f'Результаты фильтрации по {field}', current_sort_key=current)
            else:
                if current == 'surname':
                    await self.sort_surname(update, context)
                elif current == 'gr1':
                    await self.sort_gr1(update, context)
                elif current == 'group':
                    await self.sort_group(update, context)
                elif current == 'floor':
                    await self.sort_floor(update, context)
            return
