import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "database.db"

def get_connection():
    """Open or create the database."""

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA foreign_keys = ON") 
    conn.row_factory = sqlite3.Row
    return conn
