from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
import asyncio
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters
import settings
import logging
from db.models import User


async def _delete_message_later(bot, chat_id: int, message_id: int, delay_seconds: int = 10):
    """Удалить сообщение через delay_seconds (тихий, безопасный фоновой таск)."""
    try:
        await asyncio.sleep(delay_seconds)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logging.debug('Не удалось удалить временное сообщение (возможно уже удалено)')
    except Exception:
        logging.exception('Ошибка в фоне при плановом удалении сообщения')


async def get_user_id_message(update, context):
    user_id = update.message.from_user.id
    await update.message.reply_text(f"Ваш уникальный идентификатор Telegram: {user_id}")

logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def start_command(update, context):
    # Ответ на команду /start с кнопками
    # Клавиатура (используется, когда нужно показать пользователю), но по умолчанию скрыта
    keyboard = [["Новости", "Фото"], ["Видео", "Контакты"], ["Справка", "ДП"]]
    # Inline-клавиатура приветствия: сначала кнопка "Меню бота", затем "Справка"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton('Меню бота', callback_data='menu:show'), InlineKeyboardButton('Справка', callback_data='help:show')]])
    # Используем message из Update (если есть)
    msg_obj = update.message if getattr(update, 'message', None) else (update.callback_query.message if getattr(update, 'callback_query', None) else None)
    greeting_text = "Добро пожаловать! Я бот Анжеро-Судженской МО ВОС. Чем могу помочь?"
    if msg_obj is not None:
        await msg_obj.reply_text(greeting_text, reply_markup=kb)
    else:
        # fallback: отправка через bot.send_message, если можно определить чат
        chat_id = update.effective_chat.id if getattr(update, 'effective_chat', None) else None
        if chat_id:
            sent = await context.bot.send_message(chat_id=chat_id, text=greeting_text, reply_markup=kb)
            # Сохраним отправленное приветствие в chat_data, чтобы другие модули (control_room) могли его сохранить/соблюдать
            try:
                lst = context.chat_data.get('control_room_sent_messages', [])
                lst.append({'chat_id': sent.chat.id, 'message_id': sent.message_id, 'text': greeting_text})
                context.chat_data['control_room_sent_messages'] = lst
            except Exception:
                logging.exception('Не удалось сохранить приветствие в chat_data')

async def greet_user(update, context):
    # Ответ на приветствие
    await update.message.reply_text("Здравствуйте! Вас приветствует бот Анжеро-Судженской МО ВОС!")

async def help_message(update, context):
    # Ответ на сообщение "справка"
    await update.message.reply_text("Справка: Этот бот может отвечать на команды и сообщения, такие как 'привет' и 'справка'.")


async def help_callback(update, context):
    # Обработчик для inline-кнопки Справка / Закрыть справку
    query = update.callback_query
    data = getattr(query, 'data', '')
    logging.info(f"admin_callback received callback data: {data!r} from user_id={getattr(query.from_user,'id',None)}")
    try:
        await query.answer()
    except Exception:
        pass

    origin = query.message
    # Текст справки
    help_text = "Справка: Этот бот может отвечать на команды и сообщения, такие как 'привет' и 'справка'."

    # Если уже есть ранее отправленная справка — удалим её перед отправкой новой
    prev = context.user_data.get('control_help_message')
    if prev and data == 'help:show':
        try:
            await context.bot.delete_message(chat_id=prev[0], message_id=prev[1])
        except Exception:
            pass
        context.user_data.pop('control_help_message', None)

    if data == 'help:show':
        # Отправляем сообщение со справкой и кнопку "Закрыть справку"
        try:
            kb_help = InlineKeyboardMarkup([[InlineKeyboardButton('Закрыть справку', callback_data='help:close')]])
            sent = await origin.reply_text(help_text, reply_markup=kb_help)
            # Сохраним sent message id для последующего удаления
            if getattr(sent, 'chat', None):
                context.user_data['control_help_message'] = (sent.chat.id, sent.message_id)
        except Exception:
            logging.exception('Не удалось отправить справку по callback')
        # Изменим клавиатуру на исходном сообщении — заменим кнопку на "Закрыть справку"
        try:
            kb_toggle = InlineKeyboardMarkup([[InlineKeyboardButton('Закрыть справку', callback_data='help:close')]])
            await origin.edit_reply_markup(reply_markup=kb_toggle)
        except Exception:
            # редактирование может быть недоступно — игнорируем
            logging.debug('Не удалось изменить клавиатуру исходного сообщения (help:show)')
        return


