#!pip install prettytable
from pickle import TRUE
import prettytable
import pandas as pd
import sqlite3
import yfinance as yf
import hashlib
import re
import matplotlib.pyplot as plt
import requests
import nltk
import csv
from bs4 import BeautifulSoup
from nltk.sentiment import SentimentIntensityAnalyzer
from datetime import datetime, timedelta
from tabulate import tabulate
from collections import defaultdict
import math
import numpy as np
from scipy.stats import norm
nltk.download('vader_lexicon')

# ------------------------------
# Database Setup
# ------------------------------
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

# ------------------------------
# User Authentication
# ------------------------------
class User:
    def __init__(self, db_name='portfolio.db'):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.current_user_id = None # Stored Logged-in user ID

        self.conn.commit()

    def hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()

    def is_strong_password(self, password):
        if (len(password) >= 8 and
            re.search(r"[A-Z]", password) and
            re.search(r"[a-z]", password) and
            re.search(r"[0-9]", password) and
            re.search(r"[!@#$%^&*(),.?\":{}|<>]", password)):
            return True
        return False

    def register(self):
        while True:
            username = input("Enter a username: ")
            self.cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            if self.cursor.fetchone():
                print("Username already exists.")
                choice = input("Do you have an existing account? (y/n): ").strip().lower()
                if choice == 'y':
                    self.login()
                    return
                else:
                    print("Please try registering with a different username.")
            else:
                break

        while True:
            password = input("Enter a strong password (min 8 chars, upper, lower, number, special char): ")
            if self.is_strong_password(password):
                break
            else:
                print("Weak password. Please follow the guidelines.")

        security_question = input("Enter a security question (e.g., What is your pet's name?): ")
        security_answer = input("Enter the answer to your security question: ")

        hashed_password = self.hash_password(password)
        hashed_answer = self.hash_password(security_answer)

        self.cursor.execute("INSERT INTO users (username, password, security_question, security_answer) VALUES (?, ?, ?, ?)",
                            (username, hashed_password, security_question, hashed_answer))
        self.conn.commit()
        print("Registration successful!")
        print("Proceed to login!")
        return self.login()

    def login(self):
        while True:
            username = input("Enter your username: ")

            # Check if username exists in the database
            self.cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user_exists = self.cursor.fetchone() # check user exists
            if not user_exists:
                print("Username do not exist. Would you like to register?")
                choice = input("Type 'y' to register and 'n' to try again: ").strip().lower()
                if choice == "y":
                    return self.register()
                else:
                    continue

            password = input("Enter your password: ")
            hashed_password = self.hash_password(password)

            self.cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hashed_password))
            user = self.cursor.fetchone()

            if user:
                self.current_user_id = username # Stored logged-in username
                print("Login successful!")
                return username
            else:
                print("Invalid credentials.")
                choice = input("Forgot password? (y/n): ").strip().lower()
                if choice == 'y':
                    self.reset_password(username)
                    return username


    def reset_password(self, username):
        self.cursor.execute("SELECT security_question FROM users WHERE username = ?", (username,))
        result = self.cursor.fetchone()
        if result:
            while True:
                print(f"Security Question: {result[0]}")
                answer = input("Answer: ")
                hashed_answer = self.hash_password(answer)
                self.cursor.execute("SELECT * FROM users WHERE username = ? AND security_answer = ?", (username, hashed_answer))
                if self.cursor.fetchone():
                    while True:
                        new_password = input("Enter a new strong password: ")
                        if self.is_strong_password(new_password):
                            hashed_new_password = self.hash_password(new_password)
                            self.cursor.execute("UPDATE users SET password = ? WHERE username = ?", (hashed_new_password, username))
                            self.conn.commit()
                            print("Password reset successful!")
                            print("Please proceed to login!")
                            self.login()
                            break
                        else:
                            print("Weak password. Please follow the guidelines.")
                    break
                else:
                    print("Incorrect answer to the security question.")
        else:
            print("Username not found.")

# Logs out current user and clears session data
    def logout(self):
        if self.current_user_id is not None:
            self.current_user_id = None
            print("Logged out successfully.")
        else:
            print("No user is currently logged in.")

# ------------------------------
# Data Loading Functions
# ------------------------------
def load_csv_data():
    usa_large_companies = pd.read_csv("USA large companies.csv", delimiter="\t")
    stock_info = pd.read_csv("stock_info_tickers_exchange.csv")
    nasdaq_data = pd.read_csv("nasdaq_tickers_sector.csv")
    sp_data = pd.read_csv("SnP_tickers_sector.csv")
    return usa_large_companies, stock_info, nasdaq_data, sp_data

# ------------------------------
# Data Insertion into SQLite
# ------------------------------
def insert_data_to_db(conn, stock_info):
    cursor = conn.cursor()
    for _, row in stock_info.iterrows():
        cursor.execute('''
            INSERT OR REPLACE INTO companies (ticker, name, exchange)
            VALUES (?, ?, ?)
        ''', (row['Ticker'], row['Name'], row['Exchange']))
    conn.commit()

