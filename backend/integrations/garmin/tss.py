from __future__ import annotations
from integrations.garmin.client import GarminActivity
from domain.athlete import Thresholds


def activity_tss(activity: GarminActivity, thresholds: Thresholds) -> float:
    """
    Estimate Training Stress Score for a completed Garmin activity.

    If Garmin already computed a TSS for the activity, trust it. Otherwise
    estimate per sport:
      Bike: NP → avg power → HR → moderate-effort fallback
      Run:  pace (rTSS) → HR fallback
      Swim: pace (sTSS) → HR fallback
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
    if activity.sport == "multi":
        # Multi-sport (triathlon/duathlon): use Garmin TSS or HR, defaulting to threshold-level effort
        return _hr_tss(activity, thresholds, hours, default_if=0.90)
    if activity.sport == "strength":
        # Strength training: causes fatigue but not aerobic stress.
        # HR-based if available; otherwise ~40 TSS/hr (moderate session estimate).
        return _hr_tss(activity, thresholds, hours, default_if=0.60)
    if activity.sport == "cardio":
        # Indoor rowing, elliptical etc: aerobic, similar to easy run effort.
        return _hr_tss(activity, thresholds, hours, default_if=0.65)
    # Other (volleyball, recreational): low-moderate effort
    return _hr_tss(activity, thresholds, hours, default_if=0.50)


def _hr_tss(activity: GarminActivity, thresholds: Thresholds, hours: float, default_if: float) -> float:
    if activity.average_hr and thresholds.run_lthr:
        intensity_factor = activity.average_hr / thresholds.run_lthr
        return hours * intensity_factor ** 2 * 100
    return hours * default_if ** 2 * 100


# ── bike ─────────────────────────────────────────────────────────────────────

def _bike_tss(activity: GarminActivity, thresholds: Thresholds, hours: float) -> float:
    ftp = thresholds.ftp_watts

    if activity.normalized_power:
        intensity_factor = activity.normalized_power / ftp
        return hours * intensity_factor ** 2 * 100

    if activity.average_power:
        intensity_factor = activity.average_power / ftp
        return hours * intensity_factor ** 2 * 100

    return _hr_tss(activity, thresholds, hours, default_if=0.65)


# ── run ──────────────────────────────────────────────────────────────────────

def _run_tss(activity: GarminActivity, thresholds: Thresholds, hours: float) -> float:
    threshold_pace = thresholds.run_threshold_pace_sec_per_km  # sec/km

    if activity.distance > 0:
        actual_pace = activity.duration / (activity.distance / 1000.0)  # sec/km
        intensity_factor = threshold_pace / actual_pace
        return hours * intensity_factor ** 2 * 100

    return _hr_tss(activity, thresholds, hours, default_if=0.65)


# ── swim ─────────────────────────────────────────────────────────────────────

def _swim_tss(activity: GarminActivity, thresholds: Thresholds, hours: float) -> float:
    css = thresholds.swim_css_sec_per_100m  # sec/100m

    if activity.distance > 0:
        actual_pace = activity.duration / (activity.distance / 100.0)  # sec/100m
        intensity_factor = css / actual_pace
        return hours * intensity_factor ** 2 * 100

    return _hr_tss(activity, thresholds, hours, default_if=0.55)
