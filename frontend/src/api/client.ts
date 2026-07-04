import type {
  AthleteProfile, FullPlan, WeekPlan, DayPlan, GarminStatus,
  FitnessHistory, Insight, ZonesResponse, RaceTypeOption,
  NextSession, WorkoutDetail, PushResult,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const PREFIX = `${API_BASE}/api/v1`;

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${PREFIX}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`${PREFIX}${path}`, { method: "POST" });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

// FastAPI returns `detail` as a string (HTTPException) or an array of error
// objects (422 validation). Normalize both to a readable message.
function extractDetail(json: unknown, fallback: string): string {
  const d = (json as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    const msgs = d
      .map((e) => String((e as { msg?: string })?.msg ?? "").replace(/^Value error,\s*/, ""))
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  return fallback;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${PREFIX}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = extractDetail(await res.json(), msg); } catch { /* keep status */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${PREFIX}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PUT ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  profile: () => get<AthleteProfile>("/profile"),
  saveProfile: (p: AthleteProfile) => put<AthleteProfile>("/profile", p),
  zones: () => get<ZonesResponse>("/zones"),
  raceTypes: () => get<RaceTypeOption[]>("/race-types"),
  fullPlan: () => get<FullPlan>("/plan/full"),
  week: (weekStart?: string) =>
    get<WeekPlan>(`/plan/week${weekStart ? `?week_start=${weekStart}` : ""}`),
  day: (day: string) => get<DayPlan>(`/plan/day?day=${day}`),
  tomorrow: () => get<DayPlan>("/plan/tomorrow"),
  nextSession: () => get<NextSession>("/plan/next"),
  previewWorkout: (w: WorkoutDetail) => postJson<WorkoutDetail>("/plan/preview", w),
  pushWorkout: (w: WorkoutDetail) => postJson<PushResult>("/garmin/push-workout", w),
  garminStatus: () => get<GarminStatus>("/garmin/status"),
  garminSync: (days = 90) => post<unknown>(`/garmin/sync?days=${days}`),
  history: (days = 90) => get<FitnessHistory>(`/garmin/history?days=${days}`),
  insights: () => get<Insight>("/insights"),

  // Download the .zwo for an edited indoor-bike workout (triggers a file save).
  async downloadZwo(w: WorkoutDetail): Promise<void> {
    const res = await fetch(`${PREFIX}/garmin/zwo-file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(w),
    });
    if (!res.ok) {
      let detail = `${res.status}`;
      try { detail = (await res.json()).detail ?? detail; } catch { /* keep status */ }
      throw new Error(String(detail));
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") ?? "";
    const match = cd.match(/filename="?([^"]+)"?/);
    const filename = match?.[1] ?? `${w.date}_${w.title}.zwo`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