# ------------------------------
# User Guide
# ------------------------------
def user_guide(conn):
    print("""
    Welcome to EasyFinance where we will help you manage your stock investments efficiently.
    EasyFinance is an easy-to-use interface for tracking stock investments and making informed financial decisions.

    After logging in, follow the on-screen prompts to navigate through the options.

    1. Add Stock to Portfolio - Enter a stock ticker and the number of shares to purchase.
    2. Remove Stock from Portfolio - Specify a stock ticker and the number of shares to remove.
    3. View Portfolio - Displays your current stock holdings, including quantities, purchase prices,live price and realized profit/loss. As well as a pie chart for portfolio allocation.
    4. View Past Transactions - Access to historical stock transactions, including purchases, sales, realised profit/loss and unrealised profit/loss.
    5. Fetch Stock Info - Enter a stock ticker to retrieve details such as book value, market cap, trailing PE and forward PE.
    View the stock prices for the last 6 months to observe any trend.
    View stock recommendations based on industry's benchmark and news sentiment to to determine whether the stock news is positive, negative, or neutral
    6. Update Your Risk Tolerance - View your current risk tolerance and modify it to adjust the risk threshold for stock recommendations.
    7. Import Portfolio - Import a CSV file if you have a existing portfolio for easier access """)

    search_company_name(conn)

def search_company_name(conn):
    while True:
        # Query
        user_input_guide = input("\nEnter a company name to retrieve the respective ticker (or type 'exit' to quit): ").strip()
        if user_input_guide.lower() == 'exit':
            print("Returning back to main menu.")
            break
        elif user_input_guide:
            try:
                # Full-text search, grabbing row IDs for fast lookup
                cursor = conn.cursor()
                cursor.execute("SELECT rowid FROM companies_fts WHERE companies_fts MATCH ? ORDER BY rank LIMIT 5", (user_input_guide,))
                fts_res = cursor.fetchall()
                if not fts_res:
                    print("No results found.")
                    continue
                param_ls = ','.join(['?'] * len(fts_res))
                # Lookup the ticker and name for the matched row IDs
                cursor.execute(f"SELECT ticker and name FROM companies WHERE rowid IN ({param_ls})", [x[0] for x in fts_res])
                res = cursor.fetchall()
                if not res:
                    print("No results found.")
                    continue
                print("\nFound:")
                print(tabulate(res, headers=["Ticker", "Company Name"], tablefmt="grid"))
            except Exception as e:
                print(e)
                print("Error occurred while searching company names")
                continue
        else:
            print("Please enter a company name or type 'exit' only.")

