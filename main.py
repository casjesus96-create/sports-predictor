from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
from urllib.parse import urlparse

from auth_security import (
    AuthConfigurationError, AuthProviderError, refresh_session,
    revoke_session, sign_in, validate_access_token,
    token_assurance_level, enroll_totp, verify_totp,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pending_predictions import router as pending_router
from mlb_backtest_api import router as mlb_backtest_router
from tennis_api import router as tennis_router
from tennis_history_api import router as tennis_history_router
from decision_api import router as decision_router
from best_plays_api import router as best_plays_router
from market_lab_api import router as market_lab_router
from prediction_audit_api import router as prediction_audit_router
from football_api import router as football_router
from football_archive import router as football_archive_router
from football_evaluation_api import router as football_evaluation_router
from football_learning import router as football_learning_router

from analyzer import analyze_mlb_game
from nfl_api import router as nfl_router
from nba_api import router as nba_router
from repository import (
    save_analysis,
    settle_prediction,
    get_performance,
    get_predictions,
    get_supabase_client,
    reconcile_settled_prediction,
)


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Sports Predictor API",
    version="2.0.0",
    description=(
        "API de proyecciones deportivas con análisis MLB, NFL y NBA, "
        "forma histórica, análisis pregame y liquidación de resultados."
    ),
)

# =========================================================
# PRIVATE ADMIN AUTHENTICATION
# =========================================================

class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminMfaVerifyRequest(BaseModel):
    factor_id: str
    code: str


def _cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "true").strip().lower() not in {"0", "false", "no"}


def _set_auth_cookies(response: Response, session: dict) -> None:
    common = {"secure": _cookie_secure(), "httponly": True, "samesite": "strict", "path": "/"}
    response.set_cookie("sp_access_token", session["access_token"], max_age=session["expires_in"], **common)
    response.set_cookie("sp_refresh_token", session["refresh_token"], max_age=60 * 60 * 24 * 30, **common)


def _clear_auth_cookies(response: Response) -> None:
    common = {"secure": _cookie_secure(), "httponly": True, "samesite": "strict", "path": "/"}
    response.delete_cookie("sp_access_token", **common)
    response.delete_cookie("sp_refresh_token", **common)


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        # Unsafe browser requests must prove their origin; SameSite cookies are defense-in-depth.
        referer = request.headers.get("referer")
        if not referer:
            return False
        origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
    try:
        parsed_origin = urlparse(origin)
        origin_host = parsed_origin.netloc.casefold()
        request_host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip().casefold()
        request_scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip().casefold()
        return bool(origin_host) and origin_host == request_host and parsed_origin.scheme.casefold() == request_scheme
    except (TypeError, ValueError):
        return False


