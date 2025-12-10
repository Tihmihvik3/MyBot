from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
import asyncio
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters
import settings
import logging
from db.models import User
import messages_admin as MESSAGES_ADMIN
import secrets

from db import notifications as notifications
from utils.admin_messenger import clear_tracked_before


def _clear_interaction_state(context):
    """Очистить пользовательские флаги/состояния, чтобы перейти в чистый режим (admin/control)."""
    try:
        # ключи/префиксы, которые обычно используются для хранения состояний
        prefixes = (
            'control_room_', 'searchrecords_', 'editdb_', 'workdb_', 'add_record', 'delrec_',
            'awaiting_', 'member_details_id', 'admin_menu_message', 'admin_header_message',
            'admin_sent_messages', 'control_menu_message', 'control_help_message', 'workdb_entries_message',
            'workdb_pages_message', 'workdb_member_details_message', 'workdb_member_actions_message',
            'editdb_menu_message', 'editdb_input_prompt_message'
        )
        for k in list(getattr(context, 'user_data', {}).keys()):
            try:
                for p in prefixes:
                    if isinstance(k, str) and (k == p or k.startswith(p)):
                        context.user_data.pop(k, None)
                        break
            except Exception:
                pass
        # очистим control_room_sent_messages в chat_data, если есть
        try:
            if hasattr(context, 'chat_data') and isinstance(context.chat_data, dict):
                for k in list(context.chat_data.keys()):
                    if isinstance(k, str) and k.startswith('control_room_'):
                        context.chat_data.pop(k, None)
        except Exception:
            pass
    except Exception:
        try:
            logging.exception('Failed to clear interaction state')
        except Exception:
            pass


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

# Configure root logger with explicit FileHandler using UTF-8 encoding so
# Cyrillic in logs is preserved on Windows and other platforms.
root_logger = logging.getLogger()
if not root_logger.handlers:
    root_logger.setLevel(logging.INFO)
    fh = logging.FileHandler('bot.log', encoding='utf-8')
    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(fmt)
    root_logger.addHandler(fh)

# Диагностический лог при загрузке модуля bot.py — поможет понять, какой файл реально загружен в процессе
try:
    logging.info(f"bot module loaded from {__file__}")
except Exception:
    try:
        logging.exception('bot: failed to log module path on load')
    except Exception:
        pass

@clear_tracked_before
async def start_command(update, context):
    # Ответ на команду /start с кнопками
    # Клавиатура (используется, когда нужно показать пользователю), но по умолчанию скрыта
    keyboard = [["Новости", "Фото"], ["Видео", "Контакты"], ["Справка", "ДП"]]
    # Inline-клавиатура приветствия: кнопка вызова Reply-клавиатуры (Menu), Справка
    # и дополнительная кнопка-открывашка для выпадающего inline-меню (dropdown).
    # Показывать кнопку-открывашку "Меню ▾" только для super_admin
    try:
        from verification_id import VerificationID
        verifier = VerificationID()
        try:
            role = await verifier.check_role(update, context)
        except Exception:
            role = None
    except Exception:
        role = None
    rows = [[InlineKeyboardButton(MESSAGES_ADMIN.BTN_MENU, callback_data='menu:show'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_HELP, callback_data='help:show')]]
    if role == 'super_admin':
        rows.append([InlineKeyboardButton(MESSAGES_ADMIN.BTN_MENU_TOGGLE, callback_data='dropdown:toggle')])
    kb = InlineKeyboardMarkup(rows)
    # Используем message из Update (если есть)
    msg_obj = update.message if getattr(update, 'message', None) else (update.callback_query.message if getattr(update, 'callback_query', None) else None)
    greeting_text = "Добро пожаловать! Я бот Анжеро-Судженской МО ВОС. Чем могу помочь?"
    if msg_obj is not None:
        # Перед отправкой проверим, не занесён ли пользователь в блок-лист
        try:
            user_id = update.message.from_user.id if getattr(update, 'message', None) and getattr(update.message, 'from_user', None) else (getattr(update.callback_query, 'from_user', None).id if getattr(update, 'callback_query', None) and getattr(update.callback_query_from_user, 'id', None) else None)
        except Exception:
            # Fallback safe attempt
            try:
                user_id = update.effective_user.id if getattr(update, 'effective_user', None) else None
            except Exception:
                user_id = None
        try:
            from db.database import Database
            db = Database()
            with db.get_cursor() as cursor:
                # Создадим таблицу blocking_user если её нет
                try:
                    cursor.execute('CREATE TABLE IF NOT EXISTS blocking_user (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER UNIQUE)')
                except Exception:
                    pass
                if user_id is not None:
                    cursor.execute('SELECT telegram_id FROM blocking_user WHERE telegram_id = ?', (user_id,))
                    if cursor.fetchone():
                        # Пользователь заблокирован
                        try:
                            await msg_obj.reply_text('Вы заблокированы. Обратитесь к администратору бота.')
                        except Exception:
                            try:
                                await context.bot.send_message(chat_id=user_id, text='Вы заблокированы. Обратитесь к администратору бота.')
                            except Exception:
                                pass
                        context.user_data['blocked'] = True
                        return
        except Exception:
            try:
                logging.exception('start_command: failed to check blocking_user table')
            except Exception:
                pass

        # Проверим роль пользователя — если роль отсутствует или не в списке, предложим регистрацию
        try:
            from verification_id import VerificationID
            verifier = VerificationID()
            role = await verifier.check_role(update, context)
        except Exception:
            role = None

        allowed_roles = ('super_admin', 'admin', 'driver', 'user')
        if role in allowed_roles:
            await msg_obj.reply_text(greeting_text, reply_markup=kb)
        else:
            # Предложим зарегистрироваться
            try:
                # Используем уже импортированные InlineKeyboardButton/InlineKeyboardMarkup
                kb_reg = InlineKeyboardMarkup([[InlineKeyboardButton('Регистрация в боте', callback_data='register:start')]])
                await msg_obj.reply_text('Вам необходимо зарегистрироваться, чтобы продолжить.', reply_markup=kb_reg)
            except Exception:
                await msg_obj.reply_text('Вам необходимо зарегистрироваться, чтобы продолжить. Отправьте команду /register')
        return
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

