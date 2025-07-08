class EditDB:
    fields = [
        "Фамилия", "Имя", "Отчество", "Дата рождения", "Группа инвалидности", "Телефон", "Адрес", "Район", "Группа", "Справка МСЭ", "Дата выдачи справки МСЭ", "Срок действия справки MСЭ", "Пенсионное удостоверение", "Номер членского билета", "Дата вступления", "Пол"
    ]
    db_fields = [
        "surname", "name", "patronymic", "date_birth", "group_disability", "phone", "address", "area", "`group`", "help_number", "date_issue", "validity_period", "pension_number", "ticket_number", "date_entry", "floor"
    ]

    async def search_and_show_fields(self, update, context):
        # Запросить фамилию у пользователя
        await update.message.reply_text('Введите фамилию для поиска:')
        context.user_data['editdb_awaiting_surname'] = True

    async def handle_surname_search(self, update, context):
        # Обработка поиска по фамилии (LIKE, без учёта регистра) и вывод Фамилия, Имя, Отчество с нумерацией
        surname = update.message.text.strip()
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT rowid, ' + ', '.join(self.db_fields) + ' FROM members WHERE LOWER(surname) LIKE LOWER(?)', (surname + '%',))
                rows = cursor.fetchall()
                if not rows:
                    await update.message.reply_text('Совпадений не найдено.')
                    context.user_data['editdb_awaiting_surname'] = False
                    return
                context.user_data['editdb_search_results'] = rows
                if len(rows) == 1:
                    row = rows[0]
                    await update.message.reply_text(f"Вы выбрали: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}")
                    context.user_data['editdb_selected_rowid'] = row[0]
                    await self.show_edit_menu(update, context)
                else:
                    msg = 'Результаты поиска:\n'
                    for idx, row in enumerate(rows, 1):
                        msg += f"{idx}. Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}\n"
                    msg += 'Введите номер нужной записи:'
                    await update.message.reply_text(msg)
                    context.user_data['editdb_awaiting_choice'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при поиске: {e}')
        context.user_data['editdb_awaiting_surname'] = False

    async def handle_choose_result(self, update, context):
        # Обработка выбора результата поиска
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text('Введите номер из списка!')
            return
        idx = int(text)
        results = context.user_data.get('editdb_search_results', [])
        if idx < 1 or idx > len(results):
            await update.message.reply_text('Некорректный номер!')
            return
        row = results[idx-1]
        await update.message.reply_text(f"Вы выбрали: Фамилия: {row[1]} | Имя: {row[2]} | Отчество: {row[3]}")
        context.user_data['editdb_selected_rowid'] = row[0]
        await self.show_edit_menu(update, context)
        context.user_data['editdb_awaiting_choice'] = False

    async def show_edit_menu(self, update, context):
        # Показать меню редактирования
        menu = 'Выберите поле для редактирования:\n'
        for idx, col in enumerate(self.fields, 1):
            menu += f"{idx}. {col}\n"
        menu += 'Введите номер поля:'
        await update.message.reply_text(menu)
        context.user_data['editdb_awaiting_field'] = True

    async def handle_field_edit(self, update, context):
        # Обработка выбора поля для редактирования
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text('Введите номер поля!')
            return
        idx = int(text)
        if idx < 1 or idx > len(self.fields):
            await update.message.reply_text('Некорректный номер поля!')
            return
        field_name = self.fields[idx-1]
        db_field = self.db_fields[idx-1]
        # Получаем выбранную запись
        results = context.user_data.get('editdb_search_results', [])
        selected_rowid = context.user_data.get('editdb_selected_rowid')
        row = None
        if selected_rowid and results:
            for r in results:
                if r[0] == selected_rowid:
                    row = r
                    break
        elif results:
            row = results[0]
        if row:
            await update.message.reply_text(f'Текущее значение поля "{field_name}": {row[idx]}\nВведите новое значение:')
            context.user_data['editdb_awaiting_new_value'] = {'field': db_field, 'rowid': row[0], 'field_name': field_name}
            context.user_data['editdb_awaiting_field'] = False  # <--- Сброс ожидания выбора поля
        else:
            await update.message.reply_text('Ошибка: не удалось получить запись для редактирования.')

    async def handle_new_value(self, update, context):
        # Сохраняем новое значение и показываем пользователю, затем предлагаем продолжить или выйти
        data = context.user_data.get('editdb_awaiting_new_value')
        if not data:
            await update.message.reply_text('Нет данных для обновления.')
            return
        new_value = update.message.text.strip()
        field = data['field']
        rowid = data['rowid']
        field_name = data['field_name']
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                # Очищаем ячейку (ставим пустое значение)
                cursor.execute(f'UPDATE members SET {field} = NULL WHERE rowid = ?', (rowid,))
                # Вносим новое значение
                cursor.execute(f'UPDATE members SET {field} = ? WHERE rowid = ?', (new_value, rowid))
            await update.message.reply_text(f'Новое значение поля "{field_name}": {new_value} успешно сохранено!')
            # Предложить продолжить или выйти
            await update.message.reply_text('Выберите действие:\n1. Продолжить редактирование\n2. Выход')
            context.user_data['editdb_continue_or_exit'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сохранении: {e}')
        context.user_data['editdb_awaiting_new_value'] = None

    async def handle_continue_or_exit(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            # Продолжить редактирование — снова показать меню выбора поля
            await self.show_edit_menu(update, context)
            context.user_data['editdb_continue_or_exit'] = False
        elif text == '2':
            # Выход — перейти к меню выбора действия администратора (WorkDB)
            await update.message.reply_text('Выберите действие администратора:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\nВведите номер действия:')
            context.user_data['editdb_continue_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text('Введите 1 (продолжить) или 2 (выход).')
