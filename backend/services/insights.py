"""
AI coaching insights via the Claude API.

Interprets the athlete's current Performance Management Chart (CTL/ATL/TSB) and
plan context into a short, actionable coaching note. Requires ANTHROPIC_API_KEY.
"""
from __future__ import annotations
import os

import anthropic

_MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You are an expert triathlon coach analysing an athlete's Performance "
    "Management Chart for a 70.3 (Half Ironman) build. CTL is fitness "
    "(42-day load), ATL is fatigue (7-day load), TSB = CTL - ATL is form: "
    "below -25 is heavily fatigued, -25 to -10 is productive training, -10 to "
    "+5 is neutral, above +5 is fresh/tapered. Give a concise, specific "
    "coaching insight in 2-3 sentences about what these numbers mean for "
    "training decisions right now. No preamble, no greeting, no markdown headers."
)


def insights_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def generate_insight(context: dict) -> str:
    """
    context keys: ctl, atl, tsb, phase, weeks_to_race, target_tss,
    planned_tss, rationale, recent_7d_tss, recent_28d_tss.
    """
    if not insights_available():
        raise EnvironmentError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic()
    user = (
        f"Current fitness — CTL {context['ctl']}, ATL {context['atl']}, "
        f"TSB {context['tsb']}.\n"
        f"Phase: {context['phase']}, {context['weeks_to_race']} weeks to race.\n"
        f"This week's plan: {context['planned_tss']} TSS planned "
        f"(target {context['target_tss']}). Engine rationale: {context['rationale']}.\n"
        f"Recent load: last 7 days {context.get('recent_7d_tss', 'n/a')} TSS, "
        f"last 28 days {context.get('recent_28d_tss', 'n/a')} TSS.\n"
        f"Give the athlete a short coaching insight for today."
    )

    resp = client.messages.create(
        model=_MODEL,
        max_tokens=400,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
