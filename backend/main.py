from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from api.routes import router
from api.garmin_routes import router as garmin_router

app = FastAPI(title="Triathlon Training Dashboard", version="0.1.0")
app.include_router(router)
app.include_router(garmin_router)


@app.get("/health")
def health():
    return {"status": "ok"}
