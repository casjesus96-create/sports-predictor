from pathlib import Path

from fastapi.staticfiles import StaticFiles

from main import app


# =========================================================
# FRONTEND REACT
# =========================================================

DIST_DIR = Path(__file__).resolve().parent / "dist"


if DIST_DIR.exists():

    app.mount(
        "/",
        StaticFiles(
            directory=str(DIST_DIR),
            html=True,
        ),
        name="frontend",
    )
