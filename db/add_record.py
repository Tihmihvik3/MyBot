import logging
from utils.admin_messenger import send_and_track, delete_tracked_messages

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
                    sent_header = await update.message.reply_text('Заполнение карточки члена ВОС:')
                    try:
                        context.user_data['add_record_header_message'] = (sent_header.chat.id, sent_header.message_id)
                    except Exception:
                        pass
                else:
                    # fallback
                    uid = getattr(update.callback_query.from_user, 'id', None) if getattr(update, 'callback_query', None) else None
                    if uid:
                        sent_header = await context.bot.send_message(chat_id=uid, text='Заполнение карточки члена ВОС:')
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
                await update.message.reply_text('Введите Фамилию:')
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
            row.append(InlineKeyboardButton('Назад', callback_data='workdb:add:back'))
        row.append(InlineKeyboardButton('Отмена', callback_data='workdb:add:cancel'))
        buttons.append(row)
        return InlineKeyboardMarkup(buttons)

    async def ask_step(self, update, context, step: int):
        """Отправить (или отредактировать) приглашение для текущего шага добавления."""
        text = f'Введите {self.fields[step]}:'
        kb = self._build_kb(step)
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
            # удалим предыдущий prompt, если есть
            try:
                prev = context.user_data.pop('add_record_prompt_message', None)
                if prev and isinstance(prev, (list, tuple)) and len(prev) >= 2:
                    try:
                        await context.bot.delete_message(chat_id=prev[0], message_id=prev[1])
                    except Exception:
                        pass
            except Exception:
                pass
            await self.ask_step(update, context, step)
        else:
            # Все поля собраны, добавляем запись
            from db.database import Database
            db = Database()
            try:
                with db.get_cursor() as cursor:
                    fields_str = ', '.join(self.db_fields)
                    placeholders = ', '.join(['?'] * len(self.db_fields))
                    values = [data.get(f, '') for f in self.db_fields]
                    cursor.execute(f'INSERT INTO members ({fields_str}) VALUES ({placeholders})', values)
                # Показываем пользователю, что сохранено
                msg = 'Запись успешно добавлена!\nСохранённые данные:\n'
                for i, field in enumerate(self.fields):
                    msg += f"{field}: {data.get(self.db_fields[i], '')}\n"
                try:
                    await send_and_track(context, update.message, msg)
                except Exception:
                    await update.message.reply_text(msg)
                # Предложить продолжить или выйти
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
                try:
                    await send_and_track(context, update.message, 'Выберите действие:\n1. Продолжить добавление записей\n2. Выход')
                except Exception:
                    await update.message.reply_text('Выберите действие:\n1. Продолжить добавление записей\n2. Выход')
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
            await update.message.reply_text('Выберите действие администратора:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\nВведите номер действия:')
            context.user_data['add_record_continue_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text('Введите 1 (продолжить) или 2 (выход).')

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