def _add_security_headers(request: Request, response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https://*.supabase.co")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.middleware("http")
async def protect_private_api(request: Request, call_next):
    path = request.url.path
    protected = path.startswith("/api/") or path in {"/docs", "/redoc", "/openapi.json"}

    if protected and request.method in {"POST", "PUT", "PATCH", "DELETE"} and not _same_origin(request):
        return _add_security_headers(request, JSONResponse(status_code=403, content={"detail": "Solicitud de origen no autorizado."}))

    refreshed = None
    if protected:
        access_token = request.cookies.get("sp_access_token")
        refresh_token = request.cookies.get("sp_refresh_token")
        try:
            user = validate_access_token(access_token) if access_token else None
            if user is None and refresh_token:
                refreshed = refresh_session(refresh_token)
                if refreshed:
                    user = validate_access_token(refreshed["access_token"])
            if user is None:
                return _add_security_headers(request, JSONResponse(
                    status_code=401, content={"detail": "Autenticación requerida."},
                    headers={"Cache-Control": "no-store"},
                ))
        except AuthConfigurationError:
            return _add_security_headers(request, JSONResponse(
                status_code=503, content={"detail": "La autenticación privada todavía no está configurada."},
                headers={"Cache-Control": "no-store"},
            ))
        except AuthProviderError:
            return _add_security_headers(request, JSONResponse(
                status_code=503, content={"detail": "No se pudo verificar la sesión con el proveedor de autenticación."},
                headers={"Cache-Control": "no-store"},
            ))

    response = await call_next(request)
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Cookie"
    if refreshed:
        _set_auth_cookies(response, refreshed)
    return _add_security_headers(request, response)


@app.get("/auth/status")
def auth_status(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    access_token = request.cookies.get("sp_access_token")
    refresh_token = request.cookies.get("sp_refresh_token")
    try:
        active_token = access_token
        user = validate_access_token(access_token) if access_token else None
        if user is None and refresh_token:
            session = refresh_session(refresh_token)
            if session:
                active_token = session["access_token"]
                user = validate_access_token(active_token)
                if user:
                    _set_auth_cookies(response, session)
        return {
            "authenticated": bool(user),
            "email": user.get("email") if user else None,
            "mfa_required": False,
            "mfa_verified": False,
            "mfa_factor_id": None,
            "mfa_setup_needed": False,
        }
    except AuthConfigurationError:
        raise HTTPException(status_code=503, detail="La autenticación privada todavía no está configurada.")
    except AuthProviderError:
        raise HTTPException(status_code=503, detail="No se pudo verificar la sesión.")


@app.post("/auth/login")
def auth_login(payload: AdminLoginRequest, request: Request, response: Response):
    if not _same_origin(request):
        raise HTTPException(status_code=403, detail="Solicitud de origen no autorizado.")
    response.headers["Cache-Control"] = "no-store"
    try:
        session = sign_in(payload.email, payload.password)
        if not session:
            raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")
        _set_auth_cookies(response, session)
        return {
            "success": True,
            "email": session["email"],
            "mfa_required": False,
        }
    except AuthConfigurationError:
        raise HTTPException(status_code=503, detail="La autenticación privada todavía no está configurada.")
    except AuthProviderError:
        raise HTTPException(status_code=503, detail="El servicio de autenticación no está disponible.")


@app.post("/auth/mfa/enroll")
def auth_mfa_enroll(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not _same_origin(request):
        raise HTTPException(status_code=403, detail="Solicitud de origen no autorizado.")
    token = request.cookies.get("sp_access_token")
    try:
        user = validate_access_token(token) if token else None
        if not user:
            raise HTTPException(status_code=401, detail="Inicia sesión nuevamente.")
        existing = [
            factor for factor in (user.get("factors") or [])
            if factor.get("factor_type") == "totp" and factor.get("status") == "verified"
        ]
        if existing:
            raise HTTPException(status_code=409, detail="Ya existe un segundo factor configurado.")
        setup = enroll_totp(token)
        return setup
    except AuthConfigurationError:
        raise HTTPException(status_code=503, detail="La autenticación privada no está configurada.")
    except AuthProviderError:
        raise HTTPException(status_code=503, detail="No se pudo configurar el segundo factor.")


@app.post("/auth/mfa/verify")
def auth_mfa_verify(payload: AdminMfaVerifyRequest, request: Request, response: Response):
    if not _same_origin(request):
        raise HTTPException(status_code=403, detail="Solicitud de origen no autorizado.")
    token = request.cookies.get("sp_access_token")
    try:
        user = validate_access_token(token) if token else None
        if not user:
            raise HTTPException(status_code=401, detail="Inicia sesión nuevamente.")
        session = verify_totp(token, payload.factor_id, payload.code)
        if not session:
            raise HTTPException(status_code=401, detail="Código de verificación incorrecto o vencido.")
        _set_auth_cookies(response, session)
        response.headers["Cache-Control"] = "no-store"
        return {"success": True, "email": session["email"], "mfa_verified": True}
    except AuthConfigurationError:
        raise HTTPException(status_code=503, detail="La autenticación privada no está configurada.")
    except AuthProviderError:
        raise HTTPException(status_code=503, detail="No se pudo verificar el segundo factor.")


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response):
    if not _same_origin(request):
        raise HTTPException(status_code=403, detail="Solicitud de origen no autorizado.")
    try:
        revoke_session(request.cookies.get("sp_access_token"))
    except (AuthConfigurationError, AuthProviderError):
        pass
    _clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return {"success": True}


app.include_router(pending_router)
app.include_router(mlb_backtest_router)
app.include_router(tennis_router)
app.include_router(tennis_history_router)
app.include_router(decision_router)
app.include_router(best_plays_router)
app.include_router(market_lab_router)
app.include_router(prediction_audit_router)
app.include_router(football_router)
app.include_router(football_archive_router)
app.include_router(football_evaluation_router)
app.include_router(football_learning_router)

# =========================================================
# NFL ROUTER
# =========================================================

app.include_router(
    nfl_router
)

# NBA router: módulo independiente con modelo oficial NBA-1.0.0.
app.include_router(nba_router)


# =========================================================
# MLB API
# =========================================================

MLB_API = "https://statsapi.mlb.com/api/v1"

MLB_HEADERS = {
    "User-Agent": "Sports-Predictor/1.0"
}


CURRENT_MODEL_VERSION = "2.0.0-matchup"


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "service": "sports-predictor",
        "version": "2.0.0",
        "model_version": CURRENT_MODEL_VERSION,
        "sports": [
            "MLB",
            "NFL",
            "NBA",
            "Tennis",
        ],
    }


# =========================================================
# MLB GAMES
# =========================================================

@app.get("/api/v1/mlb/games")
def get_mlb_games(
    date: str = None
):
    """
    Obtiene los partidos MLB de una fecha determinada.

    Ejemplo:

    /api/v1/mlb/games?date=2026-09-22

    Si no se proporciona una fecha,
    utiliza la fecha actual en UTC.
    """

    try:

        # -------------------------------------------------
        # 1. Determinar fecha
        # -------------------------------------------------

        if not date:

            date = datetime.now(
                timezone.utc
            ).strftime(
                "%Y-%m-%d"
            )

        # -------------------------------------------------
        # 2. Validar fecha
        # -------------------------------------------------

        try:

            datetime.strptime(
                date,
                "%Y-%m-%d"
            )

        except ValueError:

            raise HTTPException(
                status_code=400,
                detail=(
                    "La fecha debe utilizar el formato "
                    "YYYY-MM-DD. Ejemplo: 2026-09-22"
                ),
            )

        # -------------------------------------------------
        # 3. Consultar MLB
        # -------------------------------------------------

        url = (
            f"{MLB_API}/schedule"
        )

        params = {
            "sportId": 1,
            "date": date,
            "hydrate": (
                "probablePitcher,"
                "team,"
                "venue"
            ),
        }

        response = requests.get(
            url,
            params=params,
            timeout=20,
            headers=MLB_HEADERS,
        )

        response.raise_for_status()

        data = response.json()

        # -------------------------------------------------
        # 4. Procesar partidos
        # -------------------------------------------------

        games = []

        for date_block in data.get(
            "dates",
            []
        ):

            for game in date_block.get(
                "games",
                []
            ):

                game_pk = game.get(
                    "gamePk"
                )

                teams = game.get(
                    "teams",
                    {}
                )

                home = teams.get(
                    "home",
                    {}
                )

                away = teams.get(
                    "away",
                    {}
                )

                home_team = home.get(
                    "team",
                    {}
                )

                away_team = away.get(
                    "team",
                    {}
                )

                home_pitcher = (
                    home.get(
                        "probablePitcher",
                        {}
                    )
                )

                away_pitcher = (
                    away.get(
                        "probablePitcher",
                        {}
                    )
                )

                status = game.get(
                    "status",
                    {}
                )

                games.append(
                    {
                        "game_id": (
                            str(game_pk)
                            if game_pk is not None
                            else None
                        ),

                        "date": game.get(
                            "gameDate"
                        ),

                        "status": status.get(
                            "abstractGameState"
                        ),

                        "detailed_status": status.get(
                            "detailedState"
                        ),

                        "venue": (
                            game
                            .get(
                                "venue",
                                {}
                            )
                            .get(
                                "name"
                            )
                        ),

                        "home": {
                            "id": home_team.get(
                                "id"
                            ),

                            "name": home_team.get(
                                "name"
                            ),

                            "probable_pitcher": {
                                "id": home_pitcher.get(
                                    "id"
                                ),

                                "name": home_pitcher.get(
                                    "fullName"
                                ),
                            },
                        },

                        "away": {
                            "id": away_team.get(
                                "id"
                            ),

                            "name": away_team.get(
                                "name"
                            ),

                            "probable_pitcher": {
                                "id": away_pitcher.get(
                                    "id"
                                ),

                                "name": away_pitcher.get(
                                    "fullName"
                                ),
                            },
                        },
                    }
                )

        return {
            "success": True,
            "date": date,
            "total": len(games),
            "games": games,
        }

    except HTTPException:

        raise

    except requests.exceptions.HTTPError as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "error": "MLB_API_HTTP_ERROR",
                "message": (
                    "MLB respondió con un error HTTP."
                ),
                "details": str(exc),
            },
        )

    except requests.exceptions.RequestException as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "error": "MLB_API_CONNECTION_ERROR",
                "message": (
                    "No fue posible comunicarse "
                    "con la API de MLB."
                ),
                "details": str(exc),
            },
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": "MLB_GAMES_ERROR",
                "message": (
                    "Error obteniendo los partidos MLB."
                ),
                "details": str(exc),
            },
        )


