"""
Parameterized workout library — the session templates the weekly generator
draws from (see [[frontend-design]] / plan-engine notes).

Philosophy: 80/20 polarized skeleton with enforced weekly intensity
(1 interval session when ≤5 tri sessions/week, 2 when ≥6 — never the same
sport twice in one week), weekly flavor rotation via a seeded RNG, and a
3-weeks-load → 1-recovery dose progression (`dose` = 0/1/2 within a block).

Swim sessions are always distance-based, carry per-set fixed rest, and use
the technique matrix (pull buoy / kick / fins / paddles / breathing / one-arm
drills; breast & backstroke only inside steady warm-up/cool-down blocks).
"""
from __future__ import annotations
import random

from domain.workout import (
    Sport, Target, TargetType, WorkoutStep, RepeatBlock, StepOrBlock,
    SwimEquipment, SwimStroke, estimate_swim_seconds,
)


def _min(n: float) -> int:
    return round(n * 60)


# ── step factories ────────────────────────────────────────────────────────────

def swim_step(name: str, dist: int, zone: int | None, css: float, rest: int = 0,
              equipment: SwimEquipment | None = None, stroke: SwimStroke | None = None,
              notes: str = "") -> WorkoutStep:
    target = (Target(type=TargetType.PACE_ZONE, zone=zone) if zone
              else Target(type=TargetType.OPEN))
    return WorkoutStep(
        name=name, distance_meters=dist, rest_seconds=rest,
        duration_seconds=estimate_swim_seconds(dist, zone, css, equipment=equipment, stroke=stroke),
        target=target, equipment=equipment, stroke=stroke, notes=notes,
    )


def timed_step(name: str, minutes: float, target: Target, notes: str = "") -> WorkoutStep:
    return WorkoutStep(name=name, duration_seconds=_min(minutes), target=target, notes=notes)


def _pz(zone: int) -> Target:  # bike power zone
    return Target(type=TargetType.POWER_ZONE, zone=zone)


def _rz(zone: int) -> Target:  # run pace zone
    return Target(type=TargetType.PACE_ZONE, zone=zone)


# ── swim sessions (distance-based; rest per set) ─────────────────────────────

def _swim_warmup(rng: random.Random, css: float) -> list[StepOrBlock]:
    """300m easy; sometimes mixed with back/breast (only allowed in steady blocks)."""
    variant = rng.choice(["free", "mixed", "backbreast"])
    if variant == "free":
        return [swim_step("Warm-up", 300, 1, css, rest=20)]
    if variant == "mixed":
        return [swim_step("Warm-up mixed strokes", 300, 1, css, rest=20, stroke=SwimStroke.MIXED,
                          notes="alternate 50 free / 25 back / 25 breast")]
    return [
        swim_step("Warm-up free", 200, 1, css, rest=15),
        swim_step("Warm-up back/breast", 100, 1, css, rest=15, stroke=SwimStroke.BACK,
                  notes="50 backstroke + 50 breaststroke, relaxed"),
    ]


def _swim_cooldown(rng: random.Random, css: float) -> list[StepOrBlock]:
    stroke = rng.choice([None, SwimStroke.BACK, SwimStroke.MIXED])
    notes = "easy, include some back/breast" if stroke else ""
    return [swim_step("Cool-down", 200, 1, css, stroke=stroke, notes=notes)]


# Technique blocks — the user's matrix. Each returns one RepeatBlock/step.
def _tech_kick(rng, css, dose):
    n = 4 + 2 * dose
    return RepeatBlock(repeat_count=n, steps=[
        swim_step("Kick", 50, 2, css, rest=15, equipment=SwimEquipment.KICKBOARD)])


def _tech_pull(rng, css, dose):
    zone = rng.choice([2, 3])
    return RepeatBlock(repeat_count=3 + dose, steps=[
        swim_step("Pull buoy", 100, zone, css, rest=15, equipment=SwimEquipment.PULL_BUOY)])


def _tech_paddles_short(rng, css, dose):
    # capped at Z3 — Z4+ paddle work lives in the quality sessions, so easy
    # technique days stay genuinely easy
    return RepeatBlock(repeat_count=4 + 2 * dose, steps=[
        swim_step("Paddles", 50, 3, css, rest=20, equipment=SwimEquipment.PADDLES)])