@clear_tracked_before
async def greet_user(update, context):
    # Ответ на приветствие
    await update.message.reply_text("Здравствуйте! Вас приветствует бот Анжеро-Судженской МО ВОС!")

@clear_tracked_before
async def help_message(update, context):
    # Ответ на сообщение "справка"
    await update.message.reply_text("Справка: Этот бот может отвечать на команды и сообщения, такие как 'привет' и 'справка'.")


@clear_tracked_before
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
            kb_help = InlineKeyboardMarkup([[InlineKeyboardButton(MESSAGES_ADMIN.BTN_CLOSE_HELP, callback_data='help:close')]])
            sent = await origin.reply_text(help_text, reply_markup=kb_help)
            # Сохраним sent message id для последующего удаления
            if getattr(sent, 'chat', None):
                context.user_data['control_help_message'] = (sent.chat.id, sent.message_id)
        except Exception:
            logging.exception('Не удалось отправить справку по callback')
        # Изменим клавиатуру на исходном сообщении — заменим кнопку на "Закрыть справку"
        try:
            kb_toggle = InlineKeyboardMarkup([[InlineKeyboardButton(MESSAGES_ADMIN.BTN_CLOSE_HELP, callback_data='help:close')]])
            await origin.edit_reply_markup(reply_markup=kb_toggle)
        except Exception:
            # редактирование может быть недоступно — игнорируем
            logging.debug('Не удалось изменить клавиатуру исходного сообщения (help:show)')
        return


@clear_tracked_before
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
            kb_toggle = InlineKeyboardMarkup([[InlineKeyboardButton(MESSAGES_ADMIN.BTN_CLOSE_MENU, callback_data='menu:close'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_HELP, callback_data='help:show')]])
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
            kb_restore = InlineKeyboardMarkup([[InlineKeyboardButton(MESSAGES_ADMIN.BTN_MENU, callback_data='menu:show'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_HELP, callback_data='help:show')]])
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
            kb_restore = InlineKeyboardMarkup([[InlineKeyboardButton(MESSAGES_ADMIN.BTN_HELP, callback_data='help:show')]])
            await origin.edit_reply_markup(reply_markup=kb_restore)
        except Exception:
            logging.debug('Не удалось восстановить клавиатуру исходного сообщения (help:close)')
        return


