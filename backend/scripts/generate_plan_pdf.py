"""
One-off report generator: renders every planned workout from today through
race day into a detailed PDF, so the plan engine's output can be reviewed
end-to-end by a human. Not part of the running app — a reporting tool.

Run:  cd backend && PYTHONPATH=. .venv/Scripts/python.exe scripts/generate_plan_pdf.py [--test]
  --test limits output to the first 2 weeks (fast smoke test of rendering).
"""
from __future__ import annotations
import math
import sys
from datetime import date, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
)

from domain.profile_store import load_profile
from domain.zones import compute_zones
from domain.periodization import generate_week
from domain.athlete import RACE_TYPES

OUT_PATH = r"C:\Users\david\Downloads\TriFlow_Training_Plan_2026-07-05_to_2026-10-18.pdf"

SPORT_LABEL = {
    "swim": "Swim", "bike_outdoor": "Bike (Outdoor)", "bike_indoor": "Bike (Indoor)",
    "run": "Run", "brick": "Brick", "strength": "Strength",
}
EQUIP_LABEL = {
    "pull_buoy": "pull buoy", "kickboard": "kickboard", "fins": "fins",
    "paddles": "paddles", "paddles_buoy": "paddles + buoy", "paddles_fins": "paddles + fins",
    "snorkel": "snorkel",
}
STROKE_LABEL = {"back": "backstroke", "breast": "breaststroke", "drill": "drill", "mixed": "mixed strokes"}


def mmss(sec: float) -> str:
    sec = round(sec)
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def fmt_duration(seconds: float) -> str:
    seconds = round(seconds)
    m, s = divmod(int(seconds), 60)
    if m == 0:
        return f"{s}s"
    if s == 0:
        return f"{m}m"
    return f"{m}m{s:02d}"


class ZoneTables:
    """Precomputed zone -> real-value lookup, so steps show actual pace/power/HR."""

    def __init__(self, thresholds):
        z = compute_zones(thresholds)
        self.ftp = thresholds.ftp_watts
        self.bike_power = {x.number: x for x in z.bike_power}
        self.bike_hr = {x.number: x for x in z.bike_hr}
        self.run_hr = {x.number: x for x in z.run_hr}
        self.run_pace = {x.number: x for x in z.run_pace}
        self.swim_pace = {x.number: x for x in z.swim_pace}

    def power_range(self, num: int) -> str:
        zn = self.bike_power[num]
        if zn.low <= 0.5:
            return f"<{round(zn.high)}W"
        if math.isinf(zn.high):
            return f">{round(zn.low)}W"
        return f"{round(zn.low)}-{round(zn.high)}W"

    def hr_range(self, table: dict, num: int) -> str:
        zn = table[num]
        if math.isinf(zn.high):
            return f">{round(zn.low)}bpm"
        return f"{round(zn.low)}-{round(zn.high)}bpm"

    def pace_range(self, table: dict, num: int, unit: str) -> str:
        zn = table[num]
        if math.isinf(zn.high):
            return f">{mmss(zn.low)}{unit}"
        return f"{mmss(zn.low)}-{mmss(zn.high)}{unit}"


def format_target(target: dict | None, sport: str, z: ZoneTables) -> str:
    if not target:
        return "free / easy (no target)"
    ttype = target.get("type")
    zone = target.get("zone")
    pct = target.get("pct_of_anchor")
    if ttype in (None, "open"):
        return "free / easy (no target)"
    if ttype == "power_pct":
        watts = round(z.ftp * (pct or 0))
        return f"{round((pct or 0) * 100)}% FTP (~{watts}W)"
    if ttype == "power_zone":
        return f"Z{zone} power {z.power_range(zone)}"
    if ttype == "hr_zone":
        table = z.bike_hr if sport in ("bike_outdoor", "bike_indoor") else z.run_hr
        return f"Z{zone} HR {z.hr_range(table, zone)}"
    if ttype == "pace_zone":
        if sport == "swim":
            return f"Z{zone} pace {z.pace_range(z.swim_pace, zone, '/100m')}"
        return f"Z{zone} pace {z.pace_range(z.run_pace, zone, '/km')}"
    return ttype or ""


def step_extras(step: dict) -> str:
    bits = []
    if step.get("rest_seconds"):
        bits.append(f"{step['rest_seconds']}s rest")
    if step.get("equipment"):
        bits.append(EQUIP_LABEL.get(step["equipment"], step["equipment"]))
    if step.get("stroke") and step["stroke"] != "free":
        bits.append(STROKE_LABEL.get(step["stroke"], step["stroke"]))
    if step.get("notes"):
        bits.append(step["notes"])
    return f" ({', '.join(bits)})" if bits else ""


def step_line(step: dict, sport: str, z: ZoneTables) -> str:
    if step.get("distance_meters"):
        size = f"{step['distance_meters']}m (~{fmt_duration(step.get('duration_seconds') or 0)})"
    else:
        size = fmt_duration(step.get("duration_seconds") or 0)
    target = format_target(step.get("target"), sport, z)
    name = step.get("name") or "Step"
    return f"{name} — {size} — {target}{step_extras(step)}"


