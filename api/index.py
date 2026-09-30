from fastapi import FastAPI

app = FastAPI()


@app.get("/api/health")
@app.get("/health")
@app.get("/")
def health():
    return {"status": "healthy", "service": "video-deduplicator-min"}


@app.get("/api")
def api_root():
    return {"ok": True, "routes": ["/api/health"]}
