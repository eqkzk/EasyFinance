from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
from datetime import datetime

app = Flask(__name__)

# Database connection
def get_db_connection():
    conn = sqlite3.connect('portfolio.db')
    conn.row_factory = sqlite3.Row
    return conn

# Home page (renders user guide)
@app.route('/')
def home():
    return render_template('userguide.html')

# Stock info lookup
@app.route('/get_stock_info')
def get_stock_info():
    company_name = request.args.get('ticker', '')  # assuming frontend sends 'ticker' as company name
    if not company_name:
        return jsonify({'error': 'No company name provided'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Full-text search using FTS5 virtual table
    cursor.execute("SELECT rowid FROM companies_fts WHERE companies_fts MATCH ? ORDER BY rank LIMIT 5", (company_name,))
    fts_res = cursor.fetchall()

    if not fts_res:
        return jsonify({'error': 'No matching company found'}), 404

    rowids = [str(row['rowid']) for row in fts_res]
    param_placeholders = ','.join(['?'] * len(rowids))

    query = f"SELECT ticker, name, industry FROM companies WHERE rowid IN ({param_placeholders})"
    cursor.execute(query, rowids)
    results = cursor.fetchall()

    conn.close()

    if results:
        top_result = results[0]  # Return the first match
        return jsonify({
            'stock_data': {
                'Ticker': top_result['ticker'],
                'Company': top_result['name'],
                'Industry': top_result['industry']
            }
        })
    else:
        return jsonify({'error': 'No company data found'}), 404

# Logout endpoint
@app.route('/logout', methods=['POST'])
def logout():
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True)