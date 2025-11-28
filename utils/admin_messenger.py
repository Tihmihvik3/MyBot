import logging
from telegram.error import BadRequest

logger = logging.getLogger(__name__)
try:
    logger.info(f'admin_messenger loaded from {__file__}')
except Exception:
    pass


async def delete_tracked_messages(context, exclude_greeting=True):
    """Удалить все сохранённые админские сообщения, кроме приветствия (опционально).

    Сообщения хранятся в context.user_data['admin_sent_messages'] как список словарей
    {'chat_id':..., 'message_id':..., 'text':...}.
    Также учитываем context.chat_data['control_room_sent_messages'] при исключении приветствия.
    """
    try:
        bot = getattr(context, 'bot', None)
        if bot is None:
            return
        stored = context.user_data.get('admin_sent_messages', []) or []
        stored_chat = getattr(context, 'chat_data', {}).get('control_room_sent_messages', []) or []
        # build set of greeting ids to preserve
        greeting_ids = set()
        if exclude_greeting:
            for it in stored_chat:
                try:
                    if isinstance(it, dict) and it.get('text', '').startswith('Добро пожаловать'):
                        greeting_ids.add(it.get('message_id'))
                except Exception:
                    pass

        for e in stored:
            try:
                cid = e.get('chat_id')
                mid = e.get('message_id')
                if exclude_greeting and mid in greeting_ids:
                    continue
                await bot.delete_message(chat_id=cid, message_id=mid)
            except Exception as ex:
                try:
                    # ignore message already deleted errors
                    if isinstance(ex, BadRequest) and 'Message to delete not found' in str(ex):
                        continue
                except Exception:
                    pass
                try:
                    logger.debug(f'admin_messenger.delete_tracked_messages: failed to delete {e} -> {ex}')
                except Exception:
                    pass
        # clear stored
        context.user_data.pop('admin_sent_messages', None)
    except Exception:
        try:
            logger.exception('admin_messenger.delete_tracked_messages: unexpected error')
        except Exception:
            pass


async def _record_sent_message(context, sent, text: str):
    try:
        if not getattr(sent, 'chat', None):
            return
        entry = {'chat_id': sent.chat.id, 'message_id': sent.message_id, 'text': text}
        lst = context.user_data.get('admin_sent_messages', [])
        lst.append(entry)
        context.user_data['admin_sent_messages'] = lst
    except Exception:
        try:
            logger.exception('admin_messenger._record_sent_message failed')
        except Exception:
            pass


async def send_and_track(context, msg_obj, text: str, reply_markup=None, **kwargs):
    """Удаляет старые админские сообщения, отправляет новое и сохраняет его для последующей очистки.

    msg_obj: объект с методом `reply_text` (например, update.message или callback_query.message)
    """
    try:
        await delete_tracked_messages(context, exclude_greeting=True)
    except Exception:
        try:
            logger.exception('admin_messenger.send_and_track: pre-cleanup failed')
        except Exception:
            pass
    # Determine chat_id from msg_obj or kwargs and send via bot.send_message.
    try:
        chat_id = None
        if getattr(msg_obj, 'chat', None) and getattr(msg_obj.chat, 'id', None):
            chat_id = msg_obj.chat.id
        elif getattr(msg_obj, 'message', None) and getattr(msg_obj.message, 'chat', None) and getattr(msg_obj.message.chat, 'id', None):
            chat_id = msg_obj.message.chat.id
        elif getattr(msg_obj, 'from_user', None) and getattr(msg_obj.from_user, 'id', None):
            chat_id = msg_obj.from_user.id
        elif getattr(msg_obj, 'chat_id', None):
            chat_id = getattr(msg_obj, 'chat_id')
        # last-resort: try to get chat_id from kwargs
        if chat_id is None:
            chat_id = kwargs.get('chat_id')

        if chat_id is not None:
            sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, **{k: v for k, v in kwargs.items() if k != 'chat_id'})
            try:
                await _record_sent_message(context, sent, text)
            except Exception:
                pass
            return sent
    except Exception:
        try:
            logger.exception('admin_messenger.send_and_track: bot.send_message fallback failed')
        except Exception:
            pass

    try:
        logger.exception('admin_messenger.send_and_track: failed to send message')
    except Exception:
        pass
    return None


