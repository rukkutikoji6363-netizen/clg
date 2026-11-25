"""All LLM features: inventory chat agent (tool use), drug info, prescription parsing, reorder drafts."""
import json
import os
import re
from datetime import date, timedelta

import anthropic

from . import db

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    return _client


SYSTEM = (
    "You are the assistant inside a pharmacy management system, used by pharmacy staff. "
    "Use the provided tools to answer questions about stock, expiry and sales with real data; never invent numbers. "
    "Be concise. For clinical questions give general reference information only and remind staff that a "
    "licensed pharmacist or doctor must confirm before dispensing or advising a patient."
)

TOOLS = [
    {"name": "search_medicines", "description": "Search inventory by brand or generic name.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "low_stock", "description": "List medicines at or below their reorder level.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "expiring_soon", "description": "List medicines expired or expiring within N days.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": ["days"]}},
    {"name": "sales_summary", "description": "Revenue and number of sales over the last N days.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": ["days"]}},
    {"name": "top_sellers", "description": "Best-selling medicines over the last N days.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}, "limit": {"type": "integer"}},
                      "required": ["days"]}},
]


def since(days):
    return (date.today() - timedelta(days=int(days))).isoformat()


def run_tool(name, a):
    if name == "search_medicines":
        like = f"%{a['query']}%"
        return db.q("SELECT * FROM medicines WHERE name LIKE ? OR generic_name LIKE ? LIMIT 20", (like, like))
    if name == "low_stock":
        return db.q("SELECT * FROM medicines WHERE quantity <= reorder_level ORDER BY quantity")
    if name == "expiring_soon":
        limit = (date.today() + timedelta(days=int(a["days"]))).isoformat()
        return db.q("SELECT * FROM medicines WHERE expiry_date <= ? ORDER BY expiry_date", (limit,))
    if name == "sales_summary":
        return db.q("SELECT COUNT(*) AS sales, COALESCE(SUM(total),0) AS revenue FROM sales WHERE created_at >= ?",
                    (since(a["days"]),), one=True)
    if name == "top_sellers":
        return db.q("SELECT m.name, SUM(i.qty) AS units FROM sale_items i JOIN sales s ON s.id=i.sale_id "
                    "JOIN medicines m ON m.id=i.medicine_id WHERE s.created_at >= ? "
                    "GROUP BY m.id ORDER BY units DESC LIMIT ?", (since(a["days"]), int(a.get("limit", 5))))
    return {"error": "unknown tool"}


def text_of(resp):
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def ask(system, user, max_tokens=1200):
    r = client().messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": user}])
    return text_of(r)


def chat(messages):
    """Agent loop: let the model call read-only inventory tools until it has an answer."""
    msgs = [{"role": m["role"], "content": m["content"]} for m in messages]
    for _ in range(6):
        r = client().messages.create(model=MODEL, max_tokens=1500, system=SYSTEM, tools=TOOLS, messages=msgs)
        if r.stop_reason != "tool_use":
            return text_of(r)
        msgs.append({"role": "assistant", "content": r.content})
        results = [{"type": "tool_result", "tool_use_id": b.id,
                    "content": json.dumps(run_tool(b.name, b.input), default=str)}
                   for b in r.content if b.type == "tool_use"]
        msgs.append({"role": "user", "content": results})
    return "Sorry, I couldn't finish that request. Try a more specific question."


def drug_info(name):
    return ask(SYSTEM, f"Give a short reference card for '{name}': uses, typical adult dose range, common side effects, "
                       "key interactions and contraindications, counselling points, and 2-3 common substitutes "
                       "with the same active ingredient. End with a reminder that a pharmacist must verify.")


def parse_prescription(text):
    """Extract medicines from free-text prescription, then match them to inventory."""
    raw = ask("You extract data. Reply with ONLY a JSON array, no prose.",
              "From this prescription text return [{\"name\": str, \"dosage\": str, \"quantity\": int}]. "
              "If quantity is unclear use 1.\n\n" + text, 800)
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Could not read the prescription. Check the text and try again.", "raw": raw}
    out = []
    for it in items:
        like = f"%{str(it.get('name', '')).split()[0]}%" if it.get("name") else "%"
        matches = db.q("SELECT id,name,generic_name,quantity,price,expiry_date FROM medicines "
                       "WHERE (name LIKE ? OR generic_name LIKE ?) AND expiry_date >= ? ORDER BY quantity DESC LIMIT 3",
                       (like, like, date.today().isoformat()))
        out.append({**it, "matches": matches})
    return {"items": out}


def reorder_draft():
    low = db.q("SELECT name,supplier,quantity,reorder_level FROM medicines WHERE quantity <= reorder_level")
    vel = db.q("SELECT m.name, SUM(i.qty) AS units_30d FROM sale_items i JOIN sales s ON s.id=i.sale_id "
               "JOIN medicines m ON m.id=i.medicine_id WHERE s.created_at >= ? GROUP BY m.id", (since(30),))
    if not low:
        return "Nothing is below its reorder level right now."
    return ask(SYSTEM, "Draft purchase orders grouped by supplier for these low-stock items. Suggest a quantity "
                       "for each using the 30-day sales data (about 30 days of cover; if no sales data, "
                       "use 2x the reorder level). Show a short table per supplier.\n"
                       f"Low stock: {json.dumps(low)}\n30-day sales: {json.dumps(vel)}", 1500)
