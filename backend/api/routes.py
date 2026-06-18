from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from domain.athlete import AthleteProfile, Goals, Thresholds, Fitness, RaceGoal, Discipline
from domain.zones import compute_zones, AthleteZones, Zone
from domain.periodization import generate_week, get_phase, WeekPlan

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
    heart_rate: list[ZoneOut]
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
        heart_rate=[ZoneOut.from_zone(z) for z in zones.heart_rate],
        run_pace=[ZoneOut.from_zone(z) for z in zones.run_pace],
        swim_pace=[ZoneOut.from_zone(z) for z in zones.swim_pace],
    )


@router.get("/plan/week")
def get_week_plan(week_start: date | None = None, week_number: int = 1):
    profile = _stub_profile()
    plan = generate_week(profile, week_start=week_start, week_number=week_number)
    return plan.summary()


@router.get("/plan/phase")
def get_current_phase():
    profile = _stub_profile()
    today = date.today()
    phase = get_phase(profile.goals.race_date, today)
    weeks_to_race = max(0, (profile.goals.race_date - today).days // 7)
    return {"phase": phase.value, "weeks_to_race": weeks_to_race}