async def menu_callback(update, context):
    # Обработчик для inline-кнопки Меню бота / Закрыть меню
    query = update.callback_query
    data = getattr(query, 'data', '')
    try:
        await query.answer()
    except Exception:
        pass

    origin = query.message
    # Основная клавиатура (ReplyKeyboard)
    keyboard = [["Новости", "Фото"], ["Видео", "Контакты"], ["Справка", "ДП"]]
    if data == 'menu:show':
        try:
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            sent = await origin.reply_text('Главное меню:', reply_markup=reply_markup)
            # Сохраним sent message id, чтобы при закрытии можно было удалить/очистить
            if getattr(sent, 'chat', None):
                context.user_data['control_menu_message'] = (sent.chat.id, sent.message_id)
        except Exception:
            logging.exception('Не удалось отправить главное меню по callback')
        # Изменим клавиатуру на исходном сообщении — заменим кнопку на "Закрыть меню"
        try:
            kb_toggle = InlineKeyboardMarkup([[InlineKeyboardButton('Закрыть меню', callback_data='menu:close'), InlineKeyboardButton('Справка', callback_data='help:show')]])
            await origin.edit_reply_markup(reply_markup=kb_toggle)
        except Exception:
            logging.debug('Не удалось изменить клавиатуру исходного сообщения (menu:show)')
        return

    if data == 'menu:close':
        # Удалим ранее отправленное сообщение с меню, если оно было отправлено
        stored = context.user_data.pop('control_menu_message', None)
        if stored:
            try:
                await context.bot.delete_message(chat_id=stored[0], message_id=stored[1])
            except Exception:
                # В любом случае отправим ReplyKeyboardRemove, чтобы убрать клавиатуру
                pass
        # Отправим команду снять клавиатуру — сообщение временное, удалим через 10 секунд
        try:
            sent_close = await origin.reply_text('Меню закрыто', reply_markup=ReplyKeyboardRemove())
            # Удалим уведомление через 10 секунд (fire-and-forget задача)
            try:
                bot = getattr(context, 'bot', None)
                if bot and getattr(sent_close, 'chat', None):
                    asyncio.create_task(_delete_message_later(bot, sent_close.chat.id, sent_close.message_id, 10))
            except Exception:
                logging.exception('Не удалось запланировать удаление сообщения "Меню закрыто"')
        except Exception:
            logging.debug('Не удалось отправить сообщение с удалением ReplyKeyboard')
        # Восстановим inline-кнопку на исходном сообщении обратно на 'Меню бота'
        try:
            kb_restore = InlineKeyboardMarkup([[InlineKeyboardButton('Меню бота', callback_data='menu:show'), InlineKeyboardButton('Справка', callback_data='help:show')]])
            await origin.edit_reply_markup(reply_markup=kb_restore)
        except Exception:
            logging.debug('Не удалось восстановить клавиатуру исходного сообщения (menu:close)')
        return

    if data == 'help:close':
        # удалить ранее отправленную справку (если есть)
        stored = context.user_data.pop('control_help_message', None)
        if stored:
            try:
                await context.bot.delete_message(chat_id=stored[0], message_id=stored[1])
            except Exception:
                logging.debug('Не удалось удалить сообщение со справкой')
        # Восстановим кнопку на исходном сообщении обратно на 'Справка'
        try:
            kb_restore = InlineKeyboardMarkup([[InlineKeyboardButton('Справка', callback_data='help:show')]])
            await origin.edit_reply_markup(reply_markup=kb_restore)
        except Exception:
            logging.debug('Не удалось восстановить клавиатуру исходного сообщения (help:close)')
        return


