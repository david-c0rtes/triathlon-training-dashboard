"""
Plan materialization service — the layer between the generative engine
(domain/periodization.py) and the API.

The engine stays pure/deterministic; this service decides what gets WRITTEN
DOWN. Weeks from the current Monday through race day are materialized into
the plan store on first access, forward-simulating fitness week over week
(rolling through STORED weeks' actual TSS, so edits feed the simulation).
Once stored, a week never changes behind the athlete's back:

  - Garmin fitness syncs never touch stored weeks.
  - Plan-affecting profile changes (fingerprint in plan_store) auto-regenerate
    future weeks — the API warns first when edits would be discarded.
  - Past days of the current week survive regeneration untouched.

Dates outside the stored horizon (history before materialization existed,
or beyond race day) fall back to transient generation, served without ids.
"""
from __future__ import annotations
from datetime import date, timedelta

from domain.athlete import AthleteProfile
from domain.fitness import advance_fitness
from domain.periodization import generate_week, generate_plan
from domain.workout import Workout
from domain import plan_store


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _anchored(workout: Workout, profile: AthleteProfile) -> Workout:
    thr = profile.thresholds
    return workout.with_anchors(
        ftp=thr.ftp_watts,
        threshold_pace=thr.run_threshold_pace_sec_per_km,
        css=thr.swim_css_sec_per_100m,
        max_hr=thr.max_hr,
        lthr=thr.run_lthr,
    )


def _row_summary(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "sport": row["sport"],
        "date": row["scheduled_date"],
        "duration_min": row["duration_min"],
        "planned_tss": row["planned_tss"],
        "edited": bool(row["edited"]),
        "pushed": row["garmin_workout_id"] is not None,
    }


def _row_detail(row, profile: AthleteProfile) -> dict:
    w = _anchored(Workout.model_validate_json(row["workout_json"]), profile)
    return {
        **w.detail(),
        "id": row["id"],
        "edited": bool(row["edited"]),
        "pushed": row["garmin_workout_id"] is not None,
    }


def _rows_daily_tss(week_start: date, rows) -> list[float]:
    daily = {(week_start + timedelta(days=i)).isoformat(): 0.0 for i in range(7)}
    for r in rows:
        if r["scheduled_date"] in daily:
            daily[r["scheduled_date"]] += r["planned_tss"]
    return [daily[(week_start + timedelta(days=i)).isoformat()] for i in range(7)]


def ensure_plan(profile: AthleteProfile, today: date | None = None) -> None:
    """
    Materialize every missing week from the current Monday through race day.
    Fitness is forward-simulated through each week in order — stored weeks
    contribute their stored (possibly edited) TSS, so the simulation always
    matches the plan the athlete actually sees.
    """
    today = today or date.today()
    start = _monday(today)
    race = profile.goals.race_date
    if race < start:
        return

    fingerprint = plan_store.profile_fingerprint(profile)
    stored = plan_store.stored_week_starts()
    fitness = profile.fitness
    week = start
    guard = 0
    while week <= race and guard < 60:
        ws = week.isoformat()
        if ws in stored:
            daily = _rows_daily_tss(week, plan_store.week_workouts(ws))
        else:
            plan = generate_week(profile, week_start=week, fitness=fitness)
            plan_store.save_week(plan, fingerprint)
            daily = _rows_daily_tss(week, plan_store.week_workouts(ws))
        fitness = advance_fitness(fitness.ctl, fitness.atl, daily)
        week += timedelta(days=7)
        guard += 1


def regenerate_future(profile: AthleteProfile, today: date | None = None) -> dict:
    """
    Rebuild the plan from the current Monday onward. Manually-edited workouts
    on today or later are DISCARDED (the API layer warns first); the current
    week's already-past days are preserved verbatim — history doesn't move.
    """
    today = today or date.today()
    start = _monday(today)
    discarded_edits = plan_store.edited_count_from(today.isoformat())

    preserved = [dict(r) for r in plan_store.week_workouts(start.isoformat())
                 if r["scheduled_date"] < today.isoformat()]

    plan_store.delete_weeks_from(start.isoformat())
    ensure_plan(profile, today=today)

    if preserved:
        plan_store.delete_workouts_before(start.isoformat(), today.isoformat())
        for row in preserved:
            plan_store.insert_raw_workout(row)

    return {"regenerated": True, "replaced_edited": discarded_edits}


