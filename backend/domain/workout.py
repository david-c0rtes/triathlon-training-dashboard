from __future__ import annotations
from datetime import date
from enum import Enum
from typing import Union
from pydantic import BaseModel, Field, computed_field

from domain.training_load import THRESHOLD_HOUR_TSS, STRENGTH_TSS_PER_HOUR


class Sport(str, Enum):
    SWIM = "swim"
    BIKE_OUTDOOR = "bike_outdoor"   # exports to Garmin Connect (.fit on watch)
    BIKE_INDOOR = "bike_indoor"     # exports as .zwo for Rouvy/Zwift
    RUN = "run"
    BRICK = "brick"      # bike→run transition workout
    STRENGTH = "strength"  # simple timed session, flat TSS, no structured steps


# Both bike variants behave identically for zones/TSS — only export differs.
_BIKE_SPORTS = {Sport.BIKE_OUTDOOR, Sport.BIKE_INDOOR}


def is_bike(sport: Sport) -> bool:
    return sport in _BIKE_SPORTS


def load_group(sport: Sport) -> str:
    """Map a sport to its training-load group (for TSS distribution)."""
    if sport == Sport.SWIM:
        return "swim"
    if sport == Sport.RUN:
        return "run"
    if sport == Sport.STRENGTH:
        return "strength"
    return "bike"  # bike indoor/outdoor + brick


class TargetType(str, Enum):
    POWER_ZONE = "power_zone"       # bike, zone number 1-6
    POWER_PERCENT_FTP = "power_pct" # bike, % of FTP
    HR_ZONE = "hr_zone"             # any sport, zone number 1-5
    PACE_ZONE = "pace_zone"         # run/swim, zone number 1-5
    OPEN = "open"                   # no target (warm-up, cool-down feel)


class SwimEquipment(str, Enum):
    """Swim toys — exported to Garmin as the step's equipmentType."""
    PULL_BUOY = "pull_buoy"
    KICKBOARD = "kickboard"
    FINS = "fins"
    PADDLES = "paddles"
    PADDLES_BUOY = "paddles_buoy"   # paddles + pull buoy (Garmin: paddles)
    PADDLES_FINS = "paddles_fins"   # paddles + fins (Garmin: paddles)
    SNORKEL = "snorkel"


class SwimStroke(str, Enum):
    """Stroke for a swim step — free unless it's a drill/recovery variation."""
    FREE = "free"
    BACK = "back"
    BREAST = "breast"
    DRILL = "drill"     # one-arm, catch-up, sculling… described in notes
    MIXED = "mixed"


# Swim pace multipliers vs CSS per zone — mirrors the TSS pace ratios and is
# used to estimate a swim step's duration from its distance.
SWIM_ZONE_PACE_RATIO = {1: 1.35, 2: 1.22, 3: 1.12, 4: 1.04, 5: 0.95}
# Equipment that meaningfully changes speed vs clean freestyle at the same effort.
_EQUIPMENT_PACE_FACTOR = {
    SwimEquipment.KICKBOARD: 1.65,      # kick sets are much slower
    SwimEquipment.FINS: 0.85,
    SwimEquipment.PADDLES_FINS: 0.82,
    SwimEquipment.PULL_BUOY: 1.0,
    SwimEquipment.PADDLES: 0.95,
    SwimEquipment.PADDLES_BUOY: 0.95,
    SwimEquipment.SNORKEL: 1.05,
}
_STROKE_PACE_FACTOR = {
    SwimStroke.BREAST: 1.35,
    SwimStroke.BACK: 1.20,
    SwimStroke.DRILL: 1.45,
    SwimStroke.MIXED: 1.15,
}


def estimate_swim_seconds(distance_m: int, zone: int | None, css_sec_per_100m: float,
                          equipment: "SwimEquipment | None" = None,
                          stroke: "SwimStroke | None" = None) -> int:
    """Estimated swim time for a step: distance × CSS × zone ratio × gear/stroke factor."""
    ratio = SWIM_ZONE_PACE_RATIO.get(zone or 2, 1.22)
    factor = _EQUIPMENT_PACE_FACTOR.get(equipment, 1.0) * _STROKE_PACE_FACTOR.get(stroke, 1.0)
    return max(10, round(distance_m / 100.0 * css_sec_per_100m * ratio * factor))


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
    rest_seconds: int = 0               # fixed rest AFTER the step (swim sets)
    equipment: SwimEquipment | None = None  # swim only
    stroke: SwimStroke | None = None        # swim only

    @property
    def elapsed_seconds(self) -> int:
        """Work + rest — what the step actually costs on the clock."""
        return self.duration_seconds + max(0, self.rest_seconds)

    def detail(self) -> dict:
        return {
            "kind": "step",
            "name": self.name,
            "duration_seconds": self.duration_seconds,
            "distance_meters": self.distance_meters,
            "rest_seconds": self.rest_seconds,
            "equipment": self.equipment.value if self.equipment else None,
            "stroke": self.stroke.value if self.stroke else None,
            "target": self.target.model_dump(),
            "notes": self.notes,
        }