def _tech_paddles_long(rng, css, dose):
    zone = rng.choice([2, 3])
    return RepeatBlock(repeat_count=2 + dose, steps=[
        swim_step("Paddles long", 200, zone, css, rest=25, equipment=SwimEquipment.PADDLES)])


def _tech_paddle_buoy(rng, css, dose):
    return RepeatBlock(repeat_count=3 + dose, steps=[
        swim_step("Paddles + buoy", 100, 2, css, rest=15, equipment=SwimEquipment.PADDLES_BUOY)])


def _tech_paddle_fins(rng, css, dose):
    return RepeatBlock(repeat_count=3 + dose, steps=[
        swim_step("Paddles + fins", 100, 2, css, rest=15, equipment=SwimEquipment.PADDLES_FINS)])


def _tech_breathing(rng, css, dose):
    pattern = rng.choice(["3-5-7 by 100", "every 5 strokes", "every 3/5 alternating 50s"])
    return swim_step("Breathing control", 300, 2, css, rest=30,
                     notes=f"breathe {pattern} — stay relaxed (always Z2)")


def _tech_one_arm(rng, css, dose):
    return RepeatBlock(repeat_count=4 + dose, steps=[
        swim_step("One-arm drill", 50, None, css, rest=20, stroke=SwimStroke.DRILL,
                  notes="25 left arm + 25 right arm")])


def _tech_fins_speed(rng, css, dose):
    return RepeatBlock(repeat_count=6 + 2 * dose, steps=[
        swim_step("Fins fast", 50, 5, css, rest=30, equipment=SwimEquipment.FINS)])


_SWIM_TECH = [_tech_kick, _tech_pull, _tech_paddles_short, _tech_paddles_long,
              _tech_paddle_buoy, _tech_paddle_fins, _tech_breathing, _tech_one_arm]


def swim_quality(phase: str, dose: int, rng: random.Random, css: float, size_ratio: float):
    """Interval swim: warm-up, technique block, CSS main set (+fins speed), cool-down."""
    r = max(0.6, min(1.8, size_ratio))
    flavors = {
        "css_100s": lambda: RepeatBlock(repeat_count=round((6 + 2 * dose) * r),
                                        steps=[swim_step("CSS 100", 100, 4, css, rest=20)]),
        "css_200s": lambda: RepeatBlock(repeat_count=round((3 + dose) * r),
                                        steps=[swim_step("CSS 200", 200, 4, css, rest=30)]),
        "ladder": lambda: RepeatBlock(repeat_count=1, steps=[
            swim_step("Ladder 200", 200, 3, css, rest=20),
            swim_step("Ladder 300", 300, 3, css, rest=25),
            swim_step("Ladder 400", 400, 2, css, rest=30),
            swim_step("Ladder 200 strong", 200, 4, css, rest=20),
        ]),
        "sprint_fins": lambda: _tech_fins_speed(rng, css, dose),
    }
    menu = ["css_100s", "css_200s", "ladder"] if phase != "Peak" else ["css_100s", "sprint_fins"]
    pick = rng.choice(menu)
    steps: list[StepOrBlock] = [*_swim_warmup(rng, css),
                                rng.choice(_SWIM_TECH)(rng, css, dose),
                                flavors[pick](),
                                *_swim_cooldown(rng, css)]
    titles = {"css_100s": "Swim CSS 100s", "css_200s": "Swim CSS 200s",
              "ladder": "Swim Ladder", "sprint_fins": "Swim Speed (fins)"}
    return f"{titles[pick]} ({phase})", steps


def swim_easy(phase: str, dose: int, rng: random.Random, css: float, size_ratio: float):
    """Technique/endurance swim: warm-up + two technique blocks + steady swim."""
    t1, t2 = rng.sample(_SWIM_TECH, 2)
    r = max(0.6, min(1.8, size_ratio))
    steady = swim_step("Steady swim", round(400 * r / 50) * 50, 2, css, rest=0,
                       notes="smooth aerobic freestyle")
    steps: list[StepOrBlock] = [*_swim_warmup(rng, css), t1(rng, css, dose), t2(rng, css, dose),
                                steady, *_swim_cooldown(rng, css)]
    return f"Swim Technique ({phase})", steps


# ── bike sessions (time-based only) ───────────────────────────────────────────

