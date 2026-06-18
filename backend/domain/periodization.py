from __future__ import annotations
from datetime import date, timedelta
from enum import Enum
from dataclasses import dataclass, field

from domain.athlete import AthleteProfile
from domain.workout import (
    Sport, Target, TargetType, WorkoutStep, RepeatBlock, Workout
)


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


def weekly_tss_target(profile: AthleteProfile, phase: Phase, week_number: int) -> float:
    """
    Base weekly TSS derived from available training hours.
    Ramps 5% per week. Recovery weeks (every 4th) drop by 30%.
    Tapers aggressively in peak/taper phases.
    """
    hours = profile.goals.weekly_hours_available
    base_tss = hours * 55  # ~55 TSS/hr is a reasonable aerobic average

    ramp = 1 + (0.05 * (week_number - 1))
    tss = base_tss * ramp

    if week_number % 4 == 0:
        tss *= 0.70  # recovery week

    phase_modifiers = {
        Phase.BASE: 0.80,
        Phase.BUILD: 1.00,
        Phase.PEAK: 1.10,
        Phase.TAPER: 0.55,
    }
    tss *= phase_modifiers.get(phase, 1.0)

    return round(tss)


# ── session builders ────────────────────────────────────────────────────────

def _min(n: int) -> int:
    return n * 60


def build_swim_session(scheduled_date: date, phase: Phase, ftp: int, threshold_pace: float, css: float) -> Workout:
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
    ).with_anchors(ftp, threshold_pace, css)
    return workout


def build_bike_session(scheduled_date: date, phase: Phase, long: bool,
                       ftp: int, threshold_pace: float, css: float) -> Workout:
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
        sport=Sport.BIKE,
        scheduled_date=scheduled_date,
        title=title,
        steps=steps,
    ).with_anchors(ftp, threshold_pace, css)


def build_run_session(scheduled_date: date, phase: Phase, long: bool,
                      ftp: int, threshold_pace: float, css: float) -> Workout:
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
    ).with_anchors(ftp, threshold_pace, css)


def build_brick_session(scheduled_date: date, phase: Phase,
                        ftp: int, threshold_pace: float, css: float) -> Workout:
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
    ).with_anchors(ftp, threshold_pace, css)


# ── weekly plan ─────────────────────────────────────────────────────────────

@dataclass
class WeekPlan:
    week_start: date  # Monday
    phase: Phase
    target_tss: float
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
            "workouts": [w.summary() for w in self.workouts],
        }


def generate_week(profile: AthleteProfile, week_start: date | None = None,
                  week_number: int = 1) -> WeekPlan:
    """
    Generate a structured training week for a 70.3 athlete.

    Default week layout (Mon=rest day, adjustable later):
      Mon: rest
      Tue: swim
      Wed: bike (intervals/aerobic)
      Thu: run (intervals/easy)
      Fri: rest or easy swim
      Sat: long ride
      Sun: long run (or brick in Build/Peak)
    """
    if week_start is None:
        today = date.today()
        # Roll back to Monday
        week_start = today - timedelta(days=today.weekday())

    phase = get_phase(profile.goals.race_date, week_start)
    target_tss = weekly_tss_target(profile, phase, week_number)

    ftp = profile.thresholds.ftp_watts
    tp = profile.thresholds.run_threshold_pace_sec_per_km
    css = profile.thresholds.swim_css_sec_per_100m

    mon, tue, wed, thu, fri, sat, sun = [week_start + timedelta(days=i) for i in range(7)]

    workouts: list[Workout] = []

    # Tuesday — swim
    workouts.append(build_swim_session(tue, phase, ftp, tp, css))

    # Wednesday — bike
    workouts.append(build_bike_session(wed, phase, long=False, ftp=ftp, threshold_pace=tp, css=css))

    # Thursday — run
    workouts.append(build_run_session(thu, phase, long=False, ftp=ftp, threshold_pace=tp, css=css))

    # Saturday — long ride (Base/Build) or brick (Peak)
    if phase == Phase.PEAK:
        workouts.append(build_brick_session(sat, phase, ftp, tp, css))
    else:
        workouts.append(build_bike_session(sat, phase, long=True, ftp=ftp, threshold_pace=tp, css=css))

    # Sunday — long run (except Taper which is easy)
    workouts.append(build_run_session(sun, phase, long=(phase != Phase.TAPER),
                                      ftp=ftp, threshold_pace=tp, css=css))

    return WeekPlan(week_start=week_start, phase=phase, target_tss=target_tss, workouts=workouts)
