"""
Convert our domain Workout into a Garmin Connect structured workout and push it.

Garmin step targets carry the actual value range in `targetValueOne/Two`
(extra fields the workout model permits). We compute those ranges from the
athlete's thresholds rather than relying on Garmin-side zone numbers, so the
target shown on the watch matches exactly what the planner intended.

Per sport (see [[workout-export-design]]):
  Cycling: power primary (watts) + heart-rate secondary.
  Running: pace primary (speed m/s, from min/km).
  Swimming: pace primary (speed m/s, from per-100m).
"""
from __future__ import annotations
from datetime import date

from garminconnect.workout import (
    CyclingWorkout, RunningWorkout, SwimmingWorkout,
    WorkoutSegment, ExecutableStep, RepeatGroup,
    StepType, ConditionType, TargetType as GTarget, SportType,
)

from domain.workout import (
    Workout, WorkoutStep, RepeatBlock, Sport, TargetType, is_bike,
)
from domain.athlete import Thresholds
from integrations.garmin.auth import get_client


# ── zone → value tables (self-contained; consistent with the planner intent) ──
# Bike power as % of FTP (6 zones)
_BIKE_POWER_PCT = {
    1: (0.40, 0.55), 2: (0.55, 0.75), 3: (0.75, 0.90),
    4: (0.90, 1.05), 5: (1.05, 1.20), 6: (1.20, 1.50),
}
# HR as % of max HR
_BIKE_HR_PCT = {1: (0.48, 0.61), 2: (0.62, 0.73), 3: (0.74, 0.82), 4: (0.83, 0.89), 5: (0.90, 1.00)}
_RUN_HR_PCT  = {1: (0.56, 0.67), 2: (0.68, 0.77), 3: (0.78, 0.85), 4: (0.86, 0.91), 5: (0.92, 1.00)}
# Pace as multiplier of threshold pace (sec/km for run, sec/100m for swim).
# Larger multiplier = slower = easier. (slow_bound, fast_bound)
_RUN_PACE_MULT  = {1: (1.50, 1.29), 2: (1.29, 1.14), 3: (1.14, 1.06), 4: (1.06, 1.00), 5: (1.00, 0.90)}
_SWIM_PACE_MULT = {1: (1.45, 1.29), 2: (1.29, 1.16), 3: (1.16, 1.08), 4: (1.08, 1.00), 5: (1.00, 0.90)}

# Map a bike power zone (1-6) to a corresponding HR zone (1-5) for the secondary target
_POWER_TO_HR_ZONE = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 5}

_TIME_END = {
    "conditionTypeId": ConditionType.TIME,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}
# NOTE: garminconnect's ConditionType.DISTANCE (=1) is wrong — in Garmin's API
# condition 1 is "lap.button" and distance is 3. Hardcode the correct value.
_DISTANCE_END = {
    "conditionTypeId": 3,
    "conditionTypeKey": "distance",
    "displayOrder": 3,
    "displayable": True,
}
_KM_UNIT = {"unitKey": "kilometer"}
_NO_TARGET = {
    "workoutTargetTypeId": GTarget.NO_TARGET,
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}
_POWER_TT = {"workoutTargetTypeId": GTarget.POWER, "workoutTargetTypeKey": "power.zone", "displayOrder": 1}
_HR_TT = {"workoutTargetTypeId": GTarget.HEART_RATE, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 1}
_SPEED_TT = {"workoutTargetTypeId": GTarget.SPEED, "workoutTargetTypeKey": "speed.zone", "displayOrder": 1}
# Pace target — Garmin stores the same m/s value but displays it as min/km (id 6).
_PACE_TT = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}


def _step_type_for(name: str) -> tuple[int, str, int]:
    n = name.lower()
    if "warm" in n:
        return (StepType.WARMUP, "warmup", 1)
    if "cool" in n:
        return (StepType.COOLDOWN, "cooldown", 2)
    if "recover" in n or "rest" in n or "jog" in n:
        return (StepType.RECOVERY, "recovery", 4)
    return (StepType.INTERVAL, "interval", 3)


def _pace_to_speed(pace_sec: float, distance_m: float) -> float:
    """Convert a pace (sec per distance_m) to speed in m/s."""
    return distance_m / pace_sec if pace_sec > 0 else 0.0


