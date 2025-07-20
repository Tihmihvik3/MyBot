async def get_user_id_message(update, context):
    user_id = update.message.from_user.id
    await update.message.reply_text(f"Ваш уникальный идентификатор Telegram: {user_id}")
from telegram import ReplyKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters
import settings
import logging
from db.models import User


logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def start_command(update, context):
    # Ответ на команду /start с кнопками
    keyboard = [["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
               ["Новости", "Фото"], ["Видео", "Контакты"], ["Справка"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Добро пожаловать! Я бот Анжеро-Судженской МО ВОС. Чем могу помочь?",
        reply_markup=reply_markup
    )

async def greet_user(update, context):
    # Ответ на приветствие
    await update.message.reply_text("Здравствуйте! Вас приветствует бот Анжеро-Судженской МО ВОС!")

async def help_message(update, context):
    # Ответ на сообщение "справка"
    await update.message.reply_text("Справка: Этот бот может отвечать на команды и сообщения, такие как 'привет' и 'справка'.")

async def contact_message(update, context):
    # Ответ на сообщение "контакты"
    await update.message.reply_text("Контакты: Вы можете связаться с нами по телефону +7 (38453) 6-18-85 или email amvos42@gmail.com.")

async def admin_message(update, context):
    # Проверка роли пользователя через VerificationID
    from verification_id import VerificationID
    verifier = VerificationID()
    USER_ROLE = await verifier.check_role(update, context)
    if USER_ROLE in ("admin", "super admin"):
        await update.message.reply_text("Режим администратора: доступ разрешён.")
        await update.message.reply_text(
            "Выберите действие:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\n6. Сортировка и фильтр.\nВведите номер действия:")
        context.user_data['admin_mode'] = True
    else:
        await update.message.reply_text("Эта команда вам не доступна. Обратитесь к администратору бота.")
        context.user_data['admin_mode'] = False

async def admin_action_handler(update, context):
    from db.sort_and_filtr import SortAndFiltr
    sortfiltr = SortAndFiltr()
    # --- SortAndFiltr этапы ---
    if context.user_data.get('sortfiltr_awaiting_action'):
        await sortfiltr.handle_action(update, context)
        return
    if context.user_data.get('sortfiltr_awaiting_sort_field'):
        await sortfiltr.handle_sort_field(update, context)
        return
    from db.search_records import SearchRecords
    search_records = SearchRecords()
    # --- SearchRecords этапы ---
    if context.user_data.get('searchrecords_awaiting_surname'):
        await search_records.handle_surname_search(update, context)
        return
    if context.user_data.get('searchrecords_awaiting_choice'):
        await search_records.handle_choose_result(update, context)
        return
    if context.user_data.get('searchrecords_repeat_or_exit'):
        await search_records.handle_repeat_or_exit(update, context)
        return
    # Обработчик выбора действия админа
    if not context.user_data.get('admin_mode'):
        return
    from db.work_db import WorkDB
    from db.edit_db import EditDB
    from db.add_record import AddRecord
    from db.del_record import DelRecord
    work_db = WorkDB()
    edit_db = EditDB()
    add_record = AddRecord()
    del_record = DelRecord()
    # --- DelRecord этапы ---
    if context.user_data.get('delrecord_awaiting_surname'):
        await del_record.handle_surname_search(update, context)
        return
    if context.user_data.get('delrecord_awaiting_choice'):
        await del_record.handle_choose_result(update, context)
        return
    if context.user_data.get('delrecord_awaiting_confirm'):
        await del_record.handle_confirm(update, context)
        return
    if context.user_data.get('delrecord_repeat_or_exit'):
        await del_record.handle_repeat_or_exit(update, context)
        return
    if context.user_data.get('editdb_awaiting_surname'):
        await edit_db.handle_surname_search(update, context)
        return
    if context.user_data.get('editdb_awaiting_choice'):
        await edit_db.handle_choose_result(update, context)
        return
    if context.user_data.get('editdb_awaiting_field'):
        await edit_db.handle_field_edit(update, context)
        return
    if context.user_data.get('editdb_awaiting_new_value'):
        await edit_db.handle_new_value(update, context)
        return
    if context.user_data.get('editdb_continue_or_exit'):
        await edit_db.handle_continue_or_exit(update, context)
        return
    if context.user_data.get('awaiting_surname'):
        context.user_data['awaiting_surname'] = False
        await work_db.search_by_second_field(update, context)
        return
    if context.user_data.get('add_record_in_progress'):
        await add_record.handle_add_step(update, context)
        return
    if context.user_data.get('add_record_continue_or_exit'):
        await add_record.handle_continue_or_exit(update, context)
        return
    else:
        # Если выбрано "2" — запуск поиска через SearchRecords
        if update.message.text.strip() == '2':
            await search_records.start_search(update, context)
        # Если выбрано "6" — запуск сортировки и фильтра
        elif update.message.text.strip() == '6':
            await sortfiltr.start(update, context)
        else:
            await work_db.handle_admin_action(update, context)

async def news_message(update, context):
    await update.message.reply_text("Новости: Здесь будут последние новости организации.")

async def photo_message(update, context):
    await update.message.reply_text("Фото: Здесь будут опубликованы фотографии мероприятий.")

async def video_message(update, context):
    await update.message.reply_text("Видео: Здесь будут опубликованы видеоматериалы.")

async def number_message(update, context):
    number = update.message.text.strip()
    await update.message.reply_text(f"Вы нажали кнопку: {number}")

def main():
    # Создаем экземпляр приложения
    application = Application.builder().token(settings.API_KEY).build()

    # Добавляем обработчик команды /start
    application.add_handler(CommandHandler("start", start_command))

    # Добавляем обработчик сообщений с фильтром на текст "привет"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)привет'), greet_user))

    # Добавляем обработчик сообщений с фильтром на текст "справка"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)справка'), help_message))

    # Добавляем обработчик сообщений с фильтром на текст "контакты"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)контакты'), contact_message))

    # Добавляем обработчик сообщений с фильтром на текст "админ"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)админ'), admin_message))
    # Добавляем обработчик для получения идентификатора пользователя
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)получить идентификатор'), get_user_id_message))
    # Добавляем обработчик для выбора действия админа
    application.add_handler(MessageHandler(filters.TEXT & (~filters.Regex(r'(?i)админ')), admin_action_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)новости'), news_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)фото'), photo_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)видео'), video_message))
    # Обработчики для цифровых кнопок 1-9
    for i in range(1, 10):
        application.add_handler(MessageHandler(filters.TEXT & filters.Regex(fr'^\s*{i}\s*$'), number_message))

    logging.info("Бот стартовал")

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
