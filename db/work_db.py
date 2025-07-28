from db.database import Database
from db.edit_db import EditDB
from db.add_record import AddRecord

class WorkDB:
    def __init__(self):
        self.db = Database()
    # ...

    async def handle_admin_action(self, update, context):
        text = update.message.text.strip()
        # Если ожидается выбор пользователя из отсортированного списка
        if context.user_data.get('awaiting_member_detail_choice'):
            context.user_data['awaiting_member_detail_choice'] = False
            if text == '0':
                await update.message.reply_text('Выход в меню администратора.')
                return
            try:
                idx = int(text)
            except Exception:
                await update.message.reply_text('Некорректный номер. Попробуйте снова.')
                return
            members_list = context.user_data.get('sorted_members_list', [])
            if 1 <= idx <= len(members_list):
                member_id = members_list[idx - 1]
                await self.show_member_details(update, member_id)
            else:
                await update.message.reply_text('Некорректный номер. Попробуйте снова.')
            return
        if text == '1':
            await self.show_sorted_by_surname(update, context)
        elif text == '2':
            await update.message.reply_text("Введите фамилию для поиска:")
            context.user_data['awaiting_surname'] = True
        elif text == '3':
            # Запуск поиска фамилии для редактирования через EditDB
            edit_db = EditDB()
            await edit_db.search_and_show_fields(update, context)
        elif text == '4':
            # Запуск добавления записи
            add_record = AddRecord()
            await add_record.start_add(update, context)
        elif text == '5':
            from db.del_record import DelRecord
            del_record = DelRecord()
            await del_record.start_delete(update, context)
        else:
            await update.message.reply_text("Некорректный выбор. Введите номер действия от 1 до 5.")

    async def show_sorted_by_surname(self, update, context):
        """
        Выводит отсортированный по фамилии список пользователей (нумерация, Фамилия, Имя, Отчество),
        затем предлагает выбрать номер для подробного просмотра или 0 для выхода.
        """
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute('SELECT id, surname, name, patronymic FROM members ORDER BY surname COLLATE NOCASE ASC')
                rows = cursor.fetchall()
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
        except Exception as e:
            await update.message.reply_text(f'Ошибка при сортировке: {e}')
    async def show_member_details(self, update, member_id):
        """
        Выводит подробные данные выбранной записи с пользовательскими названиями полей
        """
        field_map = {
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
        try:
            with self.db.get_cursor() as cursor:
                cursor.execute('PRAGMA table_info(members)')
                columns = [col[1] for col in cursor.fetchall()]
                select_fields = [col for col in field_map if col in columns]
                fields_sql = ', '.join([f'"{col}"' for col in select_fields])
                cursor.execute(f"SELECT {fields_sql} FROM members WHERE id = ?", (member_id,))
                result = cursor.fetchone()
                if result:
                    details = '\n'.join(f"{field_map.get(field, field)}: {value}" for field, value in zip(select_fields, result))
                    await update.message.reply_text(f'Данные выбранной записи:\n{details}')
                else:
                    await update.message.reply_text('Запись не найдена.')
        except Exception as e:
            await update.message.reply_text(f'Ошибка при выборе записи: {e}')

    async def search_by_second_field(self, update, context):
        # Поиск по полю surname без учёта регистра, вывод всех полей, поиск по началу фамилии (LIKE ...%)
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
