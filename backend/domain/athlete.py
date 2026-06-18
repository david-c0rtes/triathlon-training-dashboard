from __future__ import annotations
from datetime import date
from enum import Enum
from pydantic import BaseModel, Field


class RaceGoal(str, Enum):
    FINISH = "finish"
    TARGET_TIME = "target_time"
    COMPETE = "compete"


class Discipline(str, Enum):
    SWIM = "swim"
    BIKE = "bike"
    RUN = "run"


class Goals(BaseModel):
    race_date: date
    goal: RaceGoal = RaceGoal.FINISH
    target_finish_seconds: int | None = None  # e.g. 5*3600 for 5h finish
    weekly_hours_available: float = Field(10.0, ge=3.0, le=25.0)
    limiter_discipline: Discipline | None = None  # discipline to emphasise


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
