from __future__ import annotations
from datetime import date
from enum import Enum
from typing import Union
from pydantic import BaseModel, Field, computed_field


class Sport(str, Enum):
    SWIM = "swim"
    BIKE_OUTDOOR = "bike_outdoor"   # exports to Garmin Connect (.fit on watch)
    BIKE_INDOOR = "bike_indoor"     # exports as .zwo for Rouvy/Zwift
    RUN = "run"
    BRICK = "brick"  # bike→run transition workout


# Both bike variants behave identically for zones/TSS — only export differs.
_BIKE_SPORTS = {Sport.BIKE_OUTDOOR, Sport.BIKE_INDOOR}


def is_bike(sport: Sport) -> bool:
    return sport in _BIKE_SPORTS


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
    duration_seconds: int          # always set — used for TSS + estimated duration
    target: Target
    notes: str = ""
    distance_meters: int | None = None  # if set, the step ends by distance, not time

    def detail(self) -> dict:
        return {
            "kind": "step",
            "name": self.name,
            "duration_seconds": self.duration_seconds,
            "distance_meters": self.distance_meters,
            "target": self.target.model_dump(),
            "notes": self.notes,
        }


class RepeatBlock(BaseModel):
    repeat_count: int = Field(ge=1)
    steps: list[WorkoutStep]

    @property
    def total_duration_seconds(self) -> int:
        return self.repeat_count * sum(s.duration_seconds for s in self.steps)

    def detail(self) -> dict:
        return {
            "kind": "repeat",
            "repeat_count": self.repeat_count,
            "steps": [s.detail() for s in self.steps],
        }


StepOrBlock = Union[WorkoutStep, RepeatBlock]


# HR zone midpoints as % of max HR — midpoint of each zone's % range.
# Bike: 48-61 / 62-73 / 74-82 / 83-89 / 90-100
BIKE_HR_ZONE_MIDPOINTS_PCT = {1: 0.545, 2: 0.675, 3: 0.780, 4: 0.860, 5: 0.950}
# Run:  56-67 / 68-77 / 78-85 / 86-91 / 92-100
RUN_HR_ZONE_MIDPOINTS_PCT  = {1: 0.615, 2: 0.725, 3: 0.815, 4: 0.885, 5: 0.960}


def _step_tss(
    step: WorkoutStep,
    ftp: int,
    threshold_pace: float,
    css: float,
    sport: Sport,
    max_hr: int | None = None,
    lthr: int | None = None,
) -> float:
    """Estimate TSS contribution for a single step."""
    hours = step.duration_seconds / 3600.0

    # HR_ZONE uses sport-specific midpoint tables anchored on max HR.
    # IF = (zone midpoint % of max HR) / (LTHR % of max HR).
    # Bike and run have separate zone boundaries; swim falls back to run zones.
    # Default LTHR ≈ 80% of max HR when lthr is not explicitly provided.
    if step.target.type == TargetType.HR_ZONE and step.target.zone and max_hr:
        if is_bike(sport):
            midpoints = BIKE_HR_ZONE_MIDPOINTS_PCT
        else:
            midpoints = RUN_HR_ZONE_MIDPOINTS_PCT
        midpoint_pct = midpoints.get(step.target.zone, 0.70)
        lthr_pct_of_max = (lthr / max_hr) if lthr else 0.80
        intensity_factor = midpoint_pct / lthr_pct_of_max
        return hours * intensity_factor ** 2 * 100

    if is_bike(sport):
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
    _max_hr: int | None = None
    _lthr: int | None = None

    def with_anchors(
        self,
        ftp: int,
        threshold_pace: float,
        css: float,
        max_hr: int | None = None,
        lthr: int | None = None,
    ) -> "Workout":
        self._ftp = ftp
        self._threshold_pace = threshold_pace
        self._css = css
        self._max_hr = max_hr
        self._lthr = lthr
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
                tss += _step_tss(item, self._ftp, self._threshold_pace, self._css, self.sport,
                                 self._max_hr, self._lthr)
            else:
                for _ in range(item.repeat_count):
                    for step in item.steps:
                        tss += _step_tss(step, self._ftp, self._threshold_pace, self._css, self.sport,
                                         self._max_hr, self._lthr)
        return round(tss, 1)

    def summary(self) -> dict:
        return {
            "title": self.title,
            "sport": self.sport,
            "date": self.scheduled_date.isoformat(),
            "duration_min": self.total_duration_minutes,
            "planned_tss": self.planned_tss(),
        }

    def detail(self) -> dict:
        """Full structure for the review/edit screen."""
        return {
            **self.summary(),
            "description": self.description,
            "steps": [item.detail() for item in self.steps],
        }