async def show_menu_command(update, context):
    # Показать главное меню (ReplyKeyboardMarkup)
    keyboard = [["Новости", "Фото"], ["Видео", "Контакты"], ["Справка", "ДП"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text('Главное меню:', reply_markup=reply_markup)

async def contact_message(update, context):
    # Ответ на сообщение "контакты"
    await update.message.reply_text("Контакты: Вы можете связаться с нами по телефону +7 (38453) 6-18-85 или email amvos42@gmail.com.")

async def admin_message(update, context):
    # Проверка роли пользователя через VerificationID
    from verification_id import VerificationID
    verifier = VerificationID()
    USER_ROLE = await verifier.check_role(update, context)
    if USER_ROLE in ("admin", "super admin"):
        # Удаляем ранее отправленные служебные/админ-сообщения перед выводом нового меню,
        # кроме приветственного сообщения "Добро пожаловать...".
        try:
            # список возможных ключей где хранятся message ids
            keys = ['control_menu_message', 'control_help_message', 'workdb_entries_message', 'workdb_pages_message']
            # собираем id приветственных сообщений, чтобы их не удалять
            greeting_ids = set()
            try:
                for item in context.chat_data.get('control_room_sent_messages', []):
                    # item может быть dict {'chat_id':..., 'message_id':..., 'text':...}
                    if isinstance(item, dict) and item.get('text', '').startswith('Добро пожаловать'):
                        greeting_ids.add(item.get('message_id'))
            except Exception:
                pass
            for k in keys:
                val = context.user_data.get(k)
                if not val:
                    continue
                try:
                    # val может быть tuple (chat_id, message_id) or list/tuple
                    if isinstance(val, (list, tuple)) and len(val) >= 2:
                        cid, mid = val[0], val[1]
                        if mid in greeting_ids:
                            continue
                        try:
                            await context.bot.delete_message(chat_id=cid, message_id=mid)
                        except Exception:
                            # игнорируем ошибки удаления
                            pass
                    # удалим ключы из user_data
                    context.user_data.pop(k, None)
                except Exception:
                    try:
                        logging.exception('Failed to cleanup admin message %s', k)
                    except Exception:
                        pass
        except Exception:
            try:
                logging.exception('Error while cleaning previous admin messages')
            except Exception:
                pass
        # Отправляем сообщение и Inline-клавиатуру с действиями (кнопки отправляют callback_data 'admin:1'..'admin:6')
        try:
            sent_header = await update.message.reply_text("Режим администратора: доступ разрешён.")
            # Сохраним id заголовочного сообщения админа, чтобы его можно было удалять при показе списков
            if getattr(sent_header, 'chat', None):
                context.user_data['admin_header_message'] = (sent_header.chat.id, sent_header.message_id)
        except Exception:
            logging.exception('Не удалось отправить заголовок режима администратора')
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('1. Показать весь список', callback_data='admin:1')],
            [InlineKeyboardButton('2. Найти по фамилии', callback_data='admin:2')],
            [InlineKeyboardButton('3. Редактировать запись', callback_data='admin:3')],
            [InlineKeyboardButton('4. Добавить запись', callback_data='admin:4')],
            [InlineKeyboardButton('5. Удалить запись', callback_data='admin:5')],
            [InlineKeyboardButton('6. Сортировка и фильтр', callback_data='admin:6')]
        ])
        try:
            sent_menu = await update.message.reply_text('Выберите действие:', reply_markup=kb)
            if getattr(sent_menu, 'chat', None):
                context.user_data['admin_menu_message'] = (sent_menu.chat.id, sent_menu.message_id)
        except Exception:
            logging.exception('Не удалось отправить меню администратора')
        context.user_data['admin_mode'] = True
    else:
        await update.message.reply_text("Эта команда вам не доступна. Обратитесь к администратору бота.")
        context.user_data['admin_mode'] = False