def bike_quality(phase: str, dose: int, rng: random.Random, size_ratio: float):
    wu = timed_step("Warm-up", 15, _pz(2))
    cd = timed_step("Cool-down", 10, _pz(1))
    flavors = {
        "sweet_spot": ("Bike Sweet Spot", RepeatBlock(repeat_count=2 + dose, steps=[
            WorkoutStep(name="Sweet spot", duration_seconds=_min(12),
                        target=Target(type=TargetType.POWER_PERCENT_FTP, pct_of_anchor=0.90)),
            timed_step("Recovery", 4, _pz(1)),
        ])),
        "threshold": ("Bike Threshold", RepeatBlock(repeat_count=min(2 + dose, 3), steps=[
            timed_step("Threshold", 15, _pz(4)),
            timed_step("Recovery", 5, _pz(1)),
        ])),
        "threshold_short": ("Bike Short Threshold", RepeatBlock(repeat_count=3 + dose, steps=[
            timed_step("Threshold", 8, _pz(4)),
            timed_step("Recovery", 3, _pz(1)),
        ])),
        "vo2": ("Bike VO2", RepeatBlock(repeat_count=4 + dose, steps=[
            timed_step("VO2 interval", 3, _pz(5)),
            timed_step("Recovery", 3, _pz(1)),
        ])),
        # strength-endurance: low-cadence Z3 torque work capped by a Z4 surge,
        # so the session still counts as genuine interval work
        "low_cadence": ("Bike Low-Cadence Strength", RepeatBlock(repeat_count=2 + dose, steps=[
            timed_step("Low cadence", 8, _pz(3), notes="55-65 rpm, seated, strong core"),
            timed_step("Surge normal cadence", 2, _pz(4), notes="back to 90 rpm, lift the power"),
            timed_step("Recovery", 3, _pz(1)),
        ])),
    }
    menus = {"Base": ["sweet_spot", "low_cadence", "threshold_short"],
             "Build": ["threshold", "sweet_spot", "vo2"],
             "Peak": ["vo2", "threshold"],
             "Taper": ["vo2"]}
    pick = rng.choice(menus.get(phase, ["sweet_spot"]))
    title, main = flavors[pick]
    if phase == "Taper":  # sharpen, don't load
        main = RepeatBlock(repeat_count=max(2, main.repeat_count // 2), steps=main.steps)
    return f"{title} ({phase})", [wu, main, cd]


def bike_easy(phase: str, dose: int, rng: random.Random, size_ratio: float):
    if rng.random() < 0.4:
        steps = [timed_step("Warm-up", 10, _pz(1)),
                 RepeatBlock(repeat_count=6, steps=[
                     timed_step("High cadence", 2, _pz(2), notes="100-110 rpm, smooth"),
                     timed_step("Normal", 3, _pz(2)),
                 ]),
                 timed_step("Cool-down", 5, _pz(1))]
        return f"Bike Cadence Play ({phase})", steps
    steps = [timed_step("Warm-up", 10, _pz(1)),
             timed_step("Aerobic", 45, _pz(2)),
             timed_step("Cool-down", 5, _pz(1))]
    return f"Aerobic Ride ({phase})", steps


def bike_long(phase: str, dose: int, rng: random.Random, size_ratio: float):
    ratio = max(0.35, min(2.5, size_ratio))
    base = 90 if phase == "Base" else 110
    steps: list[StepOrBlock] = [timed_step("Warm-up", 15, _pz(2)),
                                timed_step("Long endurance", round(base * ratio), _pz(2))]
    if phase in ("Build", "Peak"):
        steps.append(timed_step("Tempo finish", 20, _pz(3), notes="race-effort focus"))
    steps.append(timed_step("Cool-down", 10, _pz(1)))
    return f"Long Ride ({phase})", steps


# ── run sessions ──────────────────────────────────────────────────────────────

def run_quality(phase: str, dose: int, rng: random.Random, size_ratio: float):
    wu = timed_step("Warm-up", 12, _rz(1))
    cd = timed_step("Cool-down", 8, _rz(1))
    flavors = {
        "hills": ("Run Hill Repeats", RepeatBlock(repeat_count=6 + 2 * dose, steps=[
            timed_step("Hill hard", 1, _rz(5), notes="strong uphill, drive the arms"),
            timed_step("Jog down", 1.5, _rz(1)),
        ])),
        "fartlek": ("Run Fartlek", RepeatBlock(repeat_count=6 + 2 * dose, steps=[
            timed_step("Surge", 1, _rz(4), notes="strong but controlled"),
            timed_step("Float", 2, _rz(2)),
        ])),
        # tempo carries a threshold finish so the session includes true Z4 work
        "tempo": ("Run Tempo", [
            timed_step("Tempo", 20 + 5 * dose, _rz(3)),
            timed_step("Threshold finish", 5, _rz(4)),
        ]),
        "cruise": ("Run Cruise Intervals", RepeatBlock(repeat_count=3 + dose, steps=[
            timed_step("Threshold", 8, _rz(4)),
            timed_step("Float", 2, _rz(1)),
        ])),
        "progression": ("Run Progression", [
            timed_step("Steady", 25, _rz(2)),
            timed_step("Progress", 10 + 3 * dose, _rz(3), notes="build to strong finish"),
            timed_step("Final push", 5, _rz(4)),
        ]),
    }
    menus = {"Base": ["hills", "fartlek", "tempo"],
             "Build": ["cruise", "tempo", "progression"],
             "Peak": ["cruise", "progression"],
             "Taper": ["cruise"]}
    pick = rng.choice(menus.get(phase, ["tempo"]))
    title, main = flavors[pick]
    if phase == "Taper" and isinstance(main, RepeatBlock):
        main = RepeatBlock(repeat_count=max(2, main.repeat_count // 2), steps=main.steps)
    mains = main if isinstance(main, list) else [main]
    return f"{title} ({phase})", [wu, *mains, cd]


def run_easy(phase: str, dose: int, rng: random.Random, size_ratio: float):
    if rng.random() < 0.5:
        steps = [timed_step("Easy run", 35, _rz(2)),
                 RepeatBlock(repeat_count=6, steps=[
                     timed_step("Stride", 0.4, _rz(5), notes="fast + relaxed, full recovery"),
                     timed_step("Walk/jog", 1, _rz(1)),
                 ])]
        return f"Easy Run + Strides ({phase})", steps
    return f"Easy Run ({phase})", [timed_step("Easy run", 40, _rz(2))]


def run_long(phase: str, dose: int, rng: random.Random, size_ratio: float):
    ratio = max(0.4, min(1.8, size_ratio))
    base = 70 if phase == "Base" else 85
    steps: list[StepOrBlock] = [timed_step("Warm-up", 10, _rz(1)),
                                timed_step("Long run", round(base * ratio), _rz(2))]
    if phase in ("Build", "Peak"):
        steps.append(timed_step("Race-pace finish", 15, _rz(3)))
    steps.append(timed_step("Cool-down", 8, _rz(1)))
    return f"Long Run ({phase})", steps


# ── race-week openers (fixed, short — no phase/dose scaling) ─────────────────
# The final taper week bypasses the normal quality/easy library entirely: a
# handful of short sessions with a few race-pace touches, sized to feel sharp
# without adding fatigue before race day.

def swim_opener(css: float):
    steps: list[StepOrBlock] = [
        swim_step("Warm-up", 300, 1, css, rest=15),
        RepeatBlock(repeat_count=6, steps=[swim_step("Quick", 50, 4, css, rest=15)]),
        swim_step("Steady", 300, 2, css, rest=0),
        swim_step("Cool-down", 200, 1, css, rest=0),
    ]
    return "Swim Opener (Taper)", steps


def bike_opener():
    steps: list[StepOrBlock] = [
        timed_step("Warm-up", 10, _pz(2)),
        RepeatBlock(repeat_count=4, steps=[
            timed_step("Quick", 1, _pz(4)),
            timed_step("Easy", 2, _pz(1)),
        ]),
        timed_step("Steady", 25, _pz(2)),
        timed_step("Cool-down", 8, _pz(1)),
    ]
    return "Bike Opener (Taper)", steps


def run_opener():
    steps: list[StepOrBlock] = [
        timed_step("Warm-up", 8, _rz(1)),
        RepeatBlock(repeat_count=4, steps=[
            timed_step("Stride", 0.5, _rz(5), notes="quick and relaxed, full recovery"),
            timed_step("Jog", 1, _rz(1)),
        ]),
        timed_step("Steady", 18, _rz(2)),
        timed_step("Cool-down", 6, _rz(1)),
    ]
    return "Run Opener (Taper)", steps
