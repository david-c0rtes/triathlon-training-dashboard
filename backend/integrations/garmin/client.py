from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, timedelta

from integrations.garmin.auth import get_client


@dataclass
class GarminActivity:
    id: int
    name: str
    sport: str                       # "bike"|"run"|"swim"|"multi"|"strength"|"cardio"|"other"
    start_date: datetime
    duration: float                  # seconds (moving time preferred)
    distance: float                  # meters
    average_speed: float             # m/s
    average_hr: float | None
    average_power: float | None      # bike: avg power
    normalized_power: float | None   # bike: normalized power (NP)
    has_power: bool                  # True = real power meter data present
    garmin_tss: float | None         # Garmin-computed TSS if available


def _map_sport(type_key: str) -> str:
    t = (type_key or "").lower()
    if "swim" in t:
        return "swim"
    if "run" in t or "treadmill" in t:
        return "run"
    if "cycl" in t or "bik" in t or "ride" in t:
        return "bike"
    if "multi_sport" in t or "triathlon" in t or "duathlon" in t:
        return "multi"
    if "strength" in t or "weight" in t:
        return "strength"
    if "row" in t or "elliptic" in t or "cardio" in t or "aerobic" in t:
        return "cardio"
    return "other"


def _to_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse(raw: dict) -> GarminActivity:
    type_key = (raw.get("activityType") or {}).get("typeKey", "")
    start_str = raw.get("startTimeLocal") or raw.get("startTimeGMT", "")
    start_date = datetime.fromisoformat(start_str) if start_str else datetime.min

    norm_power = _to_float(raw.get("normPower"))
    avg_power = _to_float(raw.get("avgPower") or raw.get("averagePower"))

    # Garmin sometimes reports moving duration separately from elapsed
    duration = _to_float(raw.get("movingDuration")) or _to_float(raw.get("duration")) or 0.0

    return GarminActivity(
        id=raw.get("activityId", 0),
        name=raw.get("activityName", ""),
        sport=_map_sport(type_key),
        start_date=start_date,
        duration=duration,
        distance=_to_float(raw.get("distance")) or 0.0,
        average_speed=_to_float(raw.get("averageSpeed")) or 0.0,
        average_hr=_to_float(raw.get("averageHR")),
        average_power=avg_power,
        normalized_power=norm_power,
        has_power=norm_power is not None or avg_power is not None,
        garmin_tss=_to_float(raw.get("trainingStressScore")),
    )


def fetch_activities(days: int = 90) -> list[GarminActivity]:
    """
    Pull the athlete's activities for the past `days` days from Garmin Connect.
    Returns only bike, run, and swim activities, sorted oldest → newest.
    """
    client = get_client()
    end = date.today()
    start = end - timedelta(days=days)

    raw_activities = client.get_activities_by_date(
        start.isoformat(), end.isoformat()
    )

    activities = [_parse(raw) for raw in raw_activities]
    return sorted(activities, key=lambda a: a.start_date)


# Sanity bounds used only to flag obviously-corrupt Garmin data (seen in
# practice: a stale threshold-pace value that decoded to ~42 min/km). A field
# outside its bounds is still returned, just marked implausible so the caller
# doesn't offer it as a one-click "use this".
_FTP_BOUNDS = (60.0, 500.0)          # watts
_LTHR_BOUNDS = (100.0, 220.0)        # bpm
_RUN_PACE_BOUNDS = (150.0, 600.0)    # sec/km: 2:30/km .. 10:00/km


def _in_bounds(value: float | None, bounds: tuple[float, float]) -> bool:
    return value is not None and bounds[0] <= value <= bounds[1]


def fetch_max_metrics() -> dict:
    """
    Garmin's own best-known bike FTP and running LTHR/threshold-pace (+ VO2max
    running for context). Read-only: never writes to Garmin or the local
    profile — the caller decides what, if anything, to do with the result.
    """
    client = get_client()

    ftp_watts = ftp_source = ftp_date = None
    try:
        raw = client.get_cycling_ftp()
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        ftp_watts = _to_float(raw.get("functionalThresholdPower"))
        ftp_source = raw.get("biometricSourceType")
        ftp_date = (raw.get("calendarDate") or "")[:10] or None
    except Exception:
        pass

    run_lthr = run_pace_sec_per_km = None
    try:
        lt = client.get_lactate_threshold(latest=True)
        shr = lt.get("speed_and_heart_rate", {})
        run_lthr = _to_float(shr.get("heartRate"))
        speed = _to_float(shr.get("speed"))
        if speed:
            run_pace_sec_per_km = 1000.0 / speed
    except Exception:
        pass

    lthr_auto_detected = vo2max_running = None
    try:
        user_data = client.get_user_profile().get("userData", {})
        lthr_auto_detected = user_data.get("thresholdHeartRateAutoDetected")
        vo2max_running = _to_float(user_data.get("vo2MaxRunning"))
    except Exception:
        pass

    return {
        "ftp_watts": round(ftp_watts) if ftp_watts is not None else None,
        "ftp_source": ftp_source,
        "ftp_date": ftp_date,
        "ftp_plausible": _in_bounds(ftp_watts, _FTP_BOUNDS),

        "run_lthr": round(run_lthr) if run_lthr is not None else None,
        "run_lthr_auto_detected": lthr_auto_detected,
        "run_lthr_plausible": _in_bounds(run_lthr, _LTHR_BOUNDS),

        "run_threshold_pace_sec_per_km": round(run_pace_sec_per_km, 1) if run_pace_sec_per_km is not None else None,
        "run_pace_plausible": _in_bounds(run_pace_sec_per_km, _RUN_PACE_BOUNDS),

        "vo2max_running": vo2max_running,
    }
