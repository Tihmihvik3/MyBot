from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import traceback
import asyncio
from control_room import messages
import re


def normalize_manual_time(text: str) -> str:
    """Нормализовать ввод времени согласно ТЗ.

    Поддерживает следующие варианты (только цифры):
    1 digit -> 0H:00 (например '9' -> '09:00')
    2 digits -> HH:00 (например '14' -> '14:00')
    3 digits -> pad leading zero to 4 and split (e.g. '930' -> '0930' -> '09:30')
    4 digits -> split HHMM -> 'HH:MM' (e.g. '1430' -> '14:30')

    Также поддерживает уже корректные форматы с ':' и возвращает нормализованный 'HH:MM' или
    пустую строку при некорректном вводе.
    """
    if not text:
        return ''
    s = text.strip()
    # If contains colon, try to validate
    m = re.match(r'^(\d{1,2}):(\d{1,2})$', s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh < 24 and 0 <= mm < 60:
            return f"{hh:02d}:{mm:02d}"
        return ''
    # Only digits
    if re.match(r'^\d{1,4}$', s):
        L = len(s)
        try:
            if L == 1:
                hh = int(s)
                if 0 <= hh < 24:
                    return f"0{hh}:00"
                return ''
            if L == 2:
                hh = int(s)
                if 0 <= hh < 24:
                    return f"{hh:02d}:00"
                return ''
            if L == 3:
                s4 = s.zfill(4)  # e.g. '930' -> '0930'
                hh = int(s4[:2])
                mm = int(s4[2:])
                if 0 <= hh < 24 and 0 <= mm < 60:
                    return f"{hh:02d}:{mm:02d}"
                return ''
            if L == 4:
                hh = int(s[:2])
                mm = int(s[2:])
                if 0 <= hh < 24 and 0 <= mm < 60:
                    return f"{hh:02d}:{mm:02d}"
                return ''
        except Exception:
            return ''
    return ''


async def show_picker(cr, update, context):
    """Показать пользователю inline-киборду с выбором времени отправления.

    cr: экземпляр ControlRoom (передаётся, чтобы использовать _safe_edit_query/_send_and_track и _advance_create_with_value)
    """
    query = update.callback_query
    times = [
        '08:00','08:30','09:00','09:30','10:00','10:30','11:00','11:30','12:00','12:30','13:00','13:30','14:00','14:30','15:00'
    ]
    kb = []
    # Разбиваем по 3 кнопки в ряд
    row = []
    for t in times:
        token = t.replace(':', '-')
        row.append(InlineKeyboardButton(t, callback_data=f'control:departure_time:pick:{token}'))
        if len(row) >= 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    # Навигация/отмена
    # Если мы вызваны из потока создания заявки, используем локальную кнопку Back
    back_cb = 'control:create:prev' if context.user_data.get('control_room_create_in_progress') else 'control:back'
    kb.append([InlineKeyboardButton(messages.BTN_BACK, callback_data=back_cb), InlineKeyboardButton(messages.BTN_CANCEL, callback_data='control:refresh')])
    markup = InlineKeyboardMarkup(kb)
    try:
        # Попытаемся аккуратно отредактировать текущее сообщение
        # Если находимся в потоке создания — зафиксируем шаг creation как departure_time,
        # чтобы при нажатии локальной кнопки 'control:create:prev' корректно перейти на предыдущий шаг.
        if context.user_data.get('control_room_create_in_progress'):
            try:
                for i, f in enumerate(cr.fields):
                    if f[0] == 'departure_time':
                        context.user_data['control_room_create_step'] = i
                        break
            except Exception:
                pass
        await cr._safe_edit_query(query, context, messages.DEPARTURE_TIME_PROMPT, reply_markup=markup)
    except Exception:
        # fallback — отправим новое tracked-сообщение
        try:
            await cr._send_and_track(context, query.message, messages.DEPARTURE_TIME_PROMPT, reply_markup=markup)
        except Exception:
            try:
                cr.logger.exception('Не удалось показать селектор времени (departure_time.show_picker)')
            except Exception:
                pass


async def handle_pick(cr, update, context, time_str: str):
    """Обработка выбора конкретного времени: записать его в текущее поле и продвинуть шаг."""
    query = update.callback_query
    try:
        # Подтвердим нажатие, чтобы убрать индикатор на клиенте
        try:
            await query.answer()
        except Exception:
            pass

        # Восстановим читаемое значение времени (заменили ':'->'-' в callback token)
        time_label = time_str.replace('-', ':') if time_str else time_str

        # Отправим видимое подтверждение в чат и запланируем его удаление
        confirm_text = messages.DEPARTURE_TIME_CONFIRM.format(time=time_label)
        sent = None
        try:
            sent = await query.message.reply_text(confirm_text)
        except Exception:
            try:
                sent = await cr._send_and_track(context, query.message, confirm_text)
            except Exception:
                sent = None
        if sent:
            try:
                bot = getattr(context, 'bot', None)
                if bot and getattr(sent, 'chat', None):
                    asyncio.create_task(cr._delete_message_later(bot, sent.chat.id, sent.message_id, 5))
            except Exception:
                pass

        # Используем существующий метод ControlRoom для продвижения создания
        await cr._advance_create_with_value(update, context, time_label)
    except Exception:
        try:
            cr.logger.exception('Ошибка при обработке выбора времени отправления')
        except Exception:
            pass
        try:
            await cr._send_and_track(context, query.message, messages.ERROR_SET_TIME.format(time=time_str))
        except Exception:
            pass
