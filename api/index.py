"""
Vercel Python ASGI entrypoint.

- Serves the social web app (static) when possible
- Exposes /api/health JSON for monitoring
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"

app = FastAPI(title="video-deduplicator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if PUBLIC.is_dir():
    app.mount("/css", StaticFiles(directory=str(PUBLIC / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(PUBLIC / "js")), name="js")
    app.mount("/assets", StaticFiles(directory=str(PUBLIC / "assets")), name="assets")


@app.get("/api/health")
@app.get("/health")
def health():
    return {"status": "healthy", "service": "video-deduplicator"}


@app.get("/api")
def api_root():
    return {
        "service": "video-deduplicator",
        "status": "ok",
        "mode": "social-web + api",
        "app": "/",
    }


@app.get("/")
def index():
    index_file = PUBLIC / "index.html"
    if index_file.is_file():
        return FileResponse(index_file, media_type="text/html; charset=utf-8")
    return JSONResponse(
        {
            "service": "video-deduplicator",
            "status": "ok",
            "message": "Frontend not found. Expected public/index.html",
        }
    )
