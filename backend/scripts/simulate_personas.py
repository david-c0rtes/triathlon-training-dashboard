"""
Persona simulator — fabricates athletes with different races/hours and prints
each one's generated week(s) so plan quality can be eyeballed + sanity-checked.

Run:  cd backend && python -m scripts.simulate_personas
"""
from __future__ import annotations
from datetime import date, timedelta

from domain.athlete import (
    AthleteProfile, Goals, Thresholds, RaceType, CustomLeg, Discipline,
)
from domain.periodization import generate_week, Phase
from domain.workout import Sport, TargetType, WorkoutStep

PERSONAS = [
    ("Sprint novice, 5h/wk", RaceType.SPRINT_TRI, 5, None, None),
    ("Olympic, 8h/wk", RaceType.OLYMPIC_TRI, 8, None, None),
    ("70.3, 10h/wk (run limiter)", RaceType.MIDDLE_TRI, 10, Discipline.RUN, None),
    ("IRONMAN, 14h/wk", RaceType.LONG_TRI, 14, None, None),
    ("Aquabike custom, 8h/wk", RaceType.CUSTOM, 8, None,
     [CustomLeg(discipline=Discipline.SWIM, distance_m=1900),
      CustomLeg(discipline=Discipline.BIKE, distance_m=90000)]),
    ("Duathlon sprint, 6h/wk", RaceType.SPRINT_DU, 6, None, None),
]


def make_profile(race_type, hours, limiter, legs) -> AthleteProfile:
    return AthleteProfile(
        name="Sim",
        goals=Goals(race_date=date.today() + timedelta(weeks=16), race_type=race_type,
                    custom_legs=legs, weekly_hours_available=hours,
                    limiter_discipline=limiter),
        thresholds=Thresholds(ftp_watts=250, run_threshold_pace_sec_per_km=280,
                              swim_css_sec_per_100m=100, run_lthr=165, max_hr=185),
    )


def is_interval_workout(w) -> bool:
    """Quality = any step at Z4+ (or ≥Z3 repeats / sweet-spot %FTP)."""
    def hard(s: WorkoutStep) -> bool:
        t = s.target
        if t.type == TargetType.POWER_PERCENT_FTP and (t.pct_of_anchor or 0) >= 0.85:
            return True
        return t.zone is not None and t.zone >= 4
    for item in w.steps:
        steps = [item] if isinstance(item, WorkoutStep) else item.steps
        if any(hard(s) for s in steps):
            return True
    return False


def check(persona: str, profile: AthleteProfile) -> list[str]:
    problems = []
    today = date.today()
    mon = today - timedelta(days=today.weekday())
    titles_by_week = []
    tss_by_week = []
    phase_by_week = []
    for k in range(3):
        wk = generate_week(profile, week_start=mon + timedelta(weeks=k))
        tss_by_week.append(wk.target_tss)
        phase_by_week.append(wk.phase)
        by_sport: dict[str, int] = {}
        for w in wk.workouts:
            g = ("swim" if w.sport == Sport.SWIM else
                 "strength" if w.sport == Sport.STRENGTH else
                 "run" if w.sport == Sport.RUN else "bike")
            by_sport[g] = by_sport.get(g, 0) + 1
        tri_n = sum(v for k2, v in by_sport.items() if k2 != "strength")
        intervals = [w for w in wk.workouts if w.sport != Sport.STRENGTH and is_interval_workout(w)]
        interval_sports = {w.sport for w in intervals}
        titles = [w.title for w in wk.workouts if w.sport != Sport.STRENGTH]
        titles_by_week.append(set(titles))

        # invariants
        need = 1 if tri_n <= 5 else 2
        if len(interval_sports) < need:
            problems.append(f"wk{k+1}: only {len(interval_sports)} interval sport(s), need {need}")
        if by_sport.get("strength", 0) > by_sport.get("swim", 99):
            problems.append(f"wk{k+1}: strength ({by_sport.get('strength')}) > swim ({by_sport.get('swim')})")
        from domain.athlete import race_distances
        sw, bi, ru = race_distances(profile.goals)
        if sw == 0 and by_sport.get("swim"):
            problems.append(f"wk{k+1}: swim sessions for a race with no swim leg")
        if ru == 0 and by_sport.get("run"):
            problems.append(f"wk{k+1}: run sessions for a race with no run leg")
        if bi == 0 and by_sport.get("bike"):
            problems.append(f"wk{k+1}: bike sessions for a race with no bike leg")

        if k == 0:
            mix = " ".join(f"{s}:{n}" for s, n in sorted(by_sport.items()))
            print(f"  wk1 [{wk.phase.value}] target {wk.target_tss:4.0f} | {mix} | "
                  f"intervals: {', '.join(sorted(w.title.split(' (')[0] for w in intervals)) or '—'}")
    # variety: consecutive weeks shouldn't be identical
    if titles_by_week[0] == titles_by_week[1] == titles_by_week[2]:
        problems.append("weeks 1-3 have identical session titles (no variety)")

    # within a Base/Build loading block, consecutive weeks must meaningfully
    # differ in target TSS (either climbing through the block, or resetting
    # at a recovery week) — never sit flat week over week
    for a, b in ((0, 1), (1, 2)):
        if phase_by_week[a] in (Phase.BASE, Phase.BUILD) and phase_by_week[a] == phase_by_week[b]:
            t1, t2 = tss_by_week[a], tss_by_week[b]
            if t1 > 0 and abs(t2 - t1) / t1 < 0.03:
                problems.append(f"wk{a+1}->wk{a+2}: target_tss barely changes ({t1}->{t2}), no ramp")

    # full-plan progression + race-week checks
    race_date = profile.goals.race_date
    week_start = mon
    by_phase_hours: dict[str, list[float]] = {}
    race_week = None
    guard = 0
    while week_start <= race_date and guard < 60:
        wk = generate_week(profile, week_start=week_start)
        hours = sum(w.total_duration_minutes for w in wk.workouts) / 60
        by_phase_hours.setdefault(wk.phase.value, []).append(hours)
        if wk.phase.value == "Taper" and (race_date - week_start).days < 7:
            race_week = wk
        week_start += timedelta(days=7)
        guard += 1

    if "Base" in by_phase_hours and "Peak" in by_phase_hours:
        base_avg = sum(by_phase_hours["Base"]) / len(by_phase_hours["Base"])
        peak_avg = sum(by_phase_hours["Peak"]) / len(by_phase_hours["Peak"])
        if peak_avg <= base_avg * 1.15:
            problems.append(f"Peak avg {peak_avg:.1f}h isn't meaningfully above Base avg {base_avg:.1f}h")

    if race_week is not None:
        n = len(race_week.workouts)
        hours = sum(w.total_duration_minutes for w in race_week.workouts) / 60
        if not (1 <= n <= 3):
            problems.append(f"race week has {n} sessions, expected 1-3")
        if any(w.sport == Sport.STRENGTH for w in race_week.workouts):
            problems.append("race week includes a strength session")
        if hours > 3.5:
            problems.append(f"race week is {hours:.1f}h, expected a short taper (<=3.5h)")

    return problems


def main() -> None:
    failures = 0
    for persona, race_type, hours, limiter, legs in PERSONAS:
        print(f"\n== {persona} ==")
        problems = check(persona, make_profile(race_type, hours, limiter, legs))
        for p in problems:
            failures += 1
            print(f"  PROBLEM: {p}")
        if not problems:
            print("  OK — all invariants hold")
    print(f"\n{'ALL PERSONAS PASS' if failures == 0 else f'{failures} PROBLEM(S)'}")
    raise SystemExit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
