import sqlite3


def init_db(db_name="portfolio.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
                                id INTEGER PRIMARY KEY,
                                username TEXT UNIQUE,
                                password TEXT,
                                security_question TEXT,
                                security_answer TEXT,
                                risk_tolerance TEXT
                                )
                                ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            ticker TEXT PRIMARY KEY,
            name TEXT,
            exchange TEXT,
            sector TEXT,
            industry TEXT,
            market_cap REAL,
            sales REAL,
            profits REAL,
            assets REAL,
            market_value REAL
        )
    ''')
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS companies_fts USING fts5 (
            name,
            tokenize = 'trigram'
        )
    ''')
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS companies_fts_trigger
            AFTER INSERT ON companies
        BEGIN
            INSERT INTO companies_fts (rowid, name) VALUES (new.rowid, new.name);
        END
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            ticker TEXT,
            shares INTEGER,
            share_check INTEGER,
            live_price REAL,
            purchase_price REAL,
            purchase_date TEXT,
            sale_price REAL DEFAULT NULL,
            sale_date TEXT DEFAULT NULL,
            realized_profit_loss REAL DEFAULT NULL,
            unrealized_profit_loss REAL DEFAULT NULL,
            FOREIGN KEY (username) REFERENCES users(username)
        )
    ''')
    conn.commit()
    return conn


def search_company_by_name(conn, name_query):
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT rowid FROM companies_fts WHERE companies_fts MATCH ? ORDER BY rank LIMIT 5",
            (name_query,)
        )
        fts_res = cursor.fetchall()
        if not fts_res:
            return []

        param_ls = ','.join(['?'] * len(fts_res))
        cursor.execute(
            f"SELECT ticker, name FROM companies WHERE rowid IN ({param_ls})",
            [x[0] for x in fts_res]
        )
        return cursor.fetchall()
    except Exception as e:
        print("Search error:", e)
        return []