@clear_tracked_before
async def show_menu_command(update, context):
    # Показать главное меню (ReplyKeyboardMarkup)
    keyboard = [["Новости", "Фото"], ["Видео", "Контакты"], ["Справка", "ДП"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text('Главное меню:', reply_markup=reply_markup)

@clear_tracked_before
async def contact_message(update, context):
    # Ответ на сообщение "контакты"
    await update.message.reply_text("Контакты: Вы можете связаться с нами по телефону +7 (38453) 6-18-85 или email amvos42@gmail.com.")


@clear_tracked_before
async def admin_token_cmd(update, context):
    from verification_id import VerificationID
    verifier = VerificationID()
    role = await verifier.check_role(update, context)
    if role != 'super_admin':
        await update.message.reply_text('Доступ запрещён. Только super_admin может выполнять эту команду.')
        return
    token = secrets.token_urlsafe(24)
    try:
        notifications.create_admin_token(token)
    except Exception:
        try:
            notifications.create_admin_token(token)
        except Exception:
            logging.exception('Не удалось сохранить admin token')
    await update.message.reply_text(f'Admin token сгенерирован:\n{token}\nСкопируйте и используйте для входа в панель администратора.')


@clear_tracked_before
async def notify_set_template_cmd(update, context):
    from verification_id import VerificationID
    verifier = VerificationID()
    role = await verifier.check_role(update, context)
    if role != 'super_admin':
        await update.message.reply_text('Доступ запрещён.')
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text('Использование: /notify_set_template <channel> <текст шаблона>')
        return
    name = context.args[0]
    template = ' '.join(context.args[1:])
    try:
        notifications.set_template(name, template)
        await update.message.reply_text(f'Шаблон для канала "{name}" сохранён.')
    except Exception as e:
        logging.exception('notify_set_template failed')
        await update.message.reply_text(f'Ошибка при сохранении шаблона: {e}')


@clear_tracked_before
async def notify_add_target_cmd(update, context):
    from verification_id import VerificationID
    verifier = VerificationID()
    role = await verifier.check_role(update, context)
    if role != 'super_admin':
        await update.message.reply_text('Доступ запрещён.')
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text('Использование: /notify_add_target <channel> <chat_id>')
        return
    name = context.args[0]
    chat_id = context.args[1]
    try:
        ch = notifications.get_channel_by_name(name)
        if not ch:
            ch_id = notifications.ensure_channel(name, template='')
        else:
            ch_id = ch['id']
        notifications.add_target(ch_id, chat_id)
        await update.message.reply_text(f'Добавлен получатель {chat_id} для канала "{name}"')
    except Exception as e:
        logging.exception('notify_add_target failed')
        await update.message.reply_text(f'Ошибка при добавлении получателя: {e}')


@clear_tracked_before
async def notify_list_cmd(update, context):
    from verification_id import VerificationID
    verifier = VerificationID()
    role = await verifier.check_role(update, context)
    if role != 'super_admin':
        await update.message.reply_text('Доступ запрещён.')
        return
    try:
        if not context.args:
            chans = notifications.list_channels()
            if not chans:
                await update.message.reply_text('Каналов уведомлений не настроено.')
                return
            lines = []
            for c in chans:
                lines.append(f"{c['name']} (id={c['id']}) enabled={c['enabled']}")
            await update.message.reply_text('\n'.join(lines))
            return
        name = context.args[0]
        ch = notifications.get_channel_by_name(name)
        if not ch:
            await update.message.reply_text('Канал не найден')
            return
        targets = notifications.list_targets(ch['id'])
        tpl = ch.get('template') or ''
        msg = f"Канал: {name}\nВключён: {ch.get('enabled')}\nШаблон:\n{tpl}\n\nПолучатели:\n"
        if targets:
            msg += '\n'.join(str(t) for t in targets)
        else:
            msg += 'Нет получателей'
        await update.message.reply_text(msg)
    except Exception as e:
        logging.exception('notify_list failed')
        await update.message.reply_text(f'Ошибка: {e}')

@clear_tracked_before
async def admin_message(update, context):
    # Проверка роли пользователя через VerificationID
    from verification_id import VerificationID
    verifier = VerificationID()
    USER_ROLE = await verifier.check_role(update, context)
    # Перед вхождением в админ-режим очищаем все флаги взаимодействия,
    # чтобы режимы не пересекались.
    try:
        _clear_interaction_state(context)
    except Exception:
        try:
            logging.exception('Failed to clear interaction state when entering admin mode')
        except Exception:
            pass

    if USER_ROLE in ("admin", "super_admin"):
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
            sent_header = await update.message.reply_text(MESSAGES_ADMIN.ADMIN_HEADER)
            # Сохраним id заголовочного сообщения админа, чтобы его можно было удалять при показе списков
            if getattr(sent_header, 'chat', None):
                context.user_data['admin_header_message'] = (sent_header.chat.id, sent_header.message_id)
        except Exception:
            logging.exception('Не удалось отправить заголовок режима администратора')
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_ADMIN_OPT1, callback_data='admin:1')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_ADMIN_OPT2, callback_data='admin:2')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_ADMIN_OPT3, callback_data='admin:3')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_ADMIN_OPT4, callback_data='admin:4')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_ADMIN_OPT5, callback_data='admin:5')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_ADMIN_OPT6, callback_data='admin:6')]
        ])
        try:
            sent_menu = await update.message.reply_text(MESSAGES_ADMIN.ADMIN_MENU_PROMPT, reply_markup=kb)
            if getattr(sent_menu, 'chat', None):
                context.user_data['admin_menu_message'] = (sent_menu.chat.id, sent_menu.message_id)
        except Exception:
            logging.exception('Не удалось отправить меню администратора')
        context.user_data['admin_mode'] = True
    else:
        await update.message.reply_text("Эта команда вам не доступна. Обратитесь к администратору бота.")
        context.user_data['admin_mode'] = False

