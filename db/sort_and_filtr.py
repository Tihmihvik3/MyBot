class SortAndFiltr:
    async def start(self, update, context):
        await update.message.reply_text('Выберите действие:\n1. Сортировать по\n2. Фильтровать по')
        context.user_data['sortfiltr_awaiting_action'] = True

    async def handle_action(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            await update.message.reply_text('Выберите поле для сортировки:\n1. По фамилии\n2. По группе инвалидности\n3. По группам\n4. По полу')
            context.user_data['sortfiltr_awaiting_sort_field'] = True
            context.user_data['sortfiltr_awaiting_action'] = False
        elif text == '2':
            await update.message.reply_text('Фильтрация по выбранному полю пока не реализована.')
            context.user_data['sortfiltr_awaiting_action'] = False
        else:
            await update.message.reply_text('Введите 1 (сортировать) или 2 (фильтровать).')

    async def handle_sort_field(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            await self.sort_surname(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text == '2':
            await self.sort_gr1(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text in ('3', '4'):
            await update.message.reply_text('Сортировка по выбранному полю пока не реализована.')
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        else:
            await update.message.reply_text('Введите номер поля из списка.')

    async def sort_surname(self, update, context):
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT surname, name, patronymic FROM members ORDER BY surname COLLATE NOCASE ASC')
                rows = cursor.fetchall()
                if not rows:
                    await update.message.reply_text('В базе нет данных.')
                    return
                msg = 'Список по фамилии:\n'
                messages = []
                for idx, row in enumerate(rows, 1):
                    line = f"{idx}. {row[0]} {row[1]} {row[2]}\n"
                    if len(msg) + len(line) > 4000:
                        messages.append(msg)
                        msg = ''
                    msg += line
                if msg:
                    messages.append(msg)
                for m in messages:
                    await update.message.reply_text(m)
                await update.message.reply_text('1. Повторить сортировку\n2. Выход')
                context.user_data['sortfiltr_repeat_or_exit'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сортировке: {e}')

    async def sort_gr1(self, update, context):
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT group_disability, surname, name, patronymic FROM members ORDER BY group_disability COLLATE NOCASE ASC')
                rows = cursor.fetchall()
                if not rows:
                    await update.message.reply_text('В базе нет данных.')
                    return
                msg = 'Список по группе инвалидности:\n'
                messages = []
                for idx, row in enumerate(rows, 1):
                    line = f"{idx}. {row[0]} | {row[1]} {row[2]} {row[3]}\n"
                    if len(msg) + len(line) > 4000:
                        messages.append(msg)
                        msg = ''
                    msg += line
                if msg:
                    messages.append(msg)
                for m in messages:
                    await update.message.reply_text(m)
                await update.message.reply_text('1. Повторить сортировку\n2. Выход')
                context.user_data['sortfiltr_repeat_or_exit'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сортировке: {e}')

    async def handle_repeat_or_exit(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            await update.message.reply_text('Выберите поле для сортировки:\n1. По фамилии\n2. По группе инвалидности\n3. По группам\n4. По полу')
            context.user_data['sortfiltr_awaiting_sort_field'] = True
            context.user_data['sortfiltr_repeat_or_exit'] = False
        elif text == '2':
            await update.message.reply_text('Выберите действие администратора:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\n6. Сортировка и фильтр.\nВведите номер действия:')
            context.user_data['sortfiltr_repeat_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text('Введите 1 (повторить) или 2 (выход).')
