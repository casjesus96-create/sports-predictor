# =========================================================
# ETAPA 1 — FRONTEND
# =========================================================

FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY package.json ./

COPY App.tsx ./
COPY main.tsx ./
COPY index.html ./
COPY styles.css ./
COPY tsconfig.json ./

RUN npm install

RUN npm run build


# =========================================================
# ETAPA 2 — BACKEND
# =========================================================

FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Copiar frontend compilado
COPY --from=frontend-builder /frontend/dist ./dist

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
