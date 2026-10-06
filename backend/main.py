"""RAT dashboard: FastAPI app serving the API and the static frontend."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import router

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="RAT - Repo Analysis Tool")
app.include_router(router)


@app.on_event("startup")
def _startup():
    db.init_db()


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
