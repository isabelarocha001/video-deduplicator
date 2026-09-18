"""
Vercel Python ASGI entrypoint for video-deduplicator.

Heavy FFmpeg / fingerprint work belongs in CLI workers, not serverless.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="video-deduplicator",
    description="Minimal HTTP surface for the video-deduplicator toolkit.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
@app.get("/api")
def root():
    return {
        "service": "video-deduplicator",
        "status": "ok",
        "mode": "api-minimal",
        "docs": {
            "cli": "python -m app.cli process --input <file> --output <file>",
            "redteam": "python -m tools.duplicate_redteam --input <file> --iterations 50",
            "pipeline": "python -m tools.duplicate_redteam --input <file> --pipeline-check",
        },
    }


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "healthy"}