# ------------------------------
# Portfolio Management
# ------------------------------
class Portfolio:
    def __init__(self, username, conn):
        self.username = username
        self.conn = conn

    def add_stock(self, ticker, shares):
        purchase_date = input("Enter purchase date (YYYY-MM-DD) or 'today': ").strip().lower()

        if purchase_date == 'today':
            stock_data = fetch_stock_data(ticker)
            live_price = stock_data.get('Bid', stock_data.get('Previous Close', 0))
            purchase_date = datetime.today().strftime('%Y-%m-%d')
            while True:
                check_price = input(f"Purchase price at ${live_price}? (y/n): ")
                if check_price.lower() == "n":
                    while True:
                        try:
                            purchase_price = float(input("Enter your purchase price: "))
                            break
                        except ValueError:
                            print("Invalid input. Please enter a valid price.")
                    break
                elif check_price.lower() == "y":
                    purchase_price = live_price
                    break
                else:
                    print("Please key in a valid response.")
        else:
            try:
                datetime.strptime(purchase_date, "%Y-%m-%d")
                live_price = fetch_historical_price(ticker, purchase_date)
                if live_price is None:
                    print("Past data unavailable.")
                    while True:
                        try:
                            purchase_price = float(input("Enter your purchase price: "))
                            break
                        except ValueError:
                            print("Invalid input. Please enter a valid price.")

                else:
                    while True:
                        check_price = input(f"Purchase price at ${live_price}? (y/n): ")
                        if check_price.lower() == "n":
                            while True:
                                try:
                                    purchase_price = float(input("Enter your purchase price: "))
                                    break
                                except ValueError:
                                    print("Invalid input. Please enter a valid price.")
                            break
                        elif check_price.lower() == "y":
                            purchase_price = live_price
                        else:
                            print("Please enter a valid response.")


            except ValueError:
                print("Invalid date format.")
                return

        # Fetch current market price and calculate unrealized P/L
        if live_price:
            unrealized_pnl = (live_price - purchase_price) * shares
        else:
            unrealized_pnl = None

        share_check = shares

        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO portfolios (username, ticker, shares, share_check, live_price, purchase_price, purchase_date, unrealized_profit_loss)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (self.username, ticker, shares, share_check, live_price, purchase_price, purchase_date, unrealized_pnl))

        self.conn.commit()
        print(f"Added {shares} shares of {ticker} at ${purchase_price:.2f} on {purchase_date}")


    def remove_stock(self, ticker, shares_to_sell):
        cursor = self.conn.cursor()

        # Get all remaining purchased share transaction for the ticker
        cursor.execute('''
            SELECT id, purchase_price, shares, share_check, purchase_date
            FROM portfolios
            WHERE username = ? AND ticker = ? AND share_check > 0
            ORDER BY purchase_date ASC
        ''', (self.username, ticker))

        holdings = cursor.fetchall()

        if not holdings:
            print("You do not own any shares of this stock.")
            return

        # Total available shares
        cursor.execute('''
            SELECT SUM(shares)
            FROM portfolios
            WHERE username = ? AND ticker = ?
        ''', (self.username, ticker))
        total_available_shares = cursor.fetchone()[0] or 0

        if shares_to_sell > total_available_shares:
            print("Insufficient shares available. View portfolio to see available shares and try again!")
            return

        remaining_shares_to_sell = shares_to_sell
        total_realized_pnl = 0

        for row in holdings:
            purchase_id, purchase_price, available_shares, share_check, purchase_date = row

            if remaining_shares_to_sell <= 0:
                break

            if available_shares <= 0:
                continue

            if share_check <= 0:
                continue

            shares_sold = min(share_check, remaining_shares_to_sell)


            # Get sale date and price
            sale_date = input("Enter sale date (YYYY-MM-DD) or 'today': ").strip().lower()
            if sale_date == 'today':
                stock_data = fetch_stock_data(ticker)
                sale_price = stock_data.get('Bid', stock_data.get('Previous Close', 0))
                sale_date = datetime.today().strftime('%Y-%m-%d')
                while True:
                    check_price = input(f"Selling price at ${sale_price}? (y/n): ")
                    if check_price.lower() == "n":
                        while True:
                            try:
                                sale_price = float(input("Enter your selling price: "))
                                break
                            except ValueError:
                                print("Invalid input. Please enter a valid price.")
                        break
                    elif check_price.lower() == "y":
                        break
                    else:
                        print("Please enter a valid response.")
            else:
                try:
                    datetime.strptime(sale_date, "%Y-%m-%d")
                    sale_price = fetch_historical_price(ticker, sale_date)
                    if sale_price is None:
                        print("Past data unavailable.")
                        while True:
                            try:
                                sale_price = float(input("Enter your selling price: "))
                                break
                            except ValueError:
                                print("Invalid input. Please enter a valid price.")

                    else:
                        while True:
                            check_price = input(f"Selling price at ${sale_price}? (y/n): ")
                            if check_price.lower() == "n":
                                while True:
                                    try:
                                        sale_price = float(input("Enter your selling price: "))
                                        break
                                    except ValueError:
                                        print("Invalid input. Please enter a valid price.")
                                break
                            elif check_price.lower() == "y":
                                break
                            else:
                                print("Please enter a valid response.")

                except ValueError:
                    print("Invalid date format.")
                    return

            # Calculate realized P/L
            realized_pnl = (sale_price - purchase_price) * shares_sold
            total_realized_pnl += realized_pnl

            # Update share_check
            cursor.execute('''
                        UPDATE portfolios
                        SET share_check = share_check - ?
                        WHERE id = ?
                    ''', (shares_sold, purchase_id))

            # Insert a new row for the sale only — no update to original purchase row
            cursor.execute('''
                        INSERT INTO portfolios (username, ticker, shares, purchase_price, purchase_date, sale_price, sale_date, realized_profit_loss)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
            self.username, ticker, -shares_sold, purchase_price, purchase_date, sale_price, sale_date, realized_pnl))

            remaining_shares_to_sell -= shares_sold

        self.conn.commit()
        print(f"Sold {shares_to_sell} shares of {ticker} at ${sale_price:.2f} on {sale_date}")
        print(f"Total Realized Profit/Loss: ${total_realized_pnl:.2f}")

    def view_portfolio(self):
        cursor = self.conn.cursor()

        # Query to get only stocks with remaining shares that have not been fully sold
        cursor.execute('''
            SELECT ticker, SUM(shares) AS total_shares, purchase_price, purchase_date
            FROM portfolios
            WHERE username = ?
            GROUP BY ticker, purchase_price
            HAVING total_shares > 0
        ''', (self.username,))

        holdings = cursor.fetchall()

        # Query total realized profit/loss
        cursor.execute('''
                SELECT SUM(realized_profit_loss) FROM portfolios
                WHERE username = ? AND realized_profit_loss IS NOT NULL
            ''', (self.username,))
        total_realized_pnl = cursor.fetchone()[0] or 0  # Default to 0 if no realized P&L

        if not holdings:
            print("\nYour portfolio is empty.")
            return

        print("\nYour Portfolio:")
        table = prettytable.PrettyTable(["Ticker", "Shares", "Sector", "Purchase Price", "Live Price", "Unrealized P/L", "Realized P/L"])

        portfolio_data = []  # For CSV export
        total_unrealized_pnl = 0  # Track total unrealized P/L

        for ticker, shares, purchase_price, purchase_date in holdings:
            stock_data = fetch_stock_data(ticker)
            current_price = stock_data.get('Previous Close', 0)
            sector = stock_data.get('Sector', 'N/A')

            # Fetch realized P/L for this stock
            cursor.execute('''
                       SELECT SUM(realized_profit_loss) FROM portfolios
                       WHERE username = ? AND ticker = ?
                   ''', (self.username, ticker))
            realized_pnl = cursor.fetchone()[0] or 0  # Default to 0 if no realized P&L

            # Calculate Unrealized P/L
            if current_price > 0:
                unrealized_pnl = (current_price - purchase_price) * shares
                total_unrealized_pnl += unrealized_pnl
                table.add_row([ticker, shares, sector, f"${purchase_price:.2f}", f"${current_price:.2f}",
                               f"${unrealized_pnl:.2f}", f"${realized_pnl:.2f}"])
                portfolio_data.append(
                    [ticker, shares, sector, purchase_price, current_price, unrealized_pnl, realized_pnl])
            else:
                table.add_row([ticker, shares, sector, f"${purchase_price:.2f}", "Not Available", "Not Available",
                               f"${realized_pnl:.2f}"])
                portfolio_data.append(
                    [ticker, shares, sector, purchase_price, "Not Available", "Not Available", realized_pnl])

        print(table)
        print(f"\nTotal Realized P/L: ${total_realized_pnl:.2f}")
        print(f"Total Unrealized P/L: ${total_unrealized_pnl:.2f}")

        print("Please wait for your pie chart to load!")
        self.visualize_portfolio()

        # Ask if the user wants to export
        export_choice = input("Would you like to export your portfolio as a CSV file? (y/n): ").strip().lower()
        if export_choice == 'y':
            self.export_portfolio_csv(portfolio_data)


    def export_portfolio_csv(self, portfolio_data):
        filename = f"portfolio_{self.username}_{datetime.today().strftime('%Y-%m-%d')}"
        filepath = f"{filename}.csv"

        with open(filepath, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Ticker", "Shares", "Sector", "Purchase Price", "Live Price", "Unrealized P/L", "Realized P/L"])
            writer.writerows(portfolio_data)

        print(f"Portfolio exported successfully as {filename}")

    def import_portfolio(self):
        filename = input("Enter the name of the CSV file to import: ").strip() + ".csv"
        if not os.path.exists(filename):
            print("File not found. Please enter a valid file name.")
            return

        expected_headers = ["Ticker", "Shares", "Sector", "Purchase Price", "Live Price", "Unrealized P/L",
                            "Realized P/L"]

        with open(filename, mode='r') as file:
            reader = csv.reader(file)

            # Read the first row (header)
            headers = next(reader, None)
            # Validate the headers
            if headers != expected_headers:
                print(f"Invalid CSV format! Expected headers: {expected_headers}, but found: {headers}")
                return

            for row in reader:
                try:
                    ticker, shares, sector, purchase_price, live_price, unrealised_pnl, realized_pnl = row
                    shares = int(shares)
                    purchase_price = float(purchase_price)
                    live_price = float(live_price)
                    unrealised_pnl = float(unrealised_pnl)
                    realized_pnl = float(realized_pnl)

                    # Set default values for missing data
                    purchase_date = "Unknown"  # Could prompt the user if needed
                    sale_price = None
                    sale_date = None
                    realized_pnl = float(realized_pnl) if realized_pnl != "Not Available" else None

                    cursor = self.conn.cursor()
                    cursor.execute('''
                            INSERT INTO portfolios (username, ticker, shares, purchase_price, purchase_date, sale_price, sale_date, realized_profit_loss)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                    self.username, ticker, shares, purchase_price, purchase_date, sale_price, sale_date, realized_pnl))

                    self.conn.commit()
                except ValueError:
                    print(f"Skipping invalid row: {row}")

        print("Portfolio imported successfully!")

    def visualize_portfolio(self):
        cursor = self.conn.cursor()

        cursor.execute('''
            SELECT ticker, SUM(shares) FROM portfolios
            WHERE username = ? AND (sale_date IS NULL OR shares > 0)
            GROUP BY ticker
        ''', (self.username,))

        holdings = cursor.fetchall()

        if not holdings:
            print("\nYour portfolio is empty.")
            return

        ticker_values = defaultdict(float)

        for ticker, shares in holdings:
            # Ensure that the stock is still available (not fully sold)
            cursor.execute('''
                SELECT SUM(shares) FROM portfolios
                WHERE username = ? AND ticker = ? AND sale_date IS NULL
            ''', (self.username, ticker))
            remaining_shares = cursor.fetchone()[0] or 0

            if remaining_shares > 0:  # Only include if there are still shares available
                stock_data = fetch_stock_data(ticker)
                stock_price = stock_data.get('Previous Close', 0)
                total_value = stock_price * remaining_shares
                ticker_values[ticker] += total_value

        total_portfolio_value = sum(ticker_values.values())

        if total_portfolio_value == 0:
            print("No valid stock prices available for visualization.")
            return

        # Plot pie chart
        plt.figure(figsize=(8, 5))
        plt.pie(
            ticker_values.values(),
            labels=ticker_values.keys(),
            autopct=lambda p: f'{p:.1f}% (${p * total_portfolio_value / 100:.2f})',
            startangle=140
        )
        plt.title(f"Portfolio Allocation (by Value) for {self.username}")

        #Allow users to save the pie chart
        while True:
            save_option = input("Would you like to save this pie chart? (y/n): ").strip().lower()
            if save_option == 'y':
              filename = input("Enter filename (without extension): ").strip()
              file_path = f"{filename}.png"
              plt.savefig(file_path, bbox_inches='tight')
              print(f"Pie chart saved as {file_path}")
              break
            elif save_option == 'n':
                break
            else:
              print("Invalid choice. Please try again.")

        plt.show()
        plt.close()


    def past_transactions(self):
        cursor = self.conn.cursor()

        cursor.execute('''
            SELECT purchase_date, ticker, shares, live_price, purchase_price, sale_date, sale_price, realized_profit_loss
            FROM portfolios
            WHERE username = ?
            ORDER BY purchase_date ASC
        ''', (self.username,))

        transactions = cursor.fetchall()

        if not transactions:
            print("No past transactions found.")
            return

        table_data = []
        for purchase_date, ticker, shares, live_price, purchase_price, sale_date, sale_price, realized_profit_loss in transactions:
            company_name = get_company_name(ticker)

            # Fetch remaining shares (sum all purchases and subtract sales)
            cursor.execute('''
                SELECT SUM(shares)
                FROM portfolios
                WHERE username = ? AND ticker = ?
            ''', (self.username, ticker))
            remaining_shares = cursor.fetchone()[0] or 0

            unrealized_pnl = 0
            if sale_price is None:
                stock_data = fetch_stock_data(ticker)
                current_price = stock_data.get('Previous Close', 0)
                unrealized_pnl = (current_price - purchase_price) * remaining_shares

            table_data.append([purchase_date, ticker, company_name, shares, live_price, purchase_price,
                               sale_date if sale_date else "N/A", sale_price if sale_price else "N/A",
                               f"${realized_profit_loss:.2f}" if realized_profit_loss else "N/A",
                               f"${unrealized_pnl:.2f}"])

        print(tabulate(table_data, headers=["Date", "Ticker", "Company", "Shares", "Live Price", "Buy Price", "Sell Date", "Sell Price", "Realized P/L", "Unrealized P/L"], tablefmt="grid"))