def block_items(steps: list[dict], sport: str, z: ZoneTables, style_main: ParagraphStyle,
                style_sub: ParagraphStyle) -> list:
    items = []
    for block in steps:
        if block.get("kind") == "repeat":
            inner = block.get("steps", [])
            count = block.get("repeat_count", 1)
            if len(inner) <= 1 and inner:
                line = f"{count}× {step_line(inner[0], sport, z)}"
                items.append(ListItem(Paragraph(line, style_main)))
            else:
                header_text = (f"{len(inner)}-step sequence:" if count == 1
                              else f"{count}× {len(inner)}-step interval:")
                header = Paragraph(header_text, style_main)
                sub_items = [ListItem(Paragraph(step_line(s, sport, z), style_sub)) for s in inner]
                sub_list = ListFlowable(sub_items, bulletType="bullet", start="circle", leftIndent=18)
                items.append(ListItem([header, sub_list]))
        else:
            items.append(ListItem(Paragraph(step_line(block, sport, z), style_main)))
    return items


def build_pdf(test_mode: bool = False) -> None:
    profile = load_profile()
    z = ZoneTables(profile.thresholds)

    today = date.today()
    race_date = profile.goals.race_date
    week_start = today - timedelta(days=today.weekday())
    race_label = RACE_TYPES.get(profile.goals.race_type.value, {}).get("label", profile.goals.race_type.value)

    styles = getSampleStyleSheet()
    week_style = ParagraphStyle("Week", parent=styles["Heading2"], spaceBefore=18, spaceAfter=4,
                                textColor=colors.HexColor("#0b5346"))
    date_style = ParagraphStyle("DateHeading", parent=styles["Heading3"], spaceBefore=10, spaceAfter=2)
    workout_style = ParagraphStyle("Workout", parent=styles["Heading4"], spaceBefore=6, spaceAfter=2,
                                   textColor=colors.HexColor("#14785f"))
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=8.5, textColor=colors.grey,
                               spaceAfter=4)
    rest_style = ParagraphStyle("Rest", parent=styles["Normal"], textColor=colors.grey, spaceAfter=2,
                                fontName="Helvetica-Oblique")
    step_style = ParagraphStyle("Step", parent=styles["Normal"], fontSize=9.5, leading=13)
    sub_style = ParagraphStyle("Sub", parent=step_style, fontSize=9, textColor=colors.HexColor("#333333"))

    story = []
    story.append(Paragraph("TriFlow Training Plan", styles["Title"]))
    story.append(Paragraph(
        f"{profile.name} · {race_label} · Race day: {race_date.strftime('%A, %B %d, %Y')}",
        styles["Normal"]))
    story.append(Paragraph(
        f"Generated {today.strftime('%B %d, %Y')} — every planned session from today through race day.",
        styles["Normal"]))
    story.append(Paragraph(
        "Note: this plan is fitness-adaptive. Weeks are projected from today's CTL/ATL/TSB and the "
        "current profile settings; they will re-adjust automatically as real training data comes in "
        "via Garmin sync. Treat this as a snapshot, not a fixed prescription.", meta_style))
    story.append(Spacer(1, 12))

    total_workouts = 0
    weeks_done = 0
    while week_start <= race_date:
        wk = generate_week(profile, week_start=week_start)
        story.append(Paragraph(
            f"Week of {week_start.strftime('%B %d, %Y')} — {wk.phase.value} phase — "
            f"target {wk.target_tss:.0f} TSS ({wk.planned_tss:.0f} planned)",
            week_style))
        story.append(Paragraph(wk.rationale, meta_style))

        by_day: dict[date, list] = {}
        for w in wk.workouts:
            by_day.setdefault(w.scheduled_date, []).append(w)

        for i in range(7):
            day = week_start + timedelta(days=i)
            if day < today or day > race_date:
                continue
            story.append(Paragraph(day.strftime("%A %d %B, %Y:"), date_style))
            sessions = by_day.get(day, [])
            if not sessions:
                story.append(Paragraph("Rest day", rest_style))
                continue
            for w in sessions:
                total_workouts += 1
                d = w.detail()
                story.append(Paragraph(d["title"], workout_style))
                story.append(Paragraph(
                    f"{SPORT_LABEL.get(d['sport'], d['sport'])} · {d['duration_min']} min · "
                    f"{d['planned_tss']} TSS", meta_style))
                items = block_items(d["steps"], d["sport"], z, step_style, sub_style)
                story.append(ListFlowable(items, bulletType="bullet", leftIndent=14))
                story.append(Spacer(1, 4))

        week_start += timedelta(days=7)
        weeks_done += 1
        if test_mode and weeks_done >= 2:
            break

    out_path = OUT_PATH.replace(".pdf", "_TEST.pdf") if test_mode else OUT_PATH
    doc = SimpleDocTemplate(out_path, pagesize=LETTER,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            title="TriFlow Training Plan")
    doc.build(story)
    print(f"Wrote {out_path} — {weeks_done} weeks, {total_workouts} workouts")


if __name__ == "__main__":
    build_pdf(test_mode="--test" in sys.argv)
