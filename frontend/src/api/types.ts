// Types mirroring the FastAPI backend responses.

export type Sport =
  | "swim" | "bike_outdoor" | "bike_indoor" | "run" | "brick" | "strength";

export interface Fitness {
  ctl: number;
  atl: number;
  tsb: number;
}

export interface Thresholds {
  ftp_watts: number;
  run_threshold_pace_sec_per_km: number;
  run_lthr: number | null;
  swim_css_sec_per_100m: number;
  max_hr: number | null;
}

export interface CustomLeg {
  discipline: string;
  distance_m: number;
}

export interface Goals {
  race_date: string;
  race_type: string;
  custom_legs: CustomLeg[] | null;
  goal: string;
  target_finish_seconds: number | null;
  weekly_hours_available: number;
  limiter_discipline: string | null;
}

export interface RaceTypeOption {
  key: string;
  label: string;
  swim_m: number;
  bike_m: number;
  run_m: number;
  description: string;
}

export interface TrainingPreferences {
  sport_distribution: Record<string, number>;
  strength_sessions_per_week: number;
  measured_tss_per_hour: Record<string, number> | null;
}

export interface AthleteProfile {
  name: string;
  goals: Goals;
  thresholds: Thresholds;
  fitness: { ctl: number; atl: number };
  preferences: TrainingPreferences;
}

export interface WorkoutSummary {
  title: string;
  sport: Sport;
  date: string;
  duration_min: number;
  planned_tss: number;
}

export interface WeekPlan {
  week_start: string;
  phase: string;
  target_tss: number;
  planned_tss: number;
  fitness: Fitness;
  weeks_to_race: number;
  rationale: string;
  workouts: WorkoutSummary[];
}

export interface PlanWeekRow {
  week_start: string;
  phase: string;
  weeks_to_race: number;
  target_tss: number;
  planned_tss: number;
  ctl: number;
  atl: number;
  tsb: number;
  rationale: string;
}

export interface FullPlan {
  race_date: string;
  start_week: string;
  total_weeks: number;
  projected_peak_ctl: number;
  race_day_fitness: Fitness;
  weeks: PlanWeekRow[];
}

export interface WorkoutStepDetail {
  kind: "step" | "repeat";
  name?: string;
  duration_seconds?: number;
  distance_meters?: number | null;
  target?: { type: string; zone: number | null; pct_of_anchor: number | null };
  notes?: string;
  repeat_count?: number;
  steps?: WorkoutStepDetail[];
}

export interface WorkoutDetail extends WorkoutSummary {
  description: string;
  steps: WorkoutStepDetail[];
}

export interface DayPlan {
  date: string;
  sessions: WorkoutDetail[];
}

export interface GarminStatus {
  connected: boolean;
}

export interface PmcPoint {
  date: string;
  ctl: number;
  atl: number;
  tsb: number;
}

export interface TssDay {
  date: string;
  swim: number;
  bike: number;
  run: number;
  strength: number;
  other: number;
}

export interface FitnessHistory {
  days: number;
  series: PmcPoint[];
  tss_by_day: TssDay[];
}

export interface Insight {
  insight: string;
  context: Record<string, unknown>;
}

export interface ZoneOut {
  number: number;
  name: string;
  low: number;
  high: number | null;
}

export interface ZonesResponse {
  bike_power: ZoneOut[];
  bike_hr: ZoneOut[];
  run_hr: ZoneOut[];
  run_pace: ZoneOut[];
  swim_pace: ZoneOut[];
}
