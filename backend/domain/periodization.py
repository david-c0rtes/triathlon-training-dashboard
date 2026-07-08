from __future__ import annotations
import random
from datetime import date, timedelta
from enum import Enum
from dataclasses import dataclass, field

from domain.athlete import AthleteProfile, Fitness, race_distances, Discipline
from domain.workout import (
    Sport, Target, TargetType, WorkoutStep, RepeatBlock, Workout, load_group
)
from domain import library
from domain.training_load import DEFAULT_TSS_PER_HOUR, STRENGTH_TSS_PER_HOUR
from domain.fitness import advance_fitness


class Phase(str, Enum):
    BASE = "Base"
    BUILD = "Build"
    PEAK = "Peak"
    TAPER = "Taper"
    RACE = "Race"


# The engine is tuned around a 70.3 (middle-distance) race. Every other
# distance is expressed as a ratio against these reference distances so
# phase windows and long-session durations scale with the actual race.
_REFERENCE_SWIM_M = 1900.0
_REFERENCE_BIKE_M = 90000.0
_REFERENCE_RUN_M = 21100.0


def race_size_ratio(profile: AthleteProfile) -> float:
    """
    How big this race is relative to a 70.3, averaged across whichever
    disciplines it actually includes (so duathlon/aquathlon/custom races
    still get a sensible ratio). >1 = longer than 70.3, <1 = shorter.
    """
    swim_m, bike_m, run_m = race_distances(profile.goals)
    ratios = []
    if swim_m: ratios.append(swim_m / _REFERENCE_SWIM_M)
    if bike_m: ratios.append(bike_m / _REFERENCE_BIKE_M)
    if run_m: ratios.append(run_m / _REFERENCE_RUN_M)
    return sum(ratios) / len(ratios) if ratios else 1.0


# Phase-window weeks scale with race distance: short races need a short,
# sharp build; very long races need a longer gradual build and taper.
# (max_ratio, {taper, peak, build} weeks) — first matching bucket wins.
_TIER_PHASE_WEEKS: list[tuple[float, dict[str, int]]] = [
    (0.35, {"taper": 1, "peak": 1, "build": 2}),          # sprint / supersprint
    (0.65, {"taper": 1, "peak": 2, "build": 3}),          # olympic
    (1.30, {"taper": 2, "peak": 2, "build": 4}),          # 70.3 / T100 (tuned baseline)
    (2.20, {"taper": 3, "peak": 3, "build": 6}),          # full IRONMAN
    (float("inf"), {"taper": 4, "peak": 4, "build": 8}),  # double IRONMAN+
]


def _phase_weeks_for_ratio(ratio: float) -> dict[str, int]:
    for max_ratio, weeks in _TIER_PHASE_WEEKS:
        if ratio <= max_ratio:
            return weeks
    return _TIER_PHASE_WEEKS[-1][1]


def get_phase(profile: AthleteProfile, today: date) -> Phase:
    weeks_out = (profile.goals.race_date - today).days / 7
    weeks = _phase_weeks_for_ratio(race_size_ratio(profile))
    taper_end = weeks["taper"]
    peak_end = taper_end + weeks["peak"]
    build_end = peak_end + weeks["build"]
    if weeks_out <= 0:
        return Phase.RACE
    if weeks_out <= taper_end:
        return Phase.TAPER
    if weeks_out <= peak_end:
        return Phase.PEAK
    if weeks_out <= build_end:
        return Phase.BUILD
    return Phase.BASE


# The CTL-anchored ramp already drives progression, so build phases sit at/above
# maintenance (>= 1.0). Sub-1.0 here would detrain. Peak carries the heaviest
# weekend-loaded volume (see _scale_group_to_target_weighted) before a sharp
# taper cuts fatigue ahead of race day.
PHASE_MODIFIERS = {
    Phase.BASE: 1.00,
    Phase.BUILD: 1.20,
    Phase.PEAK: 1.55,
    Phase.TAPER: 0.55,
}

# Within a Base/Build 3-week loading block, volume steps up each week
# (dose 0 -> 1 -> 2) before the block's 4th week resets via the recovery cut.
_DOSE_LOAD_MULTIPLIER = {0: 1.00, 1: 1.08, 2: 1.16}


