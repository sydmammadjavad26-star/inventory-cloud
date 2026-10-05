import os
import sqlite3
import hashlib
import secrets
from flask import Flask, request, jsonify, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "inventory.db")

app = Flask(
    __name__,
    static_folder="../mobile",
    static_url_path=""
)

TOKENS = {}


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT DEFAULT '',
            purchase_price REAL DEFAULT 0,
            sale_price REAL DEFAULT 0,
            stock INTEGER DEFAULT 0,
            shelf TEXT DEFAULT '',
            last_purchase TEXT DEFAULT '-',
            last_sale TEXT DEFAULT '-'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sales(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            date TEXT NOT NULL
        )
    """)

    row = c.execute(
        "SELECT id FROM users WHERE username='admin'"
    ).fetchone()

    if not row:
        salt = secrets.token_hex(16)
        h = hashlib.sha256(
            (salt + "1234").encode()
        ).hexdigest()

        c.execute(
            "INSERT INTO users(username,password_hash,salt) VALUES(?,?,?)",
            ("admin", h, salt)
        )

    c.commit()
    c.close()


def token_user():
    t = request.headers.get("Authorization", "")

    if not t.startswith("Bearer "):
        return None

    return TOKENS.get(t[7:])


@app.get("/")
def home():
    return send_from_directory(
        app.static_folder,
        "index.html"
    )


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}

    username = data.get("username", "")
    password = data.get("password", "")

    c = db()

    row = c.execute(
        "SELECT * FROM users WHERE username=?",
        (username,)
    ).fetchone()

    c.close()

    if not row:
        return jsonify(
            error="نام کاربری یا رمز عبور اشتباه است"
        ), 401

    h = hashlib.sha256(
        (row["salt"] + password).encode()
    ).hexdigest()

    if not secrets.compare_digest(
        h,
        row["password_hash"]
    ):
        return jsonify(
            error="نام کاربری یا رمز عبور اشتباه است"
        ), 401

    t = secrets.token_urlsafe(32)

    TOKENS[t] = row["id"]

    return jsonify(token=t)


@app.get("/api/products")
def products():
    if not token_user():
        return jsonify(error="نیاز به ورود"), 401

    c = db()

    rows = c.execute(
        "SELECT * FROM products ORDER BY name"
    ).fetchall()

    c.close()

    return jsonify([dict(r) for r in rows])


@app.post("/api/products")
def add_product():
    if not token_user():
        return jsonify(error="نیاز به ورود"), 401

    d = request.get_json(silent=True) or {}

    try:
        c = db()

        cur = c.execute("""
            INSERT INTO products
            (
                name,
                category,
                purchase_price,
                sale_price,
                stock,
                shelf,
                last_purchase,
                last_sale
            )
            VALUES(?,?,?,?,?,?,?,?)
        """, (
            d.get("name", ""),
            d.get("category", ""),
            float(d.get("purchase_price", 0)),
            float(d.get("sale_price", 0)),
            int(d.get("stock", 0)),
            d.get("shelf", ""),
            d.get("last_purchase", "-"),
            d.get("last_sale", "-")
        ))

        c.commit()

        pid = cur.lastrowid

        c.close()

        return jsonify(id=pid), 201

    except Exception as e:
        return jsonify(error=str(e)), 400


@app.put("/api/products/<int:pid>")
def edit_product(pid):
    if not token_user():
        return jsonify(error="نیاز به ورود"), 401

    d = request.get_json(silent=True) or {}

    c = db()

    c.execute("""
        UPDATE products
        SET
            name=?,
            category=?,
            purchase_price=?,
            sale_price=?,
            stock=?,
            shelf=?,
            last_purchase=?,
            last_sale=?
        WHERE id=?
    """, (
        d.get("name", ""),
        d.get("category", ""),
        float(d.get("purchase_price", 0)),
        float(d.get("sale_price", 0)),
        int(d.get("stock", 0)),
        d.get("shelf", ""),
        d.get("last_purchase", "-"),
        d.get("last_sale", "-"),
        pid
    ))

    c.commit()
    c.close()

    return jsonify(ok=True)


@app.delete("/api/products/<int:pid>")
def delete_product(pid):
    if not token_user():
        return jsonify(error="نیاز به ورود"), 401

    c = db()

    c.execute(
        "DELETE FROM products WHERE id=?",
        (pid,)
    )

    c.commit()
    c.close()

    return jsonify(ok=True)


@app.post("/api/sales")
def sale():
    if not token_user():
        return jsonify(error="نیاز به ورود"), 401

    d = request.get_json(silent=True) or {}

    pid = int(d.get("product_id", 0))
    amount = int(d.get("amount", 0))
    date = d.get("date", "")

    if amount <= 0:
        return jsonify(
            error="تعداد فروش باید بیشتر از صفر باشد"
        ), 400

    c = db()

    p = c.execute(
        "SELECT * FROM products WHERE id=?",
        (pid,)
    ).fetchone()

    if not p:
        c.close()
        return jsonify(error="کالا پیدا نشد"), 404

    if p["stock"] < amount:
        c.close()
        return jsonify(error="موجودی کافی نیست"), 400

    c.execute(
        """
        UPDATE products
        SET stock=stock-?, last_sale=?
        WHERE id=?
        """,
        (amount, date, pid)
    )

    c.execute(
        """
        INSERT INTO sales(product_id,amount,date)
        VALUES(?,?,?)
        """,
        (pid, amount, date)
    )

    c.commit()
    c.close()

    return jsonify(ok=True)


@app.get("/api/report")
def report():
    if not token_user():
        return jsonify(error="نیاز به ورود"), 401

    month = request.args.get("month", "")

    c = db()

    inv = c.execute(
        """
        SELECT COALESCE(
            SUM(sale_price * stock), 0
        ) v
        FROM products
        """
    ).fetchone()["v"]

    sales = c.execute(
        """
        SELECT COALESCE(
            SUM(s.amount * p.sale_price), 0
        ) v
        FROM sales s
        JOIN products p
        ON p.id=s.product_id
        WHERE s.date LIKE ?
        """,
        (month + "%",)
    ).fetchone()["v"]

    c.close()

    return jsonify(
        month=month,
        sales=sales,
        inventory_value=inv
    )


@app.post("/api/change-password")
def change_password():
    uid = token_user()

    if not uid:
        return jsonify(error="نیاز به ورود"), 401

    d = request.get_json(silent=True) or {}

    new = d.get("password", "")

    if len(new) < 4:
        return jsonify(
            error="رمز باید حداقل ۴ کاراکتر باشد"
        ), 400

    salt = secrets.token_hex(16)

    h = hashlib.sha256(
        (salt + new).encode()
    ).hexdigest()

    c = db()

    c.execute(
        """
        UPDATE users
        SET password_hash=?, salt=?
        WHERE id=?
        """,
        (h, salt, uid)
    )

    c.commit()
    c.close()

    return jsonify(ok=True)


init_db()


if __name__ == "__main__":
    port = int(
        os.environ.get("PORT", "8000")
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
