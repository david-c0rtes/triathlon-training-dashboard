from datetime import date, timedelta
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from integrations.garmin import auth as garmin_auth
from integrations.garmin.client import fetch_activities
from integrations.garmin.export import push_workout
from integrations.garmin.zwo import workout_to_zwo, zwo_filename
from integrations.garmin.tss import measured_tss_per_hour, daily_tss_by_group
from domain.fitness import compute_fitness, compute_fitness_series, activities_to_daily_tss
from domain.profile_store import load_profile, save_profile, update_fitness
from domain.workout import Sport
from api.routes import sessions_for_date, WorkoutIn, with_anchors

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
    profile = load_profile()
    try:
        activities = fetch_activities(days=days)
    except EnvironmentError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Garmin Connect error: {e}")

    daily_tss = activities_to_daily_tss(activities, profile.thresholds)
    fitness = compute_fitness(daily_tss)

    # Persist freshly computed fitness + 90-day rolling per-sport TSS/hour
    update_fitness(fitness.ctl, fitness.atl)
    measured = measured_tss_per_hour(activities, profile.thresholds)
    if measured:
        profile = load_profile()
        profile.preferences.measured_tss_per_hour = measured
        save_profile(profile)

    return SyncResponse(
        activities_fetched=len(activities),
        date_range_days=days,
        ctl=fitness.ctl,
        atl=fitness.atl,
        tsb=fitness.tsb,
    )


@router.get("/history")
def garmin_history(days: int = 90):
    """
    Historical daily CTL/ATL/TSB series + per-day TSS by sport, for the
    Performance page. Fetches an extra 42-day warmup so the displayed CTL is
    accurate, then returns only the last `days` for display.
    """
    profile = load_profile()
    try:
        activities = fetch_activities(days=days + 42)
    except EnvironmentError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Garmin Connect error: {e}")

    daily_tss = activities_to_daily_tss(activities, profile.thresholds)
    full_series = compute_fitness_series(daily_tss)
    by_group = daily_tss_by_group(activities, profile.thresholds)

    display_start = (date.today() - timedelta(days=days)).isoformat()
    series = [pt for pt in full_series if pt["date"] >= display_start]
    tss_days = [
        {"date": d, **g}
        for d, g in sorted(by_group.items())
        if d >= display_start
    ]

    return {"days": days, "series": series, "tss_by_day": tss_days}


# ── workout export ─────────────────────────────────────────────────────────────

@router.post("/push")
def garmin_push(day: date):
    """
    Publish the Garmin-eligible session(s) scheduled on `day` to Garmin Connect.
    Indoor cycling is skipped (use /garmin/zwo to download a .zwo instead);
    brick/multisport is not supported yet.
    """
    profile = load_profile()
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


@router.post("/push-workout")
def garmin_push_workout(workout: WorkoutIn):
    """
    Publish a single (possibly edited) workout to Garmin Connect and schedule it
    on its own date. Used by the Workout review/edit screen's Publish button.
    """
    profile = load_profile()
    w = with_anchors(workout.to_domain(), profile)
    if w.sport == Sport.BIKE_INDOOR:
        raise HTTPException(status_code=400, detail="Indoor cycling exports as .zwo — use POST /garmin/zwo-file.")
    if w.sport == Sport.BRICK:
        raise HTTPException(status_code=400, detail="Brick/multisport push not supported yet.")
    if w.sport == Sport.STRENGTH:
        raise HTTPException(status_code=400, detail="Strength sessions aren't pushed to Garmin as structured workouts.")
    try:
        return push_workout(w, profile.thresholds)
    except EnvironmentError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Garmin push error: {e}")


@router.post("/zwo-file")
def garmin_zwo_file(workout: WorkoutIn):
    """Return the .zwo for a single (possibly edited) indoor cycling workout."""
    w = workout.to_domain()
    if w.sport != Sport.BIKE_INDOOR:
        raise HTTPException(status_code=400, detail="ZWO export is only for indoor cycling sessions.")
    xml = workout_to_zwo(w)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{zwo_filename(w)}"'},
    )


@router.get("/zwo/{day}")
def garmin_zwo(day: date):
    """Download the .zwo file for the indoor cycling session on `day`."""
    profile = load_profile()
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
