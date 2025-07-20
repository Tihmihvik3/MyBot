class VerificationID:
    async def check_role(self, update, context):
        telegram_id = update.message.from_user.id
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
            await update.message.reply_text(f'Ошибка при проверке роли: {e}')
            return None
        return USER_ROLE
