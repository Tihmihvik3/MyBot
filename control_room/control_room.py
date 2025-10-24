from db.database import Database
from verification_id import VerificationID


class ControlRoom:
    """Класс, обрабатывающий диспетчерскую: проверка роли, вывод и создание таблицы chart, показ заявок."""

    def __init__(self):
        self.db = Database()

    async def start(self, update, context):
        # Проверяем роль пользователя, аналогично admin_message
        verifier = VerificationID()
        role = await verifier.check_role(update, context)
        if role not in ("admin", "super admin"):
            await update.message.reply_text('Эта команда вам не доступна. Обратитесь к администратору бота.')
            return

        # Убедимся, что есть подключение к БД
        try:
            with self.db.get_cursor() as cursor:
                # Проверим наличие таблицы chart
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chart'")
                found = cursor.fetchone()
                if not found:
                    # Создадим таблицу chart
                    cursor.execute('''
                    CREATE TABLE chart (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT,
                        where_from TEXT,
                        departure_time TEXT,
                        "where" TEXT,
                        arrival_time TEXT,
                        customer TEXT,
                        phone TEXT
                    )
                    ''')
                    await update.message.reply_text('Таблица "chart" не была обнаружена и была создана.')
                    # После создания таблицы сразу предложим создать запись
                    await update.message.reply_text('Заявок нет. Наберите 0 чтобы создать заявку.')
                    context.user_data['control_room_wait_create'] = True
                    return

                # Если таблица существует — вывести все записи (сначала id, чтобы можно было ссылаться на запись)
                cursor.execute('SELECT id, date, where_from, departure_time, "where", arrival_time, customer, phone FROM chart')
                rows = cursor.fetchall()
                if not rows:
                    await update.message.reply_text('Заявок нет.')
                    await update.message.reply_text('Наберите 0 чтобы создать заявку.')
                    context.user_data['control_room_wait_create'] = True
                    return

                # Выводим список без id и имён полей, пронумерованный
                msg_lines = []
                # Сохраняем сопоставление индекса->id
                ids = []
                for idx, row in enumerate(rows, 1):
                    ids.append(row[0])
                    # Соединяем значения через ' | ' — пропускаем id (row[0])
                    values = row[1:]
                    line = ' | '.join([str(x) if x is not None else '' for x in values])
                    msg_lines.append(f"{idx}. {line}")
                context.user_data['control_room_rows_ids'] = ids
                # Отправляем порциями, если нужно
                full_msg = '\n'.join(msg_lines)
                # Telegram ограничение — отправим как есть
                await update.message.reply_text(full_msg)

                # Инструкции для дальнейших действий
                await update.message.reply_text('Введите номер записи для удаления/редактирования, 0 — создать запись, 00 — обновить список.')
                # Устанавливаем флаг ожидания выбора записи
                context.user_data['control_room_awaiting_choice'] = True
        except Exception as e:
            await update.message.reply_text(f'Ошибка доступа к базе данных: {e}')

    async def process_state(self, update, context):
        """Обрабатывает последующие сообщения пользователя в режиме диспетчерской.
        Возвращает True, если сообщение обработано модулем.
        """
        # Если уже в процессе создания заявки — обработать шаг создания
        if context.user_data.get('control_room_create_in_progress'):
            await self.handle_create_step(update, context)
            return True

        # Обработка подтверждения удаления
        if context.user_data.get('control_room_awaiting_delete_confirm'):
            text = update.message.text.strip().lower()
            if text in ('да', 'y', 'yes'):
                # удалить выбранную запись
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await update.message.reply_text('Неверный выбор записи.')
                else:
                    row_id = ids[sel - 1]
                    try:
                        with self.db.get_cursor() as cursor:
                            cursor.execute('DELETE FROM chart WHERE id = ?', (row_id,))
                        await update.message.reply_text('Запись удалена.')
                    except Exception as e:
                        await update.message.reply_text(f'Ошибка при удалении: {e}')
                # очистим флаги и обновим список
                context.user_data.pop('control_room_awaiting_delete_confirm', None)
                context.user_data.pop('control_room_selected_index', None)
                await self.start(update, context)
            else:
                await update.message.reply_text('Удаление отменено.')
                context.user_data.pop('control_room_awaiting_delete_confirm', None)
                context.user_data.pop('control_room_selected_index', None)
                await self.start(update, context)
            return True

        # Обработка выбора поля для редактирования
        if context.user_data.get('control_room_awaiting_field_choice'):
            text = update.message.text.strip()
            try:
                choice = int(text)
            except Exception:
                await update.message.reply_text('Введите корректный номер поля для редактирования.')
                return True
            fields = [f[0] for f in self.fields]
            if choice < 1 or choice > len(fields):
                await update.message.reply_text('Номер поля вне диапазона.')
                return True
            field_key = fields[choice - 1]
            # Проверим выбранную запись
            sel = context.user_data.get('control_room_selected_index')
            ids = context.user_data.get('control_room_rows_ids', [])
            if not ids or sel is None or sel < 1 or sel > len(ids):
                await update.message.reply_text('Неверный выбор записи. Начните заново.')
                context.user_data.pop('control_room_selected_index', None)
                context.user_data.pop('control_room_awaiting_field_choice', None)
                return True
            row_id = ids[sel - 1]

            # Сохраним ключ поля и подготовим запрос для получения текущего значения
            context.user_data['control_room_edit_field'] = field_key
            context.user_data.pop('control_room_awaiting_field_choice', None)
            context.user_data['control_room_awaiting_new_value'] = True

            # Получим текущее значение из БД (экранируем имя колонки если нужно)
            col_name = f'"{field_key}"' if field_key == 'where' else field_key
            current_val = ''
            try:
                with self.db.get_cursor() as cursor:
                    cursor.execute(f'SELECT {col_name} FROM chart WHERE id = ?', (row_id,))
                    row = cursor.fetchone()
                    if row and len(row) > 0 and row[0] is not None:
                        current_val = str(row[0])
            except Exception:
                current_val = ''

            # Покажем дружелюбное название и текущее значение поля при запросе нового значения
            label = self.FIELD_LABELS.get(field_key, field_key) if hasattr(self, 'FIELD_LABELS') else field_key
            prompt = f'Текущее значение для "{label}": {current_val}\nВведите новое значение для поля "{label}":'
            await update.message.reply_text(prompt)
            return True

        # Обработка ввода нового значения поля при редактировании
        if context.user_data.get('control_room_awaiting_new_value'):
            new_value = update.message.text.strip()
            field = context.user_data.get('control_room_edit_field')
            sel = context.user_data.get('control_room_selected_index')
            ids = context.user_data.get('control_room_rows_ids', [])
            if not field or sel is None or not ids or sel < 1 or sel > len(ids):
                await update.message.reply_text('Ошибка состояния. Попробуйте заново.')
                # очистим все состояние
                for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                    context.user_data.pop(k, None)
                await self.start(update, context)
                return True
            row_id = ids[sel - 1]
            # Подготовим имя столбца с экранированием, если нужно
            col_name = f'"{field}"' if field == 'where' else field
            try:
                with self.db.get_cursor() as cursor:
                    cursor.execute(f'UPDATE chart SET {col_name} = ? WHERE id = ?', (new_value, row_id))
                await update.message.reply_text('Значение обновлено.')
            except Exception as e:
                await update.message.reply_text(f'Ошибка при обновлении: {e}')
            # очистим флаги и показать обновлённый список
            for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                context.user_data.pop(k, None)
            await self.start(update, context)
            return True

        # Если ожидаем создание — запуск пошагового ввода
        if context.user_data.get('control_room_wait_create'):
            text = update.message.text.strip()
            if text == '0':
                # Запустить создание
                await self.start_create(update, context)
                context.user_data.pop('control_room_wait_create', None)
                return True
            # любое другое сообщение — игнорируем и ждем
            return True

        if context.user_data.get('control_room_awaiting_choice'):
            text = update.message.text.strip()
            if text == '00':
                # Повторить показ списка
                await self.start(update, context)
                return True
            if text == '0':
                # Запустить создание
                await self.start_create(update, context)
                context.user_data.pop('control_room_awaiting_choice', None)
                return True
            # Если введён номер записи — пока только уведомим, что удаление/редактирование позже
            try:
                n = int(text)
                if n <= 0:
                    raise ValueError()
                # Сохраним выбранный индекс и предложим редактировать или удалить
                context.user_data['control_room_selected_index'] = n
                # убираем флаг ожидания выбора записи — следующий ввод должен относиться к действию
                context.user_data.pop('control_room_awaiting_choice', None)
                context.user_data['control_room_awaiting_action_choice'] = True
                await update.message.reply_text('Выберите действие для записи: 1. Редактировать 2. Удалить 0. Отмена')
            except ValueError:
                await update.message.reply_text('Введите корректный номер записи, 0 или 00.')
            return True

        # Обработка выбора действия после выбора записи (редактировать/удалить/отмена)
        if context.user_data.get('control_room_awaiting_action_choice'):
            text = update.message.text.strip()
            if text == '0':
                await update.message.reply_text('Действие отменено.')
                context.user_data.pop('control_room_awaiting_action_choice', None)
                context.user_data.pop('control_room_selected_index', None)
                # Вернёмся к списку заявок
                await self.start(update, context)
                return True
            if text == '2':
                # Запрос подтверждения удаления
                context.user_data.pop('control_room_awaiting_action_choice', None)
                context.user_data['control_room_awaiting_delete_confirm'] = True
                await update.message.reply_text('Подтвердите удаление: введите "да" для подтверждения или "нет" для отмены.')
                return True
            if text == '1':
                # Начать редактирование: показать список полей с дружелюбными названиями
                context.user_data.pop('control_room_awaiting_action_choice', None)
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await update.message.reply_text('Неверный выбор записи.')
                    context.user_data.pop('control_room_selected_index', None)
                    return True
                msg = 'Выберите поле для редактирования:\n'
                for i, f in enumerate(self.fields, 1):
                    key = f[0]
                    label = self.FIELD_LABELS.get(key, key) if hasattr(self, 'FIELD_LABELS') else key
                    msg += f"{i}. {label}\n"
                await update.message.reply_text(msg)
                context.user_data['control_room_awaiting_field_choice'] = True
                return True
            await update.message.reply_text('Введите 1 (редактировать), 2 (удалить) или 0 (отмена).')
            return True

        return False

    # --- Создание новой заявки (пошаговый ввод) ---
    fields = [
        ('date', 'Введите дату (например, 2025-10-24):'),
        ('where_from', 'Откуда (адрес/место):'),
        ('departure_time', 'Время отправления (например, 14:30):'),
        ('where', 'Куда (адрес/место):'),
        ('arrival_time', 'Время прибытия (например, 15:30):'),
        ('customer', 'Заказчик (ФИО):'),
        ('phone', 'Телефон:')
    ]
    # Дружественные метки полей для показа пользователю
    FIELD_LABELS = {
        'date': 'Дата',
        'where_from': 'Откуда',
        'departure_time': 'Время отправления',
        'where': 'Куда',
        'arrival_time': 'Время прибытия',
        'customer': 'Заказчик',
        'phone': 'Телефон'
    }

    async def start_create(self, update, context):
        context.user_data['control_room_create_data'] = {}
        context.user_data['control_room_create_step'] = 0
        context.user_data['control_room_create_in_progress'] = True
        # Задаём первое приглашение
        await update.message.reply_text(self.fields[0][1])

    async def handle_create_step(self, update, context):
        step = context.user_data.get('control_room_create_step', 0)
        data = context.user_data.get('control_room_create_data', {})
        value = update.message.text.strip()
        key = self.fields[step][0]
        data[key] = value
        context.user_data['control_room_create_data'] = data
        step += 1
        if step < len(self.fields):
            context.user_data['control_room_create_step'] = step
            await update.message.reply_text(self.fields[step][1])
            return

        # Все поля собраны — вставляем запись в таблицу chart
        try:
            with self.db.get_cursor() as cursor:
                # Обратите внимание: имя столбца where экранировано двойными кавычками
                cursor.execute(
                    'INSERT INTO chart (date, where_from, departure_time, "where", arrival_time, customer, phone) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (
                        data.get('date', ''),
                        data.get('where_from', ''),
                        data.get('departure_time', ''),
                        data.get('where', ''),
                        data.get('arrival_time', ''),
                        data.get('customer', ''),
                        data.get('phone', '')
                    )
                )
            await update.message.reply_text('Заявка успешно создана.')
            # Очистим флаги создания
            context.user_data.pop('control_room_create_data', None)
            context.user_data.pop('control_room_create_step', None)
            context.user_data.pop('control_room_create_in_progress', None)
            # Показать обновлённый список
            await self.start(update, context)
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сохранении заявки: {e}')
