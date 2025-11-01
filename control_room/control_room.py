from db.database import Database
from verification_id import VerificationID
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import date, timedelta
import re
import logging
from typing import Optional, Tuple, List
from control_room.create_table import ensure_chart_table


class ControlRoom:
    """Класс, обрабатывающий диспетчерскую: проверка роли, вывод и создание таблицы chart, показ заявок."""

    def __init__(self):
        self.db = Database()
        self.logger = logging.getLogger(__name__)

    async def start(self, update, context) -> None:
        # Проверяем роль пользователя, аналогично admin_message
        verifier = VerificationID()
        role = await verifier.check_role(update, context)
        if role not in ("admin", "super admin"):
            msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
            await msg.reply_text('Эта команда вам не доступна. Обратитесь к администратору бота.')
            return

        # Убедимся, что есть подключение к БД
        try:
            # Вынесенная логика проверки/создания таблицы и миграций
            self.logger.debug('ControlRoom.start: вызов ensure_chart_table')
            created = await ensure_chart_table(self.db, update, context, self.logger)
            self.logger.debug(f'ControlRoom.start: ensure_chart_table вернул {created}')
            if created:
                # ensure_chart_table уже уведомил пользователя и выставил флаг создания — завершить обработку
                return
            with self.db.get_cursor() as cursor:
                # Выполняем основную выборку (включая where_from для отображения адреса)
                # Удалим просроченные заявки: если поле date заполнено и меньше текущей даты
                try:
                    today_iso = date.today().isoformat()
                    # Условие сравнения для ISO-строк корректно работает в SQLite
                    cursor.execute('DELETE FROM chart WHERE date IS NOT NULL AND date <> "" AND date < ?', (today_iso,))
                    try:
                        deleted = cursor.rowcount
                    except Exception:
                        deleted = None
                    if deleted:
                        self.logger.info(f'Удалено просроченных заявок: {deleted}')
                except Exception:
                    self.logger.exception('Ошибка при удалении просроченных заявок')

                cursor.execute('SELECT id, date, departure_time, where_from FROM chart ORDER BY date ASC, departure_time ASC')
                rows = cursor.fetchall()
                if not rows:
                    msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
                    await msg.reply_text('Заявок нет.')
                    await msg.reply_text('Наберите 0 чтобы создать заявку.')
                    context.user_data['control_room_wait_create'] = True
                    return

                # Пагинация: показываем по page_size записей на страницу
                page_size = 10
                total = len(rows)
                total_pages = (total - 1) // page_size + 1 if total > 0 else 1
                # Сохраним общее количество страниц для навигации
                context.user_data['control_room_total_pages'] = total_pages
                page = context.user_data.get('control_room_page', 0)
                # Нормализуем страницу
                if page < 0:
                    page = 0
                if page >= total_pages:
                    page = total_pages - 1
                context.user_data['control_room_page'] = page

                # Сохраняем полное сопоставление индекса->id
                ids = [r[0] for r in rows]
                context.user_data['control_room_rows_ids'] = ids
                context.user_data['control_room_awaiting_choice'] = True

                # Соберём кнопки для текущей страницы
                start_idx = page * page_size
                end_idx = min(start_idx + page_size, total)
                kb = []
                for i in range(start_idx, end_idx):
                    r = rows[i]
                    global_idx = i + 1
                    date_val = r[1] if r[1] is not None else ''
                    depart_val = r[2] if r[2] is not None else ''
                    where_from_val = r[3] if len(r) > 3 and r[3] is not None else ''
                    if date_val:
                        try:
                            from datetime import datetime
                            dt = datetime.strptime(date_val, '%Y-%m-%d')
                            date_disp = dt.strftime('%d.%m.%Y')
                        except Exception:
                            date_disp = date_val
                    else:
                        date_disp = ''
                    # Показываем в списке: индекс. Дата | Время отправления | Адрес отправления
                    label = f"{global_idx}. {date_disp} | {depart_val} | {where_from_val}"
                    if len(label) > 63:
                        label = label[:60] + '...'
                    kb.append([InlineKeyboardButton(label, callback_data=f"control:open:{global_idx}")])

                # Навигационные кнопки страниц
                nav_row = []
                if page > 0:
                    nav_row.append(InlineKeyboardButton('◀️ Назад', callback_data=f'control:page:prev:{page}'))
                nav_row.append(InlineKeyboardButton(f'Стр. {page+1}/{total_pages}', callback_data='control:noop'))
                if page < total_pages - 1:
                    nav_row.append(InlineKeyboardButton('Вперёд ▶️', callback_data=f'control:page:next:{page}'))
                kb.append(nav_row)

                # Add control buttons (create/refresh)
                kb.append([
                    InlineKeyboardButton('Создать', callback_data='control:create'),
                    InlineKeyboardButton('Обновить', callback_data='control:refresh')
                ])

                markup = InlineKeyboardMarkup(kb)
                text = 'Список заявок (нажмите на строку чтобы открыть):'
                # Если вызвано из CallbackQuery — редактируем текущее сообщение, иначе отправляем новое
                if getattr(update, 'callback_query', None):
                    try:
                        await update.callback_query.edit_message_text(text, reply_markup=markup)
                    except Exception:
                        msg = update.callback_query.message
                        self.logger.exception('Не удалось отредактировать сообщение списка, отправляем новое')
                        # Попробуем отправить новое сообщение как fallback
                        try:
                            await msg.reply_text(text, reply_markup=markup)
                        except Exception:
                            self.logger.exception('Fallback reply_text также не удался')
                else:
                    msg = update.message
                    try:
                        await msg.reply_text(text, reply_markup=markup)
                    except Exception:
                        self.logger.exception('Не удалось отправить сообщение списка заявок')
        except Exception as e:
            msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
            self.logger.exception('Ошибка доступа к базе данных')
            await msg.reply_text(f'Ошибка доступа к базе данных: {e}')

    async def process_state(self, update, context) -> bool:
        """Обрабатывает последующие сообщения пользователя в режиме диспетчерской.
        Возвращает True, если сообщение обработано модулем.
        """
        # Определим объект message — если вызов из CallbackQuery, используем callback_query.message
        msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
        # Если показан список членов и пользователь ввёл номер — считать как номер страницы (приоритет над созданием)
        if context.user_data.get('control_room_showing_members'):
            text = msg.text.strip()
            # Если сообщение — число, переключаем страницу членов
            if text.isdigit():
                try:
                    page_num = int(text)
                except Exception:
                    await msg.reply_text('Введите корректный номер страницы.')
                    return True
                if page_num <= 0:
                    await msg.reply_text('Номер страницы должен быть положительным.')
                    return True
                page_size = 10
                # Получим total страниц — из context (если есть) или по запросу
                total_pages = context.user_data.get('control_room_members_total_pages')
                if total_pages is None:
                    # узнаем общее число записей
                    _, total = self._fetch_members(page=0, page_size=page_size)
                    total_pages = (total - 1) // page_size + 1 if total > 0 else 1
                    context.user_data['control_room_members_total_pages'] = total_pages
                if page_num > total_pages:
                    await msg.reply_text(f'Нет такой страницы. Всего страниц: {total_pages}')
                    return True
                # установить страницу и показать клавиатуру членов
                context.user_data['control_room_members_page'] = page_num - 1
                kb = self._build_members_markup(context=context)
                if kb:
                    # Попробуем отредактировать ранее сохранённое сообщение со списком членов
                    stored = context.user_data.get('control_room_members_message')
                    if stored and getattr(context, 'bot', None):
                        try:
                            chat_id, message_id = stored
                            await context.bot.edit_message_text(f'Список членов — стр. {page_num}/{total_pages}:', chat_id=chat_id, message_id=message_id, reply_markup=kb)
                            # обновим stored (message_id не меняется)
                            context.user_data['control_room_members_message'] = (chat_id, message_id)
                        except Exception:
                            # fallback: отправим новое сообщение и обновим stored
                            sent = await msg.reply_text(f'Список членов — стр. {page_num}/{total_pages}:', reply_markup=kb)
                            if getattr(sent, 'chat', None):
                                context.user_data['control_room_members_message'] = (sent.chat.id, sent.message_id)
                    else:
                        sent = await msg.reply_text(f'Список членов — стр. {page_num}/{total_pages}:', reply_markup=kb)
                        if getattr(sent, 'chat', None):
                            context.user_data['control_room_members_message'] = (sent.chat.id, sent.message_id)
                else:
                    await msg.reply_text('Список членов пуст.')
                return True

        # Если уже в процессе создания заявки — обработать шаг создания
        if context.user_data.get('control_room_create_in_progress'):
            await self.handle_create_step(update, context)
            return True

        

        # Обработка подтверждения удаления
        if context.user_data.get('control_room_awaiting_delete_confirm'):
            text = msg.text.strip().lower()
            if text in ('да', 'y', 'yes'):
                # удалить выбранную запись
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await msg.reply_text('Неверный выбор записи.')
                else:
                    row_id = ids[sel - 1]
                    try:
                        with self.db.get_cursor() as cursor:
                            cursor.execute('DELETE FROM chart WHERE id = ?', (row_id,))
                        await msg.reply_text('Запись удалена.')
                    except Exception as e:
                        await msg.reply_text(f'Ошибка при удалении: {e}')
                # очистим флаги и обновим список
                context.user_data.pop('control_room_awaiting_delete_confirm', None)
                context.user_data.pop('control_room_selected_index', None)
                await self.start(update, context)
            else:
                await msg.reply_text('Удаление отменено.')
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
                await msg.reply_text('Введите корректный номер поля для редактирования.')
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
            display_current = current_val
            if field_key == 'date' and display_current:
                try:
                    from datetime import datetime
                    dt = datetime.strptime(display_current, '%Y-%m-%d')
                    display_current = dt.strftime('%d.%m.%Y')
                except Exception:
                    pass
            prompt = f'Текущее значение для "{label}": {display_current}\nВведите новое значение для поля "{label}":'
            await msg.reply_text(prompt)
            return True

        # Обработка ввода нового значения поля при редактировании
        if context.user_data.get('control_room_awaiting_new_value'):
            new_value = msg.text.strip()
            field = context.user_data.get('control_room_edit_field')
            sel = context.user_data.get('control_room_selected_index')
            ids = context.user_data.get('control_room_rows_ids', [])
            if not field or sel is None or not ids or sel < 1 or sel > len(ids):
                await msg.reply_text('Ошибка состояния. Попробуйте заново.')
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
                    await msg.reply_text('Неверный формат даты. Введите YYYY-MM-DD или DD.MM.YYYY или используйте кнопки.')
                    kb = self._build_quickdate_markup()
                    await msg.reply_text('Выберите дату:', reply_markup=kb)
                    return True
                if self._is_past_date(parsed):
                    await msg.reply_text('Выбранная дата в прошлом. Укажите текущую или будущую дату.')
                    kb = self._build_quickdate_markup()
                    await msg.reply_text('Выберите дату:', reply_markup=kb)
                    return True
                new_value = parsed.isoformat()
            # Если редактируем телефон — нормализуем и провалидируем
            if field == 'phone':
                norm_phone = self._validate_phone(new_value)
                if not norm_phone:
                    await msg.reply_text('Неверный формат телефона. Введите телефон в формате +7XXXXXXXXXX или 10 цифр.')
                    return True
                new_value = norm_phone
            # Подготовим имя столбца с экранированием, если нужно
            # Защита: разрешённые имена полей — только из описанных в fields
            allowed_cols = {f[0] for f in self.fields} | {'where_from', 'arrival_time'}
            if field not in allowed_cols:
                await msg.reply_text('Недопустимое имя поля для редактирования.')
                # очистим состояние
                for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                    context.user_data.pop(k, None)
                return True
            col_name = f'"{field}"' if field == 'where' else field
            try:
                with self.db.get_cursor() as cursor:
                    # Если редактируем дату — обновим departure_datetime, если возможно
                    if field == 'date':
                        # new_value уже в ISO YYYY-MM-DD
                        cursor.execute('SELECT departure_time FROM chart WHERE id = ?', (row_id,))
                        r = cursor.fetchone()
                        cur_time = r[0] if r and len(r) > 0 else None
                        dep_dt = None
                        try:
                            dep_dt = self._build_departure_datetime(new_value, cur_time)
                        except Exception:
                            dep_dt = None
                        cursor.execute(f'UPDATE chart SET {col_name} = ?, departure_datetime = ? WHERE id = ?', (new_value, dep_dt, row_id))
                    elif field == 'departure_time':
                        # Нормализуем время при возможности
                        tnorm = self._normalize_time(new_value)
                        store_time = tnorm if tnorm else new_value
                        cursor.execute('SELECT date FROM chart WHERE id = ?', (row_id,))
                        r = cursor.fetchone()
                        cur_date = r[0] if r and len(r) > 0 else None
                        dep_dt = None
                        try:
                            dep_dt = self._build_departure_datetime(cur_date, store_time)
                        except Exception:
                            dep_dt = None
                        cursor.execute(f'UPDATE chart SET departure_time = ?, departure_datetime = ? WHERE id = ?', (store_time, dep_dt, row_id))
                    else:
                        cursor.execute(f'UPDATE chart SET {col_name} = ? WHERE id = ?', (new_value, row_id))
                await msg.reply_text('Значение обновлено.')
            except Exception as e:
                await msg.reply_text(f'Ошибка при обновлении: {e}')
            # очистим флаги и показать обновлённый список
            for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                context.user_data.pop(k, None)
            await self.start(update, context)
            return True

        # Если ожидаем создание — запуск пошагового ввода
        if context.user_data.get('control_room_wait_create'):
            text = msg.text.strip()
            if text == '0':
                # Запустить создание
                await self.start_create(update, context)
                context.user_data.pop('control_room_wait_create', None)
                return True
            # любое другое сообщение — игнорируем и ждем
            return True

        if context.user_data.get('control_room_awaiting_choice'):
            text = msg.text.strip()
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
                await msg.reply_text('Выберите действие для записи: 1. Редактировать 2. Удалить 0. Отмена')
            except ValueError:
                await msg.reply_text('Введите корректный номер записи, 0 или 00.')
            return True

        # Обработка выбора действия после выбора записи (редактировать/удалить/отмена)
        if context.user_data.get('control_room_awaiting_action_choice'):
            text = msg.text.strip()
            if text == '0':
                await msg.reply_text('Действие отменено.')
                context.user_data.pop('control_room_awaiting_action_choice', None)
                context.user_data.pop('control_room_selected_index', None)
                # Вернёмся к списку заявок
                await self.start(update, context)
                return True
            if text == '2':
                # Запрос подтверждения удаления
                context.user_data.pop('control_room_awaiting_action_choice', None)
                context.user_data['control_room_awaiting_delete_confirm'] = True
                await msg.reply_text('Подтвердите удаление: введите "да" для подтверждения или "нет" для отмены.')
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
                await msg.reply_text(msg)
                context.user_data['control_room_awaiting_field_choice'] = True
                return True
            await update.message.reply_text('Введите 1 (редактировать), 2 (удалить) или 0 (отмена).')
            return True

        return False

    async def handle_callback(self, update, context) -> None:
        """Обработчик CallbackQuery для InlineKeyboard диспетчерской."""
        query = update.callback_query
        data = query.data
        await query.answer()
        # Формат данных: control:<action>:<params...>
        parts = data.split(':')
        if not parts or parts[0] != 'control':
            return
        action = parts[1] if len(parts) > 1 else ''
        # Явно обрабатываем noop — ничего не делаем кроме подтверждения колбэка
        if action == 'noop':
            try:
                await query.answer()
            except Exception:
                pass
            return
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
                display_val = val if val is not None else ''
                # Форматируем дату в карточке в DD.MM.YYYY
                if k == 'date' and display_val:
                    try:
                        from datetime import datetime
                        dt = datetime.strptime(display_val, '%Y-%m-%d')
                        display_val = dt.strftime('%d.%m.%Y')
                    except Exception:
                        # если парсинг не прошёл — оставим оригинал
                        pass
                text_lines.append(f"{label}: {display_val}")
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
        # Обработка навигации по страницам: control:page:prev:<cur_page> и control:page:next:<cur_page>
        if action == 'page' and len(parts) >= 4:
            direction = parts[2]
            try:
                cur_page = int(parts[3])
            except Exception:
                try:
                    await query.edit_message_text('Некорректный номер страницы.')
                except Exception:
                    self.logger.exception('Не удалось сообщить об ошибке номера страницы')
                return
            # вычислим целевую страницу
            if direction == 'prev':
                new_page = cur_page - 1
            elif direction == 'next':
                new_page = cur_page + 1
            else:
                # неизвестное направление — ничего не делаем
                return
            # Guard: не выходим за границы доступных страниц
            total_pages = context.user_data.get('control_room_total_pages')
            if total_pages is not None:
                if new_page < 0:
                    await query.answer('Нет предыдущей страницы', show_alert=False)
                    return
                if new_page >= total_pages:
                    await query.answer('Нет следующей страницы', show_alert=False)
                    return
            else:
                # Если total_pages не известно — логируем и позволяем start() пересчитать
                self.logger.debug('control_room_total_pages отсутствует в user_data, перерисуем список')

            # Сохраняем страницу для этого пользователя и перерисуем список
            context.user_data['control_room_page'] = new_page
            try:
                await query.edit_message_text('Переходим на страницу...')
            except Exception:
                self.logger.exception('Не удалось отредактировать сообщение при смене страницы')
            await self.start(update, context)
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
                # Форматирование даты для отображения
                try:
                    from datetime import datetime
                    disp = chosen.strftime('%d.%m.%Y')
                except Exception:
                    disp = iso
                # Сохраним и продвинем шаг
                await query.message.reply_text(f'Выбрана дата: {disp}')
                await self._advance_create_with_value(update, context, iso)
                return
            # Если ожидаем новое значение при редактировании поля date
            if context.user_data.get('control_room_awaiting_new_value') and context.user_data.get('control_room_edit_field') == 'date':
                if token == 'manual':
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
                # Выполним UPDATE для выбранной записи
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await query.message.reply_text('Ошибка состояния. Попробуйте снова.')
                    return
                row_id = ids[sel - 1]
                try:
                    with self.db.get_cursor() as cur:
                        cur.execute('SELECT departure_time FROM chart WHERE id = ?', (row_id,))
                        r = cur.fetchone()
                        cur_time = r[0] if r and len(r) > 0 else None
                        dep_dt = None
                        try:
                            dep_dt = self._build_departure_datetime(iso, cur_time)
                        except Exception:
                            dep_dt = None
                        cur.execute('UPDATE chart SET date = ?, departure_datetime = ? WHERE id = ?', (iso, dep_dt, row_id))
                    await query.message.reply_text('Значение обновлено.')
                except Exception as e:
                    await query.message.reply_text(f'Ошибка при обновлении: {e}')
                # Очистим состояние редактирования и обновим список
                for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                    context.user_data.pop(k, None)
                await self.start(update, context)
                return
        # Показать весь список членов по запросу: control:members:show
        if action == 'members' and len(parts) >= 3 and parts[2] == 'show':
            try:
                # Пометим, что мы показали пользователю полный список членов —
                # ожидаем, что он может ввести номер страницы в чат
                if context is not None:
                    context.user_data['control_room_showing_members'] = True
                kb = self._build_members_markup(context=context)
                if kb:
                    try:
                        await query.edit_message_text('Список членов:', reply_markup=kb)
                        # Сохраним идентификатор сообщения, которое содержит список членов,
                        # чтобы позже редактировать его вместо отправки нового
                        if context is not None and getattr(query, 'message', None):
                            context.user_data['control_room_members_message'] = (query.message.chat.id, query.message.message_id)
                    except Exception:
                        # если редактировать не удалось — отправим новое сообщение
                        msg = query.message
                        await msg.reply_text('Список членов:', reply_markup=kb)
                        if context is not None and getattr(msg, 'chat', None):
                            context.user_data['control_room_members_message'] = (msg.chat.id, msg.message_id)
                else:
                    try:
                        await query.edit_message_text('Список членов пуст.')
                    except Exception:
                        await query.message.reply_text('Список членов пуст.')
            except Exception:
                self.logger.exception('Ошибка при показе списка членов')
            return
        # Обработка навигации списка членов: control:members:prev:<cur_page> и control:members:next:<cur_page>
        if action == 'members' and len(parts) >= 4:
            direction = parts[2]
            try:
                cur_page = int(parts[3])
            except Exception:
                try:
                    await query.edit_message_text('Некорректный номер страницы.')
                except Exception:
                    self.logger.exception('Не удалось сообщить об ошибке номера страницы (members)')
                return
            # Поддерживаем prev/next и goto (переход на конкретную страницу)
            if direction == 'prev':
                new_page = cur_page - 1
            elif direction == 'next':
                new_page = cur_page + 1
            elif direction == 'goto':
                new_page = cur_page
            else:
                return
            total_pages = context.user_data.get('control_room_members_total_pages')
            if total_pages is not None:
                if new_page < 0:
                    await query.answer('Нет предыдущей страницы', show_alert=False)
                    return
                if new_page >= total_pages:
                    await query.answer('Нет следующей страницы', show_alert=False)
                    return
            else:
                self.logger.debug('control_room_members_total_pages отсутствует, перерисуем список членов')

            context.user_data['control_room_members_page'] = new_page
            try:
                kb = self._build_members_markup(context=context)
                if kb:
                    try:
                        await query.edit_message_text('Список членов:', reply_markup=kb)
                        # обновим хранение message id
                        if context is not None and getattr(query, 'message', None):
                            context.user_data['control_room_members_message'] = (query.message.chat.id, query.message.message_id)
                    except Exception:
                        # если редактирование не удалось — отправим новое сообщение
                        msg = query.message
                        await msg.reply_text('Список членов:', reply_markup=kb)
                        if context is not None and getattr(msg, 'chat', None):
                            context.user_data['control_room_members_message'] = (msg.chat.id, msg.message_id)
                else:
                    try:
                        await query.edit_message_text('Список членов пуст.')
                    except Exception:
                        await query.message.reply_text('Список членов пуст.')
            except Exception:
                self.logger.exception('Ошибка при перерисовке списка членов')
            return
        if action == 'member' and len(parts) >= 3:
            # Выбрали члена из списка для заполнения поля заказчик
            try:
                member_id = int(parts[2])
            except Exception:
                await query.answer('Некорректный выбор')
                return
            # Получим запись члена
            try:
                with self.db.get_cursor() as cur:
                    cur.execute('SELECT id, surname, name, patronymic FROM members WHERE id = ?', (member_id,))
                    mr = cur.fetchone()
            except Exception:
                self.logger.exception('Ошибка при чтении members')
                await query.answer('Ошибка при доступе к базе членов')
                return
            if not mr:
                await query.answer('Член не найден')
                return
            _, surname, name, patronymic = mr
            parts_name = [p for p in (surname, name, patronymic) if p]
            full_name = ' '.join(parts_name)
            # Если в процессе создания — вставим значение и продвинем шаг
            if context.user_data.get('control_room_create_in_progress'):
                await query.message.reply_text(f'Выбран заказчик: {full_name}')
                await self._advance_create_with_value(update, context, full_name)
                # Свернём режим показа членов после выбора
                context.user_data.pop('control_room_showing_members', None)
                return
            # Если ожидаем новое значение при редактировании и редактируем поле customer
            if context.user_data.get('control_room_awaiting_new_value') and context.user_data.get('control_room_edit_field') == 'customer':
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await query.message.reply_text('Ошибка состояния. Попробуйте снова.')
                    return
                row_id = ids[sel - 1]
                try:
                    with self.db.get_cursor() as cur:
                        cur.execute('UPDATE chart SET customer = ? WHERE id = ?', (full_name, row_id))
                    await query.message.reply_text('Значение обновлено.')
                except Exception as e:
                    await query.message.reply_text(f'Ошибка при обновлении: {e}')
                for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                    context.user_data.pop(k, None)
                # Свернём режим показа членов после выбора
                context.user_data.pop('control_room_showing_members', None)
                context.user_data.pop('control_room_members_message', None)
                await self.start(update, context)
                return
            # Иначе — просто подтвердим выбор
            await query.answer(f'Выбран: {full_name}')
            return
            # (previously there was duplicated date-update handling here; removed as unreachable)
        if action == 'refresh':
            # Повторно показать список
            try:
                # Редактируем текущее сообщение, чтобы показать, что идёт обновление
                await query.edit_message_text('Обновляю список...')
            except Exception:
                # Если редактировать не удалось, пропустим — всё равно покажем новый список
                pass
            # При обновлении списка скрываем состояние показа членов
            if context is not None:
                context.user_data.pop('control_room_showing_members', None)
            # Затем покажем актуальный список (start сам отправит новое сообщение)
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
                # Форматируем текущее значение даты для показа
                disp = current_val
                if disp:
                    try:
                        from datetime import datetime
                        dt = datetime.strptime(disp, '%Y-%m-%d')
                        disp = dt.strftime('%d.%m.%Y')
                    except Exception:
                        pass
                kb = self._build_quickdate_markup()
                await query.edit_message_text(f'Текущее значение для "{label}": {disp}\nВыберите новую дату:', reply_markup=kb)
            else:
                # Если редактируем поле заказчика — покажем список членов (members) как Inline-кнопки
                if field_key == 'customer':
                    # Предложим показать весь список по кнопке, чтобы не перегружать интерфейс
                    kb_small = InlineKeyboardMarkup([
                        [InlineKeyboardButton('Показать весь список', callback_data='control:members:show')],
                        [InlineKeyboardButton('Отмена', callback_data='control:refresh')]
                    ])
                    await query.edit_message_text(f'Текущее значение для "{label}": {current_val}\nНажмите, чтобы увидеть список заказчиков:', reply_markup=kb_small)
                else:
                    await query.edit_message_text(f'Текущее значение для "{label}": {current_val}\nОтправьте новое значение в чат.')
            return

    # --- Создание новой заявки (пошаговый ввод) ---
    # Порядок полей для создания: сначала заказчик, затем дата и остальные поля
    fields = [
        ('customer', 'Выберите заказчика (или введите ФИО вручную):'),
        ('date', 'Введите дату (например, 2025-10-24):'),
        ('where_from', 'Откуда (адрес/место):'),
        ('departure_time', 'Время отправления (например, 14:30):'),
        ('where', 'Куда (адрес/место):'),
        ('arrival_time', 'Время прибытия (например, 15:30):'),
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

    async def start_create(self, update, context) -> None:
        context.user_data['control_room_create_data'] = {}
        context.user_data['control_room_create_step'] = 0
        context.user_data['control_room_create_in_progress'] = True
        # Задаём первое приглашение
        # Используем message из callback_query, если создаём через InlineKeyboard
        msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
        # Первый запрос — теперь это заказчик; если это поле customer, покажем список членов
        await msg.reply_text(self.fields[0][1])
        first_key = self.fields[0][0]
        if first_key == 'date':
            kb = self._build_quickdate_markup()
            await msg.reply_text('Выберите дату:', reply_markup=kb)
        elif first_key == 'customer':
            # Сначала показываем кнопку «Показать весь список», чтобы не загромождать интерфейс
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton('Показать весь список', callback_data='control:members:show')],
                [InlineKeyboardButton('Отмена', callback_data='control:refresh')]
            ])
            await msg.reply_text('Нажмите, чтобы увидеть список заказчиков:', reply_markup=kb)

    async def handle_create_step(self, update, context) -> None:
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
            elif next_key == 'customer':
                # Покажем кнопку «Показать весь список» вместо вывода полного списка сразу
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Показать весь список', callback_data='control:members:show')],
                    [InlineKeyboardButton('Отмена', callback_data='control:refresh')]
                ])
                await update.message.reply_text('Нажмите, чтобы увидеть список заказчиков:', reply_markup=kb)
            return

        # Все поля собраны — вставляем запись в таблицу chart
        try:
            with self.db.get_cursor() as cursor:
                # Обратите внимание: имя столбца where экранировано двойными кавычками
                # Построим departure_datetime
                dep_dt = None
                try:
                    dep_dt = self._build_departure_datetime(data.get('date', ''), data.get('departure_time', ''))
                except Exception:
                    dep_dt = None
                # Если есть телефон — попробуем нормализовать
                phone_val = data.get('phone', '')
                if phone_val:
                    try:
                        norm_phone = self._validate_phone(phone_val)
                        if norm_phone:
                            data['phone'] = norm_phone
                        else:
                            # если телефон неверный — сохраняем оригинал, но можно оповестить пользователя
                            pass
                    except Exception:
                        pass
                cursor.execute(
                    'INSERT INTO chart (date, where_from, departure_time, "where", arrival_time, customer, phone, departure_datetime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        data.get('date', ''),
                        data.get('where_from', ''),
                        data.get('departure_time', ''),
                        data.get('where', ''),
                        data.get('arrival_time', ''),
                        data.get('customer', ''),
                        data.get('phone', ''),
                        dep_dt
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

    async def _advance_create_with_value(self, update, context, value: str) -> None:
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
            elif next_key == 'customer':
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Показать весь список', callback_data='control:members:show')],
                    [InlineKeyboardButton('Отмена', callback_data='control:refresh')]
                ])
                await msg.reply_text('Нажмите, чтобы увидеть список заказчиков:', reply_markup=kb)
            return

        # Все поля собраны — вставляем запись в таблицу chart
        try:
            with self.db.get_cursor() as cursor:
                # Построим departure_datetime
                dep_dt = None
                try:
                    dep_dt = self._build_departure_datetime(data.get('date', ''), data.get('departure_time', ''))
                except Exception:
                    dep_dt = None
                cursor.execute(
                    'INSERT INTO chart (date, where_from, departure_time, "where", arrival_time, customer, phone, departure_datetime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        data.get('date', ''),
                        data.get('where_from', ''),
                        data.get('departure_time', ''),
                        data.get('where', ''),
                        data.get('arrival_time', ''),
                        data.get('customer', ''),
                        data.get('phone', ''),
                        dep_dt
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

    def _build_quickdate_markup(self) -> InlineKeyboardMarkup:
        buttons = [
            [InlineKeyboardButton('Сегодня', callback_data='control:quickdate:today'), InlineKeyboardButton('Завтра', callback_data='control:quickdate:tomorrow')],
            [InlineKeyboardButton('Через 2 дня', callback_data='control:quickdate:plus2'), InlineKeyboardButton('Ввести вручную', callback_data='control:quickdate:manual')],
            [InlineKeyboardButton('Отмена', callback_data='control:refresh')]
        ]
        return InlineKeyboardMarkup(buttons)

    def _normalize_time(self, text: str) -> Optional[str]:
        """Нормализовать ввод времени в формат HH:MM (24-часовой). Возвращает строку 'HH:MM' или None."""
        if not text:
            return None
        t = text.strip()
        # Попробуем форматы H:M или H:M:S
        m = re.match(r'^(\d{1,2}):(\d{1,2})(?::\d{1,2})?$', t)
        if m:
            h, mi = m.group(1), m.group(2)
            try:
                hh = int(h)
                mm = int(mi)
                if 0 <= hh < 24 and 0 <= mm < 60:
                    return f"{hh:02d}:{mm:02d}"
            except Exception:
                return None
        # Попробуем просто часы 'H' или 'HH'
        m = re.match(r'^(\d{1,2})$', t)
        if m:
            try:
                hh = int(m.group(1))
                if 0 <= hh < 24:
                    return f"{hh:02d}:00"
            except Exception:
                return None
        return None

    def _build_departure_datetime(self, date_iso: str, time_text: str) -> Optional[str]:
        """Собрать комбинированную дату-время 'YYYY-MM-DD HH:MM:SS' или вернуть None, если не хватает данных."""
        if not date_iso:
            return None
        if not time_text:
            return None
        tnorm = self._normalize_time(time_text)
        if not tnorm:
            return None
        # добавим секунды
        return f"{date_iso} {tnorm}:00"

    def _validate_phone(self, text: str) -> Optional[str]:
        """Простейшая валидация/нормализация телефона.

        Возвращает строку в формате +7XXXXXXXXXX или None, если невалиден.
        Правила:
        - Убираем все нецифровые символы.
        - Если длина 11 и начинается с '8' или '7' -> нормализуем в +7XXXXXXXXXX.
        - Если длина 10 -> считаем, что это без кода региона и добавляем +7.
        - Иначе возвращаем None.
        """
        if not text:
            return None
        s = re.sub(r"\D", "", text)
        if len(s) == 11 and s[0] in ('7', '8'):
            return '+7' + s[-10:]
        if len(s) == 10:
            return '+7' + s
        return None

    def _fetch_members(self, page: int = 0, page_size: int = 10) -> Tuple[List[tuple], int]:
        """Вернуть страницу членов (rows, total_count).

        rows: список кортежей (id, surname, name, patronymic) для запрошенной страницы.
        total_count: общее количество записей в таблице members.
        """
        try:
            with self.db.get_cursor() as cur:
                # общее количество
                cur.execute('SELECT COUNT(*) FROM members')
                total = cur.fetchone()[0] or 0
                offset = page * page_size
                cur.execute(
                    'SELECT id, surname, name, patronymic FROM members ORDER BY surname COLLATE NOCASE ASC LIMIT ? OFFSET ?',
                    (page_size, offset)
                )
                rows = cur.fetchall()
                return rows, total
        except Exception:
            self.logger.exception('Ошибка при выборке членов из members')
            return [], 0

    def _build_members_markup(self, context=None) -> Optional[InlineKeyboardMarkup]:
        """Построить InlineKeyboard с пронумерованными членами, поддерживая пагинацию.

        Если передан context, читаем/сохраняем текущую страницу в context.user_data['control_room_members_page'].
        """
        page_size = 10
        # Получаем страницу из context, если доступно
        page = 0
        if context is not None:
            page = context.user_data.get('control_room_members_page', 0)
        if page < 0:
            page = 0
        # Подгружаем только требуемую страницу и общее количество
        rows, total = self._fetch_members(page=page, page_size=page_size)
        if not rows and total == 0:
            return None
        total_pages = (total - 1) // page_size + 1 if total > 0 else 1
        # Получаем страницу из context, если доступно
        if page >= total_pages:
            page = total_pages - 1
        if context is not None:
            context.user_data['control_room_members_page'] = page
            context.user_data['control_room_members_total_pages'] = total_pages

        kb = []
        # Пронумерованные глобально: индекс = page*page_size + idx_in_page + 1
        for idx_in_page, r in enumerate(rows):
            mid = r[0]
            surname = r[1] or ''
            name = r[2] or ''
            patron = r[3] or ''
            global_idx = page * page_size + idx_in_page + 1
            label = f"{global_idx}. {surname} {name} {patron}".strip()
            if len(label) > 63:
                label = label[:60] + '...'
            kb.append([InlineKeyboardButton(label, callback_data=f'control:member:{mid}')])

        # Кнопки с номерами всех страниц (показываем под списком)
        # Разбиваем номера по рядам, по 8 кнопок в ряд
        page_buttons = []
        row = []
        per_row = 8
        for p in range(total_pages):
            label = str(p + 1)
            # callback содержит целевую страницу (0-based)
            row.append(InlineKeyboardButton(label, callback_data=f'control:members:goto:{p}'))
            if len(row) >= per_row:
                page_buttons.append(row)
                row = []
        if row:
            page_buttons.append(row)

        kb.extend(page_buttons)

        # Навигация по страницам членов (предыдущая/текущая/следующая)
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton('◀️', callback_data=f'control:members:prev:{page}'))
        nav.append(InlineKeyboardButton(f'Стр. {page+1}/{total_pages}', callback_data='control:noop'))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton('▶️', callback_data=f'control:members:next:{page}'))
        kb.append(nav)

        kb.append([InlineKeyboardButton('Отмена', callback_data='control:refresh')])
        return InlineKeyboardMarkup(kb)

    def _parse_date_text(self, text: str) -> Optional[date]:
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