# ------------------------------
# Yahoo Finance Integration
# ------------------------------
def fetch_stock_data(ticker):
    stock = yf.Ticker(ticker)
    info = stock.info
    hist = stock.history(period="1y")
    returns = hist['Close'].pct_change().dropna()
    return {
        'Ticker': ticker,
        'Company': info.get('shortName', 'N/A'),
        'Sector': info.get('sector', 'N/A'),
        'Industry': info.get('industry', 'N/A'),
        'EBITDA': info.get('ebitda', 'N/A'),
        'Book Value': info.get('bookValue', 'N/A'),
        'Market Cap': info.get('marketCap', 'N/A'),
        'Previous Close': info.get('previousClose', 'N/A'),
        'Trailing PE': info.get('trailingPE', 'N/A'),
        'Forward PE': info.get('forwardPE', 'N/A'),
        'Beta': info.get('beta', 'N/A'),
        'Returns': returns
    }

def fetch_historical_price(ticker, date_str):
    """
    Fetch the historical closing price for a stock on a given date.
    If no data is available for that date (weekend/holiday), fetch the last available trading day.
    """
    try:
        # Convert date string to datetime object
        date = datetime.strptime(date_str, "%Y-%m-%d")

        # Attempt to fetch data for the exact date
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d", start=date_str, end=(date + timedelta(days=1)).strftime('%Y-%m-%d'))

        # If no data available, check previous trading days
        while hist.empty:
            date -= timedelta(days=1)  # Move to previous day
            if date.weekday() in [5, 6]:  # Skip weekends (Saturday=5, Sunday=6)
                date -= timedelta(days=2)

            # Try fetching again
            hist = stock.history(period="1d", start=date.strftime('%Y-%m-%d'), end=(date + timedelta(days=1)).strftime('%Y-%m-%d'))

            # Stop if checking too far back (e.g., 30 days ago)
            if (datetime.today() - date).days > 30:
                print("No valid historical data found in the last 30 days.")
                return None

        # Return the closing price of the last available trading day
        return hist['Close'].iloc[0]

    except Exception as e:
        print(f"Error fetching historical price for {ticker}: {e}")
        return None

