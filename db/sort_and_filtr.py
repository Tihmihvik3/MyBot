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
            # Сортировка по фамилии
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
            except Exception as e:
                await update.message.reply_text(f'Ошибка при сортировке: {e}')
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        elif text in ('2', '3', '4'):
            await update.message.reply_text('Сортировка по выбранному полю пока не реализована.')
            context.user_data['sortfiltr_awaiting_sort_field'] = False
        else:
            await update.message.reply_text('Введите номер поля из списка.')
