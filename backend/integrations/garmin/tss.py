from __future__ import annotations
from integrations.garmin.client import GarminActivity
from domain.athlete import Thresholds
from domain.training_load import THRESHOLD_HOUR_TSS, STRENGTH_TSS_PER_HOUR

# Threshold-hour TSS for sports outside the core three (rough estimates for CTL)
_MULTI_THRESHOLD_HOUR = 120
_CARDIO_THRESHOLD_HOUR = 100
_OTHER_THRESHOLD_HOUR = 80


def activity_tss(activity: GarminActivity, thresholds: Thresholds) -> float:
    """
    Estimate Training Stress Score for a completed Garmin activity.

    If Garmin already computed a TSS, trust it. Otherwise estimate per sport
    using the sport-weighted threshold-hour model:
      TSS = hours * IF**2 * threshold_hour_tss[sport]
    Strength is flat (no IF).
    """
    if activity.garmin_tss is not None:
        return activity.garmin_tss

    if activity.duration <= 0:
        return 0.0

    hours = activity.duration / 3600.0

    if activity.sport == "bike":
        return _bike_tss(activity, thresholds, hours)
    if activity.sport == "run":
        return _run_tss(activity, thresholds, hours)
    if activity.sport == "swim":
        return _swim_tss(activity, thresholds, hours)
    if activity.sport == "strength":
        return hours * STRENGTH_TSS_PER_HOUR  # flat, no intensity factor
    if activity.sport == "multi":
        return _hr_tss(activity, thresholds, hours, default_if=0.90, thr_hour=_MULTI_THRESHOLD_HOUR)
    if activity.sport == "cardio":
        return _hr_tss(activity, thresholds, hours, default_if=0.65, thr_hour=_CARDIO_THRESHOLD_HOUR)
    # Other (volleyball, padel, recreational): low-moderate effort
    return _hr_tss(activity, thresholds, hours, default_if=0.50, thr_hour=_OTHER_THRESHOLD_HOUR)


def _hr_tss(activity: GarminActivity, thresholds: Thresholds, hours: float,
            default_if: float, thr_hour: float) -> float:
    if activity.average_hr and thresholds.run_lthr:
        intensity_factor = activity.average_hr / thresholds.run_lthr
        return hours * intensity_factor ** 2 * thr_hour
    return hours * default_if ** 2 * thr_hour


def daily_tss_by_group(activities: list, thresholds: Thresholds) -> dict:
    """
    Per-day TSS broken down by discipline group for the TSS history bar chart.
    Returns {date_iso: {swim, bike, run, strength, other}}.
    """
    group_map = {"bike": "bike", "run": "run", "swim": "swim", "strength": "strength"}
    out: dict[str, dict[str, float]] = {}
    for a in activities:
        if a.duration <= 0:
            continue
        group = group_map.get(a.sport, "other")
        day = a.start_date.date().isoformat()
        bucket = out.setdefault(day, {"swim": 0.0, "bike": 0.0, "run": 0.0, "strength": 0.0, "other": 0.0})
        bucket[group] += activity_tss(a, thresholds)
    # round
    for day, bucket in out.items():
        for k in bucket:
            bucket[k] = round(bucket[k], 1)
    return out


def measured_tss_per_hour(activities: list, thresholds: Thresholds) -> dict[str, float]:
    """
    Compute the athlete's actual average TSS/hour per sport group over the given
    activities (the 90-day window). Returns only groups that have data, so the
    planner can fall back to defaults for the rest. Groups: swim/bike/run/strength.
    """
    group_map = {"bike": "bike", "run": "run", "swim": "swim", "strength": "strength"}
    totals: dict[str, list[float]] = {}  # group -> [tss_sum, hours_sum]
    for a in activities:
        group = group_map.get(a.sport)
        if group is None or a.duration <= 0:
            continue
        tss = activity_tss(a, thresholds)
        totals.setdefault(group, [0.0, 0.0])
        totals[group][0] += tss
        totals[group][1] += a.duration / 3600.0

    return {
        group: round(tss_sum / hours_sum, 1)
        for group, (tss_sum, hours_sum) in totals.items()
        if hours_sum > 0
    }


# ── bike (threshold-hour 100) ──────────────────────────────────────────────────

def _bike_tss(activity: GarminActivity, thresholds: Thresholds, hours: float) -> float:
    thr_hour = THRESHOLD_HOUR_TSS["bike"]
    ftp = thresholds.ftp_watts

    if activity.normalized_power:
        intensity_factor = activity.normalized_power / ftp
        return hours * intensity_factor ** 2 * thr_hour

    if activity.average_power:
        intensity_factor = activity.average_power / ftp
        return hours * intensity_factor ** 2 * thr_hour

    return _hr_tss(activity, thresholds, hours, default_if=0.65, thr_hour=thr_hour)


# ── run (threshold-hour 140) ───────────────────────────────────────────────────

def _run_tss(activity: GarminActivity, thresholds: Thresholds, hours: float) -> float:
    thr_hour = THRESHOLD_HOUR_TSS["run"]
    threshold_pace = thresholds.run_threshold_pace_sec_per_km  # sec/km

    if activity.distance > 0:
        actual_pace = activity.duration / (activity.distance / 1000.0)  # sec/km
        intensity_factor = threshold_pace / actual_pace
        return hours * intensity_factor ** 2 * thr_hour

    return _hr_tss(activity, thresholds, hours, default_if=0.65, thr_hour=thr_hour)


# ── swim (threshold-hour 60) ───────────────────────────────────────────────────

def _swim_tss(activity: GarminActivity, thresholds: Thresholds, hours: float) -> float:
    thr_hour = THRESHOLD_HOUR_TSS["swim"]
    css = thresholds.swim_css_sec_per_100m  # sec/100m

    if activity.distance > 0:
        actual_pace = activity.duration / (activity.distance / 100.0)  # sec/100m
        intensity_factor = css / actual_pace
        return hours * intensity_factor ** 2 * thr_hour

    return _hr_tss(activity, thresholds, hours, default_if=0.55, thr_hour=thr_hour)
