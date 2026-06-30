from datetime import date, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from domain.athlete import AthleteProfile, Goals, Thresholds, Fitness, RaceGoal, Discipline, RACE_TYPES
from domain.zones import compute_zones, AthleteZones, Zone
from domain.periodization import generate_week, generate_plan, get_phase, WeekPlan
from domain.workout import Workout
from domain.profile_store import load_profile, save_profile

router = APIRouter(prefix="/api/v1")


# ── request / response schemas ───────────────────────────────────────────────

import math


class ZoneOut(BaseModel):
    number: int
    name: str
    low: float
    high: float | None  # None means "and up" (open-ended top zone)

    @classmethod
    def from_zone(cls, z: Zone) -> "ZoneOut":
        high = None if math.isinf(z.high) else round(z.high, 1)
        return cls(number=z.number, name=z.name, low=round(z.low, 1), high=high)


class ZonesResponse(BaseModel):
    bike_power: list[ZoneOut]
    bike_hr: list[ZoneOut]
    run_hr: list[ZoneOut]
    run_pace: list[ZoneOut]
    swim_pace: list[ZoneOut]


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/profile", response_model=AthleteProfile)
def get_profile():
    return load_profile()


@router.put("/profile", response_model=AthleteProfile)
def put_profile(profile: AthleteProfile):
    """Replace the saved profile (goals + thresholds + fitness) and persist it."""
    save_profile(profile)
    return profile


@router.get("/race-types")
def get_race_types():
    """The selectable race types with distances (single source of truth for the UI)."""
    return [{"key": k, **v} for k, v in RACE_TYPES.items()]


@router.get("/zones", response_model=ZonesResponse)
def get_zones():
    profile = load_profile()
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
    profile = load_profile()
    plan = generate_week(profile, week_start=week_start, week_number=week_number)
    return plan.summary()


@router.get("/plan/full")
def get_full_plan():
    """Full periodized plan from this week to race day (week-level summaries)."""
    profile = load_profile()
    return generate_plan(profile).summary()


def sessions_for_date(profile: AthleteProfile, d: date) -> list[Workout]:
    """Generate the plan week containing `d` and return that day's session(s)."""
    week_start = d - timedelta(days=d.weekday())
    plan = generate_week(profile, week_start=week_start)
    return [w for w in plan.workouts if w.scheduled_date == d]


@router.get("/plan/day")
def get_day_plan(day: date):
    """Full structured detail of the session(s) on a given date (review screen)."""
    profile = load_profile()
    sessions = sessions_for_date(profile, day)
    return {"date": day.isoformat(), "sessions": [w.detail() for w in sessions]}


@router.get("/plan/tomorrow")
def get_tomorrow_plan():
    """Tomorrow's session(s) — the review-before-publish view."""
    profile = load_profile()
    tomorrow = date.today() + timedelta(days=1)
    sessions = sessions_for_date(profile, tomorrow)
    return {"date": tomorrow.isoformat(), "sessions": [w.detail() for w in sessions]}


@router.get("/plan/phase")
def get_current_phase():
    profile = load_profile()
    today = date.today()
    phase = get_phase(profile.goals.race_date, today)
    weeks_to_race = max(0, (profile.goals.race_date - today).days // 7)
    return {"phase": phase.value, "weeks_to_race": weeks_to_race}


@router.get("/insights")
def get_insights():
    """AI coaching insight interpreting the current fitness + plan (Claude API)."""
    from services.insights import generate_insight, insights_available
    if not insights_available():
        raise HTTPException(
            status_code=503,
            detail="AI insights unavailable — set ANTHROPIC_API_KEY in backend/.env",
        )
    profile = load_profile()
    week = generate_week(profile)
    context = {
        "ctl": week.ctl, "atl": week.atl, "tsb": round(week.tsb, 1),
        "phase": week.phase.value, "weeks_to_race": round(week.weeks_to_race, 1),
        "target_tss": week.target_tss, "planned_tss": week.planned_tss,
        "rationale": week.rationale,
    }
    try:
        insight = generate_insight(context)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Insight generation failed: {e}")
    return {"insight": insight, "context": context}