@clear_tracked_before
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

    # Если пользователь в процессе регистрации — обработаем ввод номера членского билета
    try:
        if context.user_data.get('awaiting_registration_ticket'):
            processed = await _handle_registration_ticket(update, context)
            if processed:
                return
    except Exception:
        try:
            logging.exception('admin_action_handler: registration ticket handler failed')
        except Exception:
            pass

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
        # Если пользователь ввёл цифру 1..6 — имитируем нажатие соответствующей inline-кнопки
        text_choice = update.message.text.strip()
        # choice '1' -> показать отсортированный список (WorkDB.show_sorted_by_surname)
        if text_choice == '1':
            try:
                from db.work_db import WorkDB as _WorkDB
                _work = _WorkDB()
                await _work.show_sorted_by_surname(update, context)
            except Exception:
                logging.exception('admin_action_handler: failed to handle textual choice 1')
            return
        # choice '2' -> поиск по фамилии (как в admin_callback: удаляем заголовок/меню перед стартом)
        if text_choice == '2':
            try:
                hdr = context.user_data.pop('admin_header_message', None)
                menu = context.user_data.pop('admin_menu_message', None)
                for msg in (hdr, menu):
                    if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                        try:
                            await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                        except Exception:
                            pass
            except Exception:
                try:
                    logging.exception('admin_action_handler: failed to cleanup admin header/menu before search')
                except Exception:
                    pass
            await search_records.start_search(update, context)
            return
        # choice '3' -> EditDB.search_and_show_fields (admin_callback deletes header/menu first)
        if text_choice == '3':
            try:
                hdr = context.user_data.pop('admin_header_message', None)
                menu = context.user_data.pop('admin_menu_message', None)
                for msg in (hdr, menu):
                    if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                        try:
                            await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                        except Exception:
                            pass
            except Exception:
                try:
                    logging.exception('admin_action_handler: failed to cleanup admin header/menu before edit')
                except Exception:
                    pass
            try:
                ed = EditDB()
                await ed.search_and_show_fields(update, context)
            except Exception:
                logging.exception('admin_action_handler: failed to handle textual choice 3')
            return
        # choice '4' -> AddRecord.start_add
        if text_choice == '4':
            try:
                ar = AddRecord()
                await ar.start_add(update, context)
            except Exception:
                logging.exception('admin_action_handler: failed to handle textual choice 4')
            return
        # choice '5' -> DelRecord.start_delete
        if text_choice == '5':
            try:
                # Перед запуском удаления удалим заголовок/меню администратора так же, как
                # это делает маршрут при нажатии inline-кнопки (admin_callback)
                try:
                    hdr = context.user_data.pop('admin_header_message', None)
                    menu = context.user_data.pop('admin_menu_message', None)
                    for msg in (hdr, menu):
                        if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                            try:
                                await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                            except Exception:
                                pass
                except Exception:
                    try:
                        logging.exception('admin_action_handler: failed to cleanup admin header/menu before delete (textual 5)')
                    except Exception:
                        pass
                dr = DelRecord()
                await dr.start_delete(update, context)
            except Exception:
                logging.exception('admin_action_handler: failed to handle textual choice 5')
            return
        # choice '6' -> SortAndFiltr.start
        if text_choice == '6':
            try:
                await sortfiltr.start(update, context)
            except Exception:
                logging.exception('admin_action_handler: failed to handle textual choice 6')
            return
        # В противном случае — делегируем общему обработчику work_db
        await work_db.handle_admin_action(update, context)

