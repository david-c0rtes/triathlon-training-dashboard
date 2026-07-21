from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import apppaths
from version import VERSION
from api.routes import router
from api.garmin_routes import router as garmin_router
from api.google_routes import router as google_router

app = FastAPI(title="Triathlon Training Dashboard", version=VERSION)

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
app.include_router(google_router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Desktop mode: serve the built frontend from the same origin, so the packaged
# app is one process with no CORS. In dev (Vite on 5173 + this API on 8020)
# frontend/dist usually doesn't exist and nothing here registers.
_dist = apppaths.frontend_dist_dir()
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Serve real files from dist; anything else falls back to the SPA shell
        so client-side routes (/settings, /calendar, …) survive reloads."""
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(_dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
