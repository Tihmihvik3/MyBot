from telegram.ext import Application, MessageHandler, CommandHandler, filters
import settings
import logging

logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def start_command(update, context):
    # Ответ на команду /start
    await update.message.reply_text("Добро пожаловать! Я бот Анжеро-Судженской МО ВОС. Чем могу помочь?")

async def greet_user(update, context):
    # Ответ на приветствие
    await update.message.reply_text("Здравствуйте! Вас приветствует бот Анжеро-Судженской МО ВОС!")

async def help_message(update, context):
    # Ответ на сообщение "справка"
    await update.message.reply_text("Справка: Этот бот может отвечать на команды и сообщения, такие как 'привет' и 'справка'.")

async def contact_message(update, context):
    # Ответ на сообщение "контакты"
    await update.message.reply_text("Контакты: Вы можете связаться с нами по телефону +7 (123) 456-78-90 или email example@example.com.")

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

    logging.info("Бот стартовал")

    # Запускаем бота
    application.run_polling()

if __name__ == "__main__":
    main()