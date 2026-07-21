"""
SQLite persistence for the materialized training plan.

Until now the plan was regenerated from scratch on every request, which meant
edits vanished on reload, Garmin pushes had no memory (duplicates), and every
fitness sync silently reshuffled sessions the athlete had already reviewed.
This store makes the plan a real object: generated weeks are written down,
edits stick, and pushes are recorded.

The DB lives in backend/data/ (gitignored, same as profile.json). Set the
TRIFLOW_DB env var to point elsewhere (tests use a temp path).

Regeneration policy (see services/plan_service.py): fitness changes never
touch stored weeks; plan-affecting profile changes (goals, thresholds, sport
split — fingerprinted here) auto-regenerate future weeks.
"""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import apppaths
from domain.athlete import AthleteProfile
from domain.workout import Workout

_SCHEMA = """
CREATE TABLE IF NOT EXISTS weeks (
    week_start TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    target_tss REAL NOT NULL,
    ctl REAL NOT NULL DEFAULT 0,
    atl REAL NOT NULL DEFAULT 0,
    tsb REAL NOT NULL DEFAULT 0,
    weeks_to_race REAL NOT NULL DEFAULT 0,
    rationale TEXT NOT NULL DEFAULT '',
    profile_fingerprint TEXT NOT NULL,
    generated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workouts (
    id TEXT PRIMARY KEY,
    week_start TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,
    sport TEXT NOT NULL,
    title TEXT NOT NULL,
    workout_json TEXT NOT NULL,
    duration_min REAL NOT NULL DEFAULT 0,
    planned_tss REAL NOT NULL DEFAULT 0,
    edited INTEGER NOT NULL DEFAULT 0,
    garmin_workout_id TEXT,
    pushed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_workouts_week ON workouts(week_start);
CREATE INDEX IF NOT EXISTS idx_workouts_date ON workouts(scheduled_date);
"""


def _db_path() -> Path:
    override = os.environ.get("TRIFLOW_DB")  # tests point this at a temp file
    return Path(override) if override else apppaths.plan_db_path()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def profile_fingerprint(profile: AthleteProfile) -> str:
    """
    Hash of the plan-affecting profile fields. Deliberately EXCLUDES fitness
    (CTL/ATL move on every Garmin sync) and measured TSS rates (rolling
    averages) — those changing must never rewrite a plan the athlete has seen.
    """
    payload = {
        "goals": profile.goals.model_dump(mode="json"),
        "thresholds": profile.thresholds.model_dump(mode="json"),
        "sport_distribution": profile.preferences.sport_distribution,
        "strength_sessions_per_week": profile.preferences.strength_sessions_per_week,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


# ── weeks ─────────────────────────────────────────────────────────────────────

def save_week(plan, fingerprint: str) -> None:
    """Persist a generated WeekPlan (replaces any existing copy of that week)."""
    with closing(_connect()) as conn, conn:
        ws = plan.week_start.isoformat()
        conn.execute("DELETE FROM workouts WHERE week_start = ?", (ws,))
        conn.execute("DELETE FROM weeks WHERE week_start = ?", (ws,))
        conn.execute(
            "INSERT INTO weeks (week_start, phase, target_tss, ctl, atl, tsb,"
            " weeks_to_race, rationale, profile_fingerprint, generated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ws, plan.phase.value, plan.target_tss, plan.ctl, plan.atl, plan.tsb,
             plan.weeks_to_race, plan.rationale, fingerprint, _now()),
        )
        for w in plan.workouts:
            conn.execute(
                "INSERT INTO workouts (id, week_start, scheduled_date, sport, title,"
                " workout_json, duration_min, planned_tss)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, ws, w.scheduled_date.isoformat(), w.sport.value,
                 w.title, w.model_dump_json(), w.total_duration_minutes,
                 w.planned_tss()),
            )


def get_week_row(week_start: str) -> sqlite3.Row | None:
    with closing(_connect()) as conn:
        return conn.execute("SELECT * FROM weeks WHERE week_start = ?", (week_start,)).fetchone()


def stored_week_starts() -> set[str]:
    with closing(_connect()) as conn:
        return {r["week_start"] for r in conn.execute("SELECT week_start FROM weeks")}


def delete_weeks_from(week_start: str) -> None:
    """Drop every stored week (and its workouts) from `week_start` onward."""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM workouts WHERE week_start >= ?", (week_start,))
        conn.execute("DELETE FROM weeks WHERE week_start >= ?", (week_start,))


# ── workouts ──────────────────────────────────────────────────────────────────

def week_workouts(week_start: str) -> list[sqlite3.Row]:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT * FROM workouts WHERE week_start = ? ORDER BY scheduled_date, id",
            (week_start,),
        ).fetchall()


def workouts_between(start: str, end: str) -> list[sqlite3.Row]:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT * FROM workouts WHERE scheduled_date BETWEEN ? AND ?"
            " ORDER BY scheduled_date, id",
            (start, end),
        ).fetchall()


def get_workout(workout_id: str) -> sqlite3.Row | None:
    with closing(_connect()) as conn:
        return conn.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,)).fetchone()


def update_workout(workout_id: str, workout: Workout) -> None:
    """Persist an edited workout (marks it edited; re-files it under its week)."""
    from datetime import timedelta
    monday = workout.scheduled_date - timedelta(days=workout.scheduled_date.weekday())
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE workouts SET week_start=?, scheduled_date=?, sport=?, title=?,"
            " workout_json=?, duration_min=?, planned_tss=?, edited=1 WHERE id=?",
            (monday.isoformat(), workout.scheduled_date.isoformat(), workout.sport.value,
             workout.title, workout.model_dump_json(), workout.total_duration_minutes,
             workout.planned_tss(), workout_id),
        )


def mark_pushed(workout_id: str, garmin_workout_id: str | int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE workouts SET garmin_workout_id=?, pushed_at=? WHERE id=?",
            (str(garmin_workout_id), _now(), workout_id),
        )


def delete_workouts_before(week_start: str, before_date: str) -> None:
    """Remove a week's workouts scheduled before `before_date` (regen helper)."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "DELETE FROM workouts WHERE week_start = ? AND scheduled_date < ?",
            (week_start, before_date),
        )


def insert_raw_workout(row: dict) -> None:
    """Re-insert a previously-captured workout row verbatim (regen preservation)."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO workouts (id, week_start, scheduled_date, sport,"
            " title, workout_json, duration_min, planned_tss, edited,"
            " garmin_workout_id, pushed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], row["week_start"], row["scheduled_date"], row["sport"],
             row["title"], row["workout_json"], row["duration_min"], row["planned_tss"],
             row["edited"], row["garmin_workout_id"], row["pushed_at"]),
        )


def edited_count_from(from_date: str) -> int:
    """How many manually-edited workouts sit on/after `from_date` (regen warning)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM workouts WHERE edited = 1 AND scheduled_date >= ?",
            (from_date,),
        ).fetchone()
        return int(row["n"])