def _ramp_for_weeks(weeks_to_race: float) -> float:
    """CTL ramp rate per week — steeper when the race is closer."""
    if weeks_to_race <= 8:
        return 0.09
    if weeks_to_race >= 24:
        return 0.04
    return 0.09 + (0.04 - 0.09) * (weeks_to_race - 8) / (24 - 8)


def _tsb_multiplier(tsb: float) -> float:
    """Scale weekly load by current form (TSB). Fatigued → reduce; fresh → push."""
    if tsb < -25:
        return 0.85
    if tsb < -10:
        return 1.00
    if tsb < 5:
        return 1.03
    return 1.08


def weighted_tss_per_hour(profile: AthleteProfile) -> float:
    """Blended TSS/hour from the athlete's sport split (measured rates if available)."""
    rates = dict(DEFAULT_TSS_PER_HOUR)
    if profile.preferences.measured_tss_per_hour:
        rates.update(profile.preferences.measured_tss_per_hour)
    dist = profile.preferences.sport_distribution
    return sum(frac * rates.get(sport, 50) for sport, frac in dist.items())


def weekly_tss_target(profile: AthleteProfile, phase: Phase,
                      weeks_to_race: float, fitness: "Fitness | None" = None) -> tuple[float, str]:
    """
    Compute the week's TSS target and a human-readable rationale.

    CTL-anchored progressive build (ramp scales with weeks-to-race), capped by
    the weighted available hours, reduced in recovery weeks (every 4th), and
    modulated by current TSB. Cold-starts from an hours-based baseline.

    `fitness` overrides profile.fitness (used by forward simulation so each
    projected week is planned against its simulated CTL/ATL/TSB).
    """
    fit = fitness or profile.fitness
    ctl = fit.ctl
    tsb = fit.tsb
    ramp = _ramp_for_weeks(weeks_to_race)

    ctl_based = max(ctl, 1.0) * 7 * (1 + ramp)
    rate = weighted_tss_per_hour(profile)
    hours_cap = profile.goals.weekly_hours_available * rate

    if ctl < 10:
        target = hours_cap * 0.6
        anchor = "cold-start (low CTL) -> gentle hours-based baseline"
    elif ctl_based <= hours_cap:
        target = ctl_based
        anchor = f"CTL-anchored (CTL {ctl:.0f} x 7 x +{ramp * 100:.0f}% ramp)"
    else:
        target = hours_cap
        anchor = f"hours-capped ({profile.goals.weekly_hours_available:.0f}h x {rate:.0f} TSS/h)"

    target *= PHASE_MODIFIERS.get(phase, 1.0)

    # Within a 3-week loading block, volume climbs week to week (dose 0->1->2)
    # before the 4th week's recovery cut — without this, Base/Build weeks at
    # the same CTL/phase were nearly identical week over week.
    dose, is_recovery = _dose_for_week(weeks_to_race, phase)
    if phase in (Phase.BASE, Phase.BUILD):
        target *= _DOSE_LOAD_MULTIPLIER.get(dose, 1.0)
    if is_recovery:
        target *= 0.65

    target *= _tsb_multiplier(tsb)

    # Never plan meaningfully more than the athlete said they have available,
    # even after phase/TSB multipliers stack — mainly guards low-hour athletes
    # whose Base week is already hours-capped from a Peak week blowing past it.
    target = min(target, hours_cap * 1.15)

    notes = [anchor, f"{phase.value} phase"]
    if is_recovery:
        notes.append("recovery week (-35%)")
    elif phase in (Phase.BASE, Phase.BUILD) and dose > 0:
        notes.append(f"week {dose + 1} of 3 in block (+{(_DOSE_LOAD_MULTIPLIER[dose] - 1) * 100:.0f}%)")
    if tsb < -25:
        notes.append(f"TSB {tsb:.0f} fatigued -> -15%")
    elif tsb >= 5:
        notes.append(f"TSB {tsb:.0f} fresh -> load bump")
    return round(target), "; ".join(notes)


# ── session builders ────────────────────────────────────────────────────────

def _min(n: int) -> int:
    return n * 60


