from __future__ import annotations
from datetime import date, timedelta
from enum import Enum
from dataclasses import dataclass, field

from domain.athlete import AthleteProfile
from domain.workout import (
    Sport, Target, TargetType, WorkoutStep, RepeatBlock, Workout, load_group
)
from domain.training_load import DEFAULT_TSS_PER_HOUR, STRENGTH_TSS_PER_HOUR


class Phase(str, Enum):
    BASE = "Base"
    BUILD = "Build"
    PEAK = "Peak"
    TAPER = "Taper"
    RACE = "Race"


PHASE_WEEKS = {
    Phase.TAPER: 2,
    Phase.PEAK: 2,
}


def get_phase(race_date: date, today: date) -> Phase:
    weeks_out = (race_date - today).days / 7
    if weeks_out <= 0:
        return Phase.RACE
    if weeks_out <= PHASE_WEEKS[Phase.TAPER]:
        return Phase.TAPER
    if weeks_out <= PHASE_WEEKS[Phase.TAPER] + PHASE_WEEKS[Phase.PEAK]:
        return Phase.PEAK
    # Total build period is ~40% of remaining time, base is the rest
    total_prep_weeks = weeks_out - sum(PHASE_WEEKS.values())
    build_weeks = round(total_prep_weeks * 0.40)
    if weeks_out <= PHASE_WEEKS[Phase.TAPER] + PHASE_WEEKS[Phase.PEAK] + build_weeks:
        return Phase.BUILD
    return Phase.BASE


PHASE_MODIFIERS = {
    Phase.BASE: 0.85,
    Phase.BUILD: 1.00,
    Phase.PEAK: 1.05,
    Phase.TAPER: 0.55,
}


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
                      weeks_to_race: float) -> tuple[float, str]:
    """
    Compute the week's TSS target and a human-readable rationale.

    CTL-anchored progressive build (ramp scales with weeks-to-race), capped by
    the weighted available hours, reduced in recovery weeks (every 4th), and
    modulated by current TSB. Cold-starts from an hours-based baseline.
    """
    ctl = profile.fitness.ctl
    tsb = profile.fitness.tsb
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

    is_recovery = (round(weeks_to_race) % 4 == 0) and phase in (Phase.BASE, Phase.BUILD)
    if is_recovery:
        target *= 0.65

    target *= _tsb_multiplier(tsb)

    notes = [anchor, f"{phase.value} phase"]
    if is_recovery:
        notes.append("recovery week (-35%)")
    if tsb < -25:
        notes.append(f"TSB {tsb:.0f} fatigued -> -15%")
    elif tsb >= 5:
        notes.append(f"TSB {tsb:.0f} fresh -> load bump")
    return round(target), "; ".join(notes)


# ── session builders ────────────────────────────────────────────────────────

def _min(n: int) -> int:
    return n * 60


def build_swim_session(scheduled_date: date, phase: Phase, ftp: int, threshold_pace: float,
                       css: float, max_hr: int | None = None, lthr: int | None = None) -> Workout:
    wu = WorkoutStep(name="Warm-up", duration_seconds=_min(10),
                     target=Target(type=TargetType.PACE_ZONE, zone=1))

    main_reps = 6 if phase in (Phase.BUILD, Phase.PEAK) else 4
    main_block = RepeatBlock(repeat_count=main_reps, steps=[
        WorkoutStep(name="Interval", duration_seconds=_min(3),
                    target=Target(type=TargetType.PACE_ZONE, zone=4)),
        WorkoutStep(name="Rest", duration_seconds=_min(1),
                    target=Target(type=TargetType.OPEN)),
    ])

    cd = WorkoutStep(name="Cool-down", duration_seconds=_min(8),
                     target=Target(type=TargetType.PACE_ZONE, zone=1))

    workout = Workout(
        sport=Sport.SWIM,
        scheduled_date=scheduled_date,
        title=f"Swim Intervals ({phase.value})",
        steps=[wu, main_block, cd],
    ).with_anchors(ftp, threshold_pace, css, max_hr=max_hr, lthr=lthr)
    return workout


