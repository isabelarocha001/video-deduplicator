from fastapi import FastAPI

app = FastAPI()


@app.get("/api/index")
def health():
    return {"status": "healthy", "build": "clean-min"}