class RepeatBlock(BaseModel):
    repeat_count: int = Field(ge=1)
    steps: list[WorkoutStep]

    @property
    def total_duration_seconds(self) -> int:
        return self.repeat_count * sum(s.elapsed_seconds for s in self.steps)

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


def _threshold_hour(sport: Sport, step: WorkoutStep) -> float:
    """TSS for one hour at threshold (IF=1.0) for this sport/step."""
    if sport == Sport.SWIM:
        return THRESHOLD_HOUR_TSS["swim"]
    if sport == Sport.RUN:
        return THRESHOLD_HOUR_TSS["run"]
    if is_bike(sport):
        return THRESHOLD_HOUR_TSS["bike"]
    if sport == Sport.BRICK:
        # weight each brick step by its target type (pace=run, power=bike)
        if step.target.type == TargetType.PACE_ZONE:
            return THRESHOLD_HOUR_TSS["run"]
        return THRESHOLD_HOUR_TSS["bike"]
    return THRESHOLD_HOUR_TSS["bike"]


def _step_tss(
    step: WorkoutStep,
    ftp: int,
    threshold_pace: float,
    css: float,
    sport: Sport,
    max_hr: int | None = None,
    lthr: int | None = None,
) -> float:
    """Estimate TSS contribution for a single step.

    TSS = hours * IF**2 * threshold_hour_tss[sport].
    Strength is flat (no IF) — just time on task.
    """
    hours = step.duration_seconds / 3600.0

    if sport == Sport.STRENGTH:
        return hours * STRENGTH_TSS_PER_HOUR

    thr_hour = _threshold_hour(sport, step)

    # HR_ZONE uses sport-specific midpoint tables anchored on max HR.
    # IF = (zone midpoint % of max HR) / (LTHR % of max HR).
    # Default LTHR ≈ 80% of max HR when lthr is not explicitly provided.
    if step.target.type == TargetType.HR_ZONE and step.target.zone and max_hr:
        midpoints = BIKE_HR_ZONE_MIDPOINTS_PCT if is_bike(sport) else RUN_HR_ZONE_MIDPOINTS_PCT
        midpoint_pct = midpoints.get(step.target.zone, 0.70)
        lthr_pct_of_max = (lthr / max_hr) if lthr else 0.80
        intensity_factor = midpoint_pct / lthr_pct_of_max
        return hours * intensity_factor ** 2 * thr_hour

    if is_bike(sport) or (sport == Sport.BRICK and step.target.type != TargetType.PACE_ZONE):
        if step.target.type == TargetType.POWER_ZONE and step.target.zone:
            # Mid-point watts per zone (6-zone model)
            zone_midpoints = {1: 0.45, 2: 0.65, 3: 0.83, 4: 0.98, 5: 1.13, 6: 1.30}
            intensity_factor = zone_midpoints.get(step.target.zone, 0.65)
        elif step.target.type == TargetType.POWER_PERCENT_FTP and step.target.pct_of_anchor:
            intensity_factor = step.target.pct_of_anchor
        else:
            intensity_factor = 0.60  # default: easy
        return hours * intensity_factor ** 2 * thr_hour

    if sport == Sport.RUN or (sport == Sport.BRICK and step.target.type == TargetType.PACE_ZONE):
        if step.target.type == TargetType.PACE_ZONE and step.target.zone:
            zone_pace_ratios = {1: 1.40, 2: 1.27, 3: 1.13, 4: 1.03, 5: 0.95}
            pace_ratio = zone_pace_ratios.get(step.target.zone, 1.30)
        else:
            pace_ratio = 1.30
        intensity_factor = 1.0 / pace_ratio
        return hours * intensity_factor ** 2 * thr_hour

    if sport == Sport.SWIM:
        if step.target.type == TargetType.PACE_ZONE and step.target.zone:
            zone_pace_ratios = {1: 1.35, 2: 1.22, 3: 1.12, 4: 1.04, 5: 0.95}
            pace_ratio = zone_pace_ratios.get(step.target.zone, 1.25)
        else:
            pace_ratio = 1.25
        intensity_factor = 1.0 / pace_ratio
        return hours * intensity_factor ** 2 * thr_hour

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
                total += item.elapsed_seconds
            else:
                total += item.total_duration_seconds
        return total

    def normalize(self, css_sec_per_100m: float) -> "Workout":
        """
        Re-derive swim step durations from their distances (swim is always
        distance-first; duration is an estimate used for TSS/total time).
        No-op for other sports.
        """
        if self.sport != Sport.SWIM or css_sec_per_100m <= 0:
            return self
        for item in self.steps:
            steps = [item] if isinstance(item, WorkoutStep) else item.steps
            for s in steps:
                if s.distance_meters:
                    s.duration_seconds = estimate_swim_seconds(
                        s.distance_meters, s.target.zone, css_sec_per_100m,
                        equipment=s.equipment, stroke=s.stroke,
                    )
        return self

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


