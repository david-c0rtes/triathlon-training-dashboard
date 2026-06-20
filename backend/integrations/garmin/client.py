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
