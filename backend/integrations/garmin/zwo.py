"""
Convert an indoor-cycling Workout (Sport.BIKE_INDOOR) into a .zwo file for
Rouvy / Zwift. Those platforms accept .zwo (not the .fit Garmin produces), so
indoor rides are exported here instead of being pushed to Garmin.

ZWO power values are fractions of FTP (e.g. 0.98 = 98% FTP). See
[[workout-export-design]].
"""
from __future__ import annotations
from xml.etree import ElementTree as ET
from xml.dom import minidom

from domain.workout import Workout, WorkoutStep, RepeatBlock, Sport, TargetType

# Power as fraction of FTP per power zone (midpoint of each zone band)
_ZONE_POWER = {1: 0.45, 2: 0.65, 3: 0.83, 4: 0.98, 5: 1.13, 6: 1.30}

_WARMUP_LOW = 0.45
_COOLDOWN_LOW = 0.35


def _power_fraction(step: WorkoutStep) -> float:
    t = step.target
    if t.type == TargetType.POWER_ZONE and t.zone:
        return _ZONE_POWER.get(t.zone, 0.65)
    if t.type == TargetType.POWER_PERCENT_FTP and t.pct_of_anchor:
        return round(t.pct_of_anchor, 3)
    return 0.55  # easy default for HR/open steps on the trainer


def _is_warmup(step: WorkoutStep) -> bool:
    return "warm" in step.name.lower()


def _is_cooldown(step: WorkoutStep) -> bool:
    return "cool" in step.name.lower()


def workout_to_zwo(workout: Workout, author: str = "Triathlon Training Dashboard") -> str:
    """Render the workout as a ZWO XML string."""
    if workout.sport != Sport.BIKE_INDOOR:
        raise ValueError("ZWO export is only for Sport.BIKE_INDOOR workouts.")

    root = ET.Element("workout_file")
    ET.SubElement(root, "author").text = author
    ET.SubElement(root, "name").text = workout.title
    ET.SubElement(root, "description").text = workout.description or workout.title
    ET.SubElement(root, "sportType").text = "bike"
    wk = ET.SubElement(root, "workout")

    for item in workout.steps:
        if isinstance(item, WorkoutStep):
            _render_single(wk, item)
        else:
            _render_repeat(wk, item)

    raw = ET.tostring(root, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")


def _render_single(wk: ET.Element, step: WorkoutStep) -> None:
    power = _power_fraction(step)
    dur = str(step.duration_seconds)

    if _is_warmup(step):
        ET.SubElement(wk, "Warmup", Duration=dur,
                      PowerLow=str(_WARMUP_LOW), PowerHigh=str(power))
    elif _is_cooldown(step):
        ET.SubElement(wk, "Cooldown", Duration=dur,
                      PowerLow=str(power), PowerHigh=str(_COOLDOWN_LOW))
    else:
        ET.SubElement(wk, "SteadyState", Duration=dur, Power=str(power))


def _render_repeat(wk: ET.Element, block: RepeatBlock) -> None:
    # The common case — a work step + a recovery step — maps cleanly to IntervalsT.
    if len(block.steps) == 2:
        work, recover = block.steps
        ET.SubElement(
            wk, "IntervalsT",
            Repeat=str(block.repeat_count),
            OnDuration=str(work.duration_seconds),
            OffDuration=str(recover.duration_seconds),
            OnPower=str(_power_fraction(work)),
            OffPower=str(_power_fraction(recover)),
        )
    else:
        # Fallback: expand the block into repeated SteadyState segments.
        for _ in range(block.repeat_count):
            for step in block.steps:
                ET.SubElement(wk, "SteadyState",
                              Duration=str(step.duration_seconds),
                              Power=str(_power_fraction(step)))


def zwo_filename(workout: Workout) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in workout.title)
    return f"{workout.scheduled_date.isoformat()}_{safe}.zwo"