def build_brick_session(scheduled_date: date, phase: Phase,
                        ftp: int, threshold_pace: float, css: float,
                        max_hr: int | None = None, lthr: int | None = None,
                        size_ratio: float = 1.0) -> Workout:
    """
    Peak-phase weekend session: a full-length long ride (same scale as
    library.bike_long) finishing with a race-pace run off the bike. Keeps the
    weekend slot's volume/TSS-per-hour in line with a normal long ride —
    a short standalone brick here would hit its TSS target in far fewer
    hours, silently shrinking Peak's weekend load instead of growing it.
    """
    bike_ratio = max(0.35, min(2.5, size_ratio))
    run_ratio = max(0.4, min(1.8, size_ratio))
    bike_min = round(110 * bike_ratio)
    run_min = round(20 * run_ratio)
    steps = [
        WorkoutStep(name="Bike Warm-up", duration_seconds=_min(15),
                    target=Target(type=TargetType.POWER_ZONE, zone=2)),
        WorkoutStep(name="Bike Long", duration_seconds=_min(bike_min),
                    target=Target(type=TargetType.POWER_ZONE, zone=2)),
        WorkoutStep(name="Bike Race-Pace Finish", duration_seconds=_min(10),
                    target=Target(type=TargetType.POWER_ZONE, zone=3)),
        WorkoutStep(name="Run off the Bike", duration_seconds=_min(run_min),
                    target=Target(type=TargetType.PACE_ZONE, zone=3)),
    ]
    return Workout(
        sport=Sport.BRICK,
        scheduled_date=scheduled_date,
        title=f"Brick — Long Ride + Run ({phase.value})",
        steps=steps,
    ).with_anchors(ftp, threshold_pace, css, max_hr=max_hr, lthr=lthr)


def build_strength_session(scheduled_date: date, minutes: int,
                           ftp: int, threshold_pace: float, css: float,
                           max_hr: int | None = None, lthr: int | None = None) -> Workout:
    """A simple timed strength session — flat TSS, no structured steps."""
    step = WorkoutStep(name="Strength", duration_seconds=_min(minutes),
                       target=Target(type=TargetType.OPEN))
    return Workout(
        sport=Sport.STRENGTH,
        scheduled_date=scheduled_date,
        title="Strength",
        steps=[step],
    ).with_anchors(ftp, threshold_pace, css, max_hr=max_hr, lthr=lthr)


# ── target distribution / scaling ────────────────────────────────────────────

def _scale_workout(workout: Workout, factor: float) -> None:
    """Scale every step's duration (and distance) in-place by `factor`."""
    factor = max(0.3, min(3.0, factor))  # keep durations sane
    is_swim = workout.sport == Sport.SWIM
    # Swim sets come in pool-length units — scale distances at 25 m granularity
    # (durations get re-derived from distance by Workout.normalize afterwards).
    grain, floor = (25, 25) if is_swim else (50, 100)

    def scale_step(s: WorkoutStep) -> None:
        if not is_swim:
            s.duration_seconds = max(60, round(s.duration_seconds * factor / 30) * 30)
        if s.distance_meters:
            s.distance_meters = max(floor, round(s.distance_meters * factor / grain) * grain)

    for item in workout.steps:
        if isinstance(item, WorkoutStep):
            scale_step(item)
        else:
            for s in item.steps:
                scale_step(s)


def _scale_group_to_target(workouts: list[Workout], group: str, target_tss: float) -> None:
    """Scale all workouts in a load group so their combined TSS ≈ target_tss."""
    members = [w for w in workouts if load_group(w.sport) == group]
    base = sum(w.planned_tss() for w in members)
    if base <= 0 or target_tss <= 0:
        return
    factor = target_tss / base
    for w in members:
        _scale_workout(w, factor)


def _scale_group_to_target_weighted(workouts: list[Workout], group: str, target_tss: float,
                                    long_workout: Workout | None, weekend_bias: float = 0.70) -> None:
    """
    Like _scale_group_to_target, but when RAMPING LOAD UP, bias most of the
    added volume onto the weekend long session rather than spreading it evenly
    — real periodization grows the big session, not every session equally.
    Cuts (recovery/taper weeks) fall back to a uniform scale in both directions.
    """
    members = [w for w in workouts if load_group(w.sport) == group]
    base_total = sum(w.planned_tss() for w in members)
    if base_total <= 0 or target_tss <= 0:
        return
    deficit = target_tss - base_total
    if long_workout is None or long_workout not in members or deficit <= 0:
        _scale_group_to_target(workouts, group, target_tss)
        return

    others = [w for w in members if w is not long_workout]
    base_long = long_workout.planned_tss()
    base_others = base_total - base_long

    long_factor = (base_long + deficit * weekend_bias) / base_long if base_long > 0 else 1.0
    _scale_workout(long_workout, long_factor)
    if others and base_others > 0:
        others_factor = (base_others + deficit * (1 - weekend_bias)) / base_others
        for w in others:
            _scale_workout(w, others_factor)