# ── validation (per-sport intensity + end-condition rules) ────────────────────

# Which intensity target types each sport may use.
SPORT_ALLOWED_TARGETS: dict[Sport, set[TargetType]] = {
    Sport.SWIM: {TargetType.PACE_ZONE, TargetType.OPEN},
    Sport.RUN: {TargetType.PACE_ZONE, TargetType.HR_ZONE, TargetType.OPEN},
    Sport.BIKE_OUTDOOR: {
        TargetType.POWER_ZONE, TargetType.POWER_PERCENT_FTP, TargetType.HR_ZONE, TargetType.OPEN,
    },
    Sport.BIKE_INDOOR: {
        TargetType.POWER_ZONE, TargetType.POWER_PERCENT_FTP, TargetType.HR_ZONE, TargetType.OPEN,
    },
    Sport.BRICK: {
        TargetType.POWER_ZONE, TargetType.POWER_PERCENT_FTP, TargetType.PACE_ZONE,
        TargetType.HR_ZONE, TargetType.OPEN,
    },
    Sport.STRENGTH: {TargetType.OPEN},
}

# Sports whose steps must be time-based only (no distance end condition).
TIME_ONLY_SPORTS = {Sport.BIKE_INDOOR, Sport.BIKE_OUTDOOR, Sport.STRENGTH}

_ZONE_MAX = {TargetType.POWER_ZONE: 6, TargetType.HR_ZONE: 5, TargetType.PACE_ZONE: 5}


def validate_step(sport: Sport, step: WorkoutStep) -> None:
    """Raise ValueError if a step's intensity/end-condition is invalid for the sport."""
    t = step.target
    allowed = SPORT_ALLOWED_TARGETS.get(sport, {TargetType.OPEN})
    if t.type not in allowed:
        nice = ", ".join(sorted(a.value for a in allowed))
        raise ValueError(f"{sport.value} steps can't use intensity '{t.type.value}' (allowed: {nice}).")

    if t.type in _ZONE_MAX:
        hi = _ZONE_MAX[t.type]
        if t.zone is None or not (1 <= t.zone <= hi):
            raise ValueError(f"{t.type.value} zone must be between 1 and {hi} (got {t.zone}).")

    if t.type == TargetType.POWER_PERCENT_FTP:
        if t.pct_of_anchor is None or not (0.30 <= t.pct_of_anchor <= 2.00):
            raise ValueError("power %FTP must be between 30% and 200%.")

    if step.distance_meters is not None:
        if sport in TIME_ONLY_SPORTS:
            raise ValueError(f"{sport.value} steps must be time-based — distance targets aren't allowed.")
        if step.distance_meters <= 0:
            raise ValueError("step distance must be positive.")

    # Swimming is always distance-based (pool workouts count metres, not minutes).
    if sport == Sport.SWIM and not step.distance_meters:
        raise ValueError("swim steps must have a distance in metres.")

    if step.rest_seconds < 0 or step.rest_seconds > 600:
        raise ValueError("step rest must be between 0 and 600 seconds.")

    if (step.equipment or step.stroke) and sport != Sport.SWIM:
        raise ValueError("equipment/stroke options only apply to swim steps.")

    # Swim durations are derived from distance (Workout.normalize), so a
    # zero duration is fine there; everything else needs explicit time.
    if sport != Sport.SWIM and (step.duration_seconds is None or step.duration_seconds <= 0):
        raise ValueError("every step needs a positive duration.")


def validate_workout(workout: Workout) -> None:
    """Validate a full workout's structure and per-step targets. Raises ValueError."""
    if not workout.steps:
        raise ValueError("A workout needs at least one block.")
    for item in workout.steps:
        if isinstance(item, WorkoutStep):
            validate_step(workout.sport, item)
        else:  # RepeatBlock
            if item.repeat_count < 1:
                raise ValueError("interval repeat count must be at least 1.")
            if not item.steps:
                raise ValueError("an interval block needs at least one step.")
            for sub in item.steps:
                validate_step(workout.sport, sub)
