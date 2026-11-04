# API-Football: estadísticas de partidos finalizados

## Configuración

1. Crear/usar una cuenta en API-Football (API-Sports) y comprobar que el plan cubre las competiciones y temporadas que Sports Predictor necesita.
2. En Render, abrir el servicio del backend → Environment.
3. Añadir `API_FOOTBALL_KEY` con la clave privada del panel de API-Sports.
4. Guardar los cambios y desplegar/reiniciar el servicio.

La clave se utiliza exclusivamente en el backend. No debe incluirse en React, variables `VITE_*`, commits, capturas ni respuestas del endpoint.

Opcionalmente, `API_FOOTBALL_BASE_URL` permite apuntar a un host compatible; por defecto se usa `https://v3.football.api-sports.io`.

## Endpoint disponible

`GET /api/v1/football/match-statistics/{football_data_match_id}`

- Usa football-data.org para verificar el partido, estado final y marcador.
- Busca el encuentro equivalente en API-Football por fecha UTC y nombres de ambos equipos normalizados.
- Solo acepta estados finales `FT`, `AET` o `PEN` en API-Football.
- Devuelve estadísticas observadas disponibles: corners, tarjetas, tiros, posesión, pases, faltas, fueras de juego y atajadas.
- Mantiene caché en memoria de seis horas para la búsqueda de fixtures y estadísticas.
- Si no existe una coincidencia única, no adivina ni asocia otro encuentro.

## Límites de esta primera integración

Esta primera fase es de consulta/visualización de estadísticas de un partido ya finalizado. No modifica las probabilidades oficiales, no escribe estadísticas históricas en Supabase y no genera mercados de corners/tarjetas todavía.

Antes de construir esas probabilidades, la siguiente fase debe:
- medir cobertura por competición y temporada;
- persistir estadísticas y metadatos de fuente de forma idempotente;
- construir muestras cronológicas solo con partidos finalizados antes del kickoff objetivo;
- validar calibración y backtesting walk-forward;
- mantener mercados nuevos en modo experimental hasta superar los controles.

La disponibilidad histórica y los límites dependen del plan contratado en API-Football. Verificar cobertura y cuota diaria antes de activar una ingesta masiva.
