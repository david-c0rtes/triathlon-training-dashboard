from __future__ import annotations
from datetime import date
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class RaceGoal(str, Enum):
    FINISH = "finish"
    TARGET_TIME = "target_time"
    COMPETE = "compete"


class Discipline(str, Enum):
    SWIM = "swim"
    BIKE = "bike"
    RUN = "run"


class RaceType(str, Enum):
    SUPERSPRINT_TRI = "supersprint_tri"
    SUPERSPRINT_DU = "supersprint_du"
    SPRINT_TRI = "sprint_tri"
    SPRINT_DU = "sprint_du"
    SPRINT_AQUATHLON = "sprint_aquathlon"
    SPRINT_AQUABIKE = "sprint_aquabike"
    OLYMPIC_TRI = "olympic_tri"
    OLYMPIC_DU = "olympic_du"
    T100 = "t100"
    MIDDLE_TRI = "middle_tri"
    LONG_TRI = "long_tri"
    DOUBLE_LONG_TRI = "double_long_tri"
    CUSTOM = "custom"


# key -> label + per-discipline distance in metres (run = total of all run legs).
# Source of truth for the Settings dropdown (served via GET /race-types).
RACE_TYPES: dict[str, dict] = {
    "supersprint_tri":  {"label": "Supersprint Triathlon", "swim_m": 400, "bike_m": 10000, "run_m": 2500,
                         "description": "400m swim · 10km bike · 2.5km run"},
    "supersprint_du":   {"label": "Supersprint Duathlon", "swim_m": 0, "bike_m": 10000, "run_m": 3500,
                         "description": "2.5km run · 10km bike · 1km run"},
    "sprint_tri":       {"label": "Sprint Triathlon", "swim_m": 750, "bike_m": 20000, "run_m": 5000,
                         "description": "750m swim · 20km bike · 5km run"},
    "sprint_du":        {"label": "Sprint Duathlon", "swim_m": 0, "bike_m": 20000, "run_m": 7500,
                         "description": "5km run · 20km bike · 2.5km run"},
    "sprint_aquathlon": {"label": "Sprint Aquathlon", "swim_m": 750, "bike_m": 0, "run_m": 5000,
                         "description": "750m swim · 5km run"},
    "sprint_aquabike":  {"label": "Sprint Aquabike", "swim_m": 750, "bike_m": 20000, "run_m": 0,
                         "description": "750m swim · 20km bike"},
    "olympic_tri":      {"label": "Olympic Triathlon", "swim_m": 1500, "bike_m": 40000, "run_m": 10000,
                         "description": "1.5km swim · 40km bike · 10km run"},
    "olympic_du":       {"label": "Olympic Duathlon", "swim_m": 0, "bike_m": 40000, "run_m": 15000,
                         "description": "10km run · 40km bike · 5km run"},
    "t100":             {"label": "T100 Triathlon", "swim_m": 2000, "bike_m": 80000, "run_m": 18000,
                         "description": "2km swim · 80km bike · 18km run"},
    "middle_tri":       {"label": "Middle Distance (IRONMAN 70.3)", "swim_m": 1900, "bike_m": 90000, "run_m": 21100,
                         "description": "1.9km swim · 90km bike · 21.1km run"},
    "long_tri":         {"label": "Long Distance (IRONMAN)", "swim_m": 3800, "bike_m": 180000, "run_m": 42200,
                         "description": "3.8km swim · 180km bike · 42.2km run"},
    "double_long_tri":  {"label": "Double Long Distance (Double IRONMAN)", "swim_m": 7600, "bike_m": 360000, "run_m": 84400,
                         "description": "7.6km swim · 360km bike · 84.4km run"},
}


class CustomLeg(BaseModel):
    """One leg of a custom-distance race (e.g. run leg of a duathlon)."""
    discipline: Discipline
    distance_m: int = Field(..., gt=0)


class Goals(BaseModel):
    race_date: date
    race_type: RaceType = RaceType.MIDDLE_TRI
    # Only used when race_type == CUSTOM: 2-3 ordered legs, no two consecutive
    # legs of the same discipline.
    custom_legs: list[CustomLeg] | None = None
    goal: RaceGoal = RaceGoal.FINISH
    target_finish_seconds: int | None = None  # e.g. 5*3600 for 5h finish
    weekly_hours_available: float = Field(10.0, ge=3.0, le=25.0)
    limiter_discipline: Discipline | None = None  # discipline to emphasise

    @model_validator(mode="after")
    def _validate_custom(self) -> "Goals":
        if self.race_type == RaceType.CUSTOM:
            legs = self.custom_legs or []
            if not (2 <= len(legs) <= 3):
                raise ValueError("A custom race must have 2 or 3 legs.")
            for a, b in zip(legs, legs[1:]):
                if a.discipline == b.discipline:
                    raise ValueError("A discipline cannot repeat in consecutive legs.")
        return self


class TrainingPreferences(BaseModel):
    """How the athlete splits training and how strength is scheduled."""
    # Fraction of weekly training time per sport — must roughly sum to 1.0.
    sport_distribution: dict[str, float] = Field(
        default_factory=lambda: {"swim": 0.15, "bike": 0.40, "run": 0.30, "strength": 0.15}
    )
    strength_sessions_per_week: int = Field(2, ge=0, le=7)
    # Measured 90-day rolling avg TSS/hour per sport — None until enough data,
    # then populated on Garmin sync. Falls back to DEFAULT_TSS_PER_HOUR.
    measured_tss_per_hour: dict[str, float] | None = None


class Thresholds(BaseModel):
    """User's personal performance anchors. All zones derive from these."""
    ftp_watts: int = Field(..., description="Functional Threshold Power (bike)")
    run_threshold_pace_sec_per_km: float = Field(
        ..., description="Run lactate-threshold pace in seconds per km"
    )
    run_lthr: int | None = Field(None, description="Lactate Threshold Heart Rate (run)")
    swim_css_sec_per_100m: float = Field(
        ..., description="Critical Swim Speed per 100 m in seconds"
    )
    max_hr: int | None = Field(None, description="Max heart rate (optional override)")


class Fitness(BaseModel):
    """
    Performance Management Chart values — derived from Strava history.
    Placeholder values are used until the Strava integration is connected.
    """
    ctl: float = Field(0.0, description="Chronic Training Load (fitness)")
    atl: float = Field(0.0, description="Acute Training Load (fatigue)")

    @property
    def tsb(self) -> float:
        """Training Stress Balance (form) = CTL - ATL."""
        return self.ctl - self.atl


class AthleteProfile(BaseModel):
    name: str
    goals: Goals
    thresholds: Thresholds
    fitness: Fitness = Field(default_factory=Fitness)
    preferences: TrainingPreferences = Field(default_factory=TrainingPreferences)
