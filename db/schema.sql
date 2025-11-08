CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    email TEXT UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    message TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Архив удалённых заявок из таблицы chart
CREATE TABLE IF NOT EXISTS chart_archive (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id INTEGER,
    date TEXT,
    where_from TEXT,
    departure_time TEXT,
    "where" TEXT,
    arrival_time TEXT,
    departure_datetime TEXT,
    customer TEXT,
    phone TEXT,
    archived_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Архив удалённых карточек членов
CREATE TABLE IF NOT EXISTS members_archive (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_rowid INTEGER,
    surname TEXT,
    name TEXT,
    patronymic TEXT,
    date_birth TEXT,
    group_disability TEXT,
    phone TEXT,
    address TEXT,
    area TEXT,
    "group" TEXT,
    help_number TEXT,
    date_issue TEXT,
    validity_period TEXT,
    pension_number TEXT,
    ticket_number TEXT,
    date_entry TEXT,
    floor TEXT,
    archived_at TEXT DEFAULT CURRENT_TIMESTAMP
);