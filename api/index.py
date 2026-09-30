from fastapi import FastAPI, Request

app = FastAPI()


@app.api_route("/", methods=["GET", "POST"])
@app.api_route("/{full_path:path}", methods=["GET", "POST"])
async def catch_all(request: Request, full_path: str = ""):
    return {
        "status": "alive",
        "full_path": full_path,
        "url": str(request.url),
        "method": request.method,
        "path": request.url.path,
    }
