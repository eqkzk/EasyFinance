from flask import Flask, render_template, request
from db import init_db, search_company_by_name

app = Flask(__name__)


@app.route('/', methods=['GET', 'POST'])
def homepage():
    init_db()
    search_results = []
    query = ""

    if request.method == 'POST':
        query = request.form.get('company_name', '').strip()
        if query:
            conn = init_db()
            search_results = search_company_by_name(conn, query)
            conn.close()

    return render_template('userguide.html', results=search_results, query=query)


if __name__ == '__main__':
    app.run(debug=True)

    from flask import Flask, render_template, request
    from db import init_db, search_company_by_name

    app = Flask(__name__)

