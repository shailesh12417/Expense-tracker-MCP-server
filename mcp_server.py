from fastmcp import FastMCP
import os
import aiosqlite
import json

# ─────────────────────────────────────────
#  PATH SETUP
# ─────────────────────────────────────────
DB_PATH         = os.path.join(os.path.dirname(__file__), "expenses.db")
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

print(f"Database path: {DB_PATH}")

mcp = FastMCP("ExpenseTracker")


# ─────────────────────────────────────────
#  INIT DB  (adds user_id column safely)
# ─────────────────────────────────────────
def init_db():
    import sqlite3
    with sqlite3.connect(DB_PATH) as c:
        c.execute("PRAGMA journal_mode=WAL")

        # Create table with user_id from the start
        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL DEFAULT 0,
                date           TEXT    NOT NULL,
                amount         REAL    NOT NULL,
                category       TEXT    NOT NULL,
                subcategory    TEXT    DEFAULT '',
                note           TEXT    DEFAULT '',
                payment_method TEXT    DEFAULT 'cash',
                created_at     TEXT    DEFAULT CURRENT_TIMESTAMP,
                updated_at     TEXT,
                is_deleted     INTEGER DEFAULT 0
            )
        """)

        # Safe migration: add user_id to existing tables that don't have it
        existing_cols = [row[1] for row in c.execute("PRAGMA table_info(expenses)").fetchall()]
        if "user_id" not in existing_cols:
            c.execute("ALTER TABLE expenses ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
            print("Migrated: added user_id column to expenses table")

        c.execute("CREATE INDEX IF NOT EXISTS idx_date    ON expenses(date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON expenses(user_id)")
        print("Database initialized successfully")

init_db()


# ─────────────────────────────────────────
#  ADD EXPENSE
# ─────────────────────────────────────────
@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    user_id: int = 0,
    subcategory: str = "",
    note: str = "",
    payment_method: str = "cash",
):
    """Add a new expense. user_id scopes it to a specific user (0 = legacy/unowned)."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                INSERT INTO expenses(user_id, date, amount, category, subcategory, note, payment_method)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, date, amount, category, subcategory, note, payment_method)
            )
            await c.commit()
            return {"status": "success", "id": cur.lastrowid}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────
