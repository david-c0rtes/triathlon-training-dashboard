from datetime import date, timedelta
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from domain.athlete import AthleteProfile, Goals, Thresholds, Fitness, RaceGoal, Discipline, RACE_TYPES
from domain.zones import compute_zones, AthleteZones, Zone
from domain.periodization import generate_week, generate_plan, get_phase, WeekPlan
from domain.workout import (
    Workout, WorkoutStep, RepeatBlock, Target, TargetType, Sport, validate_workout,
)
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


# ── editable-workout input (mirrors Workout.detail(); used by the editor) ──────

class TargetIn(BaseModel):
    type: TargetType
    zone: int | None = None
    pct_of_anchor: float | None = None


class StepIn(BaseModel):
    kind: Literal["step", "repeat"] = "step"
    # step fields
    name: str | None = None
    duration_seconds: int | None = None
    distance_meters: int | None = None
    rest_seconds: int = 0
    equipment: str | None = None   # swim only (SwimEquipment values)
    stroke: str | None = None      # swim only (SwimStroke values)
    target: TargetIn | None = None
    notes: str = ""
    # repeat-block fields
    repeat_count: int | None = None
    steps: list["StepIn"] | None = None


class WorkoutIn(BaseModel):
    """An edited workout coming back from the review/edit screen."""
    title: str
    sport: Sport
    date: date
    description: str = ""
    steps: list[StepIn]

    def to_domain(self) -> Workout:
        return Workout(
            title=self.title,
            sport=self.sport,
            scheduled_date=self.date,
            description=self.description,
            steps=[_convert_step(s) for s in self.steps],
        )

    @model_validator(mode="after")
    def _validate(self) -> "WorkoutIn":
        # Enforce per-sport intensity + end-condition rules at the API boundary,
        # so preview/push/zwo all reject invalid workouts with a 422.
        validate_workout(self.to_domain())
        return self


StepIn.model_rebuild()


def _convert_executable(s: StepIn) -> WorkoutStep:
    target = Target(**s.target.model_dump()) if s.target else Target(type=TargetType.OPEN)
    return WorkoutStep(
        name=s.name or "Step",
        duration_seconds=int(s.duration_seconds or 0),
        target=target,
        notes=s.notes or "",
        distance_meters=s.distance_meters,
        rest_seconds=int(s.rest_seconds or 0),
        equipment=s.equipment,
        stroke=s.stroke,
    )


def _convert_step(s: StepIn):
    if s.kind == "repeat":
        return RepeatBlock(
            repeat_count=int(s.repeat_count or 1),
            steps=[_convert_executable(x) for x in (s.steps or [])],
        )
    return _convert_executable(s)


def with_anchors(workout: Workout, profile: AthleteProfile) -> Workout:
    """Attach the athlete's thresholds so TSS/duration can be computed,
    and re-derive swim step durations from their distances."""
    thr = profile.thresholds
    return workout.with_anchors(
        ftp=thr.ftp_watts,
        threshold_pace=thr.run_threshold_pace_sec_per_km,
        css=thr.swim_css_sec_per_100m,
        max_hr=thr.max_hr,
        lthr=thr.run_lthr,
    ).normalize(thr.swim_css_sec_per_100m)


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


def workouts_in_range(profile: AthleteProfile, start: date, end: date) -> list[Workout]:
    """All planned workouts scheduled within [start, end], generated week-by-week."""
    if end < start:
        start, end = end, start
    if (end - start).days > 180:
        end = start + timedelta(days=180)  # cap to keep generation bounded
    out: list[Workout] = []
    wk = start - timedelta(days=start.weekday())  # Monday of the first week
    while wk <= end:
        for w in generate_week(profile, week_start=wk).workouts:
            if start <= w.scheduled_date <= end:
                out.append(w)
        wk += timedelta(days=7)
    return out


@router.get("/plan/range")
def get_plan_range(start: date, end: date):
    """Day-by-day workout summaries across a date range — powers the calendar grid."""
    profile = load_profile()
    days: dict[str, list[dict]] = {}
    for w in workouts_in_range(profile, start, end):
        days.setdefault(w.scheduled_date.isoformat(), []).append(w.summary())
    return {"days": [{"date": d, "sessions": s} for d, s in sorted(days.items())]}


@router.get("/plan/day")
def get_day_plan(day: date):
    """Full structured detail of the session(s) on a given date (review screen)."""
    profile = load_profile()
    sessions = sessions_for_date(profile, day)
    return {"date": day.isoformat(), "sessions": [w.detail() for w in sessions]}


@router.get("/plan/next")
def get_next_plan():
    """
    The next scheduled session(s): scans from today forward until it finds a day
    with planned workouts, and returns every session on that day. Powers the
    Workout review/edit screen.
    """
    profile = load_profile()
    today = date.today()
    for offset in range(0, 21):
        d = today + timedelta(days=offset)
        sessions = sessions_for_date(profile, d)
        if sessions:
            return {"date": d.isoformat(), "sessions": [w.detail() for w in sessions]}
    return {"date": None, "sessions": []}


@router.post("/plan/preview")
def preview_workout(workout: WorkoutIn):
    """
    Recompute duration + planned TSS + normalized structure for an edited
    workout, so the editor can show live totals without persisting anything.
    """
    profile = load_profile()
    w = with_anchors(workout.to_domain(), profile)
    return w.detail()


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
    phase = get_phase(profile, today)
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