def get_company_name(ticker):
    try:
        stock = yf.Ticker(ticker)
        return stock.info.get("longName", ticker)  # Fallback to ticker if name is unavailable
    except Exception as e:
        print(f"Error fetching company name for {ticker}: {e}")
        return ticker  # Return ticker as a fallback

def plot_stock_price(ticker):
    stock = yf.Ticker(ticker)
    history = stock.history(period="6mo")

    if history.empty:
        print(f"No price data available for {ticker}.")
        return

    plt.figure(figsize=(10, 5))
    plt.plot(history.index, history['Close'], label=f"{ticker} Price", color="blue")
    plt.title(f"{ticker} Stock Price (Last 6 Months)")
    plt.xlabel("Date")
    plt.ylabel("Closing Price ($)")
    plt.legend()

    #Allow users to save the line graph
    save_option = input("Would you like to save this graph? (y/n): ").strip().lower()
    if save_option == 'y':
      filename = input("Enter filename (without extension): ").strip()
      file_path = f"{filename}.png"
      plt.savefig(file_path, bbox_inches='tight')
      print(f"Line graph saved as {file_path}")

    plt.show()
    plt.close()

# ------------------------------
# Risk Analysis
# ------------------------------

def calculate_risk_info(stock_data):
    returns = stock_data.get('Returns')
    return_values = returns.values
    if return_values is None or len(return_values) == 0:
        return None

    # Volatility (Standard Deviation of returns)
    volatility = np.std(return_values) * math.sqrt(252)  # Annualized volatility

    # Sharpe Ratio (Assume risk-free rate = 2%)
    avg_return = np.mean(return_values) * 252  # Annualized return
    risk_free_rate = 0.02
    sharpe_ratio = (avg_return - risk_free_rate) / volatility

    # Value at Risk (VaR) at 95% confidence level
    confidence_level = 0.05
    var_95 = norm.ppf(confidence_level, np.mean(return_values), np.std(return_values)) * 100

    return {
        "volatility": volatility,
        "sharpe_ratio": sharpe_ratio,
        "var_95": var_95
    }

