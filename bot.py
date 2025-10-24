from telegram import ReplyKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters
import settings
import logging
from db.models import User


async def get_user_id_message(update, context):
    user_id = update.message.from_user.id
    await update.message.reply_text(f"Ваш уникальный идентификатор Telegram: {user_id}")

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
            "Выберите действие:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать запись.\n4. Добавить запись.\n5. Удалить запись.\n6. Сортировка и фильтр.\nВведите номер действия:")
        context.user_data['admin_mode'] = True
    else:
        await update.message.reply_text("Эта команда вам не доступна. Обратитесь к администратору бота.")
        context.user_data['admin_mode'] = False

async def admin_action_handler(update, context):
    """
    Обработчик выбора действия админа
    """
    from db.sort_and_filtr import SortAndFiltr
    sortfiltr = SortAndFiltr()
    # --- Делегируем обработку состояния ControlRoom ---
    from control_room.control_room import ControlRoom
    control = ControlRoom()
    processed = await control.process_state(update, context)
    if processed:
        return
    # --- Делегируем обработку состояний SortAndFiltr в модуль sort_and_filtr.py ---
    processed = await sortfiltr.process_state(update, context)
    if processed:
        return
    from db.search_records import SearchRecords
    search_records = SearchRecords()
    # --- Делегируем обработку состояний SearchRecords ---
    processed = await search_records.process_state(update, context)
    if processed:
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
    # --- Делегируем обработку состояний DelRecord ---
    processed = await del_record.process_state(update, context)
    if processed:
        return
    # --- Делегируем обработку состояний EditDB ---
    processed = await edit_db.process_state(update, context)
    if processed:
        return
    if context.user_data.get('awaiting_surname'):
        context.user_data['awaiting_surname'] = False
        await work_db.search_by_second_field(update, context)
        return
    # --- Делегируем обработку состояний AddRecord ---
    processed = await add_record.process_state(update, context)
    if processed:
        return
    else:
        # Если выбрано "2" — запуск поиска через SearchRecords
        if update.message.text.strip() == '2':
            await search_records.start_search(update, context)
        # Если выбрано "6" — запуск сортировки и фильтра
        elif update.message.text.strip() == '6':
            await sortfiltr.start(update, context)
        # Прямой вход в диспетчерскую теперь обрабатывается отдельным handler'ом (control_entry)
        else:
                await work_db.handle_admin_action(update, context)


async def control_entry(update, context):
    """Обработчик, который позволяет пользователю сразу набрать 'диспетчерская' и попасть в диспетчерскую после проверки роли."""
    from control_room.control_room import ControlRoom
    control = ControlRoom()
    await control.start(update, context)

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
    # Добавляем обработчик для быстрого доступа в диспетчерскую по слову 'диспетчерская'
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)^\s*диспетчерская\s*$'), control_entry))
    # Добавляем обработчик для получения идентификатора пользователя
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)получить идентификатор'), get_user_id_message))
    # Добавляем обработчик для выбора действия админа
    application.add_handler(MessageHandler(filters.TEXT & (~filters.Regex(r'(?i)админ')), admin_action_handler))
    # CallbackQuery для inline-кнопок (фильтрация / пагинация)
    from db.sort_and_filtr import SortAndFiltr
    sortfiltr = SortAndFiltr()
    # CallbackQuery для sort_and_filtr — фильтровать только callback'ы, начинающиеся с 'sortfiltr:'
    application.add_handler(CallbackQueryHandler(sortfiltr.handle_callback, pattern=r'^sortfiltr:'))
    # CallbackQuery для диспетчерской (InlineKeyboard) — фильтровать только 'control:'
    from control_room.control_room import ControlRoom
    control = ControlRoom()
    application.add_handler(CallbackQueryHandler(control.handle_callback, pattern=r'^control:'))
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
