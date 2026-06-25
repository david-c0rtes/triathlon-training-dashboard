import type {
  AthleteProfile, FullPlan, WeekPlan, DayPlan, GarminStatus,
  FitnessHistory, Insight,
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

export const api = {
  profile: () => get<AthleteProfile>("/profile"),
  fullPlan: () => get<FullPlan>("/plan/full"),
  week: (weekStart?: string) =>
    get<WeekPlan>(`/plan/week${weekStart ? `?week_start=${weekStart}` : ""}`),
  day: (day: string) => get<DayPlan>(`/plan/day?day=${day}`),
  tomorrow: () => get<DayPlan>("/plan/tomorrow"),
  garminStatus: () => get<GarminStatus>("/garmin/status"),
  garminSync: (days = 90) => post<unknown>(`/garmin/sync?days=${days}`),
  history: (days = 90) => get<FitnessHistory>(`/garmin/history?days=${days}`),
  insights: () => get<Insight>("/insights"),
};