async def admin_action_handler(update, context):
    """
    Обработчик выбора действия админа
    """
    from db.sort_and_filtr import SortAndFiltr
    sortfiltr = SortAndFiltr()
    try:
        logging.info(f"admin_action_handler entered; message_text={(update.message.text if getattr(update, 'message', None) else None)!r}; admin_mode={context.user_data.get('admin_mode')}")
    except Exception:
        logging.exception('admin_action_handler: error logging entry state')

    # --- Делегируем обработку состояния ControlRoom ---
    from control_room.control_room import ControlRoom
    control = ControlRoom()
    processed = await control.process_state(update, context)
    if processed:
        return
    # --- Делегируем обработку состояний SortAndFiltr в модуль sort_and_filtr.py ---
    processed = await sortfiltr.process_state(update, context)
    if processed:
        return
    from db.search_records import SearchRecords
    search_records = SearchRecords()
    # --- Делегируем обработку состояний SearchRecords ---
    processed = await search_records.process_state(update, context)
    if processed:
        return
    # Обработчик выбора действия админа
    if not context.user_data.get('admin_mode'):
        return
    from db.work_db import WorkDB
    from db.edit_db import EditDB
    from db.add_record import AddRecord
    from db.del_record import DelRecord
    work_db = WorkDB()
    edit_db = EditDB()
    add_record = AddRecord()
    del_record = DelRecord()
    # --- Делегируем обработку состояний DelRecord ---
    processed = await del_record.process_state(update, context)
    if processed:
        return
    # --- Делегируем обработку состояний EditDB ---
    processed = await edit_db.process_state(update, context)
    if processed:
        return
    if context.user_data.get('awaiting_surname'):
        context.user_data['awaiting_surname'] = False
        await work_db.search_by_second_field(update, context)
        return
    # --- Делегируем обработку состояний AddRecord ---
    processed = await add_record.process_state(update, context)
    if processed:
        return
    else:
        # Если выбрано "2" — запуск поиска через SearchRecords
        if update.message.text.strip() == '2':
            await search_records.start_search(update, context)
        # Если выбрано "6" — запуск сортировки и фильтра
        elif update.message.text.strip() == '6':
            await sortfiltr.start(update, context)
        # Прямой вход в диспетчерскую теперь обрабатывается отдельным handler'ом (control_entry)
        else:
                await work_db.handle_admin_action(update, context)

