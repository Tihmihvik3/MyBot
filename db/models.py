from db.database import db

class User:
    @staticmethod
    def create(user_id, username):
        with db.get_cursor() as cursor:
            cursor.execute(
                'INSERT INTO users (user_id, username) VALUES (?, ?)',
                (user_id, username)
            )

    @staticmethod
    def get_by_id(user_id):
        with db.get_cursor() as cursor:
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            return cursor.fetchone()

    @staticmethod
    def update_username(user_id, new_username):
        with db.get_cursor() as cursor:
            cursor.execute(
                'UPDATE users SET username = ? WHERE user_id = ?',
                (new_username, user_id)
            )
