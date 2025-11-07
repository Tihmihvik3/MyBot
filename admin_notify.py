import logging
import traceback
import settings

logger = logging.getLogger(__name__)

async def notify_admin(context, subject: str, details: str = None) -> None:
    """Send a notification to the configured admin chat, if available.

    context: telegram context object (to access context.bot)
    subject: short subject line
    details: optional longer text (stacktrace or extra info)
    """
    try:
        admin_chat = getattr(settings, 'ADMIN_CHAT_ID', None)
        bot = getattr(context, 'bot', None)
        if not admin_chat or not bot:
            logger.warning('Admin notify skipped (no ADMIN_CHAT_ID or bot). Subject: %s', subject)
            return
        text = f"[Бот] {subject}"
        if details:
            # truncate details if too long
            max_len = 3000
            if len(details) > max_len:
                details = details[:max_len] + '\n... (truncated)'
            text = f"{text}\n\n{details}"
        await bot.send_message(chat_id=admin_chat, text=text)
    except Exception:
        try:
            logger.exception('Failed to send admin notification')
        except Exception:
            pass