from db.database import Database
from verification_id import VerificationID
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def escape_html(text: str) -> str:
    """Простая эскейп-функция для HTML-опасных символов (заменяет &<>"').

    Используется вместо внешней зависимости, чтобы безопасно формировать HTML-сообщения.
    """
    if text is None:
        return ''
    s = str(text)
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')

from datetime import date, timedelta
import asyncio
import re
import logging
import traceback
from typing import Optional, Tuple, List
from control_room.create_table import ensure_chart_table
from admin_notify import notify_admin
from control_room.messages import (
    GREETING,
    ACCESS_DENIED,
    NO_REQUESTS,
    CREATE_INSTRUCTION,
    LIST_HEADER,
    VALUE_UPDATED,
    RECORD_DELETED,
    DELETE_CANCELLED,
    ACTION_CANCELLED,
    CREATED_SUCCESS,
    ERROR_DB_ACCESS_PREFIX,
    SELECT_DATE,
    SELECT_NEW_DATE,
    SELECT_CUSTOMER,
    SELECT_SHOW_CUSTOMERS,
    INVALID_DATE_FORMAT,
    SELECT_ADDRESS_FROM,
    SELECT_ADDRESS_FROM_MANUAL,
    SELECT_ADDRESS_TO,
    SELECT_ADDRESS_TO_MANUAL,
    SELECT_PHONE,
    PAGE_INVALID_NUMBER,
    PAGE_NUMBER_POSITIVE,
    PAGE_NOT_FOUND,
    MEMBERS_LIST_PAGED,
    MEMBERS_LIST_EMPTY,
    INVALID_SELECTION,
    ENTER_FIELD_NUMBER_PROMPT,
    FIELD_NUMBER_OUT_OF_RANGE,
    INVALID_SELECTION_START_OVER,
    CHOOSE_ACTION_FOR_RECORD,
    CHOOSE_FIELD_PROMPT,
)
from telegram.error import BadRequest
from control_room import departure_time