def fetch_user_risk_tolerance(conn, username):
    cursor = conn.cursor()
    cursor.execute('''
        SELECT risk_tolerance FROM users WHERE username = ?
    ''', (username,))
    result = cursor.fetchone()

    if not result or result[0] is None:
        default_tolerance = 'Medium'
        cursor.execute('''
            UPDATE users SET risk_tolerance = ? WHERE username = ?
        ''', (default_tolerance, username))
        conn.commit()
        return default_tolerance

    return result[0]  # Return the existing risk tolerance

def get_risk_tolerance(conn, username, risk_tolerance):
    stored_risk_tolerance = fetch_user_risk_tolerance(conn, username)

    print(f"\nCurrent Risk Tolerance: {stored_risk_tolerance}")
    while True:
        print("\nWould you like to update your risk tolerance?")
        print("1. Yes")
        print("2. No")

        choice = input("Select your option: ")
        if choice == "1":
            while True:
              print("\n1. Low Risk")
              print("2. Medium Risk")
              print("3. High Risk")

              choice = input("Select your option: ")
              if choice == "1":
                  new_risk_tolerance = "Low"
                  print(f"\nYour risk tolerance has been updated to {new_risk_tolerance}.")
                  break
              elif choice == "2":
                  new_risk_tolerance = "Medium"
                  print(f"\nYour risk tolerance has been updated to {new_risk_tolerance}.")
                  break
              elif choice == "3":
                  new_risk_tolerance = "High"
                  print(f"\nYour risk tolerance has been updated to {new_risk_tolerance}.")
                  break
              else:
                  print("Invalid choice, please try again.")

            break

        elif choice == "2":
            print("\nNo changes made to your risk tolerance.")
            return stored_risk_tolerance

        else:
            print("Invalid choice, please try again.")

    update_risk_tolerance(conn, username, new_risk_tolerance)

    return new_risk_tolerance

