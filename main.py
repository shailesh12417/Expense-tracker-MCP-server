from fastmcp import FastMCP
import os
import aiosqlite
import json
import tempfile
# ------------------ PATH SETUP ------------------

TEMP_DIR = tempfile.gettempdir()
DB_PATH = os.path.join(TEMP_DIR, "expenses.db")
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

print(f"Database path: {DB_PATH}")

mcp = FastMCP("ExpenseTracker")

# ------------------ INIT DB ------------------

def init_db():
    try:
        import sqlite3
        with sqlite3.connect(DB_PATH) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""
                CREATE TABLE IF NOT EXISTS expenses(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    payment_method TEXT DEFAULT 'cash',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT,
                    is_deleted INTEGER DEFAULT 0
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_date ON expenses(date)")
            print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization error: {e}")
        raise

init_db()

# ------------------ ADD EXPENSE ------------------

@mcp.tool()
async def add_expense(date, amount, category, subcategory="", note="", payment_method="cash"):
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                INSERT INTO expenses(date, amount, category, subcategory, note, payment_method)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (date, amount, category, subcategory, note, payment_method)
            )
            await c.commit()
            return {"status": "success", "id": cur.lastrowid}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ LIST EXPENSES ------------------

@mcp.tool()
async def list_expenses(start_date, end_date):
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                SELECT * FROM expenses
                WHERE date BETWEEN ? AND ? AND is_deleted = 0
                ORDER BY date DESC, id DESC
                """,
                (start_date, end_date)
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ UPDATE EXPENSE ------------------

@mcp.tool()
async def update_expense(expense_id: int, amount=None, category=None,
                         subcategory=None, note=None, payment_method=None):
    try:
        fields = []
        values = []

        if amount is not None:
            fields.append("amount = ?")
            values.append(amount)
        if category is not None:
            fields.append("category = ?")
            values.append(category)
        if subcategory is not None:
            fields.append("subcategory = ?")
            values.append(subcategory)
        if note is not None:
            fields.append("note = ?")
            values.append(note)
        if payment_method is not None:
            fields.append("payment_method = ?")
            values.append(payment_method)

        if not fields:
            return {"status": "error", "message": "Nothing to update"}

        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(expense_id)

        query = f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?"

        async with aiosqlite.connect(DB_PATH) as c:
            await c.execute(query, values)
            await c.commit()

        return {"status": "success", "message": "Expense updated"}

    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ DELETE EXPENSE ------------------

@mcp.tool()
async def delete_expense(expense_id: int):
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            await c.execute(
                "UPDATE expenses SET is_deleted = 1 WHERE id = ?",
                (expense_id,)
            )
            await c.commit()
            return {"status": "success", "message": "Expense deleted"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ TOTAL EXPENSE ------------------

@mcp.tool()
async def total_expense(start_date, end_date):
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                "SELECT SUM(amount) FROM expenses WHERE date BETWEEN ? AND ? AND is_deleted = 0",
                (start_date, end_date)
            )
            total = (await cur.fetchone())[0] or 0
            return {"status": "success", "total": total}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ SUMMARIZE ------------------

@mcp.tool()
async def summarize(start_date, end_date, category=None):
    try:
        query = """
            SELECT category, SUM(amount) AS total_amount, COUNT(*) as count
            FROM expenses
            WHERE date BETWEEN ? AND ? AND is_deleted = 0
        """
        params = [start_date, end_date]

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " GROUP BY category ORDER BY total_amount DESC"

        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(query, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]

    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ CATEGORY BREAKDOWN ------------------

@mcp.tool()
async def category_breakdown(start_date, end_date):
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                SELECT category, SUM(amount)
                FROM expenses
                WHERE date BETWEEN ? AND ? AND is_deleted = 0
                GROUP BY category
                """,
                (start_date, end_date)
            )
            data = await cur.fetchall()

            total = sum(row[1] for row in data)

            result = []
            for category, amt in data:
                percent = (amt / total * 100) if total > 0 else 0
                result.append({
                    "category": category,
                    "amount": amt,
                    "percentage": round(percent, 2)
                })

            return result

    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ SEARCH ------------------

@mcp.tool()
async def search_expenses(keyword: str):
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                SELECT * FROM expenses
                WHERE (note LIKE ? OR category LIKE ?) AND is_deleted = 0
                """,
                (f"%{keyword}%", f"%{keyword}%")
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ BUDGET CHECK ------------------

@mcp.tool()
async def check_budget(limit: float, start_date, end_date):
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                "SELECT SUM(amount) FROM expenses WHERE date BETWEEN ? AND ? AND is_deleted = 0",
                (start_date, end_date)
            )
            total = (await cur.fetchone())[0] or 0

            return {
                "status": "success",
                "total_spent": total,
                "budget": limit,
                "result": "exceeded" if total > limit else "within_budget"
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ CATEGORIES RESOURCE ------------------

@mcp.resource("expense:///categories", mime_type="application/json")
def categories():
    try:
        default_categories = {
            "categories": [
                "Food & Dining",
                "Transportation",
                "Shopping",
                "Entertainment",
                "Bills & Utilities",
                "Healthcare",
                "Travel",
                "Education",
                "Business",
                "Other"
            ]
        }

        try:
            with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return json.dumps(default_categories, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})

# ------------------ RUN SERVER ------------------

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)