def build_bike_session(scheduled_date: date, phase: Phase, long: bool,
                       ftp: int, threshold_pace: float, css: float,
                       max_hr: int | None = None, lthr: int | None = None,
                       sport: Sport = Sport.BIKE_OUTDOOR) -> Workout:
    wu = WorkoutStep(name="Warm-up", duration_seconds=_min(15),
                     target=Target(type=TargetType.POWER_ZONE, zone=2))
    cd = WorkoutStep(name="Cool-down", duration_seconds=_min(10),
                     target=Target(type=TargetType.POWER_ZONE, zone=1))

    if long:
        main = WorkoutStep(name="Long Endurance", duration_seconds=_min(90 if phase == Phase.BASE else 110),
                           target=Target(type=TargetType.POWER_ZONE, zone=2))
        title = f"Long Ride ({phase.value})"
        steps = [wu, main, cd]
    elif phase in (Phase.BUILD, Phase.PEAK):
        reps = 4 if phase == Phase.BUILD else 5
        main = RepeatBlock(repeat_count=reps, steps=[
            WorkoutStep(name="Threshold", duration_seconds=_min(8),
                        target=Target(type=TargetType.POWER_ZONE, zone=4)),
            WorkoutStep(name="Recovery", duration_seconds=_min(4),
                        target=Target(type=TargetType.POWER_ZONE, zone=1)),
        ])
        title = f"Bike Threshold Intervals ({phase.value})"
        steps = [wu, main, cd]
    else:
        main = WorkoutStep(name="Aerobic", duration_seconds=_min(50),
                           target=Target(type=TargetType.POWER_ZONE, zone=2))
        title = f"Aerobic Ride ({phase.value})"
        steps = [wu, main, cd]

    return Workout(
        sport=sport,
        scheduled_date=scheduled_date,
        title=title,
        steps=steps,
    ).with_anchors(ftp, threshold_pace, css, max_hr=max_hr, lthr=lthr)


def build_run_session(scheduled_date: date, phase: Phase, long: bool,
                      ftp: int, threshold_pace: float, css: float,
                      max_hr: int | None = None, lthr: int | None = None) -> Workout:
    wu = WorkoutStep(name="Warm-up", duration_seconds=_min(10),
                     target=Target(type=TargetType.PACE_ZONE, zone=1))
    cd = WorkoutStep(name="Cool-down", duration_seconds=_min(8),
                     target=Target(type=TargetType.PACE_ZONE, zone=1))

    if long:
        main = WorkoutStep(name="Long Run", duration_seconds=_min(70 if phase == Phase.BASE else 85),
                           target=Target(type=TargetType.PACE_ZONE, zone=2))
        title = f"Long Run ({phase.value})"
        steps = [wu, main, cd]
    elif phase in (Phase.BUILD, Phase.PEAK):
        reps = 5 if phase == Phase.BUILD else 6
        main = RepeatBlock(repeat_count=reps, steps=[
            WorkoutStep(name="Interval", duration_seconds=_min(4),
                        target=Target(type=TargetType.PACE_ZONE, zone=4)),
            WorkoutStep(name="Jog", duration_seconds=_min(2),
                        target=Target(type=TargetType.PACE_ZONE, zone=1)),
        ])
        title = f"Run Intervals ({phase.value})"
        steps = [wu, main, cd]
    else:
        main = WorkoutStep(name="Easy Run", duration_seconds=_min(40),
                           target=Target(type=TargetType.PACE_ZONE, zone=2))
        title = f"Easy Run ({phase.value})"
        steps = [wu, main, cd]

    return Workout(
        sport=Sport.RUN,
        scheduled_date=scheduled_date,
        title=title,
        steps=steps,
    ).with_anchors(ftp, threshold_pace, css, max_hr=max_hr, lthr=lthr)


