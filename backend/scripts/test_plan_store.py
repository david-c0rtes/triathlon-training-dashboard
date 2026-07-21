"""
Plan-persistence regression tests — runs against a THROWAWAY temp DB (never
touches backend/data/plan.db) and a synthetic profile.

Run:  cd backend && PYTHONPATH=. .venv/Scripts/python.exe scripts/test_plan_store.py
"""
from __future__ import annotations
import os
import sys
import tempfile
from datetime import date, timedelta

os.environ["TRIFLOW_DB"] = os.path.join(tempfile.mkdtemp(), "plan_test.db")

from domain.athlete import AthleteProfile, Goals, Thresholds, Fitness, RaceType
from domain.workout import Workout
from domain import plan_store
from services import plan_service

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'FAIL'} {name}{' — ' + detail if detail and not ok else ''}")
    if not ok:
        FAILURES.append(name)


def make_profile(hours: float = 10.0) -> AthleteProfile:
    return AthleteProfile(
        name="StoreTest",
        goals=Goals(race_date=date.today() + timedelta(weeks=12), race_type=RaceType.MIDDLE_TRI,
                    weekly_hours_available=hours),
        thresholds=Thresholds(ftp_watts=250, run_threshold_pace_sec_per_km=280,
                              swim_css_sec_per_100m=100, run_lthr=165, max_hr=185),
        fitness=Fitness(ctl=45.0, atl=50.0),
    )


def main() -> None:
    profile = make_profile()
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    print("== materialization ==")
    plan_service.ensure_plan(profile)
    weeks = plan_store.stored_week_starts()
    check("plan materializes to race day", len(weeks) == 13, f"got {len(weeks)} weeks")
    ids_before = {r["id"] for r in plan_store.workouts_between("2000-01-01", "2100-01-01")}
    plan_service.ensure_plan(profile)
    ids_after = {r["id"] for r in plan_store.workouts_between("2000-01-01", "2100-01-01")}
    check("ensure_plan is idempotent (ids stable)", ids_before == ids_after)

    print("== edits persist ==")
    future = plan_store.workouts_between(
        (today + timedelta(days=1)).isoformat(), (today + timedelta(days=10)).isoformat())
    row = future[0]
    w = Workout.model_validate_json(row["workout_json"])
    w.title = "EDITED " + w.title
    saved = plan_service.save_workout_edit(profile, row["id"], w)
    check("edit saves and returns detail", saved is not None and saved["title"].startswith("EDITED"))
    check("edited flag set", bool(saved and saved["edited"]))
    plan_service.ensure_plan(profile)
    again = plan_service.get_workout_detail(profile, row["id"])
    check("edit survives re-ensure", bool(again and again["title"].startswith("EDITED")))
    check("edited_future_count sees it", plan_service.edited_future_count() == 1)

    print("== push recording ==")
    plan_store.mark_pushed(row["id"], 987654321)
    pushed = plan_store.get_workout(row["id"])
    check("garmin id recorded", pushed["garmin_workout_id"] == "987654321")
    check("detail exposes pushed flag", plan_service.get_workout_detail(profile, row["id"])["pushed"])

    print("== regeneration ==")
    past_ids = {r["id"] for r in plan_store.week_workouts(monday.isoformat())
                if r["scheduled_date"] < today.isoformat()}
    res = plan_service.regenerate_future(profile)
    check("regen reports discarded edits", res["replaced_edited"] == 1, str(res))
    check("edits gone after regen", plan_service.edited_future_count() == 0)
    check("edited workout id no longer exists", plan_store.get_workout(row["id"]) is None)
    past_after = {r["id"] for r in plan_store.week_workouts(monday.isoformat())
                  if r["scheduled_date"] < today.isoformat()}
    check("current week's past days preserved verbatim", past_ids == past_after,
          f"{len(past_ids)} vs {len(past_after)}")

    print("== fingerprint (auto-regen trigger) ==")
    fp1 = plan_store.profile_fingerprint(profile)
    profile.fitness = Fitness(ctl=60.0, atl=40.0)
    check("fitness change does NOT change fingerprint", plan_store.profile_fingerprint(profile) == fp1)
    profile.preferences.measured_tss_per_hour = {"run": 90.0}
    check("measured rates do NOT change fingerprint", plan_store.profile_fingerprint(profile) == fp1)
    profile.goals.weekly_hours_available = 12.0
    check("hours change DOES change fingerprint", plan_store.profile_fingerprint(profile) != fp1)

    print("== date move re-files the workout ==")
    future = plan_store.workouts_between(
        (today + timedelta(days=1)).isoformat(), (today + timedelta(days=6)).isoformat())
    row = future[0]
    w = Workout.model_validate_json(row["workout_json"])
    w.scheduled_date = w.scheduled_date + timedelta(days=7)  # into next week
    plan_service.save_workout_edit(profile, row["id"], w)
    moved = plan_store.get_workout(row["id"])
    expected_monday = (w.scheduled_date - timedelta(days=w.scheduled_date.weekday())).isoformat()
    check("week_start follows the new date", moved["week_start"] == expected_monday)

    print(f"\n{'ALL STORE TESTS PASS' if not FAILURES else f'{len(FAILURES)} FAILURE(S): {FAILURES}'}")
    sys.exit(0 if not FAILURES else 1)


if __name__ == "__main__":
    main()