@clear_tracked_before
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
            # Перед показом запроса удалим служебные админские сообщения (заголовок и меню),
            # чтобы они не мешали вводу поиска (поведение аналогично choice == '3').
            try:
                hdr = context.user_data.pop('admin_header_message', None)
                menu = context.user_data.pop('admin_menu_message', None)
                for msg in (hdr, menu):
                    if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                        try:
                            await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                        except Exception:
                            pass
            except Exception:
                try:
                    logging.exception('admin_callback: failed to cleanup admin header/menu before search')
                except Exception:
                    pass

            if getattr(update, 'message', None):
                await sr.start_search(update, context)
            else:
                # Build a minimal fake update with message.reply_text delegating to bot.send_message
                class _ProxyMsg:
                    def __init__(self, chat_id, bot):
                        self.chat = type('C', (), {'id': chat_id})
                        self._bot = bot
                    async def reply_text(self, text, **kwargs):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text, **kwargs)
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
            # Перед запуском режима редактирования удалим служебные сообщения
            # администратора (заголовок и меню), чтобы они не мешали вводу.
            try:
                hdr = context.user_data.pop('admin_header_message', None)
                menu = context.user_data.pop('admin_menu_message', None)
                for msg in (hdr, menu):
                    if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                        try:
                            await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                        except Exception:
                            pass
            except Exception:
                try:
                    logging.exception('admin_callback: failed to cleanup admin header/menu before edit')
                except Exception:
                    pass
            if getattr(update, 'message', None):
                await ed.search_and_show_fields(update, context)
            else:
                # Построим минимальный fake update, как в case '2'
                class _ProxyMsg:
                    def __init__(self, chat_id, bot):
                        self.chat = type('C', (), {'id': chat_id})
                        self._bot = bot
                    async def reply_text(self, text, **kwargs):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text, **kwargs)
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
                    async def reply_text(self, text, **kwargs):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text, **kwargs)
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
            # перед запуском удаления — удалим заголовок/меню администратора, как делается для других быстрых путей
            try:
                hdr = context.user_data.pop('admin_header_message', None)
                menu = context.user_data.pop('admin_menu_message', None)
                for msg in (hdr, menu):
                    if msg and isinstance(msg, (list, tuple)) and len(msg) >= 2:
                        try:
                            await context.bot.delete_message(chat_id=msg[0], message_id=msg[1])
                        except Exception:
                            pass
            except Exception:
                try:
                    logging.exception('admin_callback: failed to cleanup admin header/menu before delete')
                except Exception:
                    pass
            if getattr(update, 'message', None):
                await dr.start_delete(update, context)
            else:
                class _ProxyMsg:
                    def __init__(self, chat_id, bot):
                        self.chat = type('C', (), {'id': chat_id})
                        self._bot = bot
                    async def reply_text(self, text, **kwargs):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text, **kwargs)
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
                    async def reply_text(self, text, **kwargs):
                        return await self._bot.send_message(chat_id=self.chat.id, text=text, **kwargs)
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


@clear_tracked_before
async def dropdown_callback(update, context):
    """Обработчик для простого выпадающего inline-меню (открыть/закрыть и показ пунктов)."""
    query = update.callback_query
    data = getattr(query, 'data', '')
    try:
        await query.answer()
    except Exception:
        pass

    # Открыть выпадающее меню — показать список пунктов как InlineKeyboard
    if data in ('dropdown:toggle', 'dropdown:open'):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_INLINE_NEWS, callback_data='inline_menu:news')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_INLINE_PHOTO, callback_data='inline_menu:photo')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_INLINE_VIDEO, callback_data='inline_menu:video')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_INLINE_CONTACTS, callback_data='inline_menu:contacts')],
            [InlineKeyboardButton(MESSAGES_ADMIN.BTN_INLINE_CLOSE, callback_data='dropdown:close')]
        ])
        try:
            await query.edit_message_text('Выберите пункт меню:', reply_markup=kb)
        except Exception:
            try:
                await query.message.reply_text('Выберите пункт меню:', reply_markup=kb)
            except Exception:
                pass
        return

    # Закрыть выпадающее меню — восстановить первоначальную клавиатуру
    if data == 'dropdown:close':
        # При восстановлении меню — показываем кнопку-открывашку только super_admin
        try:
            from verification_id import VerificationID
            verifier = VerificationID()
            try:
                role = await verifier.check_role(update, context)
            except Exception:
                role = None
        except Exception:
            role = None
        rows = [[InlineKeyboardButton(MESSAGES_ADMIN.BTN_MENU, callback_data='menu:show'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_HELP, callback_data='help:show')]]
        if role == 'super_admin':
            rows.append([InlineKeyboardButton(MESSAGES_ADMIN.BTN_MENU_TOGGLE, callback_data='dropdown:toggle')])
        kb = InlineKeyboardMarkup(rows)
        try:
            # Попытка вернуть исходный текст приветствия (корректнее, если это сообщение-приветствие)
            await query.edit_message_text('Добро пожаловать! Я бот Анжеро-Судженской МО ВОС. Чем могу помочь?', reply_markup=kb)
        except Exception:
            try:
                await query.message.reply_text('Добро пожаловать! Я бот Анжеро-Судженской МО ВОС. Чем могу помочь?', reply_markup=kb)
            except Exception:
                pass
        return


