# Sports Predictor v1.0 Cloud
React/Vite frontend + FastAPI backend + Supabase PostgreSQL.

Render backend:
Build: `pip install -r requirements.txt`
Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
Root directory: `backend`

Run `database/schema.sql` in Supabase SQL Editor before enabling persistence.
Never commit `.env` or service-role keys.
