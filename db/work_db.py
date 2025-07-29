from bot import admin_message
from db.database import Database
from db.edit_db import EditDB
from db.add_record import AddRecord
from db.del_record import DelRecord

class WorkDB:
    def __init__(self):
        """
        Инициализация класса WorkDB, подключение к базе данных.
        """
        self.db = Database()

    async def handle_admin_action(self, update, context):
        """
        Обрабатывает действия администратора, перенаправляет на соответствующий метод по выбору.
        """
        text = update.message.text.strip()
        # Обработка выбора пользователя из отсортированного списка
        if context.user_data.get('awaiting_member_detail_choice'):
            await self._handle_member_detail_choice(update, context, text)
            return
        # Обработка выбора действия над записью (редактировать/удалить/выйти)
        if context.user_data.get('awaiting_member_details_action'):
            await self.handle_member_details_action(update, context)
            return
        # Основное меню действий
        actions = {
            '1': self.show_sorted_by_surname,
            '2': self._handle_search_surname,
            '3': self._handle_edit_surname,
            '4': self._handle_add_record,
            '5': self._handle_delete_record,
        }
        action = actions.get(text)
        if action:
            await action(update, context)
        else:
            await update.message.reply_text("Некорректный выбор. Введите номер действия от 1 до 5.")

    async def _handle_member_detail_choice(self, update, context, text):
        """
        Обрабатывает выбор пользователя для просмотра подробных данных по номеру записи.
        """
        context.user_data['awaiting_member_detail_choice'] = False
        if text == '0':
            await update.message.reply_text('Выход в меню администратора.')
            
            await admin_message(update, context)
            return
        try:
            idx = int(text)
        except Exception:
            await update.message.reply_text('Некорректный номер. Попробуйте снова.')
            return
        members_list = context.user_data.get('sorted_members_list', [])
        if 1 <= idx <= len(members_list):
            member_id = members_list[idx - 1]
            await self.show_member_details(update, context, member_id)
        else:
            await update.message.reply_text('Некорректный номер. Попробуйте снова.')

    async def _handle_search_surname(self, update, context):
        """
        Запрашивает у администратора фамилию для поиска пользователя.
        """
        await update.message.reply_text("Введите фамилию для поиска:")
        context.user_data['awaiting_surname'] = True

    async def _handle_edit_surname(self, update, context):
        """
        Запускает процесс редактирования пользователя по фамилии.
        """
        edit_db = EditDB()
        await edit_db.search_and_show_fields(update, context)

    async def _handle_add_record(self, update, context):
        """
        Запускает процесс добавления новой записи пользователя.
        """
        add_record = AddRecord()
        await add_record.start_add(update, context)

    async def _handle_delete_record(self, update, context):
        """
        Запускает процесс удаления записи пользователя.
        """
        from db.del_record import DelRecord
        del_record = DelRecord()
        await del_record.start_delete(update, context)

    async def show_sorted_by_surname(self, update, context):
        """
        Выводит отсортированный по фамилии список пользователей (нумерация, Фамилия, Имя, Отчество),
        затем предлагает выбрать номер для подробного просмотра или 0 для выхода.
        """
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute('SELECT id, surname, name, patronymic FROM members ORDER BY surname COLLATE NOCASE ASC')
                rows = cursor.fetchall()
                await self._send_user_list(update, context, rows)
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сортировке: {e}')

    async def _send_user_list(self, update, context, rows):
        """
        Формирует и отправляет список пользователей, отсортированный по фамилии.
        """
        if rows:
            msg = 'Список пользователей (отсортировано по фамилии):\n'
            messages = []
            for idx, row in enumerate(rows, 1):
                line = f"{idx} | {row[1]} | {row[2]} | {row[3]}\n"
                if len(msg) + len(line) > 4000:
                    messages.append(msg)
                    msg = ''
                msg += line
            if msg:
                messages.append(msg)
            for m in messages:
                await update.message.reply_text(m)
            context.user_data['sorted_members_list'] = [row[0] for row in rows]
            await update.message.reply_text('Введите номер записи для подробного просмотра или 0 для выхода:')
            context.user_data['awaiting_member_detail_choice'] = True
        else:
            await update.message.reply_text('В базе нет данных.')
    FIELD_MAP = {
        'surname': 'Фамилия',
        'name': 'Имя',
        'patronymic': 'Отчество',
        'date_birth': 'Дата рождения',
        'group_disability': 'Группа инвалидности',
        'phone': 'Телефон',
        'address': 'Адрес',
        'area': 'Район',
        'group': 'Группа',
        'help_number': 'Справка МСЭ',
        'date_issue': 'Дата выдачи справки МСЭ',
        'validity_period': 'Срок действия справки MСЭ',
        'pension_number': 'Пенсионное удостоверение',
        'ticket_number': 'Номер членского билета',
        'date_entry': 'Дата вступления',
        'floor': 'Пол',
    }

    async def show_member_details(self, update, context, member_id):
        """
        Выводит подробные данные выбранной записи с пользовательскими названиями полей и предлагает действия над записью.
        """
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute('PRAGMA table_info(members)')
                columns = [col[1] for col in cursor.fetchall()]
                select_fields = [col for col in self.FIELD_MAP if col in columns]
                fields_sql = ', '.join([f'"{col}"' for col in select_fields])
                cursor.execute(f"SELECT {fields_sql} FROM members WHERE id = ?", (member_id,))
                result = cursor.fetchone()
                if result:
                    details = '\n'.join(f"{self.FIELD_MAP.get(field, field)}: {value}" for field, value in zip(select_fields, result))
                    await update.message.reply_text(f'Данные выбранной записи:\n{details}')
                    await update.message.reply_text(
                        'Выберите действие для этой записи:\n1. Редактировать данные\n2. Удалить запись\n0. Выйти'
                    )
                    # Сохраняем id выбранной записи и ожидаем ввод действия
                    context.user_data['member_details_id'] = member_id
                    context.user_data['awaiting_member_details_action'] = True
                else:
                    await update.message.reply_text('Запись не найдена.')
        except Exception as e:
            await update.message.reply_text(f'Ошибка при выборе записи: {e}')
    async def handle_member_details_action(self, update, context):
        """
        Обрабатывает выбор действия над записью: редактировать, удалить, выйти.
        """
        text = update.message.text.strip()
        member_id = context.user_data.get('member_details_id')
        context.user_data['awaiting_member_details_action'] = False
        if text == '0':
            from bot import admin_message
            await admin_message(update, context)
            return
        elif text == '1':
            from db.edit_db import EditDB
            edit_db = EditDB()
            await edit_db.edit_member_by_id(update, context, member_id)
            return
        elif text == '2':
            from db.del_record import DelRecord
            del_record = DelRecord()
            await del_record.delete_member_by_id(update, context, member_id)
            return
        else:
            await update.message.reply_text('Некорректный выбор. Введите 1, 2 или 0.')
            context.user_data['awaiting_member_details_action'] = True

    async def search_by_second_field(self, update, context):
        """
        Поиск пользователей по фамилии (начало строки, без учёта регистра), выводит все найденные записи.
        """
        surname = update.message.text.strip()
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute('SELECT * FROM members WHERE LOWER(surname) LIKE LOWER(?) LIMIT 30', (surname + '%',))
                rows = cursor.fetchall()
                if rows:
                    msg = 'Результаты поиска:\n'
                    messages = []
                    for idx, row in enumerate(rows, 1):
                        line = f"{idx} | " + ' | '.join(str(field) for field in row[1:]) + '\n'
                        if len(msg) + len(line) > 4000:
                            messages.append(msg)
                            msg = ''
                        msg += line
                    if msg:
                        messages.append(msg)
                    for m in messages:
                        await update.message.reply_text(m)
                else:
                    await update.message.reply_text('Совпадений не найдено.')
        except Exception as e:
            await update.message.reply_text(f'Ошибка при поиске: {e}')
    # Здесь будут методы для работы с базой данных (позже)
