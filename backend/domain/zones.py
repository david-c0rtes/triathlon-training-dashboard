from __future__ import annotations
from dataclasses import dataclass
from domain.athlete import Thresholds


@dataclass(frozen=True)
class Zone:
    number: int
    name: str
    low: float   # inclusive lower bound (watts, sec/km, bpm, or sec/100m)
    high: float  # exclusive upper bound (use float("inf") for the top zone)


def _build_zones(boundaries: list[float], names: list[str], unit_is_pace: bool = False) -> list[Zone]:
    """
    Build Zone objects from a list of N+1 boundary values for N zones.
    For pace-based zones (run/swim), lower bound = slower = easier, so the
    list goes from fast→slow and we reverse the inequality semantics via
    unit_is_pace (just stored as-is; callers interpret direction).
    """
    zones = []
    for i, name in enumerate(names):
        zones.append(Zone(
            number=i + 1,
            name=name,
            low=boundaries[i],
            high=boundaries[i + 1],
        ))
    return zones


def bike_power_zones(ftp: int) -> list[Zone]:
    """
    6-zone power model anchored on FTP.
    Zone boundaries as % of FTP: <55 / 56-75 / 76-90 / 91-105 / 106-120 / >120
    """
    names = [
        "Z1 Active Recovery",
        "Z2 Endurance",
        "Z3 Tempo",
        "Z4 Threshold",
        "Z5 VO2 Max",
        "Z6 Anaerobic",
    ]
    pcts = [0.0, 0.55, 0.75, 0.90, 1.05, 1.20, float("inf")]
    boundaries = [ftp * p for p in pcts]
    return _build_zones(boundaries, names)


# HR zone boundaries as % of max HR — bike and run differ.
# Low bound of Z1 is the lowest value in that zone's range.
BIKE_HR_ZONE_PCTS = [0.48, 0.62, 0.74, 0.83, 0.90, 1.01]  # 6 boundaries for 5 zones
RUN_HR_ZONE_PCTS  = [0.56, 0.68, 0.78, 0.86, 0.92, 1.01]

_HR_ZONE_NAMES = ["Z1 Recovery", "Z2 Aerobic", "Z3 Tempo", "Z4 Threshold", "Z5 VO2 Max"]


def bike_hr_zones(max_hr: int) -> list[Zone]:
    """5-zone bike HR model anchored on max HR. Boundaries: 48/62/74/83/90/100%."""
    boundaries = [max_hr * p for p in BIKE_HR_ZONE_PCTS]
    boundaries[-1] = float("inf")
    return _build_zones(boundaries, _HR_ZONE_NAMES)


def run_hr_zones(max_hr: int) -> list[Zone]:
    """5-zone run HR model anchored on max HR. Boundaries: 56/68/78/86/92/100%."""
    boundaries = [max_hr * p for p in RUN_HR_ZONE_PCTS]
    boundaries[-1] = float("inf")
    return _build_zones(boundaries, _HR_ZONE_NAMES)


def run_pace_zones(threshold_sec_per_km: float) -> list[Zone]:
    """
    5-zone run pace model anchored on threshold pace.
    Zones are expressed in sec/km — higher value = slower pace.
    Boundary multipliers (pace ratios relative to threshold):
      Z1 >135% / Z2 120-135% / Z3 107-120% / Z4 100-107% / Z5 <100%
    NOTE: low < high means faster (lower sec/km), opposite to power zones.
    """
    names = [
        "Z1 Recovery",
        "Z2 Aerobic",
        "Z3 Tempo",
        "Z4 Threshold",
        "Z5 Speed",
    ]
    # Boundaries sorted slow→fast (descending sec/km) then reversed for Zone model convention
    pcts = [float("inf"), 1.35, 1.20, 1.07, 1.00, 0.90]
    boundaries = [threshold_sec_per_km * p if p != float("inf") else float("inf") for p in pcts]
    # Flip so low=fast, high=slow (consistent with Zone.low < Zone.high meaning easier to interpret)
    boundaries_asc = list(reversed(boundaries))
    return _build_zones(boundaries_asc, names, unit_is_pace=True)


def swim_css_zones(css_sec_per_100m: float) -> list[Zone]:
    """
    5-zone swim model anchored on CSS (Critical Swim Speed).
    Expressed in sec/100m — higher = slower.
    Z1 >140% CSS / Z2 120-140% / Z3 108-120% / Z4 100-108% / Z5 <100%
    """
    names = [
        "Z1 Recovery",
        "Z2 Aerobic",
        "Z3 Tempo",
        "Z4 Threshold",
        "Z5 Speed",
    ]
    pcts = [float("inf"), 1.40, 1.20, 1.08, 1.00, 0.90]
    boundaries = [css_sec_per_100m * p if p != float("inf") else float("inf") for p in pcts]
    boundaries_asc = list(reversed(boundaries))
    return _build_zones(boundaries_asc, names, unit_is_pace=True)


@dataclass
class AthleteZones:
    bike_power: list[Zone]
    bike_hr: list[Zone]
    run_hr: list[Zone]
    run_pace: list[Zone]
    swim_pace: list[Zone]


def compute_zones(thresholds: Thresholds) -> AthleteZones:
    if not thresholds.max_hr:
        raise ValueError("max_hr must be set to compute HR zones.")
    return AthleteZones(
        bike_power=bike_power_zones(thresholds.ftp_watts),
        bike_hr=bike_hr_zones(thresholds.max_hr),
        run_hr=run_hr_zones(thresholds.max_hr),
        run_pace=run_pace_zones(thresholds.run_threshold_pace_sec_per_km),
        swim_pace=swim_css_zones(thresholds.swim_css_sec_per_100m),
    )