# =========================================================
# MLB ANALYZE DAY
# =========================================================

@app.get("/api/v1/mlb/analyze-day")
def analyze_mlb_day(
    date: str = None
):
    """
    Analiza automáticamente todos los partidos MLB
    de una fecha determinada.

    Evita duplicar predicciones PENDING
    de la misma versión del modelo.
    """

    try:

        if not date:

            date = datetime.now(
                timezone.utc
            ).strftime(
                "%Y-%m-%d"
            )

        try:

            datetime.strptime(
                date,
                "%Y-%m-%d"
            )

        except ValueError:

            raise HTTPException(
                status_code=400,
                detail=(
                    "La fecha debe utilizar el formato "
                    "YYYY-MM-DD. Ejemplo: 2026-09-22"
                ),
            )

        games_response = get_mlb_games(
            date=date
        )

        games = games_response.get(
            "games",
            []
        )

        total_games = len(
            games
        )

        predictions = []
        skipped = []
        failed = []

        analyzed_count = 0
        skipped_count = 0
        failed_count = 0

        supabase = get_supabase_client()

        for game in games:

            event_id = game.get(
                "game_id"
            )

            home_name = (
                game
                .get(
                    "home",
                    {}
                )
                .get(
                    "name"
                )
            )

            away_name = (
                game
                .get(
                    "away",
                    {}
                )
                .get(
                    "name"
                )
            )

            game_status = game.get(
                "status"
            )

            detailed_status = game.get(
                "detailed_status"
            )

            # -------------------------------------------------
            # VALIDAR GAME ID
            # -------------------------------------------------

            if not event_id:

                failed_count += 1

                failed.append(
                    {
                        "event_id": None,
                        "home": home_name,
                        "away": away_name,
                        "error": (
                            "El partido no tiene game_id."
                        ),
                    }
                )

                continue

            # -------------------------------------------------
            # NO ANALIZAR FINAL
            # -------------------------------------------------

            if game_status == "Final":

                skipped_count += 1

                skipped.append(
                    {
                        "event_id": event_id,
                        "home": home_name,
                        "away": away_name,
                        "status": game_status,
                        "detailed_status": detailed_status,
                        "reason": (
                            "El partido ya está Final."
                        ),
                    }
                )

                continue

            # -------------------------------------------------
            # REANÁLISIS SEGURO DE PENDING
            # -------------------------------------------------
            # No omitir snapshots pendientes aquí: se consulta de nuevo
            # la fuente pregame. save_analysis decide si hay mejoras
            # materiales y actualiza el mismo registro con historial.
            # El analizador rechaza juegos Live/Final antes de guardar.

            # -------------------------------------------------
            # ANALIZAR
            # -------------------------------------------------

            try:

                analysis = analyze_mlb_game(
                    str(event_id)
                )

                if not analysis.get(
                    "success"
                ):

                    failed_count += 1

                    failed.append(
                        {
                            "event_id": event_id,
                            "home": home_name,
                            "away": away_name,
                            "error": (
                                analysis.get(
                                    "message"
                                )
                                or analysis.get(
                                    "error"
                                )
                                or "El análisis falló."
                            ),
                            "analysis": analysis,
                        }
                    )

                    continue

                # -------------------------------------------------
                # GUARDAR
                # -------------------------------------------------

                persistence = (
                    save_analysis(
                        analysis
                    )
                )

                prediction = (
                    analysis.get(
                        "prediction",
                        {}
                    )
                )

                analyzed_count += 1

                prediction_id = None

                if (
                    isinstance(
                        persistence,
                        dict
                    )
                    and persistence.get(
                        "data"
                    )
                ):

                    prediction_id = (
                        persistence
                        .get(
                            "data",
                            [{}]
                        )[0]
                        .get(
                            "id"
                        )
                    )

                predictions.append(
                    {
                        "event_id": str(
                            event_id
                        ),

                        "home": home_name,
                        "away": away_name,

                        "status": game_status,

                        "detailed_status":
                            detailed_status,

                        "game_date":
                            game.get(
                                "date"
                            ),

                        "venue":
                            game.get(
                                "venue"
                            ),

                        "predicted_winner":
                            prediction.get(
                                "winner"
                            ),

                        "home_probability":
                            prediction.get(
                                "home_probability"
                            ),

                        "away_probability":
                            prediction.get(
                                "away_probability"
                            ),

                        "confidence":
                            prediction.get(
                                "confidence"
                            ),

                        "data_quality":
                            prediction.get(
                                "data_quality"
                            ),

                        "model_version":
                            analysis.get(
                                "model_version",
                                CURRENT_MODEL_VERSION
                            ),

                        "saved": (
                            persistence.get(
                                "saved",
                                False
                            )
                            if isinstance(
                                persistence,
                                dict
                            )
                            else False
                        ),

                        "prediction_id":
                            prediction_id,
                    }
                )

            except Exception as exc:

                failed_count += 1

                failed.append(
                    {
                        "event_id": event_id,
                        "home": home_name,
                        "away": away_name,
                        "error": str(exc),
                    }
                )

                continue

        return {
            "success": True,
            "date": date,
            "model_version":
                CURRENT_MODEL_VERSION,

            "summary": {
                "total_games":
                    total_games,

                "analyzed":
                    analyzed_count,

                "skipped":
                    skipped_count,

                "failed":
                    failed_count,
            },

            "predictions":
                predictions,

            "skipped":
                skipped,

            "failed":
                failed,
        }

    except HTTPException:

        raise

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error":
                    "MLB_ANALYZE_DAY_ERROR",

                "message": (
                    "Error ejecutando el "
                    "análisis automático "
                    "de la jornada MLB."
                ),

                "details":
                    str(exc),
            },
        )