async def admin_callback(update, context):
    """
    Конвертируем CallbackQuery от inline-кнопок администратора (admin:1..6)
    в поведение эквивалентного текстового сообщения и вызываем
    `admin_action_handler` для дальнейшей обработки.
    """
    query = update.callback_query
    data = getattr(query, 'data', '')
    try:
        await query.answer()
    except Exception:
        pass

    # формат данных: admin:<num>
    parts = data.split(':')
    if len(parts) < 2:
        return
    choice = parts[1]

    # Попытаться подготовить дополнительные данные для downstream-кода.
    # Не присваиваем `update.message`, т.к. Update запрещает динамическое
    # добавление атрибутов в этой версии библиотеки (вызывало AttributeError).
    msg = getattr(query, 'message', None)
    if msg:
        try:
            msg.from_user = query.from_user
        except Exception:
            pass
        try:
            msg.text = choice
        except Exception:
            pass

    logging.info(f"admin_callback calling admin_action_handler with choice={choice!r}; has_query_message={bool(msg)}; has_update_message={bool(getattr(update,'message',None))}")

    # Быстрая-path: если нажата кнопка '1' (Показать весь список), вызовем
    # соответствующий метод напрямую. Подстраховываемся — если update.message
    # отсутствует, создаём простой прокси-объект с reply_text, который делегирует
    # на context.bot.send_message.
    if choice == '1':
        try:
            from db.work_db import WorkDB
            work = WorkDB()
            # Просто вызываем метод — внутри есть fallback для случая, когда
            # update.message отсутствует (будет использован context.bot)
            await work.show_sorted_by_surname(update, context)
            return
        except Exception:
            logging.exception('admin_callback: direct call to WorkDB.show_sorted_by_surname failed')
            # Падение — уведомим пользователя коротким сообщением и выйдем
            try:
                chat_id = msg.chat.id if msg and getattr(msg, 'chat', None) else getattr(query.from_user, 'id', None)
                if chat_id:
                    await context.bot.send_message(chat_id=chat_id, text='Ошибка при формировании списка. Подробности в логах.')
            except Exception:
                pass
            return

    if choice == '2':
        try:
            from db.search_records import SearchRecords
            sr = SearchRecords()
            # If we have update.message already, call directly
            if getattr(update, 'message', None):
                await sr.start_search(update, context)
            else:
                # Build a minimal fake update with message.reply_text delegating to bot.send_message
                class _ProxyMsg:
                    def __init__(self, chat_id, bot):
                        self.chat = type('C', (), {'id': chat_id})
                        self._bot = bot
                    async def reply_text(self, text):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text)
                class _FakeUpdate:
                    pass
                chat_id = query.message.chat.id if getattr(query, 'message', None) and getattr(query.message, 'chat', None) else getattr(query.from_user, 'id', None)
                fake = _FakeUpdate()
                fake.message = _ProxyMsg(chat_id, context.bot)
                fake.callback_query = query
                fake.effective_user = query.from_user
                await sr.start_search(fake, context)
            return
        except Exception:
            logging.exception('admin_callback: direct call to SearchRecords.start_search failed')
            try:
                chat_id = msg.chat.id if msg and getattr(msg, 'chat', None) else getattr(query.from_user, 'id', None)
                if chat_id:
                    await context.bot.send_message(chat_id=chat_id, text='Ошибка при запуске поиска. Подробности в логах.')
            except Exception:
                pass
            return

    # Быстрые пути для других admin-кнопок (3..6)
    if choice == '3':
        try:
            # EditDB: запрос фамилии и запуск режима редактирования
            from db.edit_db import EditDB
            ed = EditDB()
            if getattr(update, 'message', None):
                await ed.search_and_show_fields(update, context)
            else:
                # Построим минимальный fake update, как в case '2'
                class _ProxyMsg:
                    def __init__(self, chat_id, bot):
                        self.chat = type('C', (), {'id': chat_id})
                        self._bot = bot
                    async def reply_text(self, text):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text)
                class _FakeUpdate:
                    pass
                chat_id = query.message.chat.id if getattr(query, 'message', None) and getattr(query.message, 'chat', None) else getattr(query.from_user, 'id', None)
                fake = _FakeUpdate()
                fake.message = _ProxyMsg(chat_id, context.bot)
                fake.callback_query = query
                fake.effective_user = query.from_user
                await ed.search_and_show_fields(fake, context)
            return
        except Exception:
            logging.exception('admin_callback: direct call to EditDB.search_and_show_fields failed')
            try:
                chat_id = msg.chat.id if msg and getattr(msg, 'chat', None) else getattr(query.from_user, 'id', None)
                if chat_id:
                    await context.bot.send_message(chat_id=chat_id, text='Ошибка при запуске режима редактирования. Подробности в логах.')
            except Exception:
                pass
            return

    if choice == '4':
        try:
            from db.add_record import AddRecord
            ar = AddRecord()
            if getattr(update, 'message', None):
                await ar.start_add(update, context)
            else:
                class _ProxyMsg:
                    def __init__(self, chat_id, bot):
                        self.chat = type('C', (), {'id': chat_id})
                        self._bot = bot
                    async def reply_text(self, text):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text)
                class _FakeUpdate:
                    pass
                chat_id = query.message.chat.id if getattr(query, 'message', None) and getattr(query.message, 'chat', None) else getattr(query.from_user, 'id', None)
                fake = _FakeUpdate()
                fake.message = _ProxyMsg(chat_id, context.bot)
                fake.callback_query = query
                fake.effective_user = query.from_user
                await ar.start_add(fake, context)
            return
        except Exception:
            logging.exception('admin_callback: direct call to AddRecord.start_add failed')
            try:
                chat_id = msg.chat.id if msg and getattr(msg, 'chat', None) else getattr(query.from_user, 'id', None)
                if chat_id:
                    await context.bot.send_message(chat_id=chat_id, text='Ошибка при запуске добавления записи. Подробности в логах.')
            except Exception:
                pass
            return

    if choice == '5':
        try:
            from db.del_record import DelRecord
            dr = DelRecord()
            if getattr(update, 'message', None):
                await dr.start_delete(update, context)
            else:
                class _ProxyMsg:
                    def __init__(self, chat_id, bot):
                        self.chat = type('C', (), {'id': chat_id})
                        self._bot = bot
                    async def reply_text(self, text):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text)
                class _FakeUpdate:
                    pass
                chat_id = query.message.chat.id if getattr(query, 'message', None) and getattr(query.message, 'chat', None) else getattr(query.from_user, 'id', None)
                fake = _FakeUpdate()
                fake.message = _ProxyMsg(chat_id, context.bot)
                fake.callback_query = query
                fake.effective_user = query.from_user
                await dr.start_delete(fake, context)
            return
        except Exception:
            logging.exception('admin_callback: direct call to DelRecord.start_delete failed')
            try:
                chat_id = msg.chat.id if msg and getattr(msg, 'chat', None) else getattr(query.from_user, 'id', None)
                if chat_id:
                    await context.bot.send_message(chat_id=chat_id, text='Ошибка при запуске удаления записи. Подробности в логах.')
            except Exception:
                pass
            return

    if choice == '6':
        try:
            # SortAndFiltr.start
            from db.sort_and_filtr import SortAndFiltr
            sf = SortAndFiltr()
            if getattr(update, 'message', None):
                await sf.start(update, context)
            else:
                class _ProxyMsg:
                    def __init__(self, chat_id, bot):
                        self.chat = type('C', (), {'id': chat_id})
                        self._bot = bot
                    async def reply_text(self, text):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text)
                class _FakeUpdate:
                    pass
                chat_id = query.message.chat.id if getattr(query, 'message', None) and getattr(query.message, 'chat', None) else getattr(query.from_user, 'id', None)
                fake = _FakeUpdate()
                fake.message = _ProxyMsg(chat_id, context.bot)
                fake.callback_query = query
                fake.effective_user = query.from_user
                await sf.start(fake, context)
            return
        except Exception:
            logging.exception('admin_callback: direct call to SortAndFiltr.start failed')
            try:
                chat_id = msg.chat.id if msg and getattr(msg, 'chat', None) else getattr(query.from_user, 'id', None)
                if chat_id:
                    await context.bot.send_message(chat_id=chat_id, text='Ошибка при запуске сортировки/фильтра. Подробности в логах.')
            except Exception:
                pass
            return

    # Fallback: вызвать общий обработчик (имитируем текстовое сообщение)
    try:
        # If original Update has no message (CallbackQuery case), create a lightweight
        # proxy message that contains `.text` equal to the chosen menu number and
        # a `.reply_text` that delegates to bot.send_message. This avoids mutating
        # the real Update/Message objects (which may raise AttributeError) and
        # ensures downstream handlers that access `update.message.text` work.
        if not getattr(update, 'message', None):
            class _ProxyMsg:
                def __init__(self, chat_id, bot, text, from_user):
                    self.chat = type('C', (), {'id': chat_id})
                    self._bot = bot
                    self.text = text
                    self.from_user = from_user
                async def reply_text(self, text, **kwargs):
                    return await self._bot.send_message(chat_id=self.chat.id, text=text, **kwargs)
            class _FakeUpdate:
                pass
            chat_id = query.message.chat.id if getattr(query, 'message', None) and getattr(query.message, 'chat', None) else getattr(query.from_user, 'id', None)
            fake = _FakeUpdate()
            fake.message = _ProxyMsg(chat_id, context.bot, choice, query.from_user)
            fake.callback_query = query
            fake.effective_user = query.from_user
            await admin_action_handler(fake, context)
        else:
            await admin_action_handler(update, context)
    except Exception:
        logging.exception('admin_callback: admin_action_handler failed')
        try:
            chat_id = msg.chat.id if msg and getattr(msg, 'chat', None) else getattr(query.from_user, 'id', None)
            if chat_id:
                await context.bot.send_message(chat_id=chat_id, text='Ошибка при обработке действия администратора. Подробности в логах.')
        except Exception:
            pass
    return
    