def update_risk_tolerance(conn, username, risk_tolerance):
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users SET risk_tolerance = ? WHERE username = ?
    ''', (risk_tolerance, username))
    conn.commit()

# ------------------------------
# Recommendation
# ------------------------------
def recommend_stocks(ticker, risk_tolerance):
    stock_data = fetch_stock_data(ticker)
    risk_info = calculate_risk_info(stock_data)

    if stock_data['Trailing PE'] is None or stock_data['Trailing PE'] == "N/A" or risk_info is None:
        print(f"No P/E ratio available for {ticker}. Cannot provide recommendation.")
        return

    pe_ratio = stock_data['Trailing PE']

    # Industry/Sector average P/E (For simplicity, assume we have an average of 20)
    industry_avg_pe = 20
    recommendation = None

    print(f"\nStock Analysis for {ticker}:")
    print(f"Industry: {stock_data['Industry']}")
    print(f"Trailing PE: {pe_ratio}")
    print(f"Industry Avg PE: {industry_avg_pe}\n")
    print(f"\nRisk Analysis for {ticker}:")
    print(f"Volatility: {risk_info['volatility']:.2f}")
    print(f"Sharpe Ratio: {risk_info['sharpe_ratio']:.2f}")
    print(f"Value at Risk (95%): {risk_info['var_95']:.2f}%\n")

    if risk_tolerance == "Low":
        sharpe_threshold = 1.5  # Low-risk tolerance: Sharpe Ratio > 1.5
    elif risk_tolerance == "Medium":
        sharpe_threshold = 1.0  # Medium-risk tolerance: Sharpe Ratio > 1.0
    else:
        sharpe_threshold = 0.5  # High-risk tolerance: Sharpe Ratio > 0.5

    # Recommendation Logic
    if pe_ratio < industry_avg_pe * 0.8 and risk_info["sharpe_ratio"] > sharpe_threshold:
        recommendation = f"(✅) {ticker} is within your risk tolerance and appears under-valued compared to its industry average. Consider adding."
    elif pe_ratio > industry_avg_pe * 1.2 or risk_info["sharpe_ratio"] < sharpe_threshold:
        recommendation = f"(⚠️)  {ticker} is outside of your risk tolerance or appears overvalued. It might be wise to avoid or reduce holdings."
    else:
        recommendation = f"(⏸️) {ticker} is within your risk tolerance and fairly valued. Consider holding."
    return recommendation

# ------------------------------
# News Market Sentiment
# ------------------------------

# Cache dictionary to store results every 5 mins
cache = {}
cache_expired = timedelta(minutes=5)

# To print results
def show_overall_results(ticker, sentiment_scores):
    scores = [score for _, score, _ in sentiment_scores]

    if not scores:
        print(f"No sentiment data available for {ticker}.")
        return None

    # Calculate overall sentiment score
    overall_sentiment = sum(scores) / len(scores)

    # Determine overall sentiment label
    sentiment_label = "Positive✅" if overall_sentiment > 0 else "Negative❌" if overall_sentiment < 0 else "Neutral🟡"

    overall_statement = f"\nOverall Market Sentiment for {ticker}: {sentiment_label} ({overall_sentiment:.2f})"
    print(overall_statement)
    return overall_statement

# To retrieve market sentiment
def get_market_sentiment(ticker):
    url = f"https://finance.yahoo.com/quote/{ticker}/news"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers)
    now = datetime.now()

    if ticker in cache and now - cache[ticker]['timestamp'] < cache_expired:
        print("Cached results for", ticker)
        # show_results(ticker, cache[ticker]['sentiment_scores'])
        return # Prevents opening the browser unnecessarily

    if response.status_code != 200:
        print("Failed to fetch market sentiment.")
        return None

    soup = BeautifulSoup(response.content, 'html.parser')


    # Extract all headlines and URLs
    all_headlines = set()
    all_urls = set()

    # Get headlines and associated URLs
    for anchor in soup.find_all('a', href=True):
        headline1 = anchor.get_text(strip=True)
        url = anchor['href']

        if ticker.upper() in headline1.upper() and headline1:
            all_headlines.add(headline1)
            all_urls.add(f"{url}")  # Properly formatted URL

    if not all_headlines:
        return f"No news headlines found for {ticker}."

    # Filter news links that are related to the ticker symbol
    if ticker.upper() in headline1.upper() and headline1:
        all_urls.add(url)

    all_headlines = list(all_headlines)
    all_urls = list(all_urls)
    headlines_with_urls = [(headline, f"https://finance.yahoo.com{url}") for headline, url in zip(all_headlines, all_urls)]

    if headlines_with_urls:
        # Sentiment Analysis with VADER
        analyzer = SentimentIntensityAnalyzer()
        sentiment_scores = []

        # Pair headlines with their URLs for sentiment analysis
        headlines_with_urls = zip(all_headlines, all_urls)
        for headline, url in headlines_with_urls:
            score = analyzer.polarity_scores(headline)['compound']
            sentiment_scores.append((headline, score, url))

        # Store in cache
        cache[ticker] = {'sentiment_scores': sentiment_scores, 'timestamp': now}

        return show_results(ticker, sentiment_scores), show_overall_results(ticker, sentiment_scores)
    else:
        return f"No news headlines found for {ticker}."

def show_results(ticker, sentiment_scores):
    print(f"\nMarket Sentiment for {ticker}:")
    for headline, score, url in sentiment_scores:
        print(f"\nHeadline: {headline}\nSentiment Score: {score}\nURL: {url}")

# ------------------------------
# Command-Line Interface
# ------------------------------
def main():
    conn = init_db()
    usa_large_companies, stock_info, nasdaq_data, sp_data = load_csv_data()
    insert_data_to_db(conn, stock_info)

    # Initialize user authentication system
    user_system = User()

    # Main menu loop
    print("\n--- 📈 Welcome to the Stock Portfolio Management System 📊 ---")

    while True:
        print("\n Main Menu:")
        print("1. Register")
        print("2. Login")
        print("3. Exit")
        choice = input("Select an option: ")

        if choice == '1':
            username = user_system.register()
            print("Welcome to Portfolio Manager!")
            # Initialize Portfolio Manager after successful registering
            user_menu(username, conn, user_system)
        elif choice == '2':
            username = user_system.login()
            if username:
                print("Welcome to Portfolio Manager!")
                # Initialize Portfolio Manager after successful login
                user_menu(username, conn, user_system)
        elif choice == '3':
            print("Goodbye!")
            break
        else:
            print("Invalid option. Please try again.")

# ------------------------------
# User Menu After Login
# ------------------------------
def user_menu(username, conn, user_system):
    portfolio = Portfolio(username, conn)

    # Fetch risk tolerance from the database
    cursor = conn.cursor()
    cursor.execute('''
        SELECT risk_tolerance FROM users WHERE username = ?
    ''', (username,))
    result = cursor.fetchone()
    risk_tolerance = result[0] if result else "Medium"  # Default to "Medium"

    while True:
        print(f"\n--- Portfolio Management for {username} ---")
        print("1. User Guide")
        print("2. Add Stock to Portfolio")
        print("3. Remove Stock from Portfolio")
        print("4. View Portfolio")
        print("5. View Past Transactions")
        print("6. Fetch Stock Info")
        print("7. Import Portfolio")
        print("8. Update your Risk Tolerance")
        print("9. Logout")

        choice = input("Select an option: ")

        if choice == '1':
            user_guide(conn)

        elif choice == '2':
            ticker = input("Enter stock ticker: ").upper()
            while True:
              shares_input = input("Enter number of shares: ").strip()
              if shares_input.isdigit():
                shares = int(shares_input)
                break
            else:
                print("Invalid input. Please enter a valid number of shares.")

            portfolio.add_stock(ticker, shares)

        elif choice == '3':
            ticker = input("Enter stock ticker: ").upper()
            while True:
                try:
                    shares = int(input("Enter number of shares to remove: "))
                    break
                except ValueError:
                    print("Invalid input. Please enter a numeric value.")
            portfolio.remove_stock(ticker, shares)

        elif choice == '4':
            portfolio.view_portfolio()

        elif choice == '5':
            portfolio.past_transactions()

        elif choice == '6':
            while True:
                ticker = None
                data = None
                ticker = input("Enter stock ticker: ").upper()
                data = fetch_stock_data(ticker)
                if data:
                    break
                else:
                    print("Ticker does not exist. Please try again.")
            print(f"\nStock Info for {ticker}:")
            # Prepare the data to print
            stock_info_text = ""
            for key, value in data.items():
               if key != 'Returns': # Not print 'Returns'
                print(f"{key}: {value}")
                stock_info_text += f"{key}: {value}\n"  # Append each piece of information to the text

            # Save stock information to a text file
            filename = None
            saved_filename = None
            while True:
                save_text_option = input("Would you like to save this stock information to a text file? (y/n): ").strip().lower()
                if save_text_option == 'y':
                    filename = input("Enter filename for the text file (without extension): ").strip()
                    with open(f"{filename}.txt", "w") as file:
                        file.write(f"Stock Info for {ticker}:\n")
                        file.write(stock_info_text)
                        saved_filename = f"{filename}.txt"  # Store the filename for future appending
                        print(f"Stock information saved as {filename}.txt")
                    break
                elif save_text_option == 'n':
                    break
                else:
                    print("Invalid choice. Please try again.")

            print("Please wait while the stock price for the last 6 months is loading!")
            plot_stock_price(ticker)

            plt.show(block=False)

            while True:
                print(f"\nView more options for Stock {ticker}!")
                print("1. Get Stock Recommendation")
                print("2. View Stock's Market Sentiment")
                print("3. Back to Main Menu")
                sub_choice = input("Enter your choice: ")

                if sub_choice == "1":
                    recommendation = recommend_stocks(ticker, risk_tolerance)
                    print("Recommendation: \n", recommendation)

                    # Check if we have a filename to append to
                    if saved_filename:
                        # Get the current date and time
                        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        with open(saved_filename, "a", encoding="utf-8") as file:  # Open file in append mode and use UTF-8 encoding
                            file.write(f"\nStock Recommendation on {current_time}:\n")
                            file.write(recommendation + "\n")
                        print(f"Stock recommendation appended to {saved_filename}")

                elif sub_choice == "2":
                    # Fetch and display the market sentiment for the ticker
                    sentiment_result = get_market_sentiment(ticker)
                    if sentiment_result:
                        if saved_filename:
                            # Get the current date and time for market sentiment
                            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            with open(saved_filename, "a", encoding="utf-8") as file:  # Use UTF-8 encoding
                                file.write(f"\nMarket Sentiment on {current_time}:\n")
                                file.write(f"{sentiment_result}\n")
                            print(f"Market sentiment appended to {saved_filename}")

                elif sub_choice == "3":
                    break
                else:
                    print("Invalid choice. Please try again.")

        elif choice == '7':
            portfolio.import_portfolio()

        elif choice == '8':
            risk_tolerance = get_risk_tolerance(conn, username, risk_tolerance)

        elif choice == '9':
            print("Logging out...")
            user_system.logout()
            break
        else:
            print("Invalid option. Please try again.")


if __name__ == "__main__":
    main()