# =========================================================
# MLB ANALYZE GAME
# =========================================================

@app.post("/api/v1/analyze")
def analyze_game(
    event_id: str
):
    """
    Analiza un partido MLB utilizando
    el modelo 2.0.0-matchup.
    """

    try:

        analysis = analyze_mlb_game(
            event_id
        )

        if not analysis.get(
            "success"
        ):

            return analysis

        persistence = save_analysis(
            analysis
        )

        analysis[
            "persistence"
        ] = persistence

        return analysis

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# =========================================================
# MLB SETTLE GAME
# =========================================================

@app.post("/api/v1/settle/{event_id}")
def settle_game(
    event_id: str,
    prediction_id: str = None,
):

    try:

        event_id = str(
            event_id
        )

        # -------------------------------------------------
        # CONSULTAR MLB
        # -------------------------------------------------

        schedule_url = (
            f"{MLB_API}/schedule"
        )

        schedule_params = {
            "sportId": 1,
            "gamePk": event_id,
            "hydrate": (
                "probablePitcher,"
                "team,"
                "venue"
            ),
        }

        schedule_response = requests.get(
            schedule_url,
            params=schedule_params,
            timeout=20,
            headers=MLB_HEADERS,
        )

        if schedule_response.status_code == 404:

            return {
                "success": False,
                "event_id": event_id,
                "status": "NOT_FOUND",
                "message": (
                    "MLB no encontró un partido "
                    "con este event_id. "
                    "Verifica que el gamePk sea correcto."
                ),
            }

        schedule_response.raise_for_status()

        schedule_data = (
            schedule_response.json()
        )

        scheduled_games = []

        for date_block in schedule_data.get(
            "dates",
            []
        ):

            scheduled_games.extend(
                date_block.get(
                    "games",
                    []
                )
            )

        # -------------------------------------------------
        # BUSCAR PARTIDO
        # -------------------------------------------------

        target_game = None

        for game in scheduled_games:

            if (
                str(
                    game.get(
                        "gamePk"
                    )
                )
                == event_id
            ):

                target_game = game

                break

        if target_game is None:

            return {
                "success": False,
                "event_id": event_id,
                "status": "NOT_FOUND",
                "message": (
                    "El event_id no aparece "
                    "en el calendario actual de MLB. "
                    "Puede tratarse de un gamePk "
                    "incorrecto o de un partido que MLB "
                    "ya no expone mediante este endpoint."
                ),
            }

        # -------------------------------------------------
        # ESTADO
        # -------------------------------------------------

        game_status = (
            target_game
            .get(
                "status",
                {}
            )
            .get(
                "abstractGameState"
            )
        )

        detailed_state = (
            target_game
            .get(
                "status",
                {}
            )
            .get(
                "detailedState"
            )
        )

        teams = target_game.get(
            "teams",
            {}
        )

        # -------------------------------------------------
        # EQUIPOS
        # -------------------------------------------------

        home_team = (
            teams
            .get(
                "home",
                {}
            )
            .get(
                "team",
                {}
            )
            .get(
                "name"
            )
        )

        away_team = (
            teams
            .get(
                "away",
                {}
            )
            .get(
                "team",
                {}
            )
            .get(
                "name"
            )
        )

        # -------------------------------------------------
        # MARCADORES
        # -------------------------------------------------

        home_score = (
            teams
            .get(
                "home",
                {}
            )
            .get(
                "score"
            )
        )

        away_score = (
            teams
            .get(
                "away",
                {}
            )
            .get(
                "score"
            )
        )

        # -------------------------------------------------
        # NO FINAL
        # -------------------------------------------------

        if game_status != "Final":

            return {
                "success": False,
                "event_id": event_id,
                "status": game_status,
                "detailed_status":
                    detailed_state,

                "home":
                    home_team,

                "away":
                    away_team,

                "home_score":
                    home_score,

                "away_score":
                    away_score,

                "message": (
                    "El partido todavía no ha terminado. "
                    "La predicción permanece PENDING."
                ),
            }

        # -------------------------------------------------
        # RECONCILIAR CON EL FEED OFICIAL DEL JUEGO
        # -------------------------------------------------
        # El endpoint schedule puede devolver un estado Final sin scores
        # para juegos reprogramados. Antes de rechazar la liquidación,
        # consultar el feed oficial del gamePk y aceptar solo un Final
        # con carreras completas. Nunca usar un score de otro gamePk.
        if home_score is None or away_score is None:
            try:
                feed_response = requests.get(
                    f"https://statsapi.mlb.com/api/v1.1/game/{event_id}/feed/live",
                    timeout=20,
                    headers=MLB_HEADERS,
                )
                feed_response.raise_for_status()
                feed_data = feed_response.json()
                feed_game_data = feed_data.get("gameData") or {}
                feed_status = feed_game_data.get("status") or {}
                feed_live = feed_data.get("liveData") or {}
                feed_linescore = feed_live.get("linescore") or {}
                feed_teams = feed_game_data.get("teams") or {}
                feed_home = feed_teams.get("home") or {}
                feed_away = feed_teams.get("away") or {}
                feed_home_score = (feed_linescore.get("teams") or {}).get("home") or {}
                feed_away_score = (feed_linescore.get("teams") or {}).get("away") or {}

                if feed_status.get("abstractGameState") == "Final":
                    if feed_home_score.get("runs") is not None and feed_away_score.get("runs") is not None:
                        game_status = "Final"
                        detailed_state = feed_status.get("detailedState") or "Final"
                        home_team = feed_home.get("name") or home_team
                        away_team = feed_away.get("name") or away_team
                        home_score = feed_home_score.get("runs")
                        away_score = feed_away_score.get("runs")
            except (requests.exceptions.RequestException, ValueError, TypeError):
                # Preserve the original safe response if the feed is unavailable.
                pass

        # -------------------------------------------------
        # NO LIQUIDAR EVENTOS APLAZADOS/CANCELADOS
        # -------------------------------------------------
        normalized_detail = str(detailed_state or "").strip().lower()
        if any(token in normalized_detail for token in ("postponed", "cancelled", "canceled")):
            return {
                "success": False,
                "event_id": event_id,
                "status": "POSTPONED",
                "detailed_status": detailed_state,
                "home": home_team,
                "away": away_team,
                "home_score": home_score,
                "away_score": away_score,
                "message": (
                    "MLB identifica este gamePk como aplazado o cancelado. "
                    "No se liquidó para evitar registrar un resultado falso; "
                    "verifica el gamePk del encuentro realmente disputado."
                ),
            }

        # -------------------------------------------------
        # VALIDAR MARCADOR
        # -------------------------------------------------

        if (
            home_score is None
            or away_score is None
        ):

            return {
                "success": False,
                "event_id": event_id,
                "status": "Final",

                "home":
                    home_team,

                "away":
                    away_team,

                "message": (
                    "MLB marca el partido como Final, "
                    "pero todavía no proporcionó "
                    "el marcador completo."
                ),
            }

        home_score = int(
            home_score
        )

        away_score = int(
            away_score
        )

        # -------------------------------------------------
        # GANADOR
        # -------------------------------------------------

        if home_score > away_score:

            actual_winner = (
                home_team
            )

        elif away_score > home_score:

            actual_winner = (
                away_team
            )

        else:

            return {
                "success": False,
                "event_id": event_id,
                "status": "Final",

                "home":
                    home_team,

                "away":
                    away_team,

                "home_score":
                    home_score,

                "away_score":
                    away_score,

                "message": (
                    "El marcador recibido no permite "
                    "determinar un ganador."
                ),
            }

        # -------------------------------------------------
        # LIQUIDAR
        # -------------------------------------------------

        settlement = settle_prediction(
            event_id=event_id,

            actual_winner=
                actual_winner,

            actual_home_score=
                home_score,

            actual_away_score=
                away_score,

            prediction_id=
                prediction_id,

            model_version=
                CURRENT_MODEL_VERSION,
        )

        return {
            "success": True,

            "event_id":
                event_id,

            "status":
                "Final",

            "home":
                home_team,

            "away":
                away_team,

            "home_score":
                home_score,

            "away_score":
                away_score,

            "actual_winner":
                actual_winner,

            "prediction_result":
                settlement.get(
                    "prediction_result"
                ),

            "settled_at":
                settlement.get(
                    "settled_at"
                ),

            "settlement":
                settlement,
        }

    except requests.exceptions.HTTPError as exc:

        return {
            "success": False,
            "event_id": str(
                event_id
            ),
            "status":
                "MLB_API_ERROR",

            "message": (
                "MLB respondió con un error HTTP."
            ),

            "details":
                str(exc),
        }

    except requests.exceptions.RequestException as exc:

        return {
            "success": False,
            "event_id": str(
                event_id
            ),
            "status":
                "MLB_CONNECTION_ERROR",

            "message": (
                "No fue posible comunicarse "
                "con MLB."
            ),

            "details":
                str(exc),
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# =========================================================
# RECONCILIATION
# =========================================================

@app.post(
    "/api/v1/reconcile/{event_id}"
)
def reconcile(
    event_id: str
):

    try:

        return reconcile_settled_prediction(
            event_id
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error":
                    "RECONCILE_ERROR",

                "message": (
                    "No fue posible "
                    "reconciliar el resultado."
                ),

                "details":
                    str(exc),
            },
        )


# =========================================================
# PERFORMANCE
# =========================================================

@app.get(
    "/api/v1/performance"
)
def performance():

    try:

        return get_performance()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "Error obteniendo "
                    "rendimiento del modelo"
                ),

                "details":
                    str(exc),
            },
        )


# =========================================================
# PREDICTIONS
# =========================================================

@app.get(
    "/api/v1/predictions"
)
def predictions():

    try:

        return get_predictions()

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail={
                "error": (
                    "Error obteniendo "
                    "predicciones"
                ),

                "details":
                    str(exc),
            },
        )


# =========================================================
# FRONTEND WEB
# =========================================================

FRONTEND_DIST = (
    Path(__file__).resolve().parent
    / "dist"
)


if FRONTEND_DIST.exists():

    @app.get(
        "/",
        include_in_schema=False
    )
    def frontend_index():

        return FileResponse(
            FRONTEND_DIST
            / "index.html"
        )

    app.mount(
        "/",
        StaticFiles(
            directory=str(
                FRONTEND_DIST
            ),
            html=True,
        ),
        name="frontend",
    )
