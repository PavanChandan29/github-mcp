import sqlite3
from pathlib import Path

db_path = Path.home() / ".github-mcp" / "PavanChandan29.db"

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("Tables:")
for row in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table';"
):
    print("-", row["name"])

print("\nSample repos:")
for row in conn.execute(
    "SELECT repo, language, last_ingested_at FROM repos LIMIT 5;"
):
    print(dict(row))
