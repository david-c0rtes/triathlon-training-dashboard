"""
Training-load constants for the sport-weighted TSS model.

Two distinct concepts (kept separate on purpose):

1. THRESHOLD_HOUR_TSS — the intensity scaling constant. One hour AT THRESHOLD
   (IF = 1.0) is worth this many TSS, and it differs per sport (running is more
   taxing than cycling than swimming for the same relative intensity). The core
   formula is:  TSS = hours * IF**2 * THRESHOLD_HOUR_TSS[sport].

2. DEFAULT_TSS_PER_HOUR — a rough AVERAGE accrual rate per sport, used only to
   convert available hours into a weekly TSS ceiling and to split the weekly
   target across sports. These placeholders are replaced by the athlete's own
   90-day rolling average once enough activity data exists.

Keys are plain strings ("swim"/"bike"/"run"/"strength") so this module stays
import-free and avoids cycles with domain.workout.
"""
from __future__ import annotations

# 1 hour at threshold (IF = 1.0) → this many TSS
THRESHOLD_HOUR_TSS = {"swim": 60, "bike": 100, "run": 140}

# Placeholder average accrual rates (TSS per hour) — overridden by rolling avg
DEFAULT_TSS_PER_HOUR = {"run": 80, "bike": 55, "swim": 45, "strength": 38}

# Strength is flat — no intensity factor, just time on task
STRENGTH_TSS_PER_HOUR = 38
