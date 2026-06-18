from fastapi import FastAPI
from api.routes import router

app = FastAPI(title="Triathlon Training Dashboard", version="0.1.0")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
