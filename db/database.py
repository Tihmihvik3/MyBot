import sqlite3
import os
from contextlib import contextmanager
from db.config import Config

class Database:
    def __init__(self):
        db_path = os.path.join(os.path.dirname(__file__), Config.DB_NAME)
        if not os.path.exists(db_path):
            print('База данных members_vos.db не существует!')
            self.connection = None
            self.cursor = None
            return
        self.connection = sqlite3.connect(db_path)
        self.cursor = self.connection.cursor()
        print('Вы подключены к базе данных Анжеро-Судженской МО ВОС.')

    @contextmanager
    def get_cursor(self):
        if self.cursor is None:
            raise Exception('Нет подключения к базе данных!')
        try:
            yield self.cursor
        finally:
            self.connection.commit()

    def close(self):
        if self.connection:
            self.connection.close()

# Создание экземпляра БД
db = Database()
