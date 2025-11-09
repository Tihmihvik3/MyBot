import logging
from telegram.error import BadRequest

logger = logging.getLogger(__name__)


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
    try:
        sent = await msg_obj.reply_text(text, reply_markup=reply_markup, **kwargs)
        try:
            await _record_sent_message(context, sent, text)
        except Exception:
            pass
        return sent
    except Exception:
        try:
            # fallback send without markup
            sent = await msg_obj.reply_text(text, **kwargs)
            try:
                await _record_sent_message(context, sent, text)
            except Exception:
                pass
            return sent
        except Exception:
            try:
                logger.exception('admin_messenger.send_and_track: failed to send message')
            except Exception:
                pass
            return None
