"""One-off: dump weekly planned training hours from today through race day as JSON."""
from __future__ import annotations
import json
from datetime import date, timedelta

from domain.profile_store import load_profile
from domain.periodization import generate_week

profile = load_profile()
today = date.today()
race_date = profile.goals.race_date
week_start = today - timedelta(days=today.weekday())

rows = []
while week_start <= race_date:
    wk = generate_week(profile, week_start=week_start)
    hours = sum(w.total_duration_minutes for w in wk.workouts) / 60
    rows.append({
        "week_start": week_start.isoformat(),
        "phase": wk.phase.value,
        "hours": round(hours, 2),
        "target_tss": wk.target_tss,
        "planned_tss": wk.planned_tss,
        "weeks_to_race": round(wk.weeks_to_race, 1),
    })
    week_start += timedelta(days=7)

print(json.dumps(rows, indent=2))