def edited_future_count(today: date | None = None) -> int:
    today = today or date.today()
    return plan_store.edited_count_from(today.isoformat())


# ── read views (stored where available, transient fallback outside horizon) ──

def week_view(profile: AthleteProfile, week_start: date | None = None) -> dict:
    today = date.today()
    week_start = week_start or _monday(today)
    ensure_plan(profile)

    row = plan_store.get_week_row(week_start.isoformat())
    if row is None:  # outside the stored horizon — serve a transient projection
        return generate_week(profile, week_start=week_start).summary()

    workouts = [_row_summary(r) for r in plan_store.week_workouts(row["week_start"])]
    return {
        "week_start": row["week_start"],
        "phase": row["phase"],
        "target_tss": row["target_tss"],
        "planned_tss": round(sum(w["planned_tss"] for w in workouts), 1),
        "fitness": {"ctl": row["ctl"], "atl": row["atl"], "tsb": round(row["tsb"], 1)},
        "weeks_to_race": round(row["weeks_to_race"], 1),
        "rationale": row["rationale"],
        "workouts": workouts,
    }


def day_sessions(profile: AthleteProfile, d: date) -> list[dict]:
    """Full detail dicts for the sessions on date `d` (with ids when stored)."""
    ensure_plan(profile)
    monday = _monday(d)
    if plan_store.get_week_row(monday.isoformat()) is not None:
        rows = plan_store.workouts_between(d.isoformat(), d.isoformat())
        return [_row_detail(r, profile) for r in rows]
    # outside stored horizon: transient, no ids (read-only in the editor)
    plan = generate_week(profile, week_start=monday)
    return [w.detail() for w in plan.workouts if w.scheduled_date == d]


def next_session_day(profile: AthleteProfile, scan_days: int = 21) -> dict:
    """The next day (today onward) that has planned sessions, with full detail."""
    ensure_plan(profile)
    today = date.today()
    rows = plan_store.workouts_between(
        today.isoformat(), (today + timedelta(days=scan_days)).isoformat())
    if rows:
        first_day = rows[0]["scheduled_date"]
        details = [_row_detail(r, profile) for r in rows if r["scheduled_date"] == first_day]
        return {"date": first_day, "sessions": details}
    return {"date": None, "sessions": []}


def range_days(profile: AthleteProfile, start: date, end: date) -> dict:
    """Day-by-day summaries across [start, end] — powers the calendar grid."""
    if end < start:
        start, end = end, start
    if (end - start).days > 180:
        end = start + timedelta(days=180)
    ensure_plan(profile)

    days: dict[str, list[dict]] = {}
    for r in plan_store.workouts_between(start.isoformat(), end.isoformat()):
        days.setdefault(r["scheduled_date"], []).append(_row_summary(r))

    # transient fill for weeks in range that were never materialized
    stored = plan_store.stored_week_starts()
    wk = _monday(start)
    while wk <= end:
        if wk.isoformat() not in stored:
            for w in generate_week(profile, week_start=wk).workouts:
                if start <= w.scheduled_date <= end:
                    days.setdefault(w.scheduled_date.isoformat(), []).append(w.summary())
        wk += timedelta(days=7)

    return {"days": [{"date": d, "sessions": s} for d, s in sorted(days.items())]}


