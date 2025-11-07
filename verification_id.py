class VerificationID:
    async def check_role(self, update, context):
        # Поддерживаем как обычные сообщения, так и CallbackQuery
        if getattr(update, 'callback_query', None):
            # для callback используем from_user из callback (это пользователь, который нажал кнопку)
            user = update.callback_query.from_user
            msg = update.callback_query.message
        else:
            user = update.message.from_user if getattr(update, 'message', None) else None
            msg = update.message
        if not user or not getattr(user, 'id', None):
            # Невозможно определить пользователя
            return None
        telegram_id = user.id
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f'VerificationID.check_role: telegram_id={telegram_id}')
        from db.database import Database
        db = Database()
        USER_ROLE = None
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT role FROM members WHERE telegram_id = ?', (telegram_id,))
                result = cursor.fetchone()
                if result:
                    USER_ROLE = result[0]
        except Exception as e:
            logger.exception('Ошибка при чтении роли из members')
            try:
                await msg.reply_text(f'Ошибка при проверке роли: {e}')
            except Exception:
                pass
            try:
                import traceback
                from admin_notify import notify_admin
                await notify_admin(context, 'Ошибка при чтении роли из members (verification_id)', traceback.format_exc())
            except Exception:
                pass
            return None
        logger.debug(f'VerificationID.check_role: found role={USER_ROLE}')
        return USER_ROLE
