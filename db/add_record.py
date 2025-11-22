import logging
from utils.admin_messenger import send_and_track, delete_tracked_messages
import messages_admin as MESSAGES_ADMIN

logger = logging.getLogger(__name__)


class AddRecord:
    fields = [
        "Фамилия", "Имя", "Отчество", "Дата рождения", "Группа инвалидности", "Телефон", "Адрес", "Район", "Группа", "Справка МСЭ", "Дата выдачи справки МСЭ", "Срок действия справки МСЭ", "Пенсионное удостоверение", "Номер членского билета", "Дата вступления", "Пол"
    ]
    db_fields = [
        "surname", "name", "patronymic", "date_birth", "group_disability", "phone", "address", "area", "`group`", "help_number", "date_issue", "validity_period", "pension_number", "ticket_number", "date_entry", "floor"
    ]

    async def start_add(self, update, context):
        # Отправим приглашение через send_and_track (он удалит старые admin-сообщения)
        context.user_data['add_record_data'] = {}
        context.user_data['add_record_step'] = 0
        try:
            # Удалим предыдущие админские заголовок/меню, чтобы не оставлять их в чате
            try:
                for k in ('admin_header_message', 'admin_menu_message'):
                    val = context.user_data.pop(k, None)
                    if val and isinstance(val, (list, tuple)) and len(val) >= 2:
                        try:
                            await context.bot.delete_message(chat_id=val[0], message_id=val[1])
                        except Exception:
                            pass
            except Exception:
                logger.exception('start_add: failed to cleanup admin header/menu')

            # Показать информационное сообщение перед началом заполнения карточки
            try:
                if getattr(update, 'message', None):
                    sent_header = await update.message.reply_text(MESSAGES_ADMIN.ADD_RECORD_HEADER)
                    try:
                        context.user_data['add_record_header_message'] = (sent_header.chat.id, sent_header.message_id)
                    except Exception:
                        pass
                else:
                    # fallback
                    uid = getattr(update.callback_query.from_user, 'id', None) if getattr(update, 'callback_query', None) else None
                    if uid:
                        sent_header = await context.bot.send_message(chat_id=uid, text=MESSAGES_ADMIN.ADD_RECORD_HEADER)
                        try:
                            context.user_data['add_record_header_message'] = (sent_header.chat.id, sent_header.message_id)
                        except Exception:
                            pass
            except Exception:
                logger.exception('start_add: failed to send card header')

            await self.ask_step(update, context, 0)
        except Exception:
            logger.exception('start_add: send_and_track failed; falling back')
            try:
                # Fallback: reuse ask_step to ensure the prompt includes the inline Cancel button
                await self.ask_step(update, context, 0)
            except Exception:
                try:
                    await update.message.reply_text(MESSAGES_ADMIN.ENTER_FIELD_TEMPLATE.format(field='Фамилию'))
                except Exception:
                    pass
        context.user_data['add_record_in_progress'] = True

    def _build_kb(self, step: int):
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        # Always include 'Отмена' which behaves like exit
        buttons = []
        row = []
        # 'Назад' available starting from step >= 1
        if step >= 1:
            row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='workdb:add:back'))
        row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_CANCEL, callback_data='workdb:add:cancel'))
        buttons.append(row)
        return InlineKeyboardMarkup(buttons)

    async def ask_step(self, update, context, step: int):
        """Отправить (или отредактировать) приглашение для текущего шага добавления."""
        text = MESSAGES_ADMIN.ENTER_FIELD_TEMPLATE.format(field=self.fields[step])
        kb = self._build_kb(step)
        # Для шага выбора "Группа инвалидности" предлагаем список уникальных значений из БД
        if step == 4:
            logger.info(f'ask_step: building group_disability keyboard for step={step}')
            try:
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                from db.database import Database
                from urllib.parse import quote
                db = Database()
                with db.get_cursor() as cursor:
                    cursor.execute("SELECT DISTINCT group_disability FROM members WHERE group_disability IS NOT NULL AND TRIM(group_disability) <> '' ORDER BY LOWER(group_disability) ASC")
                    rows = [r[0] for r in cursor.fetchall() if r and r[0] is not None]
                buttons = []
                for val in rows:
                    enc = quote(str(val), safe='')
                    buttons.append([InlineKeyboardButton(str(val), callback_data=f'workdb:add:group:{enc}')])
                logger.info(f'ask_step: group_disability rows fetched: {len(rows)}')
                # Добавим кнопки Назад/Отмена в последнюю строку
                row = []
                if step >= 1:
                    row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='workdb:add:back'))
                row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_CANCEL, callback_data='workdb:add:cancel'))
                buttons.append(row)
                kb = InlineKeyboardMarkup(buttons)
            except Exception:
                logger.exception('ask_step: failed to build group_disability keyboard; falling back to text prompt')
        # NOTE: removed inline keyboard for general "Группа" (step 8).
        # Earlier changes added an inline-dropdown here for step==8. That behavior
        # was reverted to keep the original text-prompt flow for this field.
        # Новый безопасный вариант: показываем inline-кнопки с индексами
        # и сохраняем список значений в context.user_data['add_record_group_values']
        # чтобы callback мог подставить значение по индексу. Это предотвращает
        # проблемы с длиной callback_data и сохраняет сортировку/уникальность.
        if step == 8:
            logger.info(f'ask_step: building group index keyboard for step={step}')
            try:
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                from db.database import Database
                db = Database()
                with db.get_cursor() as cursor:
                    cursor.execute("SELECT DISTINCT `group` FROM members WHERE `group` IS NOT NULL AND TRIM(`group`) <> '' ORDER BY LOWER(`group`) ASC")
                    rows = [r[0] for r in cursor.fetchall() if r and r[0] is not None]
                # Сохраним значения в context, чтобы по индексу подставлять их позже
                context.user_data['add_record_group_values'] = rows
                buttons = []
                for i, val in enumerate(rows):
                    buttons.append([InlineKeyboardButton(str(val), callback_data=f'workdb:add:group_idx:{i}')])
                logger.info(f'ask_step: group index rows fetched: {len(rows)}')
                # Добавим кнопки Назад/Отмена в последнюю строку
                row = []
                if step >= 1:
                    row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='workdb:add:back'))
                row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_CANCEL, callback_data='workdb:add:cancel'))
                buttons.append(row)
                kb = InlineKeyboardMarkup(buttons)
            except Exception:
                logger.exception('ask_step: failed to build group index keyboard; falling back to text prompt')
        # Для шага "Пол" (шаг index 15) показываем уникальные значения поля floor как inline-кнопки
        if step == 15:
            logger.info(f'ask_step: building floor index keyboard for step={step}')
            try:
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                from db.database import Database
                db = Database()
                with db.get_cursor() as cursor:
                    cursor.execute("SELECT DISTINCT floor FROM members WHERE floor IS NOT NULL AND TRIM(floor) <> '' ORDER BY LOWER(floor) ASC")
                    rows = [r[0] for r in cursor.fetchall() if r and r[0] is not None]
                # Сохраним список значений в context для доступа по индексу
                context.user_data['add_record_floor_values'] = rows
                buttons = []
                for i, val in enumerate(rows):
                    buttons.append([InlineKeyboardButton(str(val), callback_data=f'workdb:add:floor_idx:{i}')])
                logger.info(f'ask_step: floor rows fetched: {len(rows)}')
                # Добавим кнопки Назад/Отмена
                row = []
                if step >= 1:
                    row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data='workdb:add:back'))
                row.append(InlineKeyboardButton(MESSAGES_ADMIN.BTN_CANCEL, callback_data='workdb:add:cancel'))
                buttons.append(row)
                kb = InlineKeyboardMarkup(buttons)
            except Exception:
                logger.exception('ask_step: failed to build floor index keyboard; falling back to text prompt')
        # Сохраним текущую ожидаемую ступень
        context.user_data['add_record_step'] = step
        # Сохраним ссылку на prompt message для возможной очистки
        try:
            # При первом шаге используем send_and_track, чтобы очистить старые админ-сообщения
            if step == 0:
                sent = await send_and_track(context, update.message, text, reply_markup=kb)
            else:
                # Используем обычный reply_text, чтобы не удалять admin history на каждом шаге
                sent = await update.message.reply_text(text, reply_markup=kb)
            if getattr(sent, 'chat', None):
                context.user_data['add_record_prompt_message'] = (sent.chat.id, sent.message_id)
        except Exception:
            try:
                # fallback: send via bot
                chat_id = None
                if getattr(update, 'message', None) and getattr(update.message, 'chat', None):
                    chat_id = update.message.chat.id
                elif getattr(update, 'callback_query', None) and getattr(update.callback_query, 'from_user', None):
                    chat_id = update.callback_query.from_user.id
                if chat_id:
                    sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
                    context.user_data['add_record_prompt_message'] = (sent.chat.id, sent.message_id)
            except Exception:
                logger.exception('ask_step: failed to send prompt')

    async def handle_add_step(self, update, context):
        step = context.user_data.get('add_record_step', 0)
        data = context.user_data.get('add_record_data', {})
        value = update.message.text.strip()
        data[self.db_fields[step]] = value
        context.user_data['add_record_data'] = data
        step += 1
        if step < len(self.fields):
            context.user_data['add_record_step'] = step
            # При переходе к следующему шагу удаляем предыдущий prompt, чтобы
            # не захламлять чат. Это удаляет только предыдущие приглашения
            # (сообщения, в которых пользователь вводил значение). Заголовок
            # карточки (`add_record_header_message`) оставляем до завершения
            # или отмены, чтобы пользователь видел контекст.
            try:
                prev = context.user_data.pop('add_record_prompt_message', None)
                if prev and isinstance(prev, (list, tuple)) and len(prev) >= 2:
                    try:
                        await context.bot.delete_message(chat_id=prev[0], message_id=prev[1])
                    except Exception:
                        # Игнорируем ошибки удаления (сообщение могло быть уже удалено)
                        pass
            except Exception:
                logger.exception('handle_add_step: failed to delete previous prompt')

            await self.ask_step(update, context, step)
        else:
            # Все поля собраны, добавляем запись
            from db.database import Database
            db = Database()
            try:
                # Перед сохранением удалим последний prompt (например, "Введите Пол:"),
                # чтобы он не оставался в чате после завершения заполнения.
                try:
                    prev = context.user_data.pop('add_record_prompt_message', None)
                    if prev and isinstance(prev, (list, tuple)) and len(prev) >= 2:
                        try:
                            await context.bot.delete_message(chat_id=prev[0], message_id=prev[1])
                        except Exception:
                            pass
                except Exception:
                    logger.exception('handle_add_step: failed to delete final prompt')

                with db.get_cursor() as cursor:
                    fields_str = ', '.join(self.db_fields)
                    placeholders = ', '.join(['?'] * len(self.db_fields))
                    values = [data.get(f, '') for f in self.db_fields]
                    cursor.execute(f'INSERT INTO members ({fields_str}) VALUES ({placeholders})', values)
                    # Получим id только что вставленной записи
                    try:
                        inserted_id = cursor.lastrowid
                    except Exception:
                        inserted_id = None

                # Показываем пользователю, что сохранено
                # Выводим данные новой записи под заголовком MEMBER_DETAILS_HEADER
                msg = MESSAGES_ADMIN.MEMBER_DETAILS_HEADER + '\n'
                for i, field in enumerate(self.fields):
                    msg += f"{field}: {data.get(self.db_fields[i], '')}\n"
                try:
                    sent = await send_and_track(context, update.message, msg)
                except Exception:
                    try:
                        sent = await update.message.reply_text(msg)
                    except Exception:
                        sent = None
                # Сохраним id сообщения с деталями для возможного удаления
                try:
                    if sent and getattr(sent, 'chat', None):
                        context.user_data['workdb_member_details_message'] = (sent.chat.id, sent.message_id)
                except Exception:
                    pass

                # Отправим сообщение с кнопками действий (Редактировать, Удалить, Назад, Выход)
                try:
                    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(MESSAGES_ADMIN.BTN_EDIT, callback_data=f'workdb:detail:edit:{inserted_id}')],
                        [InlineKeyboardButton(MESSAGES_ADMIN.BTN_DELETE, callback_data=f'workdb:detail:delete:{inserted_id}')],
                        [InlineKeyboardButton(MESSAGES_ADMIN.BTN_BACK, callback_data=f'workdb:detail:back:{inserted_id}'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_EXIT, callback_data=f'workdb:detail:exit')]
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

                # Сохраним состояние — id новой записи и флаг ожидания действия
                try:
                    if inserted_id is not None:
                        context.user_data['member_details_id'] = inserted_id
                        context.user_data['awaiting_member_details_action'] = True
                except Exception:
                    pass
                # Удалим заголовок карточки, если он остался
                try:
                    hdr = context.user_data.pop('add_record_header_message', None)
                    if hdr and isinstance(hdr, (list, tuple)) and len(hdr) >= 2:
                        try:
                            await context.bot.delete_message(chat_id=hdr[0], message_id=hdr[1])
                        except Exception:
                            pass
                except Exception:
                    pass
                # Никаких дополнительных приглашений не отправляем — запись создана и данные выведены.
                context.user_data['add_record_continue_or_exit'] = True
            except Exception as e:
                await update.message.reply_text(f'Ошибка при добавлении: {e}')
            context.user_data['add_record_in_progress'] = False
            context.user_data['add_record_step'] = 0
            context.user_data['add_record_data'] = {}

    async def handle_continue_or_exit(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            # Продолжить добавление — начать заново
            await self.start_add(update, context)
            context.user_data['add_record_continue_or_exit'] = False
        elif text == '2':
            # Выход — вернуться к меню администратора
            # Удалим заголовок карточки, если он остался
            try:
                hdr = context.user_data.pop('add_record_header_message', None)
                if hdr and isinstance(hdr, (list, tuple)) and len(hdr) >= 2:
                    try:
                        await context.bot.delete_message(chat_id=hdr[0], message_id=hdr[1])
                    except Exception:
                        pass
            except Exception:
                pass
            await update.message.reply_text(MESSAGES_ADMIN.ADMIN_MAIN_MENU)
            context.user_data['add_record_continue_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text(MESSAGES_ADMIN.ENTER_1_OR_2)

    async def process_state(self, update, context):
        """
        Универсальная обработка состояний для AddRecord.
        Возвращает True, если модуль обработал текущее сообщение.
        """
        if context.user_data.get('add_record_in_progress'):
            await self.handle_add_step(update, context)
            return True
        if context.user_data.get('add_record_continue_or_exit'):
            await self.handle_continue_or_exit(update, context)
            return True
        return False