@clear_tracked_before
async def inline_menu_callback(update, context):
    """Обработка выбора пункта из inline-выпадающего меню."""
    query = update.callback_query
    data = getattr(query, 'data', '')
    try:
        await query.answer()
    except Exception:
        pass

    # Простая маршрутизация — отправляем текстовые ответы, можно интегрировать с существующими handlers
    if data == 'inline_menu:news':
        try:
            await query.message.reply_text("Новости: Здесь будут последние новости организации.")
        except Exception:
            try:
                await context.bot.send_message(chat_id=query.from_user.id, text="Новости: Здесь будут последние новости организации.")
            except Exception:
                pass
        return

    if data == 'inline_menu:photo':
        try:
            await query.message.reply_text("Фото: Здесь будут опубликованы фотографии мероприятий.")
        except Exception:
            try:
                await context.bot.send_message(chat_id=query.from_user.id, text="Фото: Здесь будут опубликованы фотографии мероприятий.")
            except Exception:
                pass
        return

    if data == 'inline_menu:video':
        try:
            await query.message.reply_text("Видео: Здесь будут опубликованы видеоматериалы.")
        except Exception:
            try:
                await context.bot.send_message(chat_id=query.from_user.id, text="Видео: Здесь будут опубликованы видеоматериалы.")
            except Exception:
                pass
        return

    if data == 'inline_menu:contacts':
        try:
            await query.message.reply_text("Контакты: +7 (38453) 6-18-85, amvos42@gmail.com")
        except Exception:
            try:
                await context.bot.send_message(chat_id=query.from_user.id, text="Контакты: +7 (38453) 6-18-85, amvos42@gmail.com")
            except Exception:
                pass
        return
    

