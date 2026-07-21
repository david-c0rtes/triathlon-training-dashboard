"""
JSON-file persistence for the athlete profile (single-user — see
[[single-user-limitation]]).

On first run the file doesn't exist, so a placeholder profile is seeded and
saved. The user edits their real FTP / pace / CSS / max HR via PUT /profile
(or by hand-editing data/profile.json).
"""
from __future__ import annotations
from datetime import date

import apppaths
from domain.athlete import (
    AthleteProfile, Goals, Thresholds, Fitness, RaceGoal, Discipline,
)


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
        onboarding_complete=False,  # the only path that should start the wizard
    )


def load_profile() -> AthleteProfile:
    """Load the saved profile, seeding a placeholder on first run."""
    profile_file = apppaths.profile_path()
    if profile_file.exists():
        return AthleteProfile.model_validate_json(profile_file.read_text())
    profile = _default_profile()
    save_profile(profile)
    return profile


def save_profile(profile: AthleteProfile) -> None:
    profile_file = apppaths.profile_path()
    profile_file.parent.mkdir(parents=True, exist_ok=True)
    profile_file.write_text(profile.model_dump_json(indent=2))


def update_fitness(ctl: float, atl: float) -> AthleteProfile:
    """Persist freshly-computed CTL/ATL into the saved profile."""
    profile = load_profile()
    profile.fitness = Fitness(ctl=ctl, atl=atl)
    save_profile(profile)
    return profile
