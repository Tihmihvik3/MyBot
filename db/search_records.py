class SearchRecords:
    db_fields = [
        "surname", "name", "patronymic", "date_birth", "group_disability", "phone", "address", "area", "`group`", "help_number", "date_issue", "validity_period", "pension_number", "ticket_number", "date_entry", "floor"
    ]

    async def start_search(self, update, context):
        await update.message.reply_text('Введите фамилию для поиска:')
        context.user_data['searchrecords_awaiting_surname'] = True

    async def handle_surname_search(self, update, context):
        surname = update.message.text.strip().split()[0]
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT rowid, ' + ', '.join(self.db_fields) + ' FROM members WHERE LOWER(surname) LIKE LOWER(?)', (surname + '%',))
                rows = cursor.fetchall()
                if not rows:
                    await update.message.reply_text('Совпадений не найдено. 1. Повторить поиск 2. Выход')
                    context.user_data['searchrecords_repeat_or_exit'] = True
                    context.user_data['searchrecords_awaiting_surname'] = False
                    return
                context.user_data['searchrecords_results'] = rows
                if len(rows) == 1:
                    row = rows[0]
                    await self.show_full_record(update, row)
                    await update.message.reply_text('1. Повторить поиск\n2. Выход')
                    context.user_data['searchrecords_repeat_or_exit'] = True
                else:
                    msg = 'Результаты поиска:\n'
                    for idx, row in enumerate(rows, 1):
                        msg += f"{idx}. {row[1]} {row[2]} {row[3]}\n"
                    msg += 'Введите номер нужной записи:'
                    await update.message.reply_text(msg)
                    context.user_data['searchrecords_awaiting_choice'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при поиске: {e}')
        context.user_data['searchrecords_awaiting_surname'] = False

    async def handle_choose_result(self, update, context):
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text('Введите номер из списка!')
            return
        idx = int(text)
        results = context.user_data.get('searchrecords_results', [])
        if idx < 1 or idx > len(results):
            await update.message.reply_text('Некорректный номер!')
            return
        row = results[idx-1]
        await self.show_full_record(update, row)
        await update.message.reply_text('1. Повторить поиск\n2. Выход')
        context.user_data['searchrecords_awaiting_choice'] = False
        context.user_data['searchrecords_repeat_or_exit'] = True

    async def handle_repeat_or_exit(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            await self.start_search(update, context)
            context.user_data['searchrecords_repeat_or_exit'] = False
        elif text == '2':
            await update.message.reply_text('Выберите действие администратора:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\nВведите номер действия:')
            context.user_data['searchrecords_repeat_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text('Введите 1 (повторить) или 2 (выход).')

    async def show_full_record(self, update, row):
        fields = [
            "Фамилия", "Имя", "Отчество", "Дата рождения", "Группа инвалидности", "Телефон", "Адрес", "Район", "Группа", "Справка МСЭ", "Дата выдачи справки МСЭ", "Срок действия справки MСЭ", "Пенсионное удостоверение", "Номер членского билета", "Дата вступления", "Пол"
        ]
        msg = 'Данные выбранной записи:\n'
        for i, field in enumerate(fields):
            msg += f"{field}: {row[i+1]}\n"
        await update.message.reply_text(msg)
