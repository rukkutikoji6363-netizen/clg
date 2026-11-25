"""FastAPI app: inventory, billing, dashboard and AI endpoints. Run: uvicorn backend.main:app --reload"""
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
from . import db, llm  # noqa: E402  (import after load_dotenv so env vars apply)

app = FastAPI(title="Pharmacy AI")
db.init()


# ---------- schemas ----------
class MedicineIn(BaseModel):
    name: str
    generic_name: str = ""
    category: str = ""
    batch_no: str = ""
    expiry_date: str  # YYYY-MM-DD
    quantity: int = Field(ge=0)
    reorder_level: int = Field(ge=0, default=10)
    price: float = Field(ge=0)
    supplier: str = ""


class SaleItem(BaseModel):
    medicine_id: int
    qty: int = Field(gt=0)


class SaleIn(BaseModel):
    customer: str = "Walk-in"
    items: List[SaleItem]


class ChatIn(BaseModel):
    messages: List[dict]


class TextIn(BaseModel):
    text: str


# ---------- inventory ----------
@app.get("/api/medicines")
def list_medicines(search: str = ""):
    like = f"%{search}%"
    return db.q("SELECT * FROM medicines WHERE name LIKE ? OR generic_name LIKE ? ORDER BY name", (like, like))


@app.post("/api/medicines")
def add_medicine(m: MedicineIn):
    c = db.conn()
    cur = c.execute(
        "INSERT INTO medicines(name,generic_name,category,batch_no,expiry_date,quantity,reorder_level,price,supplier)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (m.name, m.generic_name, m.category, m.batch_no, m.expiry_date, m.quantity, m.reorder_level, m.price, m.supplier))
    c.commit()
    new_id = cur.lastrowid
    c.close()
    return {"id": new_id}


@app.put("/api/medicines/{mid}")
def update_medicine(mid: int, m: MedicineIn):
    c = db.conn()
    cur = c.execute(
        "UPDATE medicines SET name=?,generic_name=?,category=?,batch_no=?,expiry_date=?,quantity=?,"
        "reorder_level=?,price=?,supplier=? WHERE id=?",
        (m.name, m.generic_name, m.category, m.batch_no, m.expiry_date, m.quantity, m.reorder_level,
         m.price, m.supplier, mid))
    c.commit()
    changed = cur.rowcount
    c.close()
    if not changed:
        raise HTTPException(404, "Medicine not found")
    return {"ok": True}


@app.delete("/api/medicines/{mid}")
def delete_medicine(mid: int):
    if db.q("SELECT 1 FROM sale_items WHERE medicine_id=? LIMIT 1", (mid,)):
        raise HTTPException(400, "This medicine has sales history and can't be deleted. Set its quantity to 0 instead.")
    c = db.conn()
    c.execute("DELETE FROM medicines WHERE id=?", (mid,))
    c.commit()
    c.close()
    return {"ok": True}


# ---------- billing ----------
@app.post("/api/sales")
def create_sale(s: SaleIn):
    if not s.items:
        raise HTTPException(400, "Add at least one item to the bill.")
    today = date.today().isoformat()
    c = db.conn()
    try:
        lines, total = [], 0.0
        for it in s.items:
            m = c.execute("SELECT * FROM medicines WHERE id=?", (it.medicine_id,)).fetchone()
            if not m:
                raise HTTPException(404, f"Medicine {it.medicine_id} not found")
            if m["expiry_date"] < today:
                raise HTTPException(400, f"{m['name']} is expired and can't be sold.")
            if m["quantity"] < it.qty:
                raise HTTPException(400, f"Only {m['quantity']} of {m['name']} in stock.")
            lines.append((it.medicine_id, it.qty, m["price"]))
            total += it.qty * m["price"]
        cur = c.execute("INSERT INTO sales(customer,total,created_at) VALUES (?,?,?)",
                        (s.customer or "Walk-in", round(total, 2), datetime.now().isoformat(timespec="seconds")))
        sale_id = cur.lastrowid
        for mid, qty, price in lines:
            c.execute("INSERT INTO sale_items(sale_id,medicine_id,qty,unit_price) VALUES (?,?,?,?)",
                      (sale_id, mid, qty, price))
            c.execute("UPDATE medicines SET quantity = quantity - ? WHERE id=?", (qty, mid))
        c.commit()
        return {"id": sale_id, "total": round(total, 2)}
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


@app.get("/api/sales")
def recent_sales():
    return db.q("SELECT * FROM sales ORDER BY id DESC LIMIT 50")


# ---------- dashboard ----------
@app.get("/api/dashboard")
def dashboard():
    today = date.today()
    soon = (today + timedelta(days=30)).isoformat()
    today_sales = db.q("SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS revenue FROM sales WHERE created_at >= ?",
                       (today.isoformat(),), one=True)
    return {
        "today": today_sales,
        "low_stock": db.q("SELECT * FROM medicines WHERE quantity <= reorder_level ORDER BY quantity"),
        "expiring": db.q("SELECT * FROM medicines WHERE expiry_date <= ? ORDER BY expiry_date", (soon,)),
        "total_medicines": db.q("SELECT COUNT(*) AS n FROM medicines", one=True)["n"],
    }


# ---------- AI ----------
def guarded(fn, *args):
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "ANTHROPIC_API_KEY is not set. Add it to your .env file and restart the server.")
    try:
        return fn(*args)
    except Exception as e:  # surface API errors as readable messages
        raise HTTPException(502, f"AI request failed: {e}")


@app.post("/api/ai/chat")
def ai_chat(body: ChatIn):
    return {"reply": guarded(llm.chat, body.messages)}


@app.post("/api/ai/drug-info")
def ai_drug_info(body: TextIn):
    return {"reply": guarded(llm.drug_info, body.text)}


@app.post("/api/ai/prescription")
def ai_prescription(body: TextIn):
    return guarded(llm.parse_prescription, body.text)


@app.post("/api/ai/reorder")
def ai_reorder():
    return {"reply": guarded(llm.reorder_draft)}


# ---------- frontend ----------
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