def build_brick_session(scheduled_date: date, phase: Phase,
                        ftp: int, threshold_pace: float, css: float,
                        max_hr: int | None = None, lthr: int | None = None) -> Workout:
    """Bike→Run transition session."""
    steps = [
        WorkoutStep(name="Bike Warm-up", duration_seconds=_min(10),
                    target=Target(type=TargetType.POWER_ZONE, zone=2)),
        WorkoutStep(name="Bike Main", duration_seconds=_min(50),
                    target=Target(type=TargetType.POWER_ZONE, zone=3)),
        WorkoutStep(name="Transition + Run", duration_seconds=_min(20),
                    target=Target(type=TargetType.PACE_ZONE, zone=3)),
    ]
    return Workout(
        sport=Sport.BRICK,
        scheduled_date=scheduled_date,
        title=f"Brick ({phase.value})",
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

    def scale_step(s: WorkoutStep) -> None:
        s.duration_seconds = max(60, round(s.duration_seconds * factor / 30) * 30)
        if s.distance_meters:
            s.distance_meters = max(100, round(s.distance_meters * factor / 50) * 50)

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


def generate_week(profile: AthleteProfile, week_start: date | None = None,
                  week_number: int = 1) -> WeekPlan:
    """
    Generate a fitness-aware structured training week for a 70.3 athlete.

    The weekly TSS target is CTL-anchored and TSB-modulated (see
    weekly_tss_target), then distributed across sports per the athlete's
    sport_distribution by scaling session durations. Strength is added as
    simple timed sessions sized to its share of the target.
    """
    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # roll back to Monday

    phase = get_phase(profile.goals.race_date, week_start)
    weeks_to_race = max(0.0, (profile.goals.race_date - week_start).days / 7)
    target_tss, rationale = weekly_tss_target(profile, phase, weeks_to_race)

    ftp = profile.thresholds.ftp_watts
    tp = profile.thresholds.run_threshold_pace_sec_per_km
    css = profile.thresholds.swim_css_sec_per_100m
    max_hr = profile.thresholds.max_hr
    lthr = profile.thresholds.run_lthr

    mon, tue, wed, thu, fri, sat, sun = [week_start + timedelta(days=i) for i in range(7)]
    days = [mon, tue, wed, thu, fri, sat, sun]
    dist = profile.preferences.sport_distribution

    workouts: list[Workout] = []

    # Swim, bike, run base sessions
    workouts.append(build_swim_session(tue, phase, ftp, tp, css, max_hr=max_hr, lthr=lthr))
    workouts.append(build_bike_session(wed, phase, long=False, ftp=ftp, threshold_pace=tp,
                                       css=css, max_hr=max_hr, lthr=lthr, sport=Sport.BIKE_INDOOR))
    workouts.append(build_run_session(thu, phase, long=False, ftp=ftp, threshold_pace=tp,
                                      css=css, max_hr=max_hr, lthr=lthr))
    if phase == Phase.PEAK:
        workouts.append(build_brick_session(sat, phase, ftp, tp, css, max_hr=max_hr, lthr=lthr))
    else:
        workouts.append(build_bike_session(sat, phase, long=True, ftp=ftp, threshold_pace=tp,
                                           css=css, max_hr=max_hr, lthr=lthr, sport=Sport.BIKE_OUTDOOR))
    workouts.append(build_run_session(sun, phase, long=(phase != Phase.TAPER),
                                      ftp=ftp, threshold_pace=tp, css=css, max_hr=max_hr, lthr=lthr))

    # Scale each sport group to its share of the weekly target
    for group in ("swim", "bike", "run"):
        _scale_group_to_target(workouts, group, target_tss * dist.get(group, 0.0))

    # Strength — flat TSS, sized to its share, split across N sessions
    n_strength = profile.preferences.strength_sessions_per_week
    strength_target = target_tss * dist.get("strength", 0.0)
    if n_strength > 0 and strength_target > 0:
        total_minutes = (strength_target / STRENGTH_TSS_PER_HOUR) * 60
        per_session_min = max(20, round(total_minutes / n_strength))
        for i in range(n_strength):
            day = days[_STRENGTH_DAYS[i % len(_STRENGTH_DAYS)]]
            workouts.append(build_strength_session(day, per_session_min, ftp, tp, css,
                                                   max_hr=max_hr, lthr=lthr))

    workouts.sort(key=lambda w: w.scheduled_date)

    return WeekPlan(
        week_start=week_start, phase=phase, target_tss=target_tss,
        ctl=profile.fitness.ctl, atl=profile.fitness.atl, tsb=profile.fitness.tsb,
        weeks_to_race=weeks_to_race, rationale=rationale, workouts=workouts,
    )
