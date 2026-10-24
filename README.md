# Sports Predictor v1.0 Cloud
React/Vite frontend + FastAPI backend + Supabase PostgreSQL.

Render backend:
Build: `pip install -r requirements.txt`
Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
Root directory: `backend`

Run `database/schema.sql` in Supabase SQL Editor before enabling persistence.
Never commit `.env` or service-role keys.


## Integración inicial de fútbol

El módulo de fútbol usa football-data.org v4 desde el backend FastAPI. La clave **solo** debe configurarse como variable de entorno del servidor:

- `FOOTBALL_DATA_API_KEY`: token de football-data.org.
- No colocar el token en React/Vite, en archivos `.tsx`, en `.env` versionados ni en el repositorio.
- Si un token fue compartido públicamente, revocarlo y generar otro antes de desplegar.
- En Render, configurar `FOOTBALL_DATA_API_KEY` en Environment del servicio backend y después desplegar.

Endpoints iniciales:

- `GET /api/v1/football/health`: indica si la variable está configurada; nunca devuelve el token.
- `GET /api/v1/football/competitions`: comprueba cuáles de las siete competiciones aparecen en el catálogo accesible con el plan actual.
- `GET /api/v1/football/games?competition=PL`: partidos de una competición; admite `dateFrom=YYYY-MM-DD` y `dateTo=YYYY-MM-DD`.
- `GET /api/v1/football/standings?competition=PL`: clasificación disponible.

Códigos admitidos: `PL`, `PD`, `SA`, `BL1`, `FL1`, `DED`, `PPL`. La presencia de un código en la interfaz no garantiza que la suscripción permita consultar todos sus recursos; el backend reporta los permisos reales y no simula datos. El cliente mantiene una caché en memoria de 60 segundos para reducir llamadas en el plan gratuito (10 solicitudes/minuto).

Esta entrega es una integración de datos, **no activa todavía un modelo predictivo de fútbol ni afirma rentabilidad**. El modelo se implementará tras validar cobertura, disponibilidad histórica y esquema de persistencia. Atribución visible: “Data provided by football-data.org”.
