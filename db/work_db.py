from db.database import Database

class WorkDB:
    def __init__(self):
        self.db = Database()

    async def handle_admin_action(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            # Показать все записи (первые четыре поля) из таблицы members, нумерация вместо первого поля
            try:
                with self.db.get_cursor() as cursor:
                    cursor.execute('SELECT * FROM members')
                    rows = cursor.fetchall()
                    if rows:
                        msg = 'Список пользователей (первые 4 поля, первая — номер):\n'
                        messages = []
                        for idx, row in enumerate(rows, 1):
                            # Заменяем первое поле на номер
                            line = f"{idx} | " + ' | '.join(str(field) for field in row[1:4]) + '\n'
                            if len(msg) + len(line) > 4000:
                                messages.append(msg)
                                msg = ''
                            msg += line
                        if msg:
                            messages.append(msg)
                        for m in messages:
                            await update.message.reply_text(m)
                    else:
                        await update.message.reply_text('В базе нет данных.')
            except Exception as e:
                await update.message.reply_text(f'Ошибка при чтении базы: {e}')
        elif text == '2':
            await update.message.reply_text("Введите фамилию для поиска:")
            context.user_data['awaiting_surname'] = True
        elif text == '3':
            await update.message.reply_text("Введите данные для добавления (реализация позже)")
        elif text == '4':
            await update.message.reply_text("Введите данные для удаления (реализация позже)")
        else:
            await update.message.reply_text("Некорректный выбор. Введите номер действия от 1 до 4.")
    # Здесь будут методы для работы с базой данных (позже)
