"""Tool to search for wrap logic."""
import sqlite3

from iwa.core.constants import DATA_DIR

db_path = DATA_DIR / "activity.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

hash_to_find = "0xbc6aa95a7dcf611413c72f163d7c7138af68d265ef85f73b94199fdb89d13f36"

cursor.execute("SELECT * FROM senttransaction WHERE tx_hash = ?", (hash_to_find,))
row = cursor.fetchone()

if row:
    print(f"FOUND: {row}")
else:
    print("NOT FOUND")
