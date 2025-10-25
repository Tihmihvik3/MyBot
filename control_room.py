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
                        where TEXT,
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

                # Если таблица существует — вывести все записи
                cursor.execute('SELECT date, where_from, departure_time, where, arrival_time, customer, phone FROM chart')
                rows = cursor.fetchall()
                if not rows:
                    await update.message.reply_text('Заявок нет.')
                    await update.message.reply_text('Наберите 0 чтобы создать заявку.')
                    context.user_data['control_room_wait_create'] = True
                    return

                # Выводим список без id и имён полей, пронумерованный
                msg_lines = []
                for idx, row in enumerate(rows, 1):
                    # Соединяем значения через ' | '
                    line = ' | '.join([str(x) if x is not None else '' for x in row])
                    msg_lines.append(f"{idx}. {line}")
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
        # Если ожидаем создание — пока только сообщение-подсказка
        if context.user_data.get('control_room_wait_create'):
            # Оставляем реализацию создания на будущее
            text = update.message.text.strip()
            if text == '0':
                await update.message.reply_text('Создание заявки будет реализовано позже.')
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
                await update.message.reply_text('Создание заявки будет реализовано позже.')
                context.user_data.pop('control_room_awaiting_choice', None)
                return True
            # Если введён номер записи — пока только уведомим, что удаление/редактирование позже
            try:
                n = int(text)
                if n <= 0:
                    raise ValueError()
                await update.message.reply_text('Удаление/редактирование записи будет реализовано позже.')
            except ValueError:
                await update.message.reply_text('Введите корректный номер записи, 0 или 00.')
            return True

        return False
