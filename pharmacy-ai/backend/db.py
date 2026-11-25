"""SQLite helpers, schema and demo data."""
import os
import sqlite3
from datetime import date, timedelta

DB_PATH = os.getenv("DB_PATH", "pharmacy.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS medicines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  generic_name TEXT DEFAULT '',
  category TEXT DEFAULT '',
  batch_no TEXT DEFAULT '',
  expiry_date TEXT NOT NULL,          -- YYYY-MM-DD
  quantity INTEGER NOT NULL DEFAULT 0,
  reorder_level INTEGER NOT NULL DEFAULT 10,
  price REAL NOT NULL DEFAULT 0,
  supplier TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer TEXT DEFAULT 'Walk-in',
  total REAL NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sale_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id INTEGER NOT NULL REFERENCES sales(id),
  medicine_id INTEGER NOT NULL REFERENCES medicines(id),
  qty INTEGER NOT NULL,
  unit_price REAL NOT NULL
);
"""


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def q(sql, args=(), one=False):
    """Run a SELECT and return list of dicts (or one dict / None)."""
    c = conn()
    try:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()
    if one:
        return rows[0] if rows else None
    return rows


def init():
    c = conn()
    c.executescript(SCHEMA)
    c.commit()
    c.close()
    if not q("SELECT 1 FROM medicines LIMIT 1"):
        seed()


def seed():
    today = date.today()
    d = lambda days: (today + timedelta(days=days)).isoformat()
    rows = [
        ("Crocin 500", "Paracetamol", "Analgesic", "B101", d(400), 120, 30, 2.5, "Sun Distributors"),
        ("Augmentin 625", "Amoxicillin + Clavulanate", "Antibiotic", "B102", d(200), 8, 20, 22.0, "MedLine"),
        ("Glycomet 500", "Metformin", "Antidiabetic", "B103", d(300), 60, 25, 3.2, "MedLine"),
        ("Pantop 40", "Pantoprazole", "Antacid", "B104", d(20), 45, 20, 6.5, "Sun Distributors"),
        ("Telma 40", "Telmisartan", "Antihypertensive", "B105", d(500), 15, 20, 7.8, "HealthPlus"),
        ("Cetzine", "Cetirizine", "Antihistamine", "B106", d(90), 70, 20, 1.9, "HealthPlus"),
        ("Azithral 500", "Azithromycin", "Antibiotic", "B107", d(15), 12, 15, 18.0, "MedLine"),
        ("Atorva 10", "Atorvastatin", "Statin", "B108", d(365), 90, 30, 5.1, "Sun Distributors"),
        ("Dolo 650", "Paracetamol", "Analgesic", "B109", d(600), 200, 50, 2.9, "HealthPlus"),
        ("ORS Sachet", "Oral rehydration salts", "Supplement", "B110", d(-5), 30, 10, 1.2, "MedLine"),
    ]
    c = conn()
    c.executemany(
        "INSERT INTO medicines(name,generic_name,category,batch_no,expiry_date,quantity,"
        "reorder_level,price,supplier) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
