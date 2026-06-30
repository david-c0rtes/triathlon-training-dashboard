import type {
  AthleteProfile, FullPlan, WeekPlan, DayPlan, GarminStatus,
  FitnessHistory, Insight, ZonesResponse, RaceTypeOption,
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
  garminStatus: () => get<GarminStatus>("/garmin/status"),
  garminSync: (days = 90) => post<unknown>(`/garmin/sync?days=${days}`),
  history: (days = 90) => get<FitnessHistory>(`/garmin/history?days=${days}`),
  insights: () => get<Insight>("/insights"),
};