class ControlRoom:
    """Класс, обрабатывающий диспетчерскую: проверка роли, вывод и создание таблицы chart, показ заявок."""

    def __init__(self):
        self.db = Database()
        self.logger = logging.getLogger(__name__)
        # Текст приветствия, который нельзя удалять
        self._greeting_text = GREETING

    async def _purge_control_room_messages(self, update, context) -> None:
        """Удалить все ранее сохранённые ботом сообщения в этом модуле, кроме приветствия.

        Хранится в context.user_data['control_room_sent_messages'] как список словарей
        {'chat_id': ..., 'message_id': ..., 'text': ...}.
        """
        try:
            bot = getattr(context, 'bot', None)
            if bot is None:
                return
            # Соберём записи из user_data и chat_data (чтобы приветствие, отправленное в start_command, учитывалось)
            stored_user = context.user_data.get('control_room_sent_messages', []) or []
            stored_chat = getattr(context, 'chat_data', {}).get('control_room_sent_messages', []) or []
            try:
                self.logger.debug(f"_purge_control_room_messages: stored_user={len(stored_user)}, stored_chat={len(stored_chat)}")
            except Exception:
                pass
            combined = []
            seen = set()
            for e in (stored_user + stored_chat):
                cid = e.get('chat_id')
                mid = e.get('message_id')
                key = (cid, mid)
                if key in seen:
                    continue
                seen.add(key)
                combined.append(e)

            keep = []
            for e in combined:
                try:
                    if e.get('text') == self._greeting_text:
                        keep.append(e)
                        continue
                    await bot.delete_message(chat_id=e.get('chat_id'), message_id=e.get('message_id'))
                    try:
                        self.logger.debug(f"_purge_control_room_messages: deleted chat_id={e.get('chat_id')} message_id={e.get('message_id')}")
                    except Exception:
                        pass
                except Exception as ex:
                    # Если сообщение уже удалено — не шумим ошибкой, просто пропускаем
                    try:
                        if isinstance(ex, BadRequest) and 'Message to delete not found' in str(ex):
                            try:
                                self.logger.debug(f"_purge_control_room_messages: message not found, skipping {e}")
                            except Exception:
                                pass
                            continue
                    except Exception:
                        pass
                    # не критично, просто логируем и не включаем в keep
                    try:
                        self.logger.exception(f"Не удалось удалить сообщение {e}")
                    except Exception:
                        pass
            # Сохраняем только те, которые нужно оставить (например, приветствие)
            try:
                context.user_data['control_room_sent_messages'] = keep
            except Exception:
                pass
            try:
                if hasattr(context, 'chat_data'):
                    context.chat_data['control_room_sent_messages'] = keep
            except Exception:
                pass
        except Exception:
            try:
                self.logger.exception('Ошибка при очистке старых сообщений control_room')
                try:
                    await notify_admin(context, 'Ошибка при очистке старых сообщений control_room', traceback.format_exc())
                except Exception:
                    pass
            except Exception:
                pass

    async def _record_sent_message(self, context, sent, text: str) -> None:
        """Сохранить отправленное сообщение в context.user_data для последующей очистки."""
        try:
            if not getattr(sent, 'chat', None):
                return
            entry = {'chat_id': sent.chat.id, 'message_id': sent.message_id, 'text': text}
            lst = context.user_data.get('control_room_sent_messages', [])
            lst.append(entry)
            context.user_data['control_room_sent_messages'] = lst
            try:
                self.logger.debug(f"_record_sent_message: saved chat_id={sent.chat.id} message_id={sent.message_id} text={text[:60]!r}")
            except Exception:
                pass
        except Exception:
            try:
                self.logger.exception('Ошибка при сохранении отправленного сообщения')
                try:
                    await notify_admin(context, 'Ошибка при сохранении отправленного сообщения (control_room)', traceback.format_exc())
                except Exception:
                    pass
            except Exception:
                pass

    async def _send_and_track(self, context, msg_obj, text: str, reply_markup=None):
        """Удаляет старые сообщения, отправляет новое и сохраняет его для последующей очистки."""
        try:
            # Очистим предыдущие сообщения перед отправкой нового (гарантированный вызов)
            await self._purge_control_room_messages(None, context)
        except Exception:
            # Логируем и оповещаем администратора — нельзя тихо проглатывать ошибку очистки
            try:
                self.logger.exception('Ошибка при предварительной очистке сообщений перед отправкой (send_and_track)')
            except Exception:
                pass
            try:
                await notify_admin(context, 'Ошибка при предварительной очистке сообщений перед отправкой (control_room)', traceback.format_exc())
            except Exception:
                pass
        try:
            sent = await msg_obj.reply_text(text, reply_markup=reply_markup)
            try:
                await self._record_sent_message(context, sent, text)
            except Exception:
                pass
            return sent
        except Exception:
            # fallback: если отправка не удалась — пробуем без markup
            try:
                sent = await msg_obj.reply_text(text)
                try:
                    await self._record_sent_message(context, sent, text)
                except Exception:
                    pass
                return sent
            except Exception:
                self.logger.exception('Не удалось отправить и сохранить сообщение')
                try:
                    await notify_admin(context, 'Не удалось отправить и сохранить сообщение (control_room)', traceback.format_exc())
                except Exception:
                    pass
                return None

    async def _safe_edit_query(self, query, context, text: str, reply_markup=None, **kwargs):
        """Безопасно редактировать сообщение через CallbackQuery; при отсутствии сообщения — fallback на отправку нового."""
        try:
            return await query.edit_message_text(text, reply_markup=reply_markup, **kwargs)
        except Exception as e:
            try:
                # Специально обрабатываем момент, когда сообщение уже не найдено
                if isinstance(e, BadRequest) and 'Message to edit not found' in str(e):
                    try:
                        msg = getattr(query, 'message', None)
                        if msg:
                            return await self._send_and_track(context, msg, text, reply_markup=reply_markup)
                        return None
                    except Exception:
                        self.logger.exception('Fallback send failed after edit failure')
                        try:
                            await notify_admin(context, 'Fallback send failed after edit failure (control_room)', traceback.format_exc())
                        except Exception:
                            pass
                        return None
            except Exception:
                # Если проверка типа упала по каким-то причинам — продолжаем общую обработку
                pass
            # Для прочих ошибок — логируем и оповещаем администратора
            try:
                self.logger.exception('Ошибка при попытке edit_message_text через query')
            except Exception:
                pass
            try:
                await notify_admin(context, 'Ошибка при редактировании сообщения (control_room)', traceback.format_exc())
            except Exception:
                pass
            raise

    def _move_chart_to_archive(self, cursor, row_id) -> bool:
        """Переместить запись из chart в chart_archive (копирование + удаление).

        Возвращает True если запись была успешно перемещена, иначе False.
        """
        try:
            cursor.execute('SELECT id, date, where_from, departure_time, "where", arrival_time, departure_datetime, customer, phone FROM chart WHERE id = ?', (row_id,))
            row = cursor.fetchone()
            if not row:
                return False
            # row: (id, date, where_from, departure_time, where, arrival_time, departure_datetime, customer, phone)
            _, date_val, where_from_val, departure_time_val, where_val, arrival_time_val, departure_datetime_val, customer_val, phone_val = row
            cursor.execute(
                'INSERT INTO chart_archive (original_id, date, where_from, departure_time, "where", arrival_time, departure_datetime, customer, phone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (row_id, date_val, where_from_val, departure_time_val, where_val, arrival_time_val, departure_datetime_val, customer_val, phone_val)
            )
            cursor.execute('DELETE FROM chart WHERE id = ?', (row_id,))
            return True
        except Exception:
            try:
                self.logger.exception(f'Ошибка при перемещении записи chart id={row_id} в архив')
            except Exception:
                pass
            return False

    async def start(self, update, context) -> None:
        # Проверяем роль пользователя, аналогично admin_message
        verifier = VerificationID()
        role = await verifier.check_role(update, context)
        if role not in ("admin", "super admin"):
            msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
            await self._send_and_track(context, msg, ACCESS_DENIED)
            return

        # Убедимся, что есть подключение к БД
        # Перед показом новой информации удаляем старые сообщения, кроме приветствия
        try:
            await self._purge_control_room_messages(update, context)
        except Exception:
            self.logger.exception('Ошибка при предварительной очистке сообщений')
            try:
                await notify_admin(context, 'Ошибка при предварительной очистке сообщений (control_room)', traceback.format_exc())
            except Exception:
                pass

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
                    # Архивируем просроченные заявки: сперва выбираем их id, затем по каждой переносим в chart_archive
                    cursor.execute('SELECT id FROM chart WHERE date IS NOT NULL AND date <> "" AND date < ?', (today_iso,))
                    expired = cursor.fetchall()
                    archived_count = 0
                    for er in expired:
                        try:
                            rid = er[0]
                            moved = self._move_chart_to_archive(cursor, rid)
                            if moved:
                                archived_count += 1
                        except Exception:
                            # локально логируем и продолжаем
                            try:
                                self.logger.exception(f'Не удалось архивировать запись id={er[0]}')
                            except Exception:
                                pass
                    if archived_count:
                        self.logger.info(f'Архивировано просроченных заявок: {archived_count}')
                except Exception:
                    self.logger.exception('Ошибка при архивировании просроченных заявок')
                    try:
                        await notify_admin(context, 'Ошибка при архивировании просроченных заявок (control_room)', traceback.format_exc())
                    except Exception:
                        pass

                cursor.execute('SELECT id, date, departure_time, where_from FROM chart ORDER BY date ASC, departure_time ASC')
                rows = cursor.fetchall()
                if not rows:
                    msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
                    await self._send_and_track(context, msg, NO_REQUESTS)
                    await self._send_and_track(context, msg, CREATE_INSTRUCTION)
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
                text = LIST_HEADER
                # Если вызвано из CallbackQuery — редактируем текущее сообщение, иначе отправляем новое
                if getattr(update, 'callback_query', None):
                    try:
                        await self._safe_edit_query(update.callback_query, context, text, reply_markup=markup)
                    except Exception:
                        msg = update.callback_query.message
                        self.logger.exception('Не удалось отредактировать сообщение списка, отправляем новое')
                        try:
                            await notify_admin(context, 'Не удалось отредактировать сообщение списка (control_room)', traceback.format_exc())
                        except Exception:
                            pass
                        # Попробуем отправить новое сообщение как fallback
                        try:
                            await self._send_and_track(context, msg, text, reply_markup=markup)
                        except Exception:
                            self.logger.exception('Fallback reply_text также не удался')
                            try:
                                await notify_admin(context, 'Fallback reply_text также не удался (control_room)', traceback.format_exc())
                            except Exception:
                                pass
                else:
                    msg = update.message
                    try:
                        await self._send_and_track(context, msg, text, reply_markup=markup)
                    except Exception:
                        self.logger.exception('Не удалось отправить сообщение списка заявок')
                        try:
                            await notify_admin(context, 'Не удалось отправить сообщение списка заявок (control_room)', traceback.format_exc())
                        except Exception:
                            pass
        except Exception as e:
            msg = update.callback_query.message if getattr(update, 'callback_query', None) else update.message
            self.logger.exception('Ошибка доступа к базе данных')
            try:
                await notify_admin(context, 'Ошибка доступа к базе данных (control_room)', traceback.format_exc())
            except Exception:
                pass
            await self._send_and_track(context, msg, f'{ERROR_DB_ACCESS_PREFIX} {e}')

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
                    await self._send_and_track(context, msg, PAGE_INVALID_NUMBER)
                    return True
                if page_num <= 0:
                    await self._send_and_track(context, msg, PAGE_NUMBER_POSITIVE)
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
                    await self._send_and_track(context, msg, PAGE_NOT_FOUND.format(total_pages=total_pages))
                    return True
                # Nустановить страницу и показать клавиатуру членов
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
                        except Exception as e:
                            # Если сообщение не найдено — делаем fallback отправкой нового сообщения
                            try:
                                if isinstance(e, BadRequest) and 'Message to edit not found' in str(e):
                                    pass
                            except Exception:
                                pass
                            # fallback: отправим новое сообщение и обновим stored
                            sent = await self._send_and_track(context, msg, MEMBERS_LIST_PAGED.format(page=page_num, total=total_pages), reply_markup=kb)
                            if getattr(sent, 'chat', None):
                                context.user_data['control_room_members_message'] = (sent.chat.id, sent.message_id)
                    else:
                        sent = await self._send_and_track(context, msg, MEMBERS_LIST_PAGED.format(page=page_num, total=total_pages), reply_markup=kb)
                        if getattr(sent, 'chat', None):
                            context.user_data['control_room_members_message'] = (sent.chat.id, sent.message_id)
                else:
                    await self._send_and_track(context, msg, MEMBERS_LIST_EMPTY)
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
                    await self._send_and_track(context, msg, INVALID_SELECTION)
                else:
                    row_id = ids[sel - 1]
                    try:
                        with self.db.get_cursor() as cursor:
                            moved = self._move_chart_to_archive(cursor, row_id)
                        if moved:
                            await self._send_and_track(context, msg, RECORD_DELETED)
                        else:
                            await self._send_and_track(context, msg, 'Ошибка при удалении/архивации записи.')
                    except Exception as e:
                        await self._send_and_track(context, msg, f'Ошибка при удалении: {e}')
                # очистим флаги и обновим список
                context.user_data.pop('control_room_awaiting_delete_confirm', None)
                context.user_data.pop('control_room_selected_index', None)
                await self.start(update, context)
            else:
                await self._send_and_track(context, msg, DELETE_CANCELLED)
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
                await self._send_and_track(context, msg, ENTER_FIELD_NUMBER_PROMPT)
                return True
            fields = [f[0] for f in self.fields]
            if choice < 1 or choice > len(fields):
                await self._send_and_track(context, update.message, FIELD_NUMBER_OUT_OF_RANGE)
                return True
            field_key = fields[choice - 1]
            # Проверим выбранную запись
            sel = context.user_data.get('control_room_selected_index')
            ids = context.user_data.get('control_room_rows_ids', [])
            if not ids or sel is None or sel < 1 or sel > len(ids):
                await self._send_and_track(context, update.message, INVALID_SELECTION_START_OVER)
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
            await self._send_and_track(context, msg, prompt)
            return True

        # Обработка ввода нового значения поля при редактировании
        if context.user_data.get('control_room_awaiting_new_value'):
            new_value = msg.text.strip()
            field = context.user_data.get('control_room_edit_field')
            sel = context.user_data.get('control_room_selected_index')
            ids = context.user_data.get('control_room_rows_ids', [])
            if not field or sel is None or not ids or sel < 1 or sel > len(ids):
                await self._send_and_track(context, msg, 'Ошибка состояния. Попробуйте заново.')
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
                    await self._send_and_track(context, msg, 'Неверный формат даты. Введите YYYY-MM-DD или DD.MM.YYYY или используйте кнопки.')
                    kb = self._build_quickdate_markup()
                    await self._send_and_track(context, msg, SELECT_DATE, reply_markup=kb)
                    return True
                if self._is_past_date(parsed):
                    await self._send_and_track(context, msg, 'Выбранная дата в прошлом. Укажите текущую или будущую дату.')
                    kb = self._build_quickdate_markup()
                    await self._send_and_track(context, msg, SELECT_DATE, reply_markup=kb)
                    return True
                new_value = parsed.isoformat()
            # Если редактируем телефон — нормализуем и провалидируем
            if field == 'phone':
                norm_phone = self._validate_phone(new_value)
                if not norm_phone:
                    await self._send_and_track(context, msg, 'Неверный формат телефона. Введите телефон в формате +7XXXXXXXXXX или 10 цифр.')
                    return True
                new_value = norm_phone
            # Подготовим имя столбца с экранированием, если нужно
            # Защита: разрешённые имена полей — только из описанных в fields
            allowed_cols = {f[0] for f in self.fields} | {'where_from', 'arrival_time'}
            if field not in allowed_cols:
                await self._send_and_track(context, msg, 'Недопустимое имя поля для редактирования.')
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
                await self._send_and_track(context, msg, VALUE_UPDATED)
            except Exception as e:
                await self._send_and_track(context, msg, f'Ошибка при обновлении: {e}')
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
                await self._send_and_track(context, msg, CHOOSE_ACTION_FOR_RECORD)
            except ValueError:
                await self._send_and_track(context, msg, 'Введите корректный номер записи, 0 или 00.')
            return True

        # Обработка выбора действия после выбора записи (редактировать/удалить/отмена)
        if context.user_data.get('control_room_awaiting_action_choice'):
            text = msg.text.strip()
            if text == '0':
                await self._send_and_track(context, msg, ACTION_CANCELLED)
                context.user_data.pop('control_room_awaiting_action_choice', None)
                context.user_data.pop('control_room_selected_index', None)
                # Вернёмся к списку заявок
                await self.start(update, context)
                return True
            if text == '2':
                # Запрос подтверждения удаления
                context.user_data.pop('control_room_awaiting_action_choice', None)
                context.user_data['control_room_awaiting_delete_confirm'] = True
                await self._send_and_track(context, msg, 'Подтвердите удаление: введите "да" для подтверждения или "нет" для отмены.')
                return True
            if text == '1':
                # Начать редактирование: показать список полей с дружелюбными названиями
                context.user_data.pop('control_room_awaiting_action_choice', None)
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await self._send_and_track(context, update.message, INVALID_SELECTION)
                    context.user_data.pop('control_room_selected_index', None)
                    return True
                prompt = CHOOSE_FIELD_PROMPT
                for i, f in enumerate(self.fields, 1):
                    key = f[0]
                    label = self.FIELD_LABELS.get(key, key) if hasattr(self, 'FIELD_LABELS') else key
                    prompt += f"{i}. {label}\n"
                await self._send_and_track(context, update.message, prompt)
                context.user_data['control_room_awaiting_field_choice'] = True
                return True
            await self._send_and_track(context, update.message, 'Введите 1 (редактировать), 2 (удалить) или 0 (отмена).')
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
        # Обработка пропуска ввода времени прибытия при создании заявки
        if action == 'create_skip_arrival':
            try:
                # Только в процессе создания заявки уместно пропускать arrival_time
                if context.user_data.get('control_room_create_in_progress'):
                    step = context.user_data.get('control_room_create_step', 0)
                    key = self.fields[step][0] if 0 <= step < len(self.fields) else None
                    if key != 'arrival_time':
                        try:
                            await query.answer('Нечего пропускать в данный момент')
                        except Exception:
                            pass
                        return
                    try:
                        await query.answer('Пропущено')
                    except Exception:
                        pass
                    await self._advance_create_with_value(update, context, '-')
                    return
                else:
                    try:
                        await query.answer()
                    except Exception:
                        pass
                    return
            except Exception:
                self.logger.exception('Ошибка при обработке create_skip_arrival')
                try:
                    await notify_admin(context, 'Ошибка при обработке create_skip_arrival (control_room)', traceback.format_exc())
                except Exception:
                    pass
                return
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
                await self._safe_edit_query(query, context, 'Некорректный номер записи.')
                return
            ids = context.user_data.get('control_room_rows_ids', [])
            if not ids or idx < 1 or idx > len(ids):
                await self._safe_edit_query(query, context, 'Неверный индекс записи.')
                return
            row_id = ids[idx - 1]
            # Получим полную запись
            with self.db.get_cursor() as cur:
                cur.execute('SELECT id, date, where_from, departure_time, "where", arrival_time, customer, phone FROM chart WHERE id = ?', (row_id,))
                row = cur.fetchone()
            if not row:
                await self._safe_edit_query(query, context, 'Запись не найдена.')
                return
            # Сформируем текст с дружественными названиями (экранируем HTML)
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
                        pass
                # Экранируем для HTML
                esc_label = escape_html(str(label))
                esc_val = escape_html(str(display_val))
                text_lines.append(f"{esc_label}: {esc_val}")
            text = '<b>Карточка заявки:</b>\n' + '\n'.join(text_lines)
            # Inline buttons: Edit, Delete, Back
            kb = [
                [InlineKeyboardButton('Редактировать', callback_data=f'control:edit:{idx}') , InlineKeyboardButton('Удалить', callback_data=f'control:delete:{idx}')],
                [InlineKeyboardButton('◀️ Назад', callback_data='control:refresh')]
            ]
            await self._safe_edit_query(query, context, text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            return
        if action == 'create':
            # Запустить текстовый поток создания
            context.user_data.pop('control_room_awaiting_choice', None)
            await self._send_and_track(context, query.message, 'Запуск создания заявки.')
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
                    await self._safe_edit_query(query, context, 'Некорректный номер страницы.')
                except Exception:
                    self.logger.exception('Не удалось сообщить об ошибке номера страницы')
                    try:
                        await notify_admin(context, 'Не удалось сообщить об ошибке номера страницы (control_room)', traceback.format_exc())
                    except Exception:
                        pass
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
                await self._safe_edit_query(query, context, 'Переходим на страницу...')
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
                chosen = None
                if token == 'today':
                    chosen = date.today()
                elif token == 'tomorrow':
                    chosen = date.today() + timedelta(days=1)
                elif token == 'plus2':
                    chosen = date.today() + timedelta(days=2)
                elif token == 'plus3':
                    chosen = date.today() + timedelta(days=3)
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
                await self._send_and_track(context, query.message, f'Выбрана дата: {disp}')
                await self._advance_create_with_value(update, context, iso)
                return
            # Если ожидаем новое значение при редактировании поля date
            if context.user_data.get('control_room_awaiting_new_value') and context.user_data.get('control_room_edit_field') == 'date':
                chosen = None
                if token == 'today':
                    chosen = date.today()
                elif token == 'tomorrow':
                    chosen = date.today() + timedelta(days=1)
                elif token == 'plus2':
                    chosen = date.today() + timedelta(days=2)
                elif token == 'plus3':
                    chosen = date.today() + timedelta(days=3)
                else:
                    await query.answer('Неизвестная опция даты')
                    return
                iso = chosen.isoformat()
                # Выполним UPDATE для выбранной записи
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await self._send_and_track(context, query.message, 'Ошибка состояния. Попробуйте снова.')
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
                    await self._send_and_track(context, query.message, VALUE_UPDATED)
                except Exception as e:
                    await self._send_and_track(context, query.message, f'Ошибка при обновлении: {e}')
                # Очистим состояние редактирования и обновим список
                for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                    context.user_data.pop(k, None)
                await self.start(update, context)
                return
        # Обработка выбора/показа селектора времени отправления
        if action == 'departure_time' and len(parts) >= 3:
            sub = parts[2]
            try:
                if sub == 'choose':
                    # Показать интерфейс выбора времени (в модуле departure_time)
                    try:
                        await departure_time.show_picker(self, update, context)
                    except Exception:
                        self.logger.exception('Ошибка при показе селектора времени (departure_time.choose)')
                        try:
                            await notify_admin(context, 'Ошибка при показе селектора времени (control_room)', traceback.format_exc())
                        except Exception:
                            pass
                    return
                if sub == 'pick' and len(parts) >= 4:
                    time_token = parts[3]
                    try:
                        await departure_time.handle_pick(self, update, context, time_token)
                    except Exception:
                        self.logger.exception('Ошибка при обработке выбора времени (departure_time.pick)')
                        try:
                            await notify_admin(context, 'Ошибка при обработке выбора времени (control_room)', traceback.format_exc())
                        except Exception:
                            pass
                    return
            except Exception:
                self.logger.exception('Ошибка в обработчике departure_time')
                return
        # Показать весь список членов по запросу: control:members:show
        if action == 'members' and len(parts) >= 3 and parts[2] == 'show':
            try:
                # Пометим, что мы показали пользователю полный список членов —
                # ожидаем, что он может ввести номер страницы в чат
                if context is not None:
                    context.user_data['control_room_showing_members'] = True
                    # при показе полного списка предыдущим представлением считается компактное меню членов
                    context.user_data['control_room_prev_view'] = 'members_small'
                    kb = self._build_members_markup(context=context)
                if kb:
                    try:
                        await self._safe_edit_query(query, context, 'Список членов:', reply_markup=kb)
                        # Сохраним идентификатор сообщения, которое содержит список членов,
                        # чтобы позже редактировать его вместо отправки нового
                        if context is not None and getattr(query, 'message', None):
                            context.user_data['control_room_members_message'] = (query.message.chat.id, query.message.message_id)
                    except Exception:
                        # если редактировать не удалось — отправим новое сообщение
                        msg = query.message
                        await self._send_and_track(context, msg, 'Список членов:', reply_markup=kb)
                        if context is not None and getattr(msg, 'chat', None):
                            context.user_data['control_room_members_message'] = (msg.chat.id, msg.message_id)
                else:
                    try:
                        await self._safe_edit_query(query, context, MEMBERS_LIST_EMPTY)
                    except Exception:
                        await self._send_and_track(context, query.message, MEMBERS_LIST_EMPTY)
            except Exception:
                self.logger.exception('Ошибка при показе списка членов')
                try:
                    await notify_admin(context, 'Ошибка при показе списка членов (control_room)', traceback.format_exc())
                except Exception:
                    pass
            return
        # Показать часто набираемых членов: control:members:frequent
        if action == 'members' and len(parts) >= 3 and parts[2] == 'frequent':
            try:
                # отмечаем, что показан список членов
                if context is not None:
                    context.user_data['control_room_showing_members'] = True
                    # при показе часто набираемых предыдущим представлением считается компактное меню членов
                    context.user_data['control_room_prev_view'] = 'members_small'
                with self.db.get_cursor() as cur:
                    cur.execute('''
                        SELECT m.id, m.surname, m.name, m.patronymic
                        FROM customers_rating cr
                        JOIN members m ON cr.customer_id = m.id
                        ORDER BY cr.rating DESC
                        LIMIT 50
                    ''')
                    rows = cur.fetchall()
            except Exception:
                self.logger.exception('Ошибка при выборке часто набираемых членов')
                try:
                    await notify_admin(context, 'Ошибка при выборке часто набираемых членов (control_room)', traceback.format_exc())
                except Exception:
                    pass
                await query.answer('Ошибка доступа к базе членов')
                return
                if not rows:
                    try:
                        await self._safe_edit_query(query, context, 'Список часто набираемых пуст.')
                    except Exception:
                        await self._send_and_track(context, query.message, 'Список часто набираемых пуст.')
                return
            kb = []
            for r in rows:
                mid = r[0]
                surname = r[1] or ''
                name = r[2] or ''
                patron = r[3] or ''
                label = f"{surname} {name} {patron}".strip()
                if len(label) > 63:
                    label = label[:60] + '...'
                kb.append([InlineKeyboardButton(label, callback_data=f'control:member:{mid}')])
            kb.append([InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')])
            try:
                await self._safe_edit_query(query, context, 'Часто набираемые:', reply_markup=InlineKeyboardMarkup(kb))
                if context is not None and getattr(query, 'message', None):
                    context.user_data['control_room_members_message'] = (query.message.chat.id, query.message.message_id)
            except Exception:
                await self._send_and_track(context, query.message, 'Часто набираемые:', reply_markup=InlineKeyboardMarkup(kb))
            return

        # Обработка кнопки "Назад" -> возвращаемся к предыдущему представлению (если известно)
        if action == 'back':
            prev = context.user_data.get('control_room_prev_view')
            try:
                if prev == 'members_small':
                    # Показать компактное меню выбора заказчика
                    kb_small = InlineKeyboardMarkup([
                        [InlineKeyboardButton('📋 Показать весь список', callback_data='control:members:show'), InlineKeyboardButton('🔝 Часто набираемые', callback_data='control:members:frequent')],
                        [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                    ])
                    try:
                        await self._safe_edit_query(query, context, SELECT_SHOW_CUSTOMERS, reply_markup=kb_small)
                    except Exception:
                                await self._send_and_track(context, query.message, SELECT_SHOW_CUSTOMERS, reply_markup=kb_small)
                                try:
                                    await notify_admin(context, 'Не удалось отредактировать сообщение списка заказчиков (control_room)', traceback.format_exc())
                                except Exception:
                                    pass
                    return
            except Exception:
                self.logger.exception('Ошибка при обработке кнопки Назад')
            # fallback: показать основной список
            try:
                await query.answer()
            except Exception:
                pass
            await self.start(update, context)
            return
        # Показать все адреса из таблицы addresses как Inline-кнопки
        if action == 'addresses' and len(parts) >= 3 and parts[2] == 'showall':
            # опционально принимаем направление в parts[3]
            direction = parts[3] if len(parts) >= 4 else 'отпр'
            try:
                with self.db.get_cursor() as cur:
                    cur.execute('SELECT id, address FROM addresses ORDER BY address COLLATE NOCASE ASC')
                    rows = cur.fetchall()
            except Exception:
                self.logger.exception('Ошибка при выборке всех адресов')
                await query.answer('Ошибка доступа к базе адресов')
                return
            if not rows:
                try:
                    await self._safe_edit_query(query, context, 'Список адресов пуст.')
                except Exception:
                    await self._send_and_track(context, query.message, 'Список адресов пуст.')
                return
            kb = []
            for r in rows:
                aid, addr = r[0], r[1] or ''
                label = addr if len(addr) <= 63 else addr[:60] + '...'
                # Включаем direction в callback, чтобы при выборе из полного списка направление было явно задано
                kb.append([InlineKeyboardButton(label, callback_data=f'control:address:{aid}:{direction}')])
            kb.append([InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')])
            try:
                await self._safe_edit_query(query, context, 'Все адреса:', reply_markup=InlineKeyboardMarkup(kb))
            except Exception:
                await self._send_and_track(context, query.message, 'Все адреса:', reply_markup=InlineKeyboardMarkup(kb))
            return
        # Обработка навигации списка членов: control:members:prev:<cur_page> и control:members:next:<cur_page>
        if action == 'members' and len(parts) >= 4:
            direction = parts[2]
            try:
                cur_page = int(parts[3])
            except Exception:
                try:
                    await self._safe_edit_query(query, context, 'Некорректный номер страницы.')
                except Exception:
                    self.logger.exception('Не удалось сообщить об ошибке номера страницы (members)')
                    try:
                        await notify_admin(context, 'Не удалось сообщить об ошибке номера страницы (members, control_room)', traceback.format_exc())
                    except Exception:
                        pass
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
                        await self._safe_edit_query(query, context, 'Список членов:', reply_markup=kb)
                        # обновим хранение message id
                        if context is not None and getattr(query, 'message', None):
                            context.user_data['control_room_members_message'] = (query.message.chat.id, query.message.message_id)
                    except Exception:
                        # если редактирование не удалось — отправим новое сообщение
                        msg = query.message
                        await self._send_and_track(context, msg, 'Список членов:', reply_markup=kb)
                        if context is not None and getattr(msg, 'chat', None):
                            # note: sent message id will be stored by _send_and_track via _record_sent_message
                            pass
                else:
                    try:
                        await self._safe_edit_query(query, context, MEMBERS_LIST_EMPTY)
                    except Exception:
                        await self._send_and_track(context, query.message, MEMBERS_LIST_EMPTY)
            except Exception:
                self.logger.exception('Ошибка при перерисовке списка членов')
                try:
                    await notify_admin(context, 'Ошибка при перерисовке списка членов (control_room)', traceback.format_exc())
                except Exception:
                    pass
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
                try:
                    await notify_admin(context, 'Ошибка при чтении members (control_room)', traceback.format_exc())
                except Exception:
                    pass
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
                # Сохраним id выбранного заказчика для последующих привязок адресов
                context.user_data['control_room_create_customer_id'] = member_id
                # Обновить/вставить рейтинг в customers_rating
                try:
                    with self.db.get_cursor() as cur:
                        cur.execute(
                            'INSERT INTO customers_rating (customer_id, rating) VALUES (?, 1) '
                            'ON CONFLICT(customer_id) DO UPDATE SET rating = customers_rating.rating + 1',
                            (member_id,)
                        )
                except Exception:
                    self.logger.exception('Ошибка при обновлении customers_rating')
                    try:
                        await notify_admin(context, 'Ошибка при обновлении customers_rating (control_room)', traceback.format_exc())
                    except Exception:
                        pass
                await self._send_and_track(context, query.message, f'Выбран заказчик: {full_name}')
                await self._advance_create_with_value(update, context, full_name)
                # Свернём режим показа членов после выбора
                context.user_data.pop('control_room_showing_members', None)
                return
            # Если ожидаем новое значение при редактировании и редактируем поле customer
            if context.user_data.get('control_room_awaiting_new_value') and context.user_data.get('control_room_edit_field') == 'customer':
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await self._send_and_track(context, query.message, 'Ошибка состояния. Попробуйте снова.')
                    return
                row_id = ids[sel - 1]
                try:
                    with self.db.get_cursor() as cur:
                        cur.execute('UPDATE chart SET customer = ? WHERE id = ?', (full_name, row_id))
                    await self._send_and_track(context, query.message, VALUE_UPDATED)
                except Exception as e:
                    await self._send_and_track(context, query.message, f'Ошибка при обновлении: {e}')
                # Обновить/вставить рейтинг в customers_rating при редактировании поля customer
                try:
                    with self.db.get_cursor() as cur:
                        cur.execute(
                            'INSERT INTO customers_rating (customer_id, rating) VALUES (?, 1) '
                            'ON CONFLICT(customer_id) DO UPDATE SET rating = customers_rating.rating + 1',
                            (member_id,)
                        )
                except Exception:
                    self.logger.exception('Ошибка при обновлении customers_rating (edit)')
                    try:
                        await notify_admin(context, 'Ошибка при обновлении customers_rating (edit, control_room)', traceback.format_exc())
                    except Exception:
                        pass
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
        if action == 'address' and len(parts) >= 3:
            try:
                addr_id = int(parts[2])
            except Exception:
                await query.answer('Некорректный выбор')
                return
            # Опционально: direction может быть передан в callback как четвертый параметр
            direction_from_cb = parts[3] if len(parts) >= 4 else None
            # Получим адрес из таблицы
            try:
                with self.db.get_cursor() as cur:
                    cur.execute('SELECT address FROM addresses WHERE id = ?', (addr_id,))
                    ar = cur.fetchone()
            except Exception:
                self.logger.exception('Ошибка при чтении addresses')
                await query.answer('Ошибка доступа к базе адресов')
                return
            if not ar:
                await query.answer('Адрес не найден')
                return
            address_text = ar[0]
            # Если в процессе создания — вставим значение и продвинем шаг
            if context.user_data.get('control_room_create_in_progress'):
                # Если заранее выбран заказчик — обновим рейтинг привязки.
                # Direction: используем переданный в callback, если он есть, иначе вычисляем как раньше на основе шага
                cust_id = context.user_data.get('control_room_create_customer_id')
                try:
                    if direction_from_cb:
                        direction = direction_from_cb
                    else:
                        direction = 'отпр'
                        if context.user_data.get('control_room_create_in_progress'):
                            step_idx = context.user_data.get('control_room_create_step', -1)
                            if 0 <= step_idx < len(self.fields):
                                current_key = self.fields[step_idx][0]
                                if current_key == 'where':
                                    direction = 'назн'
                                elif current_key == 'where_from':
                                    direction = 'отпр'
                    if cust_id:
                        try:
                            with self.db.get_cursor() as cur:
                                cur.execute(
                                    'INSERT INTO customer_addresse (customer_id, addresse_id, direction, rating) VALUES (?, ?, ?, 1) '
                                    'ON CONFLICT(customer_id, addresse_id, direction) DO UPDATE SET rating = customer_addresse.rating + 1',
                                    (cust_id, addr_id, direction)
                                )
                        except Exception:
                            self.logger.exception('Ошибка при обновлении рейтинга customer_addresse')
                except Exception:
                    self.logger.exception('Ошибка при обработке рейтинга адреса')

                # Показываем краткое уведомление вместо постоянного сообщения
                try:
                    await query.answer(f'Выбран адрес: {address_text}', show_alert=False)
                except Exception:
                    # fallback: если query.answer недоступен — отправим сообщение
                    await self._send_and_track(context, query.message, f'Выбран адрес: {address_text}')
                await self._advance_create_with_value(update, context, address_text)
                # Свернём режим показа членов/адресов после выбора
                context.user_data.pop('control_room_showing_members', None)
                context.user_data.pop('control_room_members_message', None)
                return

            # Если ожидаем новое значение при редактировании и редактируем поле адреса (откуда/куда)
            if context.user_data.get('control_room_awaiting_new_value') and context.user_data.get('control_room_edit_field') in ('where_from', 'where'):
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    try:
                        await self._send_and_track(context, query.message, 'Ошибка состояния. Попробуйте снова.')
                    except Exception:
                        pass
                    return
                row_id = ids[sel - 1]
                # Определим имя колонки для обновления
                col_name = 'where_from' if context.user_data.get('control_room_edit_field') == 'where_from' else 'where'
                # Обновим запись в chart и сделаем upsert в customer_addresse (direction = 'отпр' для where_from, 'назн' для where)
                try:
                    with self.db.get_cursor() as cur:
                        # Обновляем поле в chart
                        cur.execute(f'UPDATE chart SET {col_name} = ? WHERE id = ?', (address_text, row_id))
                        # Попробуем определить id заказчика, указанный в этой записи
                        cur.execute('SELECT customer FROM chart WHERE id = ?', (row_id,))
                        crow = cur.fetchone()
                        cust_name = crow[0] if crow and crow[0] else None
                        cust_id = None
                        if cust_name:
                            try:
                                cur.execute("SELECT id FROM members WHERE TRIM(surname || ' ' || name || ' ' || COALESCE(patronymic, '')) = ?", (cust_name.strip(),))
                                mr = cur.fetchone()
                                if mr:
                                    cust_id = mr[0]
                            except Exception:
                                # Не критично, продолжим без cust_id
                                pass
                        direction = 'отпр' if col_name == 'where_from' else 'назн'
                        if cust_id:
                            # upsert в customer_addresse
                            cur.execute(
                                'INSERT INTO customer_addresse (customer_id, addresse_id, direction, rating) VALUES (?, ?, ?, 1) '
                                'ON CONFLICT(customer_id, addresse_id, direction) DO UPDATE SET rating = customer_addresse.rating + 1',
                                (cust_id, addr_id, direction)
                            )
                except Exception:
                    self.logger.exception('Ошибка при обновлении адреса (edit)')
                    try:
                        await self._send_and_track(context, query.message, 'Ошибка при обновлении адреса.')
                    except Exception:
                        pass
                    # очистим флаги и обновим список, даже при ошибке
                    for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                        context.user_data.pop(k, None)
                    await self.start(update, context)
                    return
                # Успешно обновлено
                try:
                    await self._send_and_track(context, query.message, VALUE_UPDATED)
                except Exception:
                    pass
                for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                    context.user_data.pop(k, None)
                await self.start(update, context)
                return
        if action == 'phone' and len(parts) >= 3:
            try:
                member_id = int(parts[2])
            except Exception:
                await query.answer('Некорректный выбор')
                return
            # Получим телефон из таблицы members
            try:
                with self.db.get_cursor() as cur:
                    cur.execute('SELECT phone FROM members WHERE id = ?', (member_id,))
                    pr = cur.fetchone()
            except Exception:
                self.logger.exception('Ошибка при чтении телефона из members')
                await query.answer('Ошибка доступа к базе')
                return
            phone_text = pr[0] if pr and pr[0] else None
            if not phone_text:
                await query.answer('Телефон не найден', show_alert=True)
                return
            # Если в процессе создания — вставим значение и продвинем шаг
            if context.user_data.get('control_room_create_in_progress'):
                # Используем answerCallbackQuery, чтобы не оставлять лишнее сообщение в чате
                try:
                    await query.answer(f'Выбран телефон: {phone_text}', show_alert=False)
                except Exception:
                    await self._send_and_track(context, query.message, f'Выбран телефон: {phone_text}')
                await self._advance_create_with_value(update, context, phone_text)
                return
            # Если ожидаем новое значение при редактировании и редактируем поле phone
            if context.user_data.get('control_room_awaiting_new_value') and context.user_data.get('control_room_edit_field') == 'phone':
                sel = context.user_data.get('control_room_selected_index')
                ids = context.user_data.get('control_room_rows_ids', [])
                if not ids or sel is None or sel < 1 or sel > len(ids):
                    await self._send_and_track(context, query.message, 'Ошибка состояния. Попробуйте снова.')
                    return
                row_id = ids[sel - 1]
                try:
                    with self.db.get_cursor() as cur:
                        cur.execute('UPDATE chart SET phone = ? WHERE id = ?', (phone_text, row_id))
                    await self._send_and_track(context, query.message, VALUE_UPDATED)
                except Exception as e:
                    await self._send_and_track(context, query.message, f'Ошибка при обновлении: {e}')
                for k in ('control_room_awaiting_new_value','control_room_edit_field','control_room_selected_index'):
                    context.user_data.pop(k, None)
                await self.start(update, context)
                return
            # Иначе просто подтвердим телефон
            try:
                await query.answer(f'Телефон: {phone_text}')
            except Exception:
                pass
            return
        if action == 'refresh':
            # Повторно показать список
            try:
                # Редактируем текущее сообщение, чтобы показать, что идёт обновление
                await self._safe_edit_query(query, context, 'Обновляю список...')
            except Exception:
                # Если редактировать не удалось, пропустим — всё равно покажем новый список
                pass
            # При обновлении списка скрываем состояние показа членов
            if context is not None:
                context.user_data.pop('control_room_showing_members', None)
            # Затем покажем актуальный список (start сам отправит новое сообщение)
            await self.start(update, context)
            return
        # Обработчик: вставить адрес из поля members (для выбранного заказчика) в поле заявки
        if action == 'address_insert' and len(parts) >= 3:
            sub = parts[2]
            try:
                if sub == 'from_member':
                    direction = parts[3] if len(parts) >= 4 else 'отпр'
                    # Проверим, есть ли выбранный заказчик в процессе создания
                    cust_id = context.user_data.get('control_room_create_customer_id')
                    if not cust_id:
                        try:
                            await query.answer('Заказчик не выбран', show_alert=True)
                        except Exception:
                            pass
                        return
                    # Получим адрес из карточки члена
                    try:
                        with self.db.get_cursor() as cur:
                            cur.execute('SELECT address FROM members WHERE id = ?', (cust_id,))
                            mr = cur.fetchone()
                            addr_text = mr[0] if mr and mr[0] else None
                            if not addr_text:
                                try:
                                    await query.answer('В карточке заказчика не найден адрес', show_alert=True)
                                except Exception:
                                    pass
                                return
                            # Сохраним адрес в таблице addresses, если ещё не существует
                            cur.execute('SELECT id FROM addresses WHERE address = ?', (addr_text,))
                            ar = cur.fetchone()
                            if ar:
                                addr_id = ar[0]
                            else:
                                cur.execute('INSERT INTO addresses (address) VALUES (?)', (addr_text,))
                                addr_id = cur.lastrowid
                            # Обновим/вставим привязку в customer_addresse
                            try:
                                cur.execute(
                                    'INSERT INTO customer_addresse (customer_id, addresse_id, direction, rating) VALUES (?, ?, ?, 1) '
                                    'ON CONFLICT(customer_id, addresse_id, direction) DO UPDATE SET rating = customer_addresse.rating + 1',
                                    (cust_id, addr_id, direction)
                                )
                            except Exception:
                                # не критично — продолжим
                                pass
                    except Exception:
                        try:
                            self.logger.exception('Ошибка при вставке адреса из members')
                        except Exception:
                            pass
                        try:
                            await query.answer('Ошибка при доступе к базе', show_alert=True)
                        except Exception:
                            pass
                        return
                    # Уведомим пользователя видимым сообщением и продвинем шаг создания
                    sent = None
                    try:
                        # Попытка отправить краткое видимое подтверждение (не через _send_and_track), чтобы пользователь увидел факт вставки
                        msg_obj = query.message if getattr(query, 'message', None) else (update.message if getattr(update, 'message', None) else None)
                        if msg_obj:
                            sent = await msg_obj.reply_text(f'Вставлен адрес: {addr_text}')
                    except Exception:
                        try:
                            await query.answer(f'Вставлен адрес: {addr_text}', show_alert=False)
                        except Exception:
                            pass
                    # Планируем удаление видимого подтверждения через 5 секунд (если удалось отправить)
                    if sent:
                        try:
                            bot = getattr(context, 'bot', None)
                            if bot and getattr(sent, 'chat', None):
                                asyncio.create_task(self._delete_message_later(bot, sent.chat.id, sent.message_id, 5))
                        except Exception:
                            pass
                    await self._advance_create_with_value(update, context, addr_text)
                    return
            except Exception:
                try:
                    self.logger.exception('Ошибка в обработчике address_insert')
                except Exception:
                    pass
                return
        if action == 'delete' and len(parts) >= 3:
            try:
                idx = int(parts[2])
            except Exception:
                await self._safe_edit_query(query, context, 'Некорректный номер для удаления.')
                return
            # Попросим подтверждение
            kb = [[InlineKeyboardButton('✅ Да', callback_data=f'control:delete_confirm:{idx}'), InlineKeyboardButton('❌ Нет', callback_data='control:refresh')]]
            await self._safe_edit_query(query, context, 'Подтвердите удаление записи.', reply_markup=InlineKeyboardMarkup(kb))
            return
        if action == 'delete_confirm' and len(parts) >= 3:
            try:
                idx = int(parts[2])
            except Exception:
                await self._safe_edit_query(query, context, 'Некорректный номер для удаления.')
                return
            ids = context.user_data.get('control_room_rows_ids', [])
            if not ids or idx < 1 or idx > len(ids):
                await self._safe_edit_query(query, context, 'Неверный индекс для удаления.')
                return
            row_id = ids[idx - 1]
            try:
                with self.db.get_cursor() as cur:
                    moved = self._move_chart_to_archive(cur, row_id)
                if moved:
                    await self._safe_edit_query(query, context, RECORD_DELETED)
                else:
                    await self._safe_edit_query(query, context, 'Ошибка при удалении/архивации записи.')
            except Exception:
                await self._safe_edit_query(query, context, 'Ошибка при удалении/архивации записи.')
            # Обновим список (передаём Update)
            await self.start(update, context)
            return
        if action == 'edit' and len(parts) >= 3:
            try:
                idx = int(parts[2])
            except Exception:
                await self._safe_edit_query(query, context, 'Некорректный номер для редактирования.')
                return
            ids = context.user_data.get('control_room_rows_ids', [])
            if not ids or idx < 1 or idx > len(ids):
                await self._safe_edit_query(query, context, 'Неверный индекс для редактирования.')
                return
            # Показать список полей как InlineKeyboard
            kb = []
            for i, f in enumerate(self.fields, 1):
                key = f[0]
                label = self.FIELD_LABELS.get(key, key)
                kb.append([InlineKeyboardButton(f"{i}. {label}", callback_data=f'control:field:{idx}:{i}')])
            kb.append([InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')])
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
            elif field_key == 'customer':
                # Если редактируем поле заказчика — покажем список членов (members) как Inline-кнопки
                # Предложим показать весь список по кнопке, чтобы не перегружать интерфейс
                kb_small = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton('📋 Показать весь список', callback_data='control:members:show'),
                        InlineKeyboardButton('🔝 Часто набираемые', callback_data='control:members:frequent')
                    ],
                    [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                ])
                await query.edit_message_text(f'Tекущее значение для "{label}": {current_val}\n{SELECT_SHOW_CUSTOMERS}', reply_markup=kb_small)
            elif field_key in ('where', 'where_from'):
                # При редактировании адреса предложим кнопку "Показать все" (и Отмена).
                # Попробуем определить id заказчика, чтобы затем привязать адрес при выборе
                cust_id = context.user_data.get('control_room_create_customer_id')
                # Если не задан — попробуем получить из текущей записи chart
                if not cust_id:
                    try:
                        with self.db.get_cursor() as cur:
                            cur.execute('SELECT customer FROM chart WHERE id = ?', (row_id,))
                            crow = cur.fetchone()
                            cust_name = crow[0] if crow and crow[0] else None
                            if cust_name:
                                cur.execute("SELECT id FROM members WHERE TRIM(surname || ' ' || name || ' ' || COALESCE(patronymic, '')) = ?", (cust_name,))
                                mr = cur.fetchone()
                                if mr:
                                    cust_id = mr[0]
                                    # временно сохраним в context, чтобы обработчик выбора адреса смог использовать id
                                    context.user_data['control_room_create_customer_id'] = cust_id
                    except Exception:
                        self.logger.exception('Ошибка при попытке найти id заказчика для редактирования адреса')
                # Определим направление
                direction = 'назн' if field_key == 'where' else 'отпр'
                kb_small = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Вставить из БД', callback_data=f'control:address_insert:from_member:{direction}')],
                    [InlineKeyboardButton('📍 Показать все', callback_data=f'control:addresses:showall:{direction}')],
                    [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                ])
                await query.edit_message_text(f'Текущее значение для "{label}": {current_val}\nНажмите кнопку, чтобы выбрать адрес из списка, или введите вручную:', reply_markup=kb_small)
            elif field_key == 'phone':
                # Если редактируем поле телефона — попробуем показать кнопку с телефоном
                # Попробуем определить связанного заказчика: сначала посмотрим, есть ли customer_id в context
                cust_id = context.user_data.get('control_room_create_customer_id')
                phone_val = None
                member_cb_id = None
                cust_name = None
                if cust_id:
                    try:
                        with self.db.get_cursor() as cur:
                            cur.execute('SELECT phone FROM members WHERE id = ?', (cust_id,))
                            pr = cur.fetchone()
                            phone_val = pr[0] if pr and pr[0] else None
                            member_cb_id = cust_id
                    except Exception:
                        self.logger.exception('Ошибка при чтении телефона заказчика')
                        phone_val = None
                else:
                    # Если customer_id отсутствует — попробуем найти заказчика по имени в записи chart
                    try:
                        with self.db.get_cursor() as cur:
                            cur.execute('SELECT customer FROM chart WHERE id = ?', (row_id,))
                            crow = cur.fetchone()
                            cust_name = crow[0] if crow and crow[0] else None
                            if cust_name:
                                # Пытаемся найти точное совпадение полного ФИО в members
                                cur.execute("SELECT id, phone FROM members WHERE TRIM(surname || ' ' || name || ' ' || COALESCE(patronymic, '')) = ?", (cust_name,))
                                mr = cur.fetchone()
                                if mr and mr[1]:
                                    member_cb_id = mr[0]
                                    phone_val = mr[1]
                    except Exception:
                        self.logger.exception('Ошибка при поиске телефона по имени заказчика')
                if phone_val:
                    cb_id = member_cb_id if member_cb_id else ''
                    kb_small = InlineKeyboardMarkup([
                        [InlineKeyboardButton(phone_val, callback_data=f'control:phone:{cb_id}')],
                        [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                    ])
                    await query.edit_message_text(f'Текущее значение для "{label}": {current_val}\nНажмите номер, чтобы подставить телефон из карточки заказчика, или введите вручную:', reply_markup=kb_small)
                else:
                    await query.edit_message_text(f'Текущее значение для "{label}": {current_val}\nОтправьте новое значение в чат.')
            else:
                # Для остальных полей просто просим ввести новое значение
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
        # Первый запрос — теперь это заказчик; если это поле customer, покажем компактное меню
        first_key = self.fields[0][0]
        prompt = self.fields[0][1]
        if first_key == 'date':
            kb = self._build_quickdate_markup()
            await self._send_and_track(context, msg, prompt, reply_markup=kb)
        elif first_key == 'customer':
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton('📋 Показать весь список', callback_data='control:members:show'),
                    InlineKeyboardButton('🔝 Часто набираемые', callback_data='control:members:frequent')
                ],
                [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
            ])
            await self._send_and_track(context, msg, prompt, reply_markup=kb)
        else:
            await self._send_and_track(context, msg, prompt)

    async def handle_create_step(self, update, context) -> None:
        step = context.user_data.get('control_room_create_step', 0)
        data = context.user_data.get('control_room_create_data', {})
        value = update.message.text.strip()
        key = self.fields[step][0]
        # Если поле — дата, проверим формат и что дата не в прошлом
        if key == 'date':
            parsed = self._parse_date_text(value)
            if not parsed:
                await self._send_and_track(context, update.message, INVALID_DATE_FORMAT)
                kb = self._build_quickdate_markup()
                await self._send_and_track(context, update.message, SELECT_DATE, reply_markup=kb)
                return
            if self._is_past_date(parsed):
                await self._send_and_track(context, update.message, 'Выбранная дата в прошлом. Пожалуйста, укажите текущую или будущую дату.')
                kb = self._build_quickdate_markup()
                await self._send_and_track(context, update.message, SELECT_DATE, reply_markup=kb)
                return
            value = parsed.isoformat()

        # Если поле — время отправления, нормализуем ввод по правилам (модуль departure_time)
        if key == 'departure_time':
            try:
                norm = departure_time.normalize_manual_time(value)
            except Exception:
                norm = ''
            if not norm:
                # Попросим ввести корректный формат и предложим выбор времени
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Выбрать время', callback_data='control:departure_time:choose')],
                    [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                ])
                await self._send_and_track(context, update.message, 'Неверный формат времени. Введите в формате HH:MM или выберите время:', reply_markup=kb)
                return
            value = norm
            # Покажем короткое подтверждение выбора времени (не трекаем, чтобы не удалялось при _purge сразу)
            try:
                confirm_text = departure_time.messages.DEPARTURE_TIME_CONFIRM.format(time=norm)
            except Exception:
                try:
                    from control_room import messages as _m
                    confirm_text = _m.DEPARTURE_TIME_CONFIRM.format(time=norm)
                except Exception:
                    confirm_text = f'Время отправления установлено: {norm}'
            sent = None
            try:
                sent = await update.message.reply_text(confirm_text)
            except Exception:
                try:
                    sent = await self._send_and_track(context, update.message, confirm_text)
                except Exception:
                    sent = None
            if sent:
                try:
                    bot = getattr(context, 'bot', None)
                    if bot and getattr(sent, 'chat', None):
                        asyncio.create_task(self._delete_message_later(bot, sent.chat.id, sent.message_id, 5))
                except Exception:
                    pass

        # Если заполняется поле адреса вручную (откуда или куда) — сохранить адрес в таблице addresses
        if key in ('where_from', 'where'):
            direction = 'отпр' if key == 'where_from' else 'назн'
            try:
                cust_id = context.user_data.get('control_room_create_customer_id')
                with self.db.get_cursor() as cur:
                    # Проверим существует ли адрес
                    cur.execute('SELECT id FROM addresses WHERE address = ?', (value,))
                    ar = cur.fetchone()
                    if ar:
                        addr_id = ar[0]
                    else:
                        cur.execute('INSERT INTO addresses (address) VALUES (?)', (value,))
                        addr_id = cur.lastrowid
                    # Если есть идентификатор заказчика — обновим/вставим привязку
                    if cust_id:
                        try:
                            cur.execute(
                                'INSERT INTO customer_addresse (customer_id, addresse_id, direction, rating) VALUES (?, ?, ?, 1) '
                                'ON CONFLICT(customer_id, addresse_id, direction) DO UPDATE SET rating = customer_addresse.rating + 1',
                                (cust_id, addr_id, direction)
                            )
                        except Exception:
                            pass
            except Exception:
                self.logger.exception('Ошибка при сохранении адреса вручную')
        data[key] = value
        context.user_data['control_room_create_data'] = data
        step += 1
        if step < len(self.fields):
            context.user_data['control_room_create_step'] = step
            next_key = self.fields[step][0]
            prompt = self.fields[step][1]
            # Отправляем приглашение с подходящей клавиатурой, если это нужно
            if next_key == 'date':
                kb = self._build_quickdate_markup()
                await self._send_and_track(context, update.message, prompt, reply_markup=kb)
                await self._send_and_track(context, update.message, SELECT_DATE, reply_markup=kb)
            elif next_key == 'departure_time':
                # Предложим кнопку выбора времени — реализация показа/обработки вынесена в control_room.departure_time
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Выбрать время', callback_data='control:departure_time:choose')],
                    [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                ])
                await self._send_and_track(context, update.message, prompt, reply_markup=kb)
            elif next_key == 'arrival_time':
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Пропустить', callback_data='control:create_skip_arrival')],
                    [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                ])
                await self._send_and_track(context, update.message, prompt, reply_markup=kb)
            elif next_key == 'customer':
                # Покажем кнопки «Показать весь список» и «Часто набираемые» вместо вывода полного списка сразу
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton('📋 Показать весь список', callback_data='control:members:show'),
                        InlineKeyboardButton('🔝 Часто набираемые', callback_data='control:members:frequent')
                    ],
                    [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                ])
                await self._send_and_track(context, update.message, SELECT_SHOW_CUSTOMERS, reply_markup=kb)
            elif next_key == 'where_from':
                # Показать список адресов, привязанных к выбранному заказчику (если есть)
                cust_id = context.user_data.get('control_room_create_customer_id')
                if cust_id:
                    kb = self._build_addresses_markup(cust_id, include_show_all=True)
                    if kb:
                        await self._send_and_track(context, update.message, SELECT_ADDRESS_FROM, reply_markup=kb)
                    else:
                        # Если привязанных адресов нет — предложим кнопку "Показать все", кнопку "Вставить из БД" и "Отмена"
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton('Вставить из БД', callback_data=f'control:address_insert:from_member:отпр')],
                            [InlineKeyboardButton('📍 Показать все', callback_data=f'control:addresses:showall:отпр')],
                            [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                        ])
                        await self._send_and_track(context, update.message, SELECT_ADDRESS_FROM_MANUAL, reply_markup=kb)
                else:
                    # Если заказчик не выбран — всё равно предложим кнопку "Показать все", кнопку "Вставить из БД" и "Отмена"
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton('Вставить из БД', callback_data=f'control:address_insert:from_member:отпр')],
                        [InlineKeyboardButton('📍 Показать все', callback_data=f'control:addresses:showall:отпр')],
                        [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                    ])
                    await self._send_and_track(context, update.message, SELECT_ADDRESS_FROM_MANUAL, reply_markup=kb)
            elif next_key == 'where':
                # Показать список адресов назначения для выбранного заказчика
                cust_id = context.user_data.get('control_room_create_customer_id')
                if cust_id:
                    kb = self._build_addresses_markup(cust_id, direction='назн', include_show_all=True)
                    if kb:
                        await self._send_and_track(context, update.message, SELECT_ADDRESS_TO, reply_markup=kb)
                    else:
                        # Нет привязанных адресов, но предложим показать все
                        kb_fallback = InlineKeyboardMarkup([
                            [InlineKeyboardButton('📍 Показать все', callback_data=f'control:addresses:showall:назн')],
                            [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                        ])
                        await self._send_and_track(context, update.message, SELECT_ADDRESS_TO_MANUAL, reply_markup=kb_fallback)
            elif next_key == 'phone':
                # Показать кнопку с телефоном выбранного заказчика (используем id заказчика)
                cust_id = context.user_data.get('control_room_create_customer_id')
                phone_val = None
                if cust_id:
                    try:
                        with self.db.get_cursor() as cur:
                            cur.execute('SELECT phone FROM members WHERE id = ?', (cust_id,))
                            pr = cur.fetchone()
                            phone_val = pr[0] if pr and pr[0] else None
                    except Exception:
                        self.logger.exception('Ошибка при чтении телефона заказчика (create flow)')
                        phone_val = None
                if phone_val:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(phone_val, callback_data=f'control:phone:{cust_id}')],
                        [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                    ])
                    await self._send_and_track(context, update.message, SELECT_PHONE, reply_markup=kb)
            else:
                # Для всех прочих полей (например, departure_time) просто отправим приглашение
                await self._send_and_track(context, update.message, prompt)
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
                sent = await self._send_and_track(context, update.message, CREATED_SUCCESS)
                # Удалить уведомление через 10 секунд (fire-and-forget задача)
                try:
                    bot = getattr(context, 'bot', None)
                    if bot and getattr(sent, 'chat', None):
                        asyncio.create_task(self._delete_message_later(bot, sent.chat.id, sent.message_id, 10))
                except Exception:
                    # если не удалось планировать задачу — ничего не делаем
                    pass
            # Очистим флаги создания
            context.user_data.pop('control_room_create_data', None)
            context.user_data.pop('control_room_create_step', None)
            context.user_data.pop('control_room_create_in_progress', None)
            # Показать обновлённый список
            await self.start(update, context)
        except Exception as e:
            await self._send_and_track(context, update.message, f'Ошибка при сохранении заявки: {e}')

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
            next_key = self.fields[step][0]
            prompt = self.fields[step][1]
            # Отправляем приглашение с подходящей клавиатурой, если это нужно
            if next_key == 'date':
                kb = self._build_quickdate_markup()
                await self._send_and_track(context, msg, prompt, reply_markup=kb)
                await self._send_and_track(context, msg, SELECT_DATE, reply_markup=kb)
            elif next_key == 'departure_time':
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Выбрать время', callback_data='control:departure_time:choose')],
                    [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                ])
                await self._send_and_track(context, msg, prompt, reply_markup=kb)
            elif next_key == 'arrival_time':
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('Пропустить', callback_data='control:create_skip_arrival')],
                    [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                ])
                await self._send_and_track(context, msg, prompt, reply_markup=kb)
            elif next_key == 'customer':
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton('📋 Показать весь список', callback_data='control:members:show'),
                        InlineKeyboardButton('🔝 Часто набираемые', callback_data='control:members:frequent')
                    ],
                    [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                ])
                await self._send_and_track(context, msg, SELECT_SHOW_CUSTOMERS, reply_markup=kb)
            elif next_key == 'where_from':
                # Показать список адресов, привязанных к выбранному заказчику (если есть)
                cust_id = context.user_data.get('control_room_create_customer_id')
                if cust_id:
                    kb = self._build_addresses_markup(cust_id, include_show_all=True)
                    if kb:
                        await self._send_and_track(context, msg, SELECT_ADDRESS_FROM, reply_markup=kb)
                    else:
                        # Если привязанных адресов нет — предложим показать все и кнопку 'Вставить из БД'
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton('Вставить из БД', callback_data=f'control:address_insert:from_member:отпр')],
                            [InlineKeyboardButton('📍 Показать все', callback_data=f'control:addresses:showall:отпр')],
                            [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                        ])
                        await self._send_and_track(context, msg, SELECT_ADDRESS_FROM_MANUAL, reply_markup=kb)
                else:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton('📍 Показать все', callback_data=f'control:addresses:showall:отпр')],
                        [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                    ])
                    await self._send_and_track(context, msg, SELECT_ADDRESS_FROM_MANUAL, reply_markup=kb)
            elif next_key == 'where':
                # Показать список адресов назначения для выбранного заказчика
                cust_id = context.user_data.get('control_room_create_customer_id')
                if cust_id:
                    kb = self._build_addresses_markup(cust_id, direction='назн', include_show_all=True)
                    if kb:
                        await self._send_and_track(context, msg, SELECT_ADDRESS_TO, reply_markup=kb)
                    else:
                        kb_fallback = InlineKeyboardMarkup([
                            [InlineKeyboardButton('Вставить из БД', callback_data=f'control:address_insert:from_member:назн')],
                            [InlineKeyboardButton('📍 Показать все', callback_data=f'control:addresses:showall:назн')],
                            [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                        ])
                        await self._send_and_track(context, msg, SELECT_ADDRESS_TO_MANUAL, reply_markup=kb_fallback)
            elif next_key == 'phone':
                # Показать кнопку с телефоном выбранного заказчика (используем id заказчика)
                cust_id = context.user_data.get('control_room_create_customer_id')
                phone_val = None
                if cust_id:
                    try:
                        with self.db.get_cursor() as cur:
                            cur.execute('SELECT phone FROM members WHERE id = ?', (cust_id,))
                            pr = cur.fetchone()
                            phone_val = pr[0] if pr and pr[0] else None
                    except Exception:
                        self.logger.exception('Ошибка при чтении телефона заказчика (create flow callback)')
                        phone_val = None
                if phone_val:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(phone_val, callback_data=f'control:phone:{cust_id}')],
                        [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
                    ])
                    await self._send_and_track(context, msg, SELECT_PHONE, reply_markup=kb)
            else:
                # Для всех прочих полей (например, departure_time) просто отправим приглашение
                await self._send_and_track(context, msg, prompt)
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
            sent = await self._send_and_track(context, msg, CREATED_SUCCESS)
            # Удалить уведомление через 10 секунд (fire-and-forget задача)
            try:
                bot = getattr(context, 'bot', None)
                if bot and getattr(sent, 'chat', None):
                    asyncio.create_task(self._delete_message_later(bot, sent.chat.id, sent.message_id, 10))
            except Exception:
                pass
            # Очистим флаги создания
            for k in ('control_room_create_data','control_room_create_step','control_room_create_in_progress'):
                context.user_data.pop(k, None)
            # Показать обновлённый список
            await self.start(update, context)
        except Exception as e:
            await self._send_and_track(context, msg, f'Ошибка при сохранении заявки: {e}')

    def _build_quickdate_markup(self) -> InlineKeyboardMarkup:
        buttons = [
            [InlineKeyboardButton('Сегодня', callback_data='control:quickdate:today'), InlineKeyboardButton('Завтра', callback_data='control:quickdate:tomorrow')],
            [InlineKeyboardButton('Через 2 дня', callback_data='control:quickdate:plus2'), InlineKeyboardButton('Через три дня', callback_data='control:quickdate:plus3')],
            [InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')]
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

    async def _delete_message_later(self, bot, chat_id: int, message_id: int, delay: int = 10) -> None:
        """Удалить сообщение через delay секунд. Выполняется как фоновая задача."""
        try:
            await asyncio.sleep(delay)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as ex:
                try:
                    if isinstance(ex, BadRequest) and 'Message to delete not found' in str(ex):
                        try:
                            self.logger.debug(f"_delete_message_later: message not found chat_id={chat_id} message_id={message_id}")
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
                # не критично, просто логируем
                try:
                    self.logger.exception('Не удалось удалить временное сообщение')
                except Exception:
                    pass
        except Exception:
            # Если даже sleep или задача упала — ничего не делаем
            try:
                self.logger.exception('Ошибка в задаче удаления временного сообщения')
            except Exception:
                pass

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

        kb.append([InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')])
        return InlineKeyboardMarkup(kb)

    def _build_addresses_markup(self, customer_id: int, direction: str = 'отпр', include_show_all: bool = False) -> Optional[InlineKeyboardMarkup]:
        """Построить InlineKeyboard с адресами, привязанными к customer_id и заданным direction, отсортированными по rating desc.

        direction: 'отпр' для отправления, 'назн' для назначения.
        """
        try:
            with self.db.get_cursor() as cur:
                cur.execute('''
                    SELECT a.id, a.address FROM customer_addresse ca
                    JOIN addresses a ON ca.addresse_id = a.id
                    WHERE ca.customer_id = ? AND ca.direction = ?
                    ORDER BY ca.rating DESC
                ''', (customer_id, direction))
                rows = cur.fetchall()
        except Exception:
            self.logger.exception('Ошибка при выборке адресов для заказчика')
            # В случае ошибки возвращаем клавиатуру с кнопкой "Показать все" и "Отмена"
            rows = []
        # Всегда возвращаем клавиатуру — даже если нет привязанных адресов, чтобы показывать кнопку "Показать все"
        kb = []
        for r in rows:
            aid, addr = r[0], r[1] or ''
            label = addr if len(addr) <= 63 else addr[:60] + '...'
            # Включаем направление в callback, чтобы обработчик получил однозначно нужное направление
            kb.append([InlineKeyboardButton(label, callback_data=f'control:address:{aid}:{direction}')])
        # Добавим кнопку Показать все (всегда показываем) и кнопки Назад/Отмена
        kb.append([InlineKeyboardButton('Вставить из БД', callback_data=f'control:address_insert:from_member:{direction}')])
        kb.append([InlineKeyboardButton('📍 Показать все', callback_data=f'control:addresses:showall:{direction}')])
        kb.append([InlineKeyboardButton('◀️ Назад', callback_data='control:back'), InlineKeyboardButton('❌ Отмена', callback_data='control:refresh')])
        return InlineKeyboardMarkup(kb)

    def _parse_date_text(self, text: str) -> Optional[date]:
        text = text.strip().lower()
        if text in ('сегодня', 'today'):
            return date.today()
        if text in ('завтра', 'tomorrow'):
            return date.today() + timedelta(days=1)
        # Формат ДД (только день) — подставляем текущий месяц и год; если день уже в прошлом, используем следующий месяц
        m = re.match(r'^(\d{1,2})$', text)
        if m:
            d = int(m.group(1))
            try:
                today = date.today()
                year = today.year
                month = today.month
                # Попробуем текущий месяц
                try:
                    candidate = date(year, month, d)
                except Exception:
                    # Если в текущем месяце такой день невозможен — попробуем следующий месяц
                    nm = month + 1
                    ny = year
                    if nm > 12:
                        nm = 1
                        ny += 1
                    try:
                        candidate = date(ny, nm, d)
                    except Exception:
                        return None
                # Если полученная дата уже в прошлом — перейдём на следующий месяц
                if candidate < today:
                    nm = month + 1
                    ny = year
                    if nm > 12:
                        nm = 1
                        ny += 1
                    try:
                        candidate = date(ny, nm, d)
                    except Exception:
                        return None
                return candidate
            except Exception:
                return None
        # Формат ДДММ (без разделителя), например '0109' -> 01.09.current_year (или next year, если дата уже прошла)
        m = re.match(r'^(\d{2})(\d{2})$', text)
        if m:
            d, mo = map(int, m.groups())
            try:
                today = date.today()
                year = today.year
                # Попытаемся создать дату в текущем году
                try:
                    candidate = date(year, mo, d)
                except Exception:
                    return None
                # Если полученная дата в прошлом — предположим следующий год
                if candidate < today:
                    try:
                        candidate = date(year + 1, mo, d)
                    except Exception:
                        return None
                return candidate
            except Exception:
                return None
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
