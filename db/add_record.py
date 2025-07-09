class AddRecord:
    fields = [
        "Фамилия", "Имя", "Отчество", "Дата рождения", "Группа инвалидности", "Телефон", "Адрес", "Район", "Группа", "Справка МСЭ", "Дата выдачи справки МСЭ", "Срок действия справки МСЭ", "Пенсионное удостоверение", "Номер членского билета", "Дата вступления", "Пол"
    ]
    db_fields = [
        "surname", "name", "patronymic", "date_birth", "group_disability", "phone", "address", "area", "`group`", "help_number", "date_issue", "validity_period", "pension_number", "ticket_number", "date_entry", "floor"
    ]

    async def start_add(self, update, context):
        context.user_data['add_record_data'] = {}
        context.user_data['add_record_step'] = 0
        await update.message.reply_text(f'Введите {self.fields[0]}:')
        context.user_data['add_record_in_progress'] = True

    async def handle_add_step(self, update, context):
        step = context.user_data.get('add_record_step', 0)
        data = context.user_data.get('add_record_data', {})
        value = update.message.text.strip()
        data[self.db_fields[step]] = value
        context.user_data['add_record_data'] = data
        step += 1
        if step < len(self.fields):
            context.user_data['add_record_step'] = step
            await update.message.reply_text(f'Введите {self.fields[step]}:')
        else:
            # Все поля собраны, добавляем запись
            from db.database import Database
            db = Database()
            try:
                with db.get_cursor() as cursor:
                    fields_str = ', '.join(self.db_fields)
                    placeholders = ', '.join(['?'] * len(self.db_fields))
                    values = [data.get(f, '') for f in self.db_fields]
                    cursor.execute(f'INSERT INTO members ({fields_str}) VALUES ({placeholders})', values)
                # Показываем пользователю, что сохранено
                msg = 'Запись успешно добавлена!\nСохранённые данные:\n'
                for i, field in enumerate(self.fields):
                    msg += f"{field}: {data.get(self.db_fields[i], '')}\n"
                await update.message.reply_text(msg)
                # Предложить продолжить или выйти
                await update.message.reply_text('Выберите действие:\n1. Продолжить добавление записей\n2. Выход')
                context.user_data['add_record_continue_or_exit'] = True
            except Exception as e:
                await update.message.reply_text(f'Ошибка при добавлении: {e}')
            context.user_data['add_record_in_progress'] = False
            context.user_data['add_record_step'] = 0
            context.user_data['add_record_data'] = {}

    async def handle_continue_or_exit(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            # Продолжить добавление — начать заново
            await self.start_add(update, context)
            context.user_data['add_record_continue_or_exit'] = False
        elif text == '2':
            # Выход — вернуться к меню администратора
            await update.message.reply_text('Выберите действие администратора:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\nВведите номер действия:')
            context.user_data['add_record_continue_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text('Введите 1 (продолжить) или 2 (выход).')
