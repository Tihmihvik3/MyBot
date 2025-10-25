from db.database import Database
from verification_id import VerificationID
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import date, timedelta
import re


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
                await update.message.reply_text('Нажмите кнопку нужной записи или используйте кнопки ниже. Также доступны: Создать, Обновить.')
                # Устанавливаем флаг ожидания выбора записи (на случай текстового ввода)
                context.user_data['control_room_awaiting_choice'] = True
                # Отправим InlineKeyboard с кнопками для каждой записи и служебными кнопками
                kb = []
                for i in range(1, len(ids) + 1):
                    kb.append([InlineKeyboardButton(f"Открыть {i}", callback_data=f"control:open:{i}")])
                # Add control buttons
                kb.append([
                    InlineKeyboardButton('Создать', callback_data='control:create'),
                    InlineKeyboardButton('Обновить', callback_data='control:refresh')
                ])
                markup = InlineKeyboardMarkup(kb)
                await update.message.reply_text('Управление:', reply_markup=markup)
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
            # Если редактируем дату — провалидируем и запретим прошлые даты
            if field == 'date':
                parsed = self._parse_date_text(new_value)
                if not parsed:
                    await update.message.reply_text('Неверный формат даты. Введите YYYY-MM-DD или DD.MM.YYYY или используйте кнопки.')
                    kb = self._build_quickdate_markup()
                    await update.message.reply_text('Выберите дату:', reply_markup=kb)
                    return True
                if self._is_past_date(parsed):
                    await update.message.reply_text('Выбранная дата в прошлом. Укажите текущую или будущую дату.')
                    kb = self._build_quickdate_markup()
                    await update.message.reply_text('Выберите дату:', reply_markup=kb)
                    return True
                new_value = parsed.isoformat()
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

    async def handle_callback(self, update, context):
        """Обработчик CallbackQuery для InlineKeyboard диспетчерской."""
        query = update.callback_query
        data = query.data
        await query.answer()
        # Формат данных: control:<action>:<params...>
        parts = data.split(':')
        if not parts or parts[0] != 'control':
            return
        action = parts[1] if len(parts) > 1 else ''
        if action == 'open' and len(parts) >= 3:
            try:
                idx = int(parts[2])
            except Exception:
                await query.edit_message_text('Некорректный номер записи.')
                return
            ids = context.user_data.get('control_room_rows_ids', [])
            if not ids or idx < 1 or idx > len(ids):
                await query.edit_message_text('Неверный индекс записи.')
                return
            row_id = ids[idx - 1]
            # Получим полную запись
            with self.db.get_cursor() as cur:
                cur.execute('SELECT id, date, where_from, departure_time, "where", arrival_time, customer, phone FROM chart WHERE id = ?', (row_id,))
                row = cur.fetchone()
            if not row:
                await query.edit_message_text('Запись не найдена.')
                return
            # Сформируем текст с дружественными названиями
            keys = ['date','where_from','departure_time','where','arrival_time','customer','phone']
            text_lines = []
            for k, val in zip(keys, row[1:]):
                label = self.FIELD_LABELS.get(k, k)
                text_lines.append(f"{label}: {val if val is not None else ''}")
            text = '\n'.join(text_lines)
            # Inline buttons: Edit, Delete, Back
            kb = [
                [InlineKeyboardButton('Редактировать', callback_data=f'control:edit:{idx}') , InlineKeyboardButton('Удалить', callback_data=f'control:delete:{idx}')],
                [InlineKeyboardButton('Назад', callback_data='control:refresh')]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
            return
        if action == 'create':
            # Запустить текстовый поток создания
            context.user_data.pop('control_room_awaiting_choice', None)
            await query.message.reply_text('Запуск создания заявки.')
            # Передаём весь Update (с callback_query) — start_create ожидает Update-like объект
            await self.start_create(update, context)
            return
        if action == 'quickdate' and len(parts) >= 3:
            token = parts[2]
            # Если в процессе создания — установим значение и продвинем шаг
            if context.user_data.get('control_room_create_in_progress'):
                # Текущий шаг должен быть date
                step = context.user_data.get('control_room_create_step', 0)
                key = self.fields[step][0]
                if key != 'date':
                    await query.answer('Неожиданный выбор даты')
                    return
                if token == 'manual':
                    # Попросим пользователя ввести дату вручную (будет обработано handle_create_step)
                    await query.message.reply_text('Введите дату в формате YYYY-MM-DD или DD.MM.YYYY:')
                    return
                chosen = None
                if token == 'today':
                    chosen = date.today()
                elif token == 'tomorrow':
                    chosen = date.today() + timedelta(days=1)
                elif token == 'plus2':
                    chosen = date.today() + timedelta(days=2)
                else:
                    await query.answer('Неизвестная опция даты')
                    return
                iso = chosen.isoformat()
                # Сохраним и продвинем шаг
                await query.message.reply_text(f'Выбрана дата: {iso}')
                await self._advance_create_with_value(update, context, iso)
                return
            # Если ожидается новое значение при редактировании
            if context.user_data.get('control_room_awaiting_new_value') and context.user_data.get('control_room_edit_field') == 'date':
                token = parts[2]
                if token == 'manual':
                    await query.message.reply_text('Введите дату в формате YYYY-MM-DD или DD.MM.YYYY:')
                    return
                if token == 'today':
                    chosen = date.today()
                elif token == 'tomorrow':
                    chosen = date.today() + timedelta(days=1)
                elif token == 'plus2':
                    chosen = date.today() + timedelta(days=2)
                else:
                    await query.answer('Неизвестная опция даты')
                    return
                iso = chosen.isoformat()
                # Выполним UPDATE
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await query.message.reply_text('Ошибка состояния. Попробуйте снова.')
                    return
                row_id = ids[sel - 1]
                col_name = '"date"' if 'date' == 'where' else 'date'
                try:
                    with self.db.get_cursor() as cur:
                        cur.execute(f'UPDATE chart SET {col_name} = ? WHERE id = ?', (iso, row_id))
                    await query.message.reply_text('Значение обновлено.')
                except Exception as e:
                    await query.message.reply_text(f'Ошибка при обновлении: {e}')
                # очистим флаги и обновим список
                for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                    context.user_data.pop(k, None)
                await self.start(update, context)
                return
        if action == 'refresh':
            # Повторно показать список
            try:
                await query.message.delete()
            except Exception:
                pass
            # Передаём Update, а не Message
            await self.start(update, context)
            return
        if action == 'delete' and len(parts) >= 3:
            try:
                idx = int(parts[2])
            except Exception:
                await query.edit_message_text('Некорректный номер для удаления.')
                return
            # Попросим подтверждение
            kb = [[InlineKeyboardButton('Да', callback_data=f'control:delete_confirm:{idx}'), InlineKeyboardButton('Нет', callback_data='control:refresh')]]
            await query.edit_message_text('Подтвердите удаление записи.', reply_markup=InlineKeyboardMarkup(kb))
            return
        if action == 'delete_confirm' and len(parts) >= 3:
            try:
                idx = int(parts[2])
            except Exception:
                await query.edit_message_text('Некорректный номер для удаления.')
                return
            ids = context.user_data.get('control_room_rows_ids', [])
            if not ids or idx < 1 or idx > len(ids):
                await query.edit_message_text('Неверный индекс для удаления.')
                return
            row_id = ids[idx - 1]
            with self.db.get_cursor() as cur:
                cur.execute('DELETE FROM chart WHERE id = ?', (row_id,))
            await query.edit_message_text('Запись удалена.')
            # Обновим список (передаём Update)
            await self.start(update, context)
            return
        if action == 'edit' and len(parts) >= 3:
            try:
                idx = int(parts[2])
            except Exception:
                await query.edit_message_text('Некорректный номер для редактирования.')
                return
            ids = context.user_data.get('control_room_rows_ids', [])
            if not ids or idx < 1 or idx > len(ids):
                await query.edit_message_text('Неверный индекс для редактирования.')
                return
            # Показать список полей как InlineKeyboard
            kb = []
            for i, f in enumerate(self.fields, 1):
                key = f[0]
                label = self.FIELD_LABELS.get(key, key)
                kb.append([InlineKeyboardButton(f"{i}. {label}", callback_data=f'control:field:{idx}:{i}')])
            kb.append([InlineKeyboardButton('Отмена', callback_data='control:refresh')])
            await query.edit_message_text('Выберите поле для редактирования:', reply_markup=InlineKeyboardMarkup(kb))
            return
        if action == 'field' and len(parts) >= 4:
            try:
                idx = int(parts[2])
                field_idx = int(parts[3])
            except Exception:
                await query.edit_message_text('Некорректные параметры.')
                return
            ids = context.user_data.get('control_room_rows_ids', [])
            if not ids or idx < 1 or idx > len(ids):
                await query.edit_message_text('Неверный индекс записи.')
                return
            if field_idx < 1 or field_idx > len(self.fields):
                await query.edit_message_text('Неверный индекс поля.')
                return
            field_key = self.fields[field_idx - 1][0]
            # Установим состояние ожидания нового значения и запомним выбранную запись/поле
            context.user_data['control_room_selected_index'] = idx
            context.user_data['control_room_edit_field'] = field_key
            context.user_data['control_room_awaiting_new_value'] = True
            # Получим текущее значение
            row_id = ids[idx - 1]
            col_name = f'"{field_key}"' if field_key == 'where' else field_key
            current_val = ''
            try:
                with self.db.get_cursor() as cursor:
                    cursor.execute(f'SELECT {col_name} FROM chart WHERE id = ?', (row_id,))
                    r = cursor.fetchone()
                    if r and r[0] is not None:
                        current_val = str(r[0])
            except Exception:
                current_val = ''
            label = self.FIELD_LABELS.get(field_key, field_key)
            # Если редактируем поле даты, покажем quickdate-кнопки и текущее значение
            if field_key == 'date':
                kb = self._build_quickdate_markup()
                await query.edit_message_text(f'Текущее значение для "{label}": {current_val}\nВыберите новую дату:', reply_markup=kb)
            else:
                await query.edit_message_text(f'Текущее значение для "{label}": {current_val}\nОтправьте новое значение в чат.')
            return

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
        # Используем message из callback_query, если создаём через InlineKeyboard
        msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
        await msg.reply_text(self.fields[0][1])
        # Если первое поле — дата, покажем quick-date клавиатуру
        first_key = self.fields[0][0]
        if first_key == 'date':
            kb = self._build_quickdate_markup()
            await msg.reply_text('Выберите дату:', reply_markup=kb)

    async def handle_create_step(self, update, context):
        step = context.user_data.get('control_room_create_step', 0)
        data = context.user_data.get('control_room_create_data', {})
        value = update.message.text.strip()
        key = self.fields[step][0]
        # Если поле — дата, проверим формат и что дата не в прошлом
        if key == 'date':
            parsed = self._parse_date_text(value)
            if not parsed:
                await update.message.reply_text('Неверный формат даты. Введите в формате YYYY-MM-DD или DD.MM.YYYY, либо выберите кнопку.')
                kb = self._build_quickdate_markup()
                await update.message.reply_text('Выберите дату:', reply_markup=kb)
                return
            if self._is_past_date(parsed):
                await update.message.reply_text('Выбранная дата в прошлом. Пожалуйста, укажите текущую или будущую дату.')
                kb = self._build_quickdate_markup()
                await update.message.reply_text('Выберите дату:', reply_markup=kb)
                return
            value = parsed.isoformat()

        data[key] = value
        context.user_data['control_room_create_data'] = data
        step += 1
        if step < len(self.fields):
            context.user_data['control_room_create_step'] = step
            await update.message.reply_text(self.fields[step][1])
            # Если следующее поле — дата, покажем клавиатуру
            next_key = self.fields[step][0]
            if next_key == 'date':
                kb = self._build_quickdate_markup()
                await update.message.reply_text('Выберите дату:', reply_markup=kb)
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

    async def _advance_create_with_value(self, update, context, value: str):
        """Вставить value в текущее поле создания и продвинуть шаг (вызывается для quickdate)."""
        step = context.user_data.get('control_room_create_step', 0)
        data = context.user_data.get('control_room_create_data', {})
        key = self.fields[step][0]
        data[key] = value
        context.user_data['control_room_create_data'] = data
        step += 1
        # Определим объект message для ответов (в зависимости от того, вызвано ли из callback)
        msg = None
        if getattr(update, 'callback_query', None):
            msg = update.callback_query.message
        else:
            msg = update.message

        if step < len(self.fields):
            context.user_data['control_room_create_step'] = step
            await msg.reply_text(self.fields[step][1])
            # Если следующее поле — дата, покажем клавиатуру
            next_key = self.fields[step][0]
            if next_key == 'date':
                kb = self._build_quickdate_markup()
                await msg.reply_text('Выберите дату:', reply_markup=kb)
            return

        # Все поля собраны — вставляем запись в таблицу chart
        try:
            with self.db.get_cursor() as cursor:
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
            await msg.reply_text('Заявка успешно создана.')
            # Очистим флаги создания
            for k in ('control_room_create_data','control_room_create_step','control_room_create_in_progress'):
                context.user_data.pop(k, None)
            # Показать обновлённый список
            await self.start(update, context)
        except Exception as e:
            await msg.reply_text(f'Ошибка при сохранении заявки: {e}')

    def _build_quickdate_markup(self):
        buttons = [
            [InlineKeyboardButton('Сегодня', callback_data='control:quickdate:today'), InlineKeyboardButton('Завтра', callback_data='control:quickdate:tomorrow')],
            [InlineKeyboardButton('Через 2 дня', callback_data='control:quickdate:plus2'), InlineKeyboardButton('Ввести вручную', callback_data='control:quickdate:manual')],
            [InlineKeyboardButton('Отмена', callback_data='control:refresh')]
        ]
        return InlineKeyboardMarkup(buttons)

    def _parse_date_text(self, text: str):
        text = text.strip().lower()
        if text in ('сегодня', 'today'):
            return date.today()
        if text in ('завтра', 'tomorrow'):
            return date.today() + timedelta(days=1)
        # YYYY-MM-DD
        m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', text)
        if m:
            y, mo, d = map(int, m.groups())
            try:
                return date(y, mo, d)
            except Exception:
                return None
        # DD.MM.YYYY
        m = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', text)
        if m:
            d, mo, y = map(int, m.groups())
            try:
                return date(y, mo, d)
            except Exception:
                return None
        return None

    def _is_past_date(self, d: date) -> bool:
        today = date.today()
        return d < today
