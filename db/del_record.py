class DelRecord:
    db_fields = [
        "surname", "name", "patronymic", "date_birth", "group_disability", "phone", "address", "area", "`group`", "help_number", "date_issue", "validity_period", "pension_number", "ticket_number", "date_entry", "floor"
    ]

    async def start_delete(self, update, context):
        await update.message.reply_text('Введите фамилию для поиска (для удаления):')
        context.user_data['delrecord_awaiting_surname'] = True

    async def handle_surname_search(self, update, context):
        surname = update.message.text.strip()
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT rowid, ' + ', '.join(self.db_fields) + ' FROM members WHERE LOWER(surname) LIKE LOWER(?)', (surname + '%',))
                rows = cursor.fetchall()
                if not rows:
                    await update.message.reply_text('Совпадений не найдено. Повторить поиск? 1. Да 2. Выход')
                    context.user_data['delrecord_repeat_or_exit'] = True
                    context.user_data['delrecord_awaiting_surname'] = False
                    return
                context.user_data['delrecord_search_results'] = rows
                if len(rows) == 1:
                    row = rows[0]
                    context.user_data['delrecord_selected_rowid'] = row[0]
                    await update.message.reply_text(f"Найдена запись: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}. Удалить? 1. Да 2. Нет")
                    context.user_data['delrecord_awaiting_confirm'] = True
                else:
                    msg = 'Результаты поиска:\n'
                    for idx, row in enumerate(rows, 1):
                        msg += f"{idx}. Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}\n"
                    msg += 'Введите номер нужной записи:'
                    await update.message.reply_text(msg)
                    context.user_data['delrecord_awaiting_choice'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при поиске: {e}')
        context.user_data['delrecord_awaiting_surname'] = False

    async def handle_choose_result(self, update, context):
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text('Введите номер из списка!')
            return
        idx = int(text)
        results = context.user_data.get('delrecord_search_results', [])
        if idx < 1 or idx > len(results):
            await update.message.reply_text('Некорректный номер!')
            return
        row = results[idx-1]
        context.user_data['delrecord_selected_rowid'] = row[0]
        await update.message.reply_text(f"Вы выбрали: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}. Удалить? 1. Да 2. Нет")
        context.user_data['delrecord_awaiting_choice'] = False
        context.user_data['delrecord_awaiting_confirm'] = True

    async def handle_confirm(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            # Удалить запись
            rowid = context.user_data.get('delrecord_selected_rowid')
            from db.database import Database
            db = Database()
            try:
                with db.get_cursor() as cursor:
                    cursor.execute('DELETE FROM members WHERE rowid = ?', (rowid,))
                await update.message.reply_text('Запись успешно удалена! Повторить удаление? 1. Да 2. Выход')
                context.user_data['delrecord_repeat_or_exit'] = True
            except Exception as e:
                await update.message.reply_text(f'Ошибка при удалении: {e}')
                context.user_data['delrecord_repeat_or_exit'] = True
        elif text == '2':
            await update.message.reply_text('1. Повторить поиск\n2. Выход')
            context.user_data['delrecord_repeat_or_exit'] = True
        else:
            await update.message.reply_text('Введите 1 (Да) или 2 (Нет).')

        context.user_data['delrecord_awaiting_confirm'] = False

    async def handle_repeat_or_exit(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            # Повторить поиск
            await self.start_delete(update, context)
            context.user_data['delrecord_repeat_or_exit'] = False
        elif text == '2':
            # Выход — вернуться к меню администратора
            await update.message.reply_text('Выберите действие администратора:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\nВведите номер действия:')
            context.user_data['delrecord_repeat_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text('Введите 1 (повторить) или 2 (выход).')