async def control_entry(update, context):
    """Обработчик, который позволяет пользователю сразу набрать 'диспетчерская' и попасть в диспетчерскую после проверки роли."""
    from control_room.control_room import ControlRoom
    control = ControlRoom()
    await control.start(update, context)

async def news_message(update, context):
    await update.message.reply_text("Новости: Здесь будут последние новости организации.")

async def photo_message(update, context):
    await update.message.reply_text("Фото: Здесь будут опубликованы фотографии мероприятий.")

async def video_message(update, context):
    await update.message.reply_text("Видео: Здесь будут опубликованы видеоматериалы.")

async def number_message(update, context):
    number = update.message.text.strip()
    await update.message.reply_text(f"Вы нажали кнопку: {number}")

def main():
    # Создаем экземпляр приложения
    application = Application.builder().token(settings.API_KEY).build()

    # Добавляем обработчик команды /start
    application.add_handler(CommandHandler("start", start_command))

    # Добавляем обработчик сообщений с фильтром на текст "привет"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)привет'), greet_user))

    # Добавляем обработчик сообщений с фильтром на текст "справка"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)справка'), help_message))

    # Добавляем обработчик сообщений с фильтром на текст "контакты"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)контакты'), contact_message))

    # Добавляем обработчик сообщений с фильтром на текст "админ"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)админ'), admin_message))
    # Добавляем обработчик для быстрого доступа в диспетчерскую по слову 'диспетчерская'
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)^\s*диспетчерская\s*$'), control_entry))
    # Добавляем обработчик для кнопки 'ДП' (аналогично слову 'диспетчерская')
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)^\s*дп\s*$'), control_entry))
    # Команда и кнопка для показа главного меню
    application.add_handler(CommandHandler('menu', show_menu_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)^\s*меню\s*$'), show_menu_command))
    # Добавляем обработчик для получения идентификатора пользователя
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)получить идентификатор'), get_user_id_message))
    # Добавляем обработчик для выбора действия админа
    application.add_handler(MessageHandler(filters.TEXT & (~filters.Regex(r'(?i)админ')), admin_action_handler))
    # CallbackQuery для inline-кнопок (фильтрация / пагинация)
    from db.sort_and_filtr import SortAndFiltr
    sortfiltr = SortAndFiltr()
    # CallbackQuery для sort_and_filtr — фильтровать только callback'ы, начинающиеся с 'sortfiltr:'
    application.add_handler(CallbackQueryHandler(sortfiltr.handle_callback, pattern=r'^sortfiltr:'))
    # CallbackQuery для диспетчерской (InlineKeyboard) — фильтровать только 'control:'
    from control_room.control_room import ControlRoom
    control = ControlRoom()
    application.add_handler(CallbackQueryHandler(control.handle_callback, pattern=r'^control:'))
    # CallbackQuery для inline-кнопок администратора (admin:1..6)
    application.add_handler(CallbackQueryHandler(admin_callback, pattern=r'^admin:'))
    # CallbackQuery для inline-кнопки Справка (show/close)
    application.add_handler(CallbackQueryHandler(help_callback, pattern=r'^help:'))
    # CallbackQuery для inline-кнопки Меню бота (show/close)
    application.add_handler(CallbackQueryHandler(menu_callback, pattern=r'^menu:'))
    # Обработчик для сообщения '?' чтобы показать справку
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)^\s*\?\s*$'), help_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)новости'), news_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)фото'), photo_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)видео'), video_message))
    # Цифровой ряд больше не используется — обработчики удалены
    # workdb callbacks (list pages, member selection, exit)
    from db.work_db import WorkDB
    workdb = WorkDB()
    application.add_handler(CallbackQueryHandler(workdb.handle_callback, pattern=r'^workdb:'))

    logging.info("Бот стартовал")

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
