import logging
from telegram.error import BadRequest

logger = logging.getLogger(__name__)


async def cleanup_admin_messages(context, bot=None, logger_obj=None, exclude_greeting=True):
    """Удаляет известные ранее сохранённые админские сообщения перед отправкой новых.

    Ищет в context.user_data ключи с сохранёнными message id и удаляет их.
    Не трогает приветственное сообщение, если exclude_greeting=True и оно сохранено в chat_data['control_room_sent_messages'].
    """
    log = logger_obj or logger
    bot = bot or getattr(context, 'bot', None)
    if bot is None:
        return
    try:
        # Список ключей, в которых могут храниться (chat_id, message_id)
        keys = [
            'control_menu_message',
            'control_help_message',
            'workdb_entries_message',
            'workdb_pages_message',
            'control_room_members_message',
        ]
        # Соберём message_id приветствий, чтобы их не удалять
        greeting_ids = set()
        try:
            stored = getattr(context, 'chat_data', {}).get('control_room_sent_messages', []) or []
            for item in stored:
                if isinstance(item, dict) and item.get('text', '').startswith('Добро пожаловать'):
                    greeting_ids.add(item.get('message_id'))
        except Exception:
            try:
                log.debug('cleanup_admin_messages: failed to enumerate chat_data greetings')
            except Exception:
                pass

        for k in keys:
            try:
                val = context.user_data.get(k)
                if not val:
                    continue
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    cid, mid = val[0], val[1]
                    if exclude_greeting and mid in greeting_ids:
                        # skip deleting greeting
                        context.user_data.pop(k, None)
                        continue
                    try:
                        await bot.delete_message(chat_id=cid, message_id=mid)
                    except Exception as e:
                        # ignore deletion errors
                        try:
                            log.debug(f'cleanup_admin_messages: failed to delete message {cid}:{mid} -> {e}')
                        except Exception:
                            pass
                # remove key regardless
                context.user_data.pop(k, None)
            except Exception:
                try:
                    log.exception(f'cleanup_admin_messages: error cleaning key {k}')
                except Exception:
                    pass

        # Also handle control_room_sent_messages stored in user_data (list of dicts)
        try:
            stored_user = context.user_data.get('control_room_sent_messages', []) or []
            for e in stored_user:
                try:
                    cid = e.get('chat_id')
                    mid = e.get('message_id')
                    if exclude_greeting and e.get('text', '').startswith('Добро пожаловать'):
                        continue
                    try:
                        await bot.delete_message(chat_id=cid, message_id=mid)
                    except Exception:
                        pass
                except Exception:
                    pass
            context.user_data.pop('control_room_sent_messages', None)
        except Exception:
            try:
                log.exception('cleanup_admin_messages: error cleaning control_room_sent_messages from user_data')
            except Exception:
                pass
    except Exception:
        try:
            log.exception('cleanup_admin_messages: unexpected error')
        except Exception:
            pass