# ── weekly plan ─────────────────────────────────────────────────────────────

@dataclass
class WeekPlan:
    week_start: date  # Monday
    phase: Phase
    target_tss: float
    ctl: float = 0.0
    atl: float = 0.0
    tsb: float = 0.0
    weeks_to_race: float = 0.0
    rationale: str = ""
    workouts: list[Workout] = field(default_factory=list)

    @property
    def planned_tss(self) -> float:
        return round(sum(w.planned_tss() for w in self.workouts), 1)

    def summary(self) -> dict:
        return {
            "week_start": self.week_start.isoformat(),
            "phase": self.phase.value,
            "target_tss": self.target_tss,
            "planned_tss": self.planned_tss,
            "fitness": {"ctl": self.ctl, "atl": self.atl, "tsb": round(self.tsb, 1)},
            "weeks_to_race": round(self.weeks_to_race, 1),
            "rationale": self.rationale,
            "workouts": [w.summary() for w in self.workouts],
        }


# Preferred days for strength sessions (fall through as count increases)
_STRENGTH_DAYS = [0, 4, 2, 5, 1, 3, 6]  # Mon, Fri, Wed, Sat, Tue, Thu, Sun

# Strength frequency cap per phase — strength supports the season early and
# steps back as race-specific work ramps (never crowds out swim sessions).
_STRENGTH_PHASE_CAP = {Phase.BASE: 2, Phase.BUILD: 1, Phase.PEAK: 1, Phase.TAPER: 1, Phase.RACE: 0}


def _tri_sessions_for_hours(hours: float) -> int:
    """Triathlon sessions per week (strength excluded) an athlete's hours support."""
    if hours < 5.5:
        return 4
    if hours < 8:
        return 5
    if hours < 11:
        return 6
    if hours < 14:
        return 7
    return 8


def _dose_for_week(weeks_to_race: float, phase: Phase) -> tuple[int, bool]:
    """(dose 0-2 within the 3+1 block, is_recovery). Dose steps up load weeks."""
    mod = round(weeks_to_race) % 4
    is_recovery = (mod == 0) and phase in (Phase.BASE, Phase.BUILD)
    dose = {3: 0, 2: 1, 1: 2}.get(mod, 0)
    if phase in (Phase.PEAK, Phase.TAPER):
        dose = 1
    return dose, is_recovery


def _allocate_sessions(present: list[str], n_tri: int, dist: dict[str, float]) -> dict[str, int]:
    """
    Split n_tri weekly sessions across the race's disciplines. Every present
    sport gets one; swimming gets a second early (frequency matters most for
    swim technique); the rest follow the athlete's distribution weights.
    """
    counts = {s: 1 for s in present}
    remaining = n_tri - len(present)
    if "swim" in counts and remaining > 0:
        counts["swim"] += 1
        remaining -= 1
    order = sorted(present, key=lambda s: -dist.get(s, 0.0))
    i = 0
    while remaining > 0:
        s = order[i % len(order)]
        # keep any single sport from hogging the week (max 3, swim max 3 too)
        if counts[s] < 3:
            counts[s] += 1
            remaining -= 1
        i += 1
        if i > 24:  # all capped
            break
    return counts


def _race_week_sessions(present: list[str], race_date: date, week_start: date, css: float,
                        mk) -> list[Workout]:
    """
    The week containing race day: 2-3 short openers only, spread across
    whatever days remain before race day (no long sessions, no strength).
    NOTE: if race_date itself falls on week_start (a Monday race), there are
    no days left to schedule openers on — a rare edge case, not a bug.
    """
    available = [week_start + timedelta(days=i) for i in range(7)
                if week_start + timedelta(days=i) < race_date]
    if not available:
        return []

    n = min(len(present), 3, len(available))
    picked = sorted({available[round(i * (len(available) - 1) / max(1, n - 1))] for i in range(n)})
    i = 0
    while len(picked) < n and i < len(available):
        if available[i] not in picked:
            picked = sorted(picked + [available[i]])
        i += 1
    picked = picked[:n]

    order = [s for s in ("swim", "bike", "run") if s in present][:len(picked)]
    workouts: list[Workout] = []
    for day, sport in zip(picked, order):
        if sport == "swim":
            title, steps = library.swim_opener(css)
            workouts.append(mk(Sport.SWIM, day, title, steps))
        elif sport == "bike":
            title, steps = library.bike_opener()
            workouts.append(mk(Sport.BIKE_INDOOR, day, title, steps))
        else:
            title, steps = library.run_opener()
            workouts.append(mk(Sport.RUN, day, title, steps))
    return workouts