def full_plan_view(profile: AthleteProfile) -> dict:
    """Week-level view of the stored plan from this week to race day."""
    ensure_plan(profile)
    today = date.today()
    start = _monday(today)
    race = profile.goals.race_date
    if race < start:  # race has passed — fall back to the old pure projection
        return generate_plan(profile).summary()

    weeks = []
    last_daily: list[float] = [0.0] * 7
    last_row = None
    wk = start
    while wk <= race:
        row = plan_store.get_week_row(wk.isoformat())
        if row is not None:
            rows = plan_store.week_workouts(row["week_start"])
            weeks.append({
                "week_start": row["week_start"],
                "phase": row["phase"],
                "weeks_to_race": round(row["weeks_to_race"], 1),
                "target_tss": row["target_tss"],
                "planned_tss": round(sum(r["planned_tss"] for r in rows), 1),
                "ctl": row["ctl"],
                "atl": row["atl"],
                "tsb": round(row["tsb"], 1),
                "rationale": row["rationale"],
            })
            last_daily = _rows_daily_tss(wk, rows)
            last_row = row
        wk += timedelta(days=7)

    if last_row is not None:
        end = advance_fitness(last_row["ctl"], last_row["atl"], last_daily)
        race_day_fitness = {"ctl": end.ctl, "atl": end.atl, "tsb": round(end.tsb, 1)}
    else:
        race_day_fitness = {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}

    return {
        "race_date": race.isoformat(),
        "start_week": start.isoformat(),
        "total_weeks": len(weeks),
        "projected_peak_ctl": round(max((w["ctl"] for w in weeks), default=0.0), 1),
        "race_day_fitness": race_day_fitness,
        "weeks": weeks,
    }


def day_workouts(profile: AthleteProfile, d: date) -> list[tuple[str | None, Workout]]:
    """(stored id, domain Workout) pairs for date `d` — export paths need both."""
    ensure_plan(profile)
    monday = _monday(d)
    if plan_store.get_week_row(monday.isoformat()) is not None:
        rows = plan_store.workouts_between(d.isoformat(), d.isoformat())
        return [(r["id"], _anchored(Workout.model_validate_json(r["workout_json"]), profile))
                for r in rows]
    plan = generate_week(profile, week_start=monday)
    return [(None, w) for w in plan.workouts if w.scheduled_date == d]


def range_workouts(profile: AthleteProfile, start: date, end: date) -> list[Workout]:
    """Domain Workout objects across [start, end] (stored plan where available)."""
    if end < start:
        start, end = end, start
    if (end - start).days > 180:
        end = start + timedelta(days=180)
    ensure_plan(profile)

    out = [_anchored(Workout.model_validate_json(r["workout_json"]), profile)
           for r in plan_store.workouts_between(start.isoformat(), end.isoformat())]

    stored = plan_store.stored_week_starts()
    wk = _monday(start)
    while wk <= end:
        if wk.isoformat() not in stored:
            out.extend(w for w in generate_week(profile, week_start=wk).workouts
                       if start <= w.scheduled_date <= end)
        wk += timedelta(days=7)
    return sorted(out, key=lambda w: w.scheduled_date)


def week_details(profile: AthleteProfile, week_start: date) -> dict | None:
    """A stored week with FULL workout details (used by the PDF report)."""
    row = plan_store.get_week_row(week_start.isoformat())
    if row is None:
        return None
    workouts = [_row_detail(r, profile) for r in plan_store.week_workouts(row["week_start"])]
    return {
        "week_start": row["week_start"],
        "phase": row["phase"],
        "target_tss": row["target_tss"],
        "planned_tss": round(sum(w["planned_tss"] for w in workouts), 1),
        "rationale": row["rationale"],
        "workouts": workouts,
    }


# ── single-workout operations (editor) ────────────────────────────────────────

def get_workout_detail(profile: AthleteProfile, workout_id: str) -> dict | None:
    row = plan_store.get_workout(workout_id)
    return _row_detail(row, profile) if row is not None else None


def save_workout_edit(profile: AthleteProfile, workout_id: str, workout: Workout) -> dict | None:
    """Persist an edited workout (validated upstream); returns the stored detail."""
    if plan_store.get_workout(workout_id) is None:
        return None
    w = _anchored(workout, profile).normalize(profile.thresholds.swim_css_sec_per_100m)
    plan_store.update_workout(workout_id, w)
    return get_workout_detail(profile, workout_id)