#  LIST EXPENSES
# ─────────────────────────────────────────
@mcp.tool()
async def list_expenses(start_date: str, end_date: str, user_id: int = 0):
    """List expenses in a date range for a specific user."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                SELECT * FROM expenses
                WHERE user_id = ? AND date BETWEEN ? AND ? AND is_deleted = 0
                ORDER BY date DESC, id DESC
                """,
                (user_id, start_date, end_date)
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────
#  UPDATE EXPENSE
# ─────────────────────────────────────────
@mcp.tool()
async def update_expense(
    expense_id: int,
    user_id: int = 0,
    amount: float = None,
    category: str = None,
    subcategory: str = None,
    note: str = None,
    payment_method: str = None,
):
    """Update an expense. user_id ensures users can only edit their own expenses."""
    try:
        fields, values = [], []

        if amount         is not None: fields.append("amount = ?");         values.append(amount)
        if category       is not None: fields.append("category = ?");       values.append(category)
        if subcategory    is not None: fields.append("subcategory = ?");    values.append(subcategory)
        if note           is not None: fields.append("note = ?");           values.append(note)
        if payment_method is not None: fields.append("payment_method = ?"); values.append(payment_method)

        if not fields:
            return {"status": "error", "message": "Nothing to update"}

        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.extend([expense_id, user_id])

        query = f"UPDATE expenses SET {', '.join(fields)} WHERE id = ? AND user_id = ?"

        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(query, values)
            await c.commit()
            if cur.rowcount == 0:
                return {"status": "error", "message": "Expense not found or not yours"}
        return {"status": "success", "message": "Expense updated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────
#  DELETE EXPENSE
# ─────────────────────────────────────────
@mcp.tool()
async def delete_expense(expense_id: int, user_id: int = 0):
    """Soft-delete an expense. user_id ensures users can only delete their own."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                "UPDATE expenses SET is_deleted = 1 WHERE id = ? AND user_id = ?",
                (expense_id, user_id)
            )
            await c.commit()
            if cur.rowcount == 0:
                return {"status": "error", "message": "Expense not found or not yours"}
        return {"status": "success", "message": "Expense deleted"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────
#  TOTAL EXPENSE
# ─────────────────────────────────────────
@mcp.tool()
async def total_expense(start_date: str, end_date: str, user_id: int = 0):
    """Get total spending in a date range for a specific user."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                SELECT SUM(amount) FROM expenses
                WHERE user_id = ? AND date BETWEEN ? AND ? AND is_deleted = 0
                """,
                (user_id, start_date, end_date)
            )
            total = (await cur.fetchone())[0] or 0
            return {"status": "success", "total": total}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────
#  SUMMARIZE
# ─────────────────────────────────────────
@mcp.tool()
async def summarize(start_date: str, end_date: str, user_id: int = 0, category: str = None):
    """Category-wise spending summary for a user."""
    try:
        query  = """
            SELECT category, SUM(amount) AS total_amount, COUNT(*) AS count
            FROM expenses
            WHERE user_id = ? AND date BETWEEN ? AND ? AND is_deleted = 0
        """
        params = [user_id, start_date, end_date]

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " GROUP BY category ORDER BY total_amount DESC"

        async with aiosqlite.connect(DB_PATH) as c:
            cur  = await c.execute(query, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────
#  CATEGORY BREAKDOWN
# ─────────────────────────────────────────
@mcp.tool()
async def category_breakdown(start_date: str, end_date: str, user_id: int = 0):
    """Category breakdown with percentages for a user."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                SELECT category, SUM(amount)
                FROM expenses
                WHERE user_id = ? AND date BETWEEN ? AND ? AND is_deleted = 0
                GROUP BY category
                """,
                (user_id, start_date, end_date)
            )
            data  = await cur.fetchall()
            total = sum(row[1] for row in data)

            return [
                {
                    "category":   cat,
                    "amount":     amt,
                    "percentage": round((amt / total * 100) if total > 0 else 0, 2),
                }
                for cat, amt in data
            ]
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────
#  SEARCH
# ─────────────────────────────────────────
@mcp.tool()
async def search_expenses(keyword: str, user_id: int = 0):
    """Search expenses by keyword in note or category for a user."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                SELECT * FROM expenses
                WHERE user_id = ? AND (note LIKE ? OR category LIKE ?) AND is_deleted = 0
                ORDER BY date DESC
                """,
                (user_id, f"%{keyword}%", f"%{keyword}%")
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────
#  CHECK BUDGET
# ─────────────────────────────────────────
@mcp.tool()
async def check_budget(limit: float, start_date: str, end_date: str, user_id: int = 0):
    """Check if a user's spending exceeded a budget limit."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                SELECT SUM(amount) FROM expenses
                WHERE user_id = ? AND date BETWEEN ? AND ? AND is_deleted = 0
                """,
                (user_id, start_date, end_date)
            )
            total = (await cur.fetchone())[0] or 0
            return {
                "status":       "success",
                "total_spent":  total,
                "budget":       limit,
                "remaining":    round(limit - total, 2),
                "result":       "exceeded" if total > limit else "within_budget",
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    


# ─────────────────────────────────────────
#  MCP PROMPT
# ─────────────────────────────────────────

@mcp.prompt()
def expense_agent_behavior():
    return """
You are an expense tracking assistant.

STRICT RULE:

If ALL of the following fields are present:
- amount
- category
- subcategory
- note
- date (YYYY-MM-DD)
- payment_method

→ Directly call the tool (add_expense or relevant)
→ DO NOT use the resource "expense:///categories"

---

If ANY of these is missing:
→ Ask the user for missing fields

---

ONLY use the resource "expense:///categories" when:
- category is missing
- category is unclear
- or user explicitly asks for categories

---

Never call the categories resource if category is already provided.

Be strict and avoid unnecessary steps.
"""


# ─────────────────────────────────────────
#  CATEGORIES RESOURCE
# ─────────────────────────────────────────
@mcp.resource("expense:///categories", mime_type="application/json")
def categories():
    """if all field like "'amount': number, 'category': 'string', 'sub_category': 'string', 'note': 'string', 'date': 'YYYY-MM-DD', 'payment_method': 'string'" are filled in this case there is no need to go through the resource like categories_data"""
    default = {
        "categories": [
            "food", "transport", "shopping", "entertainment",
            "bills", "healthcare", "travel", "education",
            "business", "personal_care", "subscriptions", "misc"
        ]
    }
    try:
        with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return json.dumps(default, indent=2)
    

    

# ─────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
