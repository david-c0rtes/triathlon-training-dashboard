from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from api.garmin_routes import router as garmin_router

app = FastAPI(title="Triathlon Training Dashboard", version="0.1.0")

# Allow the local Vite dev server (and common variants) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000", "http://127.0.0.1:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(garmin_router)


@app.get("/health")
def health():
    return {"status": "ok"}
