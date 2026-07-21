"""
Persona simulator — fabricates athletes with different races/hours and prints
each one's generated week(s) so plan quality can be eyeballed + sanity-checked.

Run:  cd backend && python -m scripts.simulate_personas
"""
from __future__ import annotations
from datetime import date, timedelta

from domain.athlete import (
    AthleteProfile, Goals, Thresholds, RaceType, RaceGoal, CustomLeg, Discipline,
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


def hard_seconds(w) -> int:
    """Total seconds spent at Z4+ (or ≥85% FTP) in a workout."""
    total = 0
    for item in w.steps:
        pairs = ([(item, 1)] if isinstance(item, WorkoutStep)
                 else [(s, item.repeat_count) for s in item.steps])
        for s, n in pairs:
            t = s.target
            hot = ((t.zone or 0) >= 4
                   or (t.type == TargetType.POWER_PERCENT_FTP and (t.pct_of_anchor or 0) >= 0.85))
            if hot:
                total += s.duration_seconds * n
    return total


def cross_profile_checks() -> list[str]:
    """Invariants that compare PAIRS of profiles (hours scaling, goal intensity)."""
    problems = []
    today = date.today()
    mon = today - timedelta(days=today.weekday())

    # Declared hours are the volume anchor: double the hours ≈ double the time.
    # Sum across 4 weeks (a full load/recovery block) so the ratio doesn't swing
    # with whichever phase/dose today's calendar week happens to land on — a
    # single recovery week's fixed session-floors would otherwise compress it.
    lo = make_profile(RaceType.MIDDLE_TRI, 6, None, None)
    hi = make_profile(RaceType.MIDDLE_TRI, 12, None, None)
    weeks = [mon + timedelta(weeks=k) for k in range(4)]
    min_lo = sum(w.total_duration_minutes for wk in weeks for w in generate_week(lo, week_start=wk).workouts)
    min_hi = sum(w.total_duration_minutes for wk in weeks for w in generate_week(hi, week_start=wk).workouts)
    print(f"  hours scaling (4-wk block): 6h persona plans {min_lo / 60:.1f}h, 12h persona plans {min_hi / 60:.1f}h")
    if not min_hi > min_lo * 1.7:
        problems.append(f"12h persona only plans {min_hi / min_lo:.2f}x the 6h persona's time (no hours scaling)")

    # Ambitious target time on the same hours -> hotter block, not a bigger one.
    # Measured over the 4-week block: total Z4+ ("hard") seconds is the robust
    # signal; a single week's interval-sport COUNT saturates (easy-session
    # strides incidentally hit Z5), so that's only required to be >=, not >.
    std = make_profile(RaceType.MIDDLE_TRI, 10, None, None)
    agg = make_profile(RaceType.MIDDLE_TRI, 10, None, None)
    agg.goals.goal = RaceGoal.TARGET_TIME
    agg.goals.target_finish_seconds = int(4.5 * 3600)  # 4h30 in a 70.3 — ambitious
    wk_std = [generate_week(std, week_start=wk) for wk in weeks]
    wk_agg = [generate_week(agg, week_start=wk) for wk in weeks]
    ints_std = max(len({w.sport for w in wk.workouts if w.sport != Sport.STRENGTH and is_interval_workout(w)}) for wk in wk_std)
    ints_agg = max(len({w.sport for w in wk.workouts if w.sport != Sport.STRENGTH and is_interval_workout(w)}) for wk in wk_agg)
    hard_std = sum(hard_seconds(w) for wk in wk_std for w in wk.workouts if w.sport != Sport.STRENGTH)
    hard_agg = sum(hard_seconds(w) for wk in wk_agg for w in wk.workouts if w.sport != Sport.STRENGTH)
    print(f"  goal intensity (4-wk block): finish max {ints_std} interval sports / {hard_std // 60}min hard; "
          f"4h30 target {ints_agg} / {hard_agg // 60}min hard")
    if ints_agg < ints_std:
        problems.append(f"4h30 target peaks at {ints_agg} interval sports vs finisher's {ints_std} — less varied intensity")
    if hard_agg <= hard_std:
        problems.append(f"4h30 target has {hard_agg}s hard vs finisher's {hard_std}s over the block — not hotter")
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

    print("\n== cross-profile (hours scaling + goal intensity) ==")
    problems = cross_profile_checks()
    for p in problems:
        failures += 1
        print(f"  PROBLEM: {p}")
    if not problems:
        print("  OK — all invariants hold")

    print(f"\n{'ALL PERSONAS PASS' if failures == 0 else f'{failures} PROBLEM(S)'}")
    raise SystemExit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
