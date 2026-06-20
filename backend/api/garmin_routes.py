from datetime import date
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from integrations.garmin import auth as garmin_auth
from integrations.garmin.client import fetch_activities
from integrations.garmin.export import push_workout
from integrations.garmin.zwo import workout_to_zwo, zwo_filename
from domain.fitness import compute_fitness, activities_to_daily_tss
from domain.workout import Sport
from api.routes import _stub_profile, sessions_for_date

router = APIRouter(prefix="/api/v1/garmin")


@router.get("/status")
def garmin_status():
    """Whether a Garmin session can be resumed without re-entering the password."""
    return {"connected": garmin_auth.is_authenticated()}


class SyncResponse(BaseModel):
    activities_fetched: int
    date_range_days: int
    ctl: float
    atl: float
    tsb: float


@router.post("/sync")
def garmin_sync(days: int = 90) -> SyncResponse:
    """
    Fetch recent Garmin activities and compute updated CTL/ATL/TSB.
    Logs in with GARMIN_EMAIL/GARMIN_PASSWORD on first call, then reuses the
    saved session. Call this to refresh fitness after completing workouts.
    """
    profile = _stub_profile()
    try:
        activities = fetch_activities(days=days)
    except EnvironmentError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Garmin Connect error: {e}")

    daily_tss = activities_to_daily_tss(activities, profile.thresholds)
    fitness = compute_fitness(daily_tss)

    return SyncResponse(
        activities_fetched=len(activities),
        date_range_days=days,
        ctl=fitness.ctl,
        atl=fitness.atl,
        tsb=fitness.tsb,
    )


# ── workout export ─────────────────────────────────────────────────────────────

@router.post("/push")
def garmin_push(day: date):
    """
    Publish the Garmin-eligible session(s) scheduled on `day` to Garmin Connect.
    Indoor cycling is skipped (use /garmin/zwo to download a .zwo instead);
    brick/multisport is not supported yet.
    """
    profile = _stub_profile()
    sessions = sessions_for_date(profile, day)
    if not sessions:
        raise HTTPException(status_code=404, detail=f"No planned session on {day.isoformat()}")

    results = []
    for w in sessions:
        if w.sport == Sport.BIKE_INDOOR:
            results.append({"title": w.title, "skipped": "indoor cycling — use GET /garmin/zwo/{date}"})
            continue
        if w.sport == Sport.BRICK:
            results.append({"title": w.title, "skipped": "brick/multisport not supported yet"})
            continue
        try:
            results.append(push_workout(w, profile.thresholds))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Garmin push error for '{w.title}': {e}")

    return {"date": day.isoformat(), "results": results}


@router.get("/zwo/{day}")
def garmin_zwo(day: date):
    """Download the .zwo file for the indoor cycling session on `day`."""
    profile = _stub_profile()
    sessions = sessions_for_date(profile, day)
    indoor = [w for w in sessions if w.sport == Sport.BIKE_INDOOR]
    if not indoor:
        raise HTTPException(status_code=404, detail=f"No indoor cycling session on {day.isoformat()}")

    workout = indoor[0]
    xml = workout_to_zwo(workout)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{zwo_filename(workout)}"'},
    )
