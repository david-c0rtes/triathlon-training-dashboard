from __future__ import annotations
import math
from collections import defaultdict
from datetime import date, timedelta

from domain.athlete import Fitness

# Exponential decay constants for the Performance Management Chart
_CTL_DECAY = 1 - math.exp(-1 / 42)   # 42-day time constant (fitness / chronic)
_ATL_DECAY = 1 - math.exp(-1 / 7)    # 7-day time constant  (fatigue / acute)


def compute_fitness(daily_tss: dict[date, float], end_date: date | None = None) -> Fitness:
    """
    Walk `daily_tss` chronologically and compute CTL/ATL using the standard
    exponential weighted average (Performance Management Chart model).

    Args:
        daily_tss: mapping of date → TSS for that day (missing dates = 0 TSS).
        end_date:  the date to read final CTL/ATL from (defaults to today).

    Returns:
        Fitness with ctl, atl, and tsb (= ctl - atl).
    """
    if not daily_tss:
        return Fitness()

    end_date = end_date or date.today()
    start_date = min(daily_tss.keys())

    ctl = 0.0
    atl = 0.0
    current = start_date

    while current <= end_date:
        tss = daily_tss.get(current, 0.0)
        ctl += (tss - ctl) * _CTL_DECAY
        atl += (tss - atl) * _ATL_DECAY
        current += timedelta(days=1)

    return Fitness(ctl=round(ctl, 1), atl=round(atl, 1))


def compute_fitness_series(daily_tss: dict[date, float], end_date: date | None = None) -> list[dict]:
    """
    Like compute_fitness, but emits the full daily CTL/ATL/TSB series for charting.
    Returns one entry per day from the first activity date through end_date.
    """
    if not daily_tss:
        return []

    end_date = end_date or date.today()
    start_date = min(daily_tss.keys())

    ctl = 0.0
    atl = 0.0
    series: list[dict] = []
    current = start_date
    while current <= end_date:
        tss = daily_tss.get(current, 0.0)
        ctl += (tss - ctl) * _CTL_DECAY
        atl += (tss - atl) * _ATL_DECAY
        series.append({
            "date": current.isoformat(),
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": round(ctl - atl, 1),
        })
        current += timedelta(days=1)
    return series


def advance_fitness(ctl: float, atl: float, daily_tss_values: list[float]) -> Fitness:
    """
    Roll CTL/ATL forward through a sequence of daily TSS values (forward
    simulation for multi-week planning). Each day applies the same exponential
    decay used by compute_fitness.
    """
    for tss in daily_tss_values:
        ctl += (tss - ctl) * _CTL_DECAY
        atl += (tss - atl) * _ATL_DECAY
    return Fitness(ctl=round(ctl, 1), atl=round(atl, 1))


def activities_to_daily_tss(
    activities: list,   # list[GarminActivity] — typed loosely to avoid circular import
    thresholds,         # Thresholds
) -> dict[date, float]:
    """
    Convert a list of Garmin activities into a per-day TSS map.
    Multiple activities on the same day are summed.
    """
    from integrations.garmin.tss import activity_tss

    daily: dict[date, float] = defaultdict(float)
    for activity in activities:
        day = activity.start_date.date()
        daily[day] += activity_tss(activity, thresholds)

    return dict(daily)