@clear_tracked_before
async def search_callback(update, context):
    """Обработка inline-кнопок поиска (например, 'search:cancel').

    При нажатии 'search:cancel' удаляем приглашение для ввода фамилии и возвращаем
    пользователя в админ-меню.
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    # Диагностика: логируем вход в обработчик поиска и текущее состояние user_data
    try:
        logging.info(f"search_callback entered; data={getattr(query,'data',None)!r} user_id={getattr(query.from_user,'id',None)} keys_before={list(getattr(context, 'user_data', {}).keys())}")
    except Exception:
        try:
            logging.exception('search_callback: failed to log entry state')
        except Exception:
            pass

    # Унифицированный cancel -> очистка состояний и возврат в админ-меню
    try:
        import importlib
        try:
            logging.info('search_callback: importing utils.admin_messenger')
        except Exception:
            pass
        mod = importlib.import_module('utils.admin_messenger')
        cancel_fn = getattr(mod, 'cancel_and_return_to_admin', None)
        if cancel_fn:
            try:
                logging.info('search_callback: calling cancel_and_return_to_admin')
                await cancel_fn(update, context)
                try:
                    logging.info(f"search_callback: finished cancel; keys_after={list(getattr(context, 'user_data', {}).keys())}")
                except Exception:
                    pass
            except Exception:
                try:
                    logging.exception('search_callback: cancel_and_return_to_admin raised')
                except Exception:
                    pass
        else:
            try:
                logging.error('search_callback: cancel_and_return_to_admin not found in utils.admin_messenger')
            except Exception:
                pass
    except Exception:
        try:
            logging.exception('search_callback: cancel_and_return_to_admin failed')
        except Exception:
            pass
    return


@clear_tracked_before
async def register_callback(update, context):
    """Обработка нажатия inline-кнопки 'Регистрация в боте'"""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    # Удалим старое сообщение с кнопкой
    try:
        await query.message.delete()
    except Exception:
        pass
    # Инициализируем режим регистрации
    context.user_data['register_attempts'] = 1
    context.user_data['awaiting_registration_ticket'] = True
    # Отправим приглашение в чат
    try:
        chat_id = query.from_user.id if getattr(query, 'from_user', None) and getattr(query.from_user, 'id', None) else None
        text = 'Введите номер вашего членского билета (у вас 3 попытки):\nПопытка №1:'
        if chat_id:
            sent = await context.bot.send_message(chat_id=chat_id, text=text)
            # Сохраним сообщение, чтобы можно было удалить позже
            try:
                lst = context.user_data.get('admin_sent_messages', [])
                lst.append({'chat_id': sent.chat.id, 'message_id': sent.message_id, 'text': text})
                context.user_data['admin_sent_messages'] = lst
            except Exception:
                pass
        else:
            await query.message.reply_text(text)
    except Exception:
        try:
            await query.message.reply_text('Введите номер вашего членского билета (у вас 3 попытки):\nПопытка №1:')
        except Exception:
            pass
    return


async def _handle_registration_ticket(update, context):
    """Обработка введённого номера членского билета при регистрации.

    Возвращает True если сообщение обработано регистрацией (и должно быть остановлено дальнейшее обработка).
    """
    if not context.user_data.get('awaiting_registration_ticket'):
        return False
    ticket = update.message.text.strip() if getattr(update, 'message', None) and getattr(update.message, 'text', None) else ''
    user_id = update.message.from_user.id if getattr(update, 'message', None) and getattr(update.message.from_user, 'id', None) else None
    from db.database import Database
    db = Database()
    try:
        with db.get_cursor() as cursor:
            # Проверим наличие записи с таким ticket_number
            cursor.execute('SELECT id FROM members WHERE ticket_number = ?', (ticket,))
            row = cursor.fetchone()
            if row:
                member_id = row[0]
                try:
                    cursor.execute('UPDATE members SET telegram_id = ?, role = ? WHERE id = ?', (user_id, 'user', member_id))
                except Exception:
                    # Попробуем обновить только telegram_id, если роль поле отсутствует
                    try:
                        cursor.execute('UPDATE members SET telegram_id = ? WHERE id = ?', (user_id, member_id))
                    except Exception:
                        pass
                # Успех регистрации — удалим трекнутые сообщения и продолжим работу
                try:
                    from utils.admin_messenger import delete_tracked_messages
                    await delete_tracked_messages(context, exclude_greeting=True)
                except Exception:
                    pass
                # Сбросим флаги регистрации
                context.user_data.pop('awaiting_registration_ticket', None)
                context.user_data.pop('register_attempts', None)
                # Повторно проверим роль и продолжим (вызовем start_command)
                try:
                    # Отправим явное подтверждение регистрации пользователю.
                    if user_id is not None:
                        await context.bot.send_message(chat_id=user_id, text='Регистрация выполнена. Можете продолжать.')
                    else:
                        await update.message.reply_text('Регистрация выполнена. Можете продолжать.')
                except Exception:
                    try:
                        await update.message.reply_text('Регистрация выполнена. Можете продолжать.')
                    except Exception:
                        pass

                # Отправим приветствие (как в start_command), но не вызывая
                # start_command напрямую — чтобы избежать дублирования логики
                # и возможных гонок с контекстом update.
                try:
                    from verification_id import VerificationID
                    verifier = VerificationID()
                    try:
                        role = await verifier.check_role(update, context)
                    except Exception:
                        role = None
                except Exception:
                    role = None

                try:
                    rows = [[InlineKeyboardButton(MESSAGES_ADMIN.BTN_MENU, callback_data='menu:show'), InlineKeyboardButton(MESSAGES_ADMIN.BTN_HELP, callback_data='help:show')]]
                    if role == 'super_admin':
                        rows.append([InlineKeyboardButton(MESSAGES_ADMIN.BTN_MENU_TOGGLE, callback_data='dropdown:toggle')])
                    kb = InlineKeyboardMarkup(rows)
                    greeting_text = "Добро пожаловать! Я бот Анжеро-Судженской МО ВОС. Чем могу помочь?"
                    if user_id is not None:
                        await context.bot.send_message(chat_id=user_id, text=greeting_text, reply_markup=kb)
                    else:
                        try:
                            await update.message.reply_text(greeting_text, reply_markup=kb)
                        except Exception:
                            # fallback: try to send via bot if reply_text fails
                            if getattr(context, 'bot', None) and getattr(update, 'effective_user', None):
                                await context.bot.send_message(chat_id=update.effective_user.id, text=greeting_text, reply_markup=kb)
                except Exception:
                    try:
                        logging.exception('Failed to send greeting after registration')
                    except Exception:
                        pass
                return True
            else:
                # Не найдено — увеличим счётчик попыток
                attempts = context.user_data.get('register_attempts', 1)
                attempts += 1
                context.user_data['register_attempts'] = attempts
                if attempts <= 3:
                    # Сообщим о неудаче и попросим ввести снова
                    try:
                        await update.message.reply_text('Таких данных не существует.\nПопытка №{}:'.format(attempts))
                    except Exception:
                        pass
                    return True
                else:
                    # Третья попытка неудачна — блокируем пользователя
                    try:
                        from utils.admin_messenger import delete_tracked_messages
                        await delete_tracked_messages(context, exclude_greeting=True)
                    except Exception:
                        pass
                    try:
                        # Создадим таблицу blocking_user если её нет и добавим telegram_id
                        cursor.execute('CREATE TABLE IF NOT EXISTS blocking_user (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER UNIQUE)')
                        if user_id is not None:
                            try:
                                cursor.execute('INSERT OR IGNORE INTO blocking_user (telegram_id) VALUES (?)', (user_id,))
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        await update.message.reply_text('Вы заблокированы. Обратитесь к администратору бота.')
                    except Exception:
                        pass
                    context.user_data['blocked'] = True
                    context.user_data.pop('awaiting_registration_ticket', None)
                    context.user_data.pop('register_attempts', None)
                    return True
    except Exception:
        try:
            logging.exception('_handle_registration_ticket: db error')
        except Exception:
            pass
    return False



@clear_tracked_before
async def control_entry(update, context):
    """Обработчик, который позволяет пользователю сразу набрать 'диспетчерская' и попасть в диспетчерскую после проверки роли."""
    from control_room.control_room import ControlRoom
    control = ControlRoom()
    try:
        # Очистим все взаимодействия/флаги перед входом в диспетчерскую
        _clear_interaction_state(context)
    except Exception:
        try:
            logging.exception('Failed to clear interaction state before entering control_room')
        except Exception:
            pass
    await control.start(update, context)

@clear_tracked_before
async def news_message(update, context):
    await update.message.reply_text("Новости: Здесь будут последние новости организации.")

@clear_tracked_before
async def photo_message(update, context):
    await update.message.reply_text("Фото: Здесь будут опубликованы фотографии мероприятий.")

@clear_tracked_before
async def video_message(update, context):
    await update.message.reply_text("Видео: Здесь будут опубликованы видеоматериалы.")

@clear_tracked_before
async def number_message(update, context):
    number = update.message.text.strip()
    await update.message.reply_text(f"Вы нажали кнопку: {number}")

def main():
    # Создаем экземпляр приложения
    # Пост-инит регистратор джобов, чтобы job_queue уже существовал
    async def _register_jobs(app):
        try:
            from zoneinfo import ZoneInfo
            from datetime import time as _time
            tz = ZoneInfo(getattr(settings, 'TIMEZONE', 'Europe/Moscow'))

            async def _birthday_job(context):
                days = None
                try:
                    days = context.job.data.get('days') if context.job and getattr(context.job, 'data', None) else None
                except Exception:
                    days = None
                if days is None:
                    days = 0
                try:
                    from db.notifications import send_birthday_notifications
                    sent = await send_birthday_notifications(context.bot, int(days))
                    logging.info(f"birthday_job(days={days}) attempted sends={sent}")
                except Exception:
                    logging.exception('birthday_job failed')

            jq = getattr(app, 'job_queue', None)
            if jq:
                jq.run_daily(_birthday_job, time=_time(9, 10, tzinfo=tz), name='birthday_3d', data={'days': 3})
                jq.run_daily(_birthday_job, time=_time(9, 10, tzinfo=tz), name='birthday_0d', data={'days': 0})
            else:
                logging.warning('Job queue is not available on Application instance in post_init; skipping daily birthday jobs registration')
        except Exception:
            logging.exception('Failed to register birthday jobs (post_init)')

    application = Application.builder().token(settings.API_KEY).post_init(_register_jobs).build()

    # Добавляем обработчик команды /start
    application.add_handler(CommandHandler("start", start_command))
    # Admin / notification commands (super_admin only)
    application.add_handler(CommandHandler('admin_token', admin_token_cmd))
    application.add_handler(CommandHandler('notify_set_template', notify_set_template_cmd))
    application.add_handler(CommandHandler('notify_add_target', notify_add_target_cmd))
    application.add_handler(CommandHandler('notify_list', notify_list_cmd))

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
    # (Reply-menu toggle handler removed per user request)
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
    # CallbackQuery для простого выпадающего inline-меню (dropdown)
    application.add_handler(CallbackQueryHandler(dropdown_callback, pattern=r'^dropdown:'))
    # CallbackQuery для пунктов выпадающего inline-меню
    application.add_handler(CallbackQueryHandler(inline_menu_callback, pattern=r'^inline_menu:'))
    # CallbackQuery для поиска (cancel)
    application.add_handler(CallbackQueryHandler(search_callback, pattern=r'^search:'))
    # CallbackQuery для регистрации (кнопка 'Регистрация в боте')
    application.add_handler(CallbackQueryHandler(register_callback, pattern=r'^register:'))
    # Обработчик для сообщения '?' чтобы показать справку
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)^\s*\?\s*$'), help_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)новости'), news_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)фото'), photo_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)видео'), video_message))
    # Цифровой ряд больше не используется — обработчики удалены
    # workdb callbacks (list pages, member selection, exit) and related callbacks
    from db.work_db import WorkDB
    workdb = WorkDB()
    # Подпишем один обработчик на префиксы workdb:, delrec: и editdb:, чтобы все соответствующие callback'ы
    # доставлялись в WorkDB.handle_callback для централизованной маршрутизации.
    application.add_handler(CallbackQueryHandler(workdb.handle_callback, pattern=r'^(workdb:|delrec:|editdb:)'))

    logging.info("Бот стартовал")

    # Register daily birthday notifier jobs via post_init (see _register_jobs)

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
