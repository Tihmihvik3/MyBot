import logging
from utils.admin_messenger import send_and_track, delete_tracked_messages
import messages_admin as MESSAGES_ADMIN

logger = logging.getLogger(__name__)


class SearchRecords:
    db_fields = [
        "surname", "name", "patronymic", "date_birth", "group_disability", "phone", "address", "area", "`group`", "help_number", "date_issue", "validity_period", "pension_number", "ticket_number", "date_entry", "floor"
    ]

    async def start_search(self, update, context):
        # Отправим приглашение (send_and_track удалит старые сообщения перед отправкой)
        try:
            await send_and_track(context, update.message, MESSAGES_ADMIN.SEARCH_ENTER_SURNAME)
        except Exception:
            logger.exception('start_search: send_and_track failed; falling back to reply_text')
            await update.message.reply_text(MESSAGES_ADMIN.SEARCH_ENTER_SURNAME)
        context.user_data['searchrecords_awaiting_surname'] = True

    async def handle_surname_search(self, update, context):
        surname = update.message.text.strip().split()[0]
        from db.database import Database
        db = Database()
        try:
            with db.get_cursor() as cursor:
                cursor.execute('SELECT rowid, ' + ', '.join(self.db_fields) + ' FROM members WHERE LOWER(surname) LIKE LOWER(?)', (surname + '%',))
                rows = cursor.fetchall()
                if not rows:
                    try:
                        await send_and_track(context, update.message, MESSAGES_ADMIN.SEARCH_NO_MATCH_RETRY)
                    except Exception:
                        await update.message.reply_text(MESSAGES_ADMIN.SEARCH_NO_MATCH_RETRY)
                    context.user_data['searchrecords_repeat_or_exit'] = True
                    context.user_data['searchrecords_awaiting_surname'] = False
                    return
                context.user_data['searchrecords_results'] = rows
                if len(rows) == 1:
                    row = rows[0]
                    await self.show_full_record(update, row)
                    try:
                        await send_and_track(context, update.message, MESSAGES_ADMIN.SEARCH_REPEAT_EXIT)
                    except Exception:
                        await update.message.reply_text(MESSAGES_ADMIN.SEARCH_REPEAT_EXIT)
                    context.user_data['searchrecords_repeat_or_exit'] = True
                else:
                    msg = 'Результаты поиска:\n'
                    for idx, row in enumerate(rows, 1):
                        msg += f"{idx}. {row[1]} {row[2]} {row[3]}\n"
                    msg += MESSAGES_ADMIN.SEARCH_RESULTS_PROMPT
                    try:
                        await send_and_track(context, update.message, msg)
                    except Exception:
                        await update.message.reply_text(msg)
                    context.user_data['searchrecords_awaiting_choice'] = True
        except Exception as e:
            await update.message.reply_text(MESSAGES_ADMIN.ERROR_SEARCH.format(error=e))
        context.user_data['searchrecords_awaiting_surname'] = False

    async def handle_choose_result(self, update, context):
        text = update.message.text.strip()
        if not text.isdigit():
            await update.message.reply_text(MESSAGES_ADMIN.ENTER_NUMBER_FROM_LIST)
            return
        idx = int(text)
        results = context.user_data.get('searchrecords_results', [])
        if idx < 1 or idx > len(results):
            await update.message.reply_text(MESSAGES_ADMIN.INVALID_NUMBER)
            return
        row = results[idx-1]
        await self.show_full_record(update, row)
        try:
            await send_and_track(context, update.message, MESSAGES_ADMIN.SEARCH_REPEAT_EXIT)
        except Exception:
            await update.message.reply_text(MESSAGES_ADMIN.SEARCH_REPEAT_EXIT)
        context.user_data['searchrecords_awaiting_choice'] = False
        context.user_data['searchrecords_repeat_or_exit'] = True

    async def handle_repeat_or_exit(self, update, context):
        text = update.message.text.strip()
        if text == '1':
            await self.start_search(update, context)
            context.user_data['searchrecords_repeat_or_exit'] = False
        elif text == '2':
            await update.message.reply_text(MESSAGES_ADMIN.ADMIN_MAIN_MENU)
            context.user_data['searchrecords_repeat_or_exit'] = False
            context.user_data['admin_mode'] = True
        else:
            await update.message.reply_text(MESSAGES_ADMIN.ENTER_1_OR_2)

    async def show_full_record(self, update, row):
        fields = [
            "Фамилия", "Имя", "Отчество", "Дата рождения", "Группа инвалидности", "Телефон", "Адрес", "Район", "Группа", "Справка МСЭ", "Дата выдачи справки МСЭ", "Срок действия справки MСЭ", "Пенсионное удостоверение", "Номер членского билета", "Дата вступления", "Пол"
        ]
        msg = 'Данные выбранной записи:\n'
        for i, field in enumerate(fields):
            msg += f"{field}: {row[i+1]}\n"
        await update.message.reply_text(msg)

    async def process_state(self, update, context):
        """
        Универсальная обработка состояний для SearchRecords.
        Возвращает True, если сообщение обработано модулем (нужно прекратить дальнейшую обработку).
        """
        if context.user_data.get('searchrecords_repeat_or_exit'):
            await self.handle_repeat_or_exit(update, context)
            return True
        if context.user_data.get('searchrecords_awaiting_surname'):
            await self.handle_surname_search(update, context)
            return True
        if context.user_data.get('searchrecords_awaiting_choice'):
            await self.handle_choose_result(update, context)
            return True
        return False