def _target_fields(sport: Sport, step: WorkoutStep, thr: Thresholds) -> dict:
    """Return the targetType + value fields (and secondary target) for a step."""
    t = step.target
    fields: dict = {"targetType": dict(_NO_TARGET)}

    if t.type == TargetType.OPEN:
        return fields

    if is_bike(sport):
        # Primary: power
        if t.type == TargetType.POWER_ZONE and t.zone:
            lo_pct, hi_pct = _BIKE_POWER_PCT.get(t.zone, (0.55, 0.75))
            lo, hi = thr.ftp_watts * lo_pct, thr.ftp_watts * hi_pct
        elif t.type == TargetType.POWER_PERCENT_FTP and t.pct_of_anchor:
            center = thr.ftp_watts * t.pct_of_anchor
            lo, hi = center * 0.97, center * 1.03
        elif t.type == TargetType.HR_ZONE and t.zone:
            return _hr_only(sport, t.zone, thr)
        else:
            return fields
        fields["targetType"] = dict(_POWER_TT)
        fields["targetValueOne"] = round(lo)
        fields["targetValueTwo"] = round(hi)
        # Secondary: heart rate, derived from the power zone
        if thr.max_hr and t.type == TargetType.POWER_ZONE and t.zone:
            hr_zone = _POWER_TO_HR_ZONE.get(t.zone, 3)
            hlo, hhi = _BIKE_HR_PCT[hr_zone]
            fields["secondaryTargetType"] = dict(_HR_TT)
            fields["secondaryTargetValueOne"] = round(thr.max_hr * hlo)
            fields["secondaryTargetValueTwo"] = round(thr.max_hr * hhi)
        return fields

    if sport == Sport.RUN:
        if t.type == TargetType.PACE_ZONE and t.zone:
            slow_m, fast_m = _RUN_PACE_MULT.get(t.zone, (1.29, 1.14))
            slow_pace = thr.run_threshold_pace_sec_per_km * slow_m
            fast_pace = thr.run_threshold_pace_sec_per_km * fast_m
            # pace.zone so the watch shows min/km; values are still m/s
            fields["targetType"] = dict(_PACE_TT)
            fields["targetValueOne"] = round(_pace_to_speed(slow_pace, 1000), 3)
            fields["targetValueTwo"] = round(_pace_to_speed(fast_pace, 1000), 3)
            return fields
        if t.type == TargetType.HR_ZONE and t.zone:
            return _hr_only(sport, t.zone, thr)
        return fields

    if sport == Sport.SWIM:
        if t.type == TargetType.PACE_ZONE and t.zone:
            slow_m, fast_m = _SWIM_PACE_MULT.get(t.zone, (1.16, 1.08))
            slow_pace = thr.swim_css_sec_per_100m * slow_m
            fast_pace = thr.swim_css_sec_per_100m * fast_m
            fields["targetType"] = dict(_SPEED_TT)
            fields["targetValueOne"] = round(_pace_to_speed(slow_pace, 100), 3)
            fields["targetValueTwo"] = round(_pace_to_speed(fast_pace, 100), 3)
            return fields
        return fields

    return fields


def _hr_only(sport: Sport, zone: int, thr: Thresholds) -> dict:
    fields: dict = {"targetType": dict(_NO_TARGET)}
    if not thr.max_hr:
        return fields
    table = _BIKE_HR_PCT if is_bike(sport) else _RUN_HR_PCT
    lo, hi = table.get(zone, (0.70, 0.80))
    fields["targetType"] = dict(_HR_TT)
    fields["targetValueOne"] = round(thr.max_hr * lo)
    fields["targetValueTwo"] = round(thr.max_hr * hi)
    return fields


def _executable(sport: Sport, step: WorkoutStep, thr: Thresholds, order: int) -> ExecutableStep:
    type_id, type_key, display = _step_type_for(step.name)
    extra: dict = {}
    if step.distance_meters:
        end_condition, end_value = dict(_DISTANCE_END), float(step.distance_meters)
        extra["preferredEndConditionUnit"] = dict(_KM_UNIT)
    else:
        end_condition, end_value = dict(_TIME_END), float(step.duration_seconds)
    return ExecutableStep(
        stepOrder=order,
        stepType={"stepTypeId": type_id, "stepTypeKey": type_key, "displayOrder": display},
        endCondition=end_condition,
        endConditionValue=end_value,
        description=step.name,
        **_target_fields(sport, step, thr),
        **extra,
    )


def build_segment_steps(workout: Workout, thr: Thresholds) -> list:
    """Flatten the domain steps/repeats into Garmin ExecutableStep / RepeatGroup."""
    out: list = []
    order = 1
    for item in workout.steps:
        if isinstance(item, WorkoutStep):
            out.append(_executable(workout.sport, item, thr, order))
            order += 1
        else:  # RepeatBlock
            inner = []
            for sub in item.steps:
                inner.append(_executable(workout.sport, sub, thr, order))
                order += 1
            from garminconnect.workout import create_repeat_group
            out.append(create_repeat_group(item.repeat_count, inner, order))
            order += 1
    return out


def _sport_meta(sport: Sport):
    if is_bike(sport):
        return CyclingWorkout, {"sportTypeId": SportType.CYCLING, "sportTypeKey": "cycling"}
    if sport == Sport.RUN:
        return RunningWorkout, {"sportTypeId": SportType.RUNNING, "sportTypeKey": "running"}
    if sport == Sport.SWIM:
        return SwimmingWorkout, {"sportTypeId": SportType.SWIMMING, "sportTypeKey": "swimming"}
    raise ValueError(f"Sport {sport} cannot be pushed to Garmin (brick/multisport not supported yet).")


def build_garmin_workout(workout: Workout, thr: Thresholds):
    """Return a typed garminconnect workout object ready for upload."""
    workout_cls, sport_type = _sport_meta(workout.sport)
    steps = build_segment_steps(workout, thr)
    segment = WorkoutSegment(segmentOrder=1, sportType=sport_type, workoutSteps=steps)
    return workout_cls(
        workoutName=workout.title,
        sportType=sport_type,
        estimatedDurationInSecs=workout.total_duration_seconds,
        description=workout.description or "",
        workoutSegments=[segment],
    )


def push_workout(workout: Workout, thr: Thresholds, target_date: date | None = None) -> dict:
    """
    Upload the workout to Garmin Connect and schedule it on `target_date`
    (defaults to the workout's own scheduled_date).
    """
    garmin_workout = build_garmin_workout(workout, thr)
    client = get_client()
    uploaded = client.upload_workout(garmin_workout.to_dict())

    workout_id = uploaded.get("workoutId") or uploaded.get("workout", {}).get("workoutId")
    schedule_date = (target_date or workout.scheduled_date).isoformat()
    scheduled = client.schedule_workout(workout_id, schedule_date) if workout_id else {}

    return {
        "workout_id": workout_id,
        "scheduled_date": schedule_date,
        "title": workout.title,
        "schedule_response": scheduled,
    }