def generate_week(profile: AthleteProfile, week_start: date | None = None,
                  week_number: int = 1, fitness: Fitness | None = None) -> WeekPlan:
    """
    Generate a fitness-aware structured training week, scaled to the athlete's
    chosen race distance (see race_size_ratio — the engine is tuned around a
    70.3 and every other distance scales phase windows + long-session length
    relative to that baseline).

    The weekly TSS target is CTL-anchored and TSB-modulated (see
    weekly_tss_target), then distributed across sports per the athlete's
    sport_distribution by scaling session durations. Strength is added as
    simple timed sessions sized to its share of the target.

    `fitness` overrides profile.fitness (used by generate_plan's forward sim).
    """
    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # roll back to Monday

    fit = fitness or profile.fitness
    phase = get_phase(profile, week_start)
    weeks_to_race = max(0.0, (profile.goals.race_date - week_start).days / 7)
    size_ratio = race_size_ratio(profile)

    ftp = profile.thresholds.ftp_watts
    tp = profile.thresholds.run_threshold_pace_sec_per_km
    css = profile.thresholds.swim_css_sec_per_100m
    max_hr = profile.thresholds.max_hr
    lthr = profile.thresholds.run_lthr

    mon, tue, wed, thu, fri, sat, sun = [week_start + timedelta(days=i) for i in range(7)]
    days = [mon, tue, wed, thu, fri, sat, sun]
    dist = profile.preferences.sport_distribution

    # Which disciplines does this race actually involve?
    swim_m, bike_m, run_m = race_distances(profile.goals)
    present = [s for s, m in (("swim", swim_m), ("bike", bike_m), ("run", run_m)) if m > 0]
    if not present:
        present = ["swim", "bike", "run"]

    def _mk(sport: Sport, d: date, title: str, steps) -> Workout:
        return Workout(sport=sport, scheduled_date=d, title=title, steps=steps) \
            .with_anchors(ftp, tp, css, max_hr=max_hr, lthr=lthr)

    # The week containing race day: short openers only, bypassing the whole
    # ramp/allocation pipeline below (no strength, no long/quality sessions).
    if phase == Phase.TAPER and weeks_to_race < 1.0:
        workouts = _race_week_sessions(present, profile.goals.race_date, week_start, css, _mk)
        workouts.sort(key=lambda w: w.scheduled_date)
        target_tss = round(sum(w.planned_tss() for w in workouts))
        return WeekPlan(
            week_start=week_start, phase=phase, target_tss=target_tss,
            ctl=fit.ctl, atl=fit.atl, tsb=fit.tsb, weeks_to_race=weeks_to_race,
            rationale="Race week — short openers only; volume drops sharply to arrive fresh.",
            workouts=workouts,
        )

    target_tss, rationale = weekly_tss_target(profile, phase, weeks_to_race, fitness=fit)

    # Seeded per week: a given week always regenerates identically, but
    # session flavors/days shuffle from one week to the next.
    rng = random.Random(f"{week_start.isoformat()}|{profile.goals.race_date.isoformat()}")
    dose, is_recovery = _dose_for_week(weeks_to_race, phase)
    if is_recovery:
        dose = 0

    n_tri = _tri_sessions_for_hours(profile.goals.weekly_hours_available)
    counts = _allocate_sessions(present, n_tri, dist)

    # Strength — phase-capped session count, capped at a realistic duration.
    # Computed up front (not after endurance scaling) so any TSS its capped
    # duration can't absorb flows into the endurance sports below, instead of
    # just vanishing or ballooning into unrealistic 90+ minute lifting sessions.
    n_strength = min(profile.preferences.strength_sessions_per_week,
                     _STRENGTH_PHASE_CAP.get(phase, 1))
    if "swim" in counts:
        n_strength = min(n_strength, counts["swim"])
    strength_target = target_tss * dist.get("strength", 0.0)
    strength_session_min = 0
    leftover_strength_tss = 0.0
    if n_strength > 0 and strength_target > 0:
        total_minutes = (strength_target / STRENGTH_TSS_PER_HOUR) * 60
        strength_session_min = max(20, min(45, round(total_minutes / n_strength)))
        realized_tss = (strength_session_min * n_strength / 60) * STRENGTH_TSS_PER_HOUR
        leftover_strength_tss = max(0.0, strength_target - realized_tss)
    else:
        leftover_strength_tss = strength_target

    # Weekly intensity floor: 1 interval session (≤5 tri sessions) or 2 (≥6),
    # never the same sport twice (spread rule); limiter discipline gets first
    # claim on quality more often than not.
    n_intervals = min(1 if n_tri <= 5 else 2, len(present))
    limiter = profile.goals.limiter_discipline.value if profile.goals.limiter_discipline else None
    interval_sports: list[str] = []
    if limiter in present and rng.random() < 0.6:
        interval_sports.append(limiter)
    while len(interval_sports) < n_intervals:
        interval_sports.append(rng.choice([s for s in present if s not in interval_sports]))

    phase_name = phase.value
    weekday_pool = [mon, tue, wed, thu, fri]
    rng.shuffle(weekday_pool)
    _weekdays = iter(weekday_pool * 2)  # cycle again if >5 weekday sessions

    workouts: list[Workout] = []

    # Swim — first session is the interval one when swim drew quality this week
    for i in range(counts.get("swim", 0)):
        quality = "swim" in interval_sports and i == 0
        fn = library.swim_quality if quality else library.swim_easy
        title, steps = fn(phase_name, dose, rng, css, size_ratio)
        workouts.append(_mk(Sport.SWIM, next(_weekdays), title, steps))

    # Bike — weekend long ride (or race-sim brick in Peak) + weekday sessions.
    # The weekend session is tracked so Build/Peak's added volume can be
    # biased onto it instead of spread evenly (see the scaling loop below).
    bike_long_workout: Workout | None = None
    n_bike = counts.get("bike", 0)
    if n_bike:
        has_long = n_bike >= 2 or "bike" not in interval_sports
        if has_long:
            if phase == Phase.PEAK and size_ratio >= 0.65 and run_m > 0:
                bike_long_workout = build_brick_session(sat, phase, ftp, tp, css,
                                                        max_hr=max_hr, lthr=lthr, size_ratio=size_ratio)
            else:
                title, steps = library.bike_long(phase_name, dose, rng, size_ratio)
                bike_long_workout = _mk(Sport.BIKE_OUTDOOR, sat, title, steps)
            workouts.append(bike_long_workout)
        for i in range(n_bike - (1 if has_long else 0)):
            quality = "bike" in interval_sports and i == 0
            fn = library.bike_quality if quality else library.bike_easy
            title, steps = fn(phase_name, dose, rng, size_ratio)
            workouts.append(_mk(Sport.BIKE_INDOOR, next(_weekdays), title, steps))

    # Run — weekend long run + weekday sessions (same weekend-bias tracking)
    run_long_workout: Workout | None = None
    n_run = counts.get("run", 0)
    if n_run:
        has_long = (n_run >= 2 or "run" not in interval_sports) and phase != Phase.TAPER
        if has_long:
            title, steps = library.run_long(phase_name, dose, rng, size_ratio)
            run_long_workout = _mk(Sport.RUN, sun, title, steps)
            workouts.append(run_long_workout)
        for i in range(n_run - (1 if has_long else 0)):
            quality = "run" in interval_sports and i == 0
            fn = library.run_quality if quality else library.run_easy
            title, steps = fn(phase_name, dose, rng, size_ratio)
            workouts.append(_mk(Sport.RUN, next(_weekdays), title, steps))

    # Scale each present sport group to its share of the weekly target (plus
    # any strength TSS its capped duration couldn't absorb), renormalizing
    # shares of disciplines this race doesn't include. Bike/run bias load
    # growth onto their weekend long session; swim scales uniformly.
    tri_shares = {s: dist.get(s, 0.0) for s in ("swim", "bike", "run")}
    present_sum = sum(tri_shares[s] for s in present) or 1.0
    missing_sum = sum(v for s, v in tri_shares.items() if s not in present)
    long_workout_by_group = {"bike": bike_long_workout, "run": run_long_workout}
    for group in present:
        share = tri_shares[group] + missing_sum * (tri_shares[group] / present_sum)
        target = target_tss * share + leftover_strength_tss * (tri_shares[group] / present_sum)
        if group in long_workout_by_group:
            _scale_group_to_target_weighted(workouts, group, target, long_workout_by_group[group])
        else:
            _scale_group_to_target(workouts, group, target)

    # Swim durations re-derive from (scaled) distances
    for w in workouts:
        if w.sport == Sport.SWIM:
            w.normalize(css)

    # Strength sessions themselves (count/duration already computed above)
    if n_strength > 0 and strength_session_min > 0:
        for i in range(n_strength):
            day = days[_STRENGTH_DAYS[i % len(_STRENGTH_DAYS)]]
            workouts.append(build_strength_session(day, strength_session_min, ftp, tp, css,
                                                   max_hr=max_hr, lthr=lthr))

    workouts.sort(key=lambda w: w.scheduled_date)

    return WeekPlan(
        week_start=week_start, phase=phase, target_tss=target_tss,
        ctl=fit.ctl, atl=fit.atl, tsb=fit.tsb,
        weeks_to_race=weeks_to_race, rationale=rationale, workouts=workouts,
    )


