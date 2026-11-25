# Pharmacy AI

Pharmacy management web app with Claude built in. Python (FastAPI + SQLite) backend, plain HTML/JS frontend, no build step.

**Features**
- Dashboard: sales today, low-stock and expiring medicines
- Inventory: add, edit, delete, search; expiry and reorder tracking
- Billing: cart, stock checks, expired-item blocking, automatic stock deduction
- AI assistant: chat that queries live inventory and sales via tool use
- AI drug reference cards, prescription-to-inventory matching, and draft purchase orders

## Run it
```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # then paste your ANTHROPIC_API_KEY
uvicorn backend.main:app --reload
```
Open http://localhost:8000. Demo medicines are created on first start. Without an API key, everything except the AI features works.

Docker: `docker build -t pharmacy-ai . && docker run -p 8000:8000 --env-file .env pharmacy-ai`

## Structure
```
backend/db.py     SQLite schema, helpers, demo data
backend/llm.py    Claude features (tool-use agent, drug info, prescription parsing, reorder drafts)
backend/main.py   REST API + serves the frontend
frontend/         index.html (all UI)
```

## Before real-world use
- Add login and roles (pharmacist, cashier); the API is currently open.
- Add prescription records, patient data handling, and audit logs to meet your local pharmacy regulations.
- AI output is reference only. A licensed pharmacist must verify it before dispensing or advising patients.
- Use PostgreSQL instead of SQLite for multi-user production deployments.
