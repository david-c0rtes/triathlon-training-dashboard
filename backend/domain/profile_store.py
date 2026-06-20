"""
JSON-file persistence for the athlete profile (single-user — see
[[single-user-limitation]]).

On first run the file doesn't exist, so a placeholder profile is seeded and
saved. The user edits their real FTP / pace / CSS / max HR via PUT /profile
(or by hand-editing data/profile.json).
"""
from __future__ import annotations
from datetime import date
from pathlib import Path

from domain.athlete import (
    AthleteProfile, Goals, Thresholds, Fitness, RaceGoal, Discipline,
)

_DATA_DIR = Path(__file__).parent.parent / "data"
_PROFILE_FILE = _DATA_DIR / "profile.json"


def _default_profile() -> AthleteProfile:
    """Placeholder profile seeded on first run — user replaces with real values."""
    return AthleteProfile(
        name="Athlete",
        goals=Goals(
            race_date=date(2026, 10, 4),          # PLACEHOLDER — set your race date
            goal=RaceGoal.FINISH,
            target_finish_seconds=None,
            weekly_hours_available=10.0,          # PLACEHOLDER
            limiter_discipline=None,
        ),
        thresholds=Thresholds(
            ftp_watts=200,                         # PLACEHOLDER
            run_threshold_pace_sec_per_km=300.0,   # PLACEHOLDER ~5:00/km
            run_lthr=160,                          # PLACEHOLDER
            swim_css_sec_per_100m=100.0,           # PLACEHOLDER ~1:40/100m
            max_hr=190,                            # PLACEHOLDER
        ),
        fitness=Fitness(ctl=0.0, atl=0.0),
    )


def load_profile() -> AthleteProfile:
    """Load the saved profile, seeding a placeholder on first run."""
    if _PROFILE_FILE.exists():
        return AthleteProfile.model_validate_json(_PROFILE_FILE.read_text())
    profile = _default_profile()
    save_profile(profile)
    return profile


def save_profile(profile: AthleteProfile) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _PROFILE_FILE.write_text(profile.model_dump_json(indent=2))


def update_fitness(ctl: float, atl: float) -> AthleteProfile:
    """Persist freshly-computed CTL/ATL into the saved profile."""
    profile = load_profile()
    profile.fitness = Fitness(ctl=ctl, atl=atl)
    save_profile(profile)
    return profile