# ── full plan to race ─────────────────────────────────────────────────────────

def _week_daily_tss(plan: WeekPlan) -> list[float]:
    """7 daily TSS values (Mon→Sun) for a generated week, for forward simulation."""
    by_day = {plan.week_start + timedelta(days=i): 0.0 for i in range(7)}
    for w in plan.workouts:
        if w.scheduled_date in by_day:
            by_day[w.scheduled_date] += w.planned_tss()
    return [by_day[plan.week_start + timedelta(days=i)] for i in range(7)]


@dataclass
class Plan:
    race_date: date
    start_week: date
    weeks: list[WeekPlan] = field(default_factory=list)

    @property
    def projected_peak_ctl(self) -> float:
        return round(max((w.ctl for w in self.weeks), default=0.0), 1)

    @property
    def race_day_fitness(self) -> dict:
        if not self.weeks:
            return {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
        # end-of-plan projected fitness = last week's start rolled forward one week
        last = self.weeks[-1]
        end = advance_fitness(last.ctl, last.atl, _week_daily_tss(last))
        return {"ctl": end.ctl, "atl": end.atl, "tsb": round(end.tsb, 1)}

    def summary(self) -> dict:
        return {
            "race_date": self.race_date.isoformat(),
            "start_week": self.start_week.isoformat(),
            "total_weeks": len(self.weeks),
            "projected_peak_ctl": self.projected_peak_ctl,
            "race_day_fitness": self.race_day_fitness,
            "weeks": [
                {
                    "week_start": w.week_start.isoformat(),
                    "phase": w.phase.value,
                    "weeks_to_race": round(w.weeks_to_race, 1),
                    "target_tss": w.target_tss,
                    "planned_tss": w.planned_tss,
                    "ctl": w.ctl,
                    "atl": w.atl,
                    "tsb": round(w.tsb, 1),
                    "rationale": w.rationale,
                }
                for w in self.weeks
            ],
        }


def generate_plan(profile: AthleteProfile, start_week: date | None = None) -> Plan:
    """
    Generate the full periodized plan from the current week to race week,
    forward-simulating CTL/ATL so each week is planned against its projected
    fitness (not today's). Returns week-level summaries (no per-step detail).
    """
    if start_week is None:
        today = date.today()
        start_week = today - timedelta(days=today.weekday())

    plan = Plan(race_date=profile.goals.race_date, start_week=start_week)

    fitness = profile.fitness
    week_start = start_week
    guard = 0
    while week_start <= profile.goals.race_date and guard < 60:
        week = generate_week(profile, week_start=week_start, fitness=fitness)
        plan.weeks.append(week)
        # roll fitness forward through this week's daily load
        fitness = advance_fitness(fitness.ctl, fitness.atl, _week_daily_tss(week))
        week_start += timedelta(days=7)
        guard += 1

    return plan
