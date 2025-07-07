from telegram import ReplyKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters
import settings
import logging
from db.models import User


logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def start_command(update, context):
    # Ответ на команду /start с кнопками
    keyboard = [["Новости", "Фото"], ["Видео", "Контакты"], ["Справка"]]
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
    await update.message.reply_text("Контакты: Вы можете связаться с нами по телефону +7 (123) 456-78-90 или email example@example.com.")

async def admin_message(update, context):
    # Обработчик для запроса "админ"
    from db.database import Database
    db = Database()
    if db.connection:
        await update.message.reply_text("Режим администратора: подключение к базе данных выполнено.")
        # После успешного подключения выводим меню действий
        await update.message.reply_text(
            "Выберите действие:\n1. Показать весь список.\n2. Найти по фамилии.\n3. Редактировать данные.\n4. Добавить данные.\n5. Удалить данные.\nВведите номер действия:")
        # Сохраняем состояние ожидания выбора действия
        context.user_data['admin_mode'] = True
    else:
        await update.message.reply_text("Ошибка: база данных не найдена.")

async def admin_action_handler(update, context):
    # Обработчик выбора действия админа
    if not context.user_data.get('admin_mode'):
        return
    from db.work_db import WorkDB
    work_db = WorkDB()
    if context.user_data.get('awaiting_surname'):
        # Поиск по второму полю (например, фамилия)
        context.user_data['awaiting_surname'] = False
        await work_db.search_by_second_field(update, context)
    else:
        await work_db.handle_admin_action(update, context)

async def news_message(update, context):
    await update.message.reply_text("Новости: Здесь будут последние новости организации.")

async def photo_message(update, context):
    await update.message.reply_text("Фото: Здесь будут опубликованы фотографии мероприятий.")

async def video_message(update, context):
    await update.message.reply_text("Видео: Здесь будут опубликованы видеоматериалы.")

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
    # Добавляем обработчик для выбора действия админа
    application.add_handler(MessageHandler(filters.TEXT & (~filters.Regex(r'(?i)админ')), admin_action_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)новости'), news_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)фото'), photo_message))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)видео'), video_message))

    logging.info("Бот стартовал")

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
