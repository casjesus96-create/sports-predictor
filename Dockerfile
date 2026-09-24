# =========================================================
# ETAPA 1 — CONSTRUIR FRONTEND REACT
# =========================================================

FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

# Copiar archivos del frontend
COPY package.json ./
COPY App.tsx ./
COPY main.tsx ./
COPY index.html ./
COPY styles.css ./

# Instalar dependencias
RUN npm install

# Construir aplicación React/Vite
RUN npm run build


# =========================================================
# ETAPA 2 — BACKEND FASTAPI
# =========================================================

FROM python:3.13-slim

WORKDIR /app

# ---------------------------------------------------------
# Dependencias Python
# ---------------------------------------------------------

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt


# ---------------------------------------------------------
# Código Python
# ---------------------------------------------------------

COPY *.py ./


# ---------------------------------------------------------
# Frontend compilado
# ---------------------------------------------------------

COPY --from=frontend-builder /frontend/dist ./dist


# ---------------------------------------------------------
# Servidor
# ---------------------------------------------------------

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
