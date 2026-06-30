import type { Sport } from "../api/types";

export const SPORT_LABEL: Record<Sport, string> = {
  swim: "Swim",
  bike_outdoor: "Bike · Outdoor",
  bike_indoor: "Bike · Indoor",
  run: "Run",
  brick: "Brick",
  strength: "Strength",
};

// CSS color values (match the design tokens)
export const SPORT_COLOR: Record<Sport, string> = {
  swim: "#adc6ff",          // velocity blue
  bike_outdoor: "#4fdbc8",  // effort teal
  bike_indoor: "#4fdbc8",
  run: "#4ae176",           // zone green
  brick: "#ffd34f",
  strength: "#859490",
};

export const PHASE_COLOR: Record<string, string> = {
  Base: "#adc6ff",
  Build: "#4fdbc8",
  Peak: "#4ae176",
  Taper: "#ffd34f",
  Race: "#ffb4ab",
};

export function tsbColor(tsb: number): string {
  if (tsb < -20) return "#ffb4ab";   // very fatigued (error)
  if (tsb < -5) return "#ffd34f";    // building
  if (tsb <= 10) return "#4fdbc8";   // neutral / sharp
  return "#4ae176";                  // fresh
}

export function fmtDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function fmtWeekday(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short" });
}

export function fmtDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

// ── seconds <-> mm:ss (pace) ──────────────────────────────────────────────────
export function secToMmss(sec: number): string {
  if (!sec || sec <= 0) return "";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function mmssToSec(str: string): number | null {
  const m = str.trim().match(/^(\d+):([0-5]?\d)$/);
  if (!m) return null;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

// ── seconds <-> h:mm (race finish time) ───────────────────────────────────────
export function secToHhmm(sec: number | null): string {
  if (!sec || sec <= 0) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}`;
}

export function hhmmToSec(str: string): number | null {
  const m = str.trim().match(/^(\d+):([0-5]?\d)$/);
  if (!m) return null;
  return parseInt(m[1], 10) * 3600 + parseInt(m[2], 10) * 60;
}
