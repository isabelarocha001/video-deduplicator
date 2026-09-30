from fastapi import FastAPI

app = FastAPI()

@app.get("/api/index")
@app.get("/")
def health():
    return {"status": "healthy", "build": "f-health-only"}
