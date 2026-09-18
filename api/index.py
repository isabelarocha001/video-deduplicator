"""
Vercel Python entrypoint for video-deduplicator.

This project is primarily a CLI / worker toolkit. The HTTP surface is intentionally
minimal (health + metadata). Heavy FFmpeg / fingerprint jobs should run as workers,
not inside short-lived serverless functions.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    """Vercel serverless Python handler."""

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in ("/", "/api", "/api/index"):
            self._send(
                200,
                {
                    "service": "video-deduplicator",
                    "status": "ok",
                    "mode": "api-minimal",
                    "docs": {
                        "cli": "python -m app.cli process --input <file> --output <file>",
                        "redteam": "python -m tools.duplicate_redteam --input <file> --iterations 50",
                        "pipeline": "python -m tools.duplicate_redteam --input <file> --pipeline-check",
                    },
                },
            )
            return
        if path in ("/health", "/api/health"):
            self._send(200, {"status": "healthy"})
            return
        self._send(404, {"error": "not_found", "path": path})

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # quieter logs on Vercel
        return