async def cancel_and_return_to_admin(update, context):
    """Унифицированная обработка нажатия кнопки 'Отмена'.

    Действия:
    - закроет/удалит текущее callback-сообщение (если есть),
    - удалит трекинг-админ-сообщений,
    - покажет админ-меню,
    - сбросит типовые флаги модулей (searchrecords, editdb, delrecord, add_record, workdb, sortfiltr и т.п.).
    """
    try:

        query = getattr(update, 'callback_query', None)
        if query:
            try:
                await query.answer()
            except Exception:
                pass
            try:
                await query.message.delete()
            except Exception:
                pass
        else:
            try:
                msg = getattr(update, 'message', None)
                if msg:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
            except Exception:
                pass

        # Удалим все старые админские сообщения в первую очередь
        try:
            await delete_tracked_messages(context, exclude_greeting=True)
        except Exception:
            try:
                logger.exception('cancel_and_return_to_admin: failed to delete tracked messages')
            except Exception:
                pass


        # После удаления трекнутых сообщений сначала сбросим флаги и служебные ключи
        try:
            keys = list(context.user_data.keys())
            prefixes = ('searchrecords_', 'editdb_', 'delrecord_', 'delrec_', 'add_record', 'workdb_', 'sortfiltr_', 'awaiting_', 'member_details_id', 'admin_menu_message', 'admin_header_message')
            for k in keys:
                try:
                    if any(k.startswith(p) for p in prefixes) or k in ('admin_sent_messages', 'workdb_entries_message', 'workdb_pages_message', 'workdb_member_details_message', 'workdb_member_actions_message', 'editdb_menu_message', 'editdb_input_prompt_message', 'add_record_prompt_message', 'add_record_header_message', 'delrec_confirm_message'):
                        context.user_data.pop(k, None)
                except Exception:
                    pass
        except Exception:
            try:
                logger.exception('cancel_and_return_to_admin: failed to clear user_data keys')
            except Exception:
                pass

        # Показать админ-меню после очистки состояний, чтобы новое меню было записано в context
        try:
            from bot import admin_message
            fake = type('F', (), {})()
            fake.callback_query = query
            fake.message = query.message if query is not None else getattr(update, 'message', None)
            await admin_message(fake, context)
        except Exception:
            try:
                logger.exception('cancel_and_return_to_admin: failed to call admin_message')
            except Exception:
                pass

        # finished cleanup

        try:
            chat_keys = list(getattr(context, 'chat_data', {}).keys())
            for ck in chat_keys:
                try:
                    if str(ck).startswith('control_room_'):
                        context.chat_data.pop(ck, None)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        try:
            logger.exception('cancel_and_return_to_admin: unexpected error')
        except Exception:
            pass


def clear_tracked_before(func):
    """Декоратор для хендлеров: перед выполнением обработчика удаляет старые tracked-сообщения.

    Помогает централизованно гарантировать, что перед выводом нового контента старая служебная
    клавиатура/сообщения будут удалены.
    """
    from functools import wraps

    @wraps(func)
    async def _wrapped(update, context, *args, **kwargs):
        try:
            # Удаляем все tracked admin сообщения перед обработкой,
            # но сохраняем приветствие (exclude_greeting=True)
            await delete_tracked_messages(context, exclude_greeting=True)
        except Exception:
            try:
                logger.exception('clear_tracked_before: failed to delete tracked messages')
            except Exception:
                pass
        return await func(update, context, *args, **kwargs)

    return _wrapped
