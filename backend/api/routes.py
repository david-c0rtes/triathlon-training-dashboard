from datetime import date, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from domain.athlete import AthleteProfile, Goals, Thresholds, Fitness, RaceGoal, Discipline
from domain.zones import compute_zones, AthleteZones, Zone
from domain.periodization import generate_week, get_phase, WeekPlan
from domain.workout import Workout

router = APIRouter(prefix="/api/v1")


# ── request / response schemas ───────────────────────────────────────────────

class ZoneOut(BaseModel):
    number: int
    name: str
    low: float
    high: float

    @classmethod
    def from_zone(cls, z: Zone) -> "ZoneOut":
        return cls(number=z.number, name=z.name, low=round(z.low, 1), high=round(z.high, 1))


class ZonesResponse(BaseModel):
    bike_power: list[ZoneOut]
    bike_hr: list[ZoneOut]
    run_hr: list[ZoneOut]
    run_pace: list[ZoneOut]
    swim_pace: list[ZoneOut]


# ── stub profile (replaced once UI + persistence layer exists) ────────────────

def _stub_profile() -> AthleteProfile:
    """
    Placeholder athlete profile with representative values.
    Replace with DB/config read once the profile endpoint accepts POST.
    """
    return AthleteProfile(
        name="David",
        goals=Goals(
            race_date=date(2026, 10, 4),   # example 70.3 race date — update as needed
            goal=RaceGoal.TARGET_TIME,
            target_finish_seconds=int(4.5 * 3600),
            weekly_hours_available=12.0,
            limiter_discipline=Discipline.RUN,
        ),
        thresholds=Thresholds(
            ftp_watts=250,                       # placeholder — replace with real value
            run_threshold_pace_sec_per_km=285.0, # ~4:45/km placeholder
            run_lthr=162,                        # placeholder
            swim_css_sec_per_100m=95.0,          # ~1:35/100m placeholder
            max_hr=203,
        ),
        fitness=Fitness(ctl=45.0, atl=50.0),
    )


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/profile", response_model=AthleteProfile)
def get_profile():
    return _stub_profile()


@router.get("/zones", response_model=ZonesResponse)
def get_zones():
    profile = _stub_profile()
    try:
        zones = compute_zones(profile.thresholds)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return ZonesResponse(
        bike_power=[ZoneOut.from_zone(z) for z in zones.bike_power],
        bike_hr=[ZoneOut.from_zone(z) for z in zones.bike_hr],
        run_hr=[ZoneOut.from_zone(z) for z in zones.run_hr],
        run_pace=[ZoneOut.from_zone(z) for z in zones.run_pace],
        swim_pace=[ZoneOut.from_zone(z) for z in zones.swim_pace],
    )


@router.get("/plan/week")
def get_week_plan(week_start: date | None = None, week_number: int = 1):
    profile = _stub_profile()
    plan = generate_week(profile, week_start=week_start, week_number=week_number)
    return plan.summary()


def sessions_for_date(profile: AthleteProfile, d: date) -> list[Workout]:
    """Generate the plan week containing `d` and return that day's session(s)."""
    week_start = d - timedelta(days=d.weekday())
    plan = generate_week(profile, week_start=week_start)
    return [w for w in plan.workouts if w.scheduled_date == d]


@router.get("/plan/day")
def get_day_plan(day: date):
    """Full structured detail of the session(s) on a given date (review screen)."""
    profile = _stub_profile()
    sessions = sessions_for_date(profile, day)
    return {"date": day.isoformat(), "sessions": [w.detail() for w in sessions]}


@router.get("/plan/tomorrow")
def get_tomorrow_plan():
    """Tomorrow's session(s) — the review-before-publish view."""
    profile = _stub_profile()
    tomorrow = date.today() + timedelta(days=1)
    sessions = sessions_for_date(profile, tomorrow)
    return {"date": tomorrow.isoformat(), "sessions": [w.detail() for w in sessions]}


@router.get("/plan/phase")
def get_current_phase():
    profile = _stub_profile()
    today = date.today()
    phase = get_phase(profile.goals.race_date, today)
    weeks_to_race = max(0, (profile.goals.race_date - today).days // 7)
    return {"phase": phase.value, "weeks_to_race": weeks_to_race}
