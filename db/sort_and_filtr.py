class SortAndFiltr:
    # Глобальная переменная для хранения текста действия
    GLOBAL_SORTFILTR_TEXT = None
    async def start(self, update, context):
        await update.message.reply_text('Выберите действие:\n1. Сортировать по\n2. Фильтровать по\n0. Выйти')
        context.user_data['sortfiltr_awaiting_action'] = True  # Ожидаем действие пользователя
        
    async def handle_action(self, update, context):
        SortAndFiltr.GLOBAL_SORTFILTR_TEXT = update.message.text.strip()
        if SortAndFiltr.GLOBAL_SORTFILTR_TEXT == '1':
            await update.message.reply_text('Выберите поле для сортировки:\n1. По фамилии\n2. По группе инвалидности\n3. По группам\n4. По полу\n0. выйти')
            context.user_data['sortfiltr_awaiting_sort_field'] = True  # Ожидаем выбор поля для сортировки
            context.user_data['sortfiltr_awaiting_action'] = False  # Ожидаем, что пользователь выберет поле для сортировки
        elif SortAndFiltr.GLOBAL_SORTFILTR_TEXT == '2':
            await update.message.reply_text('Фильтрация по выбранному полю пока не реализована.')
            context.user_data['sortfiltr_awaiting_action'] = False  # Ожидаем, что пользователь выберет поле для фильтрации
        elif SortAndFiltr.GLOBAL_SORTFILTR_TEXT == '0':
            # Выход из SortAndFiltr и возврат к admin_message
            await update.message.reply_text('Возврат в главное меню администратора.')
            from bot import admin_message
            await admin_message(update, context)
            context.user_data['sortfiltr_awaiting_action'] = False
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        else:
            await update.message.reply_text('Введите 1 (сортировать) или 2 (фильтровать).')
            await self.start(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False  # Сброс ожидания выбора поля сортировки

    async def handle_sort_field(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            await self.sort_surname(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text == '2':
            await self.sort_gr1(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text == '3':
            await self.sort_group(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text == '4':
            await self.sort_floor(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text == '0':
            # Возврат к начальному меню
            await self.start(update, context)
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        else:
            await update.message.reply_text('Введите номер поля из списка.')

    async def sort_group(self, update, context):
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT `group`, surname, name, patronymic FROM members ORDER BY `group` COLLATE NOCASE ASC')
                rows = cursor.fetchall()
                if not rows:
                    await update.message.reply_text('В базе нет данных.')
                    return
                msg = 'Список по группам:\n'
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
            await self.show_return_menu(update, context)
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сортировке: {e}')

    async def sort_floor(self, update, context):
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT floor, surname, name, patronymic FROM members ORDER BY floor COLLATE NOCASE ASC')
                rows = cursor.fetchall()
                if not rows:
                    await update.message.reply_text('В базе нет данных.')
                    return
                msg = 'Список по полу:\n'
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
            await self.show_return_menu(update, context)
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сортировке: {e}')

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
            await self.show_return_menu(update, context)
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
            await self.show_return_menu(update, context)
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сортировке: {e}')

    async def handle_action_without_set(self, update, context):
        if SortAndFiltr.GLOBAL_SORTFILTR_TEXT == '1':
            await update.message.reply_text('Выберите поле для сортировки:\n1. По фамилии\n2. По группе инвалидности\n3. По группам\n4. По полу')
            context.user_data['sortfiltr_awaiting_sort_field'] = True
            context.user_data['sortfiltr_awaiting_action'] = False
        elif SortAndFiltr.GLOBAL_SORTFILTR_TEXT == '2':
            await update.message.reply_text('Фильтрация по выбранному полю пока не реализована.')
            context.user_data['sortfiltr_awaiting_action'] = False
        else:
            await update.message.reply_text('Введите 1 (сортировать) или 2 (фильтровать).')

    async def show_return_menu(self, update, context):
        menu_text = "\nВыберите действие после сортировки:\n1. Сохранить изменения\n2. Не сохранять изменения"
        await update.message.reply_text(menu_text)
        context.user_data['awaiting_return_menu'] = True  # Устанавливаем флаг ожидания выбора в меню возврата

    async def handle_return_menu_choice(self, update, context):
        user_reply = update.message.text.strip()
        if user_reply == '1':
            # Сохранить изменения (пример: коммит в БД, если требуется)
            # Здесь предполагается, что изменения уже внесены в БД, если нет — добавить нужную логику
            await update.message.reply_text('Изменения сохранены.')
            await self.start(update, context)
            context.user_data['awaiting_return_menu'] = False
            
        elif user_reply == '2':
            await update.message.reply_text('Изменения не сохранены.')
            await self.start(update, context)
            context.user_data['awaiting_return_menu'] = False
            
        else:
            await update.message.reply_text('Пожалуйста, выберите 1 (сохранить) или 2 (не сохранять).')
