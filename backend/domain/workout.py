from __future__ import annotations
from datetime import date
from enum import Enum
from typing import Union
from pydantic import BaseModel, Field, computed_field


class Sport(str, Enum):
    SWIM = "swim"
    BIKE = "bike"
    RUN = "run"
    BRICK = "brick"  # bike→run transition workout


class TargetType(str, Enum):
    POWER_ZONE = "power_zone"       # bike, zone number 1-6
    POWER_PERCENT_FTP = "power_pct" # bike, % of FTP
    HR_ZONE = "hr_zone"             # any sport, zone number 1-5
    PACE_ZONE = "pace_zone"         # run/swim, zone number 1-5
    OPEN = "open"                   # no target (warm-up, cool-down feel)


class Target(BaseModel):
    type: TargetType
    zone: int | None = None          # zone number when type is *_ZONE
    pct_of_anchor: float | None = None  # % of FTP/threshold when type is *_PERCENT


class WorkoutStep(BaseModel):
    name: str
    duration_seconds: int
    target: Target
    notes: str = ""


class RepeatBlock(BaseModel):
    repeat_count: int = Field(ge=1)
    steps: list[WorkoutStep]

    @property
    def total_duration_seconds(self) -> int:
        return self.repeat_count * sum(s.duration_seconds for s in self.steps)


StepOrBlock = Union[WorkoutStep, RepeatBlock]


def _step_tss(step: WorkoutStep, ftp: int, threshold_pace: float, css: float, sport: Sport) -> float:
    """Estimate TSS contribution for a single step."""
    hours = step.duration_seconds / 3600.0

    if sport == Sport.BIKE:
        if step.target.type == TargetType.POWER_ZONE and step.target.zone:
            # Mid-point watts per zone (6-zone model)
            zone_midpoints = {1: 0.45, 2: 0.65, 3: 0.83, 4: 0.98, 5: 1.13, 6: 1.30}
            intensity_factor = zone_midpoints.get(step.target.zone, 0.65)
        elif step.target.type == TargetType.POWER_PERCENT_FTP and step.target.pct_of_anchor:
            intensity_factor = step.target.pct_of_anchor
        else:
            intensity_factor = 0.60  # default: easy
        return hours * intensity_factor ** 2 * 100

    elif sport == Sport.RUN:
        if step.target.type == TargetType.PACE_ZONE and step.target.zone:
            # Zone pace multipliers relative to threshold (sec/km ratio)
            zone_pace_ratios = {1: 1.40, 2: 1.27, 3: 1.13, 4: 1.03, 5: 0.95}
            pace_ratio = zone_pace_ratios.get(step.target.zone, 1.30)
        else:
            pace_ratio = 1.30
        intensity_factor = 1.0 / pace_ratio
        return hours * intensity_factor ** 2 * 100

    elif sport == Sport.SWIM:
        if step.target.type == TargetType.PACE_ZONE and step.target.zone:
            zone_pace_ratios = {1: 1.35, 2: 1.22, 3: 1.12, 4: 1.04, 5: 0.95}
            pace_ratio = zone_pace_ratios.get(step.target.zone, 1.25)
        else:
            pace_ratio = 1.25
        intensity_factor = 1.0 / pace_ratio
        return hours * intensity_factor ** 2 * 100

    return 0.0


class Workout(BaseModel):
    sport: Sport
    scheduled_date: date
    title: str
    description: str = ""
    steps: list[StepOrBlock]

    # Athlete anchors needed for TSS calculation — not stored, passed at compute time
    _ftp: int = 0
    _threshold_pace: float = 0.0
    _css: float = 0.0

    def with_anchors(self, ftp: int, threshold_pace: float, css: float) -> "Workout":
        self._ftp = ftp
        self._threshold_pace = threshold_pace
        self._css = css
        return self

    @property
    def total_duration_seconds(self) -> int:
        total = 0
        for item in self.steps:
            if isinstance(item, WorkoutStep):
                total += item.duration_seconds
            else:
                total += item.total_duration_seconds
        return total

    @property
    def total_duration_minutes(self) -> int:
        return self.total_duration_seconds // 60

    def planned_tss(self) -> float:
        tss = 0.0
        for item in self.steps:
            if isinstance(item, WorkoutStep):
                tss += _step_tss(item, self._ftp, self._threshold_pace, self._css, self.sport)
            else:
                for _ in range(item.repeat_count):
                    for step in item.steps:
                        tss += _step_tss(step, self._ftp, self._threshold_pace, self._css, self.sport)
        return round(tss, 1)

    def summary(self) -> dict:
        return {
            "title": self.title,
            "sport": self.sport,
            "date": self.scheduled_date.isoformat(),
            "duration_min": self.total_duration_minutes,
            "planned_tss": self.planned_tss(),
        }
