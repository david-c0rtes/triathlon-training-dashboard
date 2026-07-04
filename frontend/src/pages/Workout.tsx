import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  NextSession, WorkoutDetail, WorkoutStepDetail, WeekPlan, Sport,
  ZonesResponse, ZoneOut,
} from "../api/types";
import { Card, SectionTitle, MonoLabel } from "../components/Card";
import {
  SPORT_COLOR, PHASE_COLOR, tsbColor, fmtDate, fmtWeekday,
  fmtDuration, secToMmss, mmssToSec,
} from "../lib/format";

// Training-zone palette (matches the --color-zone-* tokens / intensity-bar motif)
const ZONE_COLOR: Record<number, string> = {
  1: "#859490", 2: "#adc6ff", 3: "#4fdbc8", 4: "#4ae176", 5: "#ffd34f", 6: "#ffb4ab",
};

const inputBase =
  "bg-surface-container-high border border-outline-variant/50 rounded-btn px-2 py-1 " +
  "font-mono text-sm text-on-surface focus:border-primary focus:outline-none";

type Metric = { duration_min: number; planned_tss: number; loading: boolean; error?: string };
type ActionState = { state: "idle" | "working" | "done" | "error"; msg?: string };
type BlockKind = "steady" | "interval2" | "interval3";

const BIKE_SPORTS = new Set(["bike_indoor", "bike_outdoor"]);

// ── block/step construction helpers (pure) ────────────────────────────────────

function targetFor(sport: Sport, zone: number): WorkoutStepDetail["target"] {
  if (BIKE_SPORTS.has(sport)) return { type: "power_zone", zone, pct_of_anchor: null };
  if (sport === "run" || sport === "swim" || sport === "brick")
    return { type: "pace_zone", zone, pct_of_anchor: null };
  return { type: "open", zone: null, pct_of_anchor: null };
}

function makeStep(name: string, seconds: number, sport: Sport, zone: number): WorkoutStepDetail {
  return {
    kind: "step", name, duration_seconds: seconds, distance_meters: null,
    notes: "", target: targetFor(sport, zone),
  };
}

function makeFreshBlock(type: BlockKind, sport: Sport): WorkoutStepDetail {
  if (type === "steady") return makeStep("Active", 1200, sport, 2);
  if (type === "interval2")
    return {
      kind: "repeat", repeat_count: 4,
      steps: [makeStep("Interval", 180, sport, 4), makeStep("Recovery", 90, sport, 1)],
    };
  return {
    kind: "repeat", repeat_count: 3,
    steps: [makeStep("Interval", 180, sport, 4), makeStep("Float", 120, sport, 3), makeStep("Recovery", 90, sport, 1)],
  };
}

function blockKindOf(block: WorkoutStepDetail): BlockKind {
  if (block.kind !== "repeat") return "steady";
  return (block.steps?.length ?? 2) >= 3 ? "interval3" : "interval2";
}

/** Convert a block to another type, preserving existing steps where possible. */
function convertBlock(block: WorkoutStepDetail, type: BlockKind, sport: Sport): WorkoutStepDetail {
  const existing = block.kind === "repeat" ? (block.steps ?? []) : [block];
  const rc = block.kind === "repeat" ? (block.repeat_count ?? 4) : 4;
  if (type === "steady") {
    const first = existing[0] ?? makeStep("Active", 1200, sport, 2);
    return { ...first, kind: "step", target: normalizeTarget(first.target, sport) };
  }
  const count = type === "interval2" ? 2 : 3;
  const names = count === 2 ? ["Interval", "Recovery"] : ["Interval", "Float", "Recovery"];
  const zones = count === 2 ? [4, 1] : [4, 3, 1];
  const durs = count === 2 ? [180, 90] : [180, 120, 90];
  const steps = Array.from({ length: count }, (_, i) =>
    existing[i]
      ? { ...existing[i], kind: "step" as const, target: normalizeTarget(existing[i].target, sport) }
      : makeStep(names[i], durs[i], sport, zones[i]),
  );
  return { kind: "repeat", repeat_count: rc, steps };
}

// ── zone-range labelling (pulls the athlete's actual watts/bpm/pace ranges) ────

function zoneListFor(
  type: string, sport: Sport, zones: ZonesResponse | null,
): { list?: ZoneOut[]; unit: string; pace: boolean } {
  if (!zones) return { unit: "", pace: false };
  if (type === "power_zone") return { list: zones.bike_power, unit: "W", pace: false };
  if (type === "hr_zone")
    return { list: BIKE_SPORTS.has(sport) ? zones.bike_hr : zones.run_hr, unit: "bpm", pace: false };
  if (type === "pace_zone")
    return sport === "swim"
      ? { list: zones.swim_pace, unit: "/100m", pace: true }
      : { list: zones.run_pace, unit: "/km", pace: true };
  return { unit: "", pace: false };
}

function fmtZoneRange(z: ZoneOut, unit: string, pace: boolean): string {
  const f = (v: number) => (pace ? secToMmss(v) : String(Math.round(v)));
  if (z.high == null) return pace ? `≥${f(z.low)} ${unit}` : `${f(z.low)}+ ${unit}`;
  const lo = f(Math.min(z.low, z.high));
  const hi = f(Math.max(z.low, z.high));
  return `${lo}–${hi} ${unit}`;
}

// ── intensity metric options (per sport) ──────────────────────────────────────
type IntensityMetric = "power_zone" | "power_pct" | "hr_zone" | "pace_zone" | "open";

function sportGroup(sport: Sport): "bike" | "run" | "swim" | "brick" | "strength" {
  return BIKE_SPORTS.has(sport) ? "bike" : (sport as "run" | "swim" | "brick" | "strength");
}

const METRIC_OPTIONS: Record<string, { value: IntensityMetric; label: string }[]> = {
  bike: [{ value: "power_zone", label: "Power" }, { value: "hr_zone", label: "HR" }, { value: "open", label: "Free" }],
  run: [{ value: "pace_zone", label: "Pace" }, { value: "hr_zone", label: "HR" }, { value: "open", label: "Free" }],
  swim: [{ value: "pace_zone", label: "Pace" }, { value: "open", label: "Free" }],
  brick: [
    { value: "power_zone", label: "Power" }, { value: "pace_zone", label: "Pace" },
    { value: "hr_zone", label: "HR" }, { value: "open", label: "Free" },
  ],
  strength: [{ value: "open", label: "Free" }],
};

const METRIC_LABEL: Record<IntensityMetric, string> = {
  power_zone: "Power", power_pct: "Power %", hr_zone: "HR", pace_zone: "Pace", open: "Free",
};

/** Build a fresh target when the user switches a step's intensity metric. */
function targetForMetric(metric: IntensityMetric, prev: WorkoutStepDetail["target"]): WorkoutStepDetail["target"] {
  if (metric === "open") return { type: "open", zone: null, pct_of_anchor: null };
  if (metric === "power_pct")
    return { type: "power_pct", zone: null, pct_of_anchor: prev?.pct_of_anchor ?? 0.75 };
  const max = metric === "power_zone" ? 6 : 5;
  const keep = prev?.zone && prev.zone >= 1 && prev.zone <= max ? prev.zone : (metric === "power_zone" ? 3 : 2);
  return { type: metric, zone: keep, pct_of_anchor: null };
}

// Intensity metrics each sport allows / defaults to (mirrors the backend rules).
const ALLOWED_METRICS: Record<string, Set<IntensityMetric>> = {
  bike: new Set(["power_zone", "power_pct", "hr_zone", "open"]),
  run: new Set(["pace_zone", "hr_zone", "open"]),
  swim: new Set(["pace_zone", "open"]),
  brick: new Set(["power_zone", "power_pct", "pace_zone", "hr_zone", "open"]),
  strength: new Set(["open"]),
};
const PRIMARY_METRIC: Record<string, IntensityMetric> = {
  bike: "power_zone", run: "pace_zone", swim: "pace_zone", brick: "pace_zone", strength: "open",
};

/**
 * Coerce a step's target so it's valid AND consistent for a sport.
 * - sports with no intensity (strength) → Free.
 * - "Free" or invalid metrics → the sport's primary metric (so all steps in a
 *   block share the same kind of target instead of one being left Free).
 * - an already-valid metric (e.g. HR, which both bike & run allow) is kept.
 */
function normalizeTarget(target: WorkoutStepDetail["target"], sport: Sport): WorkoutStepDetail["target"] {
  const g = sportGroup(sport);
  const primary = PRIMARY_METRIC[g];
  if (primary === "open") return { type: "open", zone: null, pct_of_anchor: null };
  const t = target ?? { type: "open", zone: null, pct_of_anchor: null };
  if (t.type === "open" || !ALLOWED_METRICS[g].has(t.type as IntensityMetric))
    return targetForMetric(primary, t);
  return t;
}

const SPORT_OPTIONS: { value: Sport; label: string }[] = [
  { value: "swim", label: "Swim" },
  { value: "bike_outdoor", label: "Bike · Outdoor" },
  { value: "bike_indoor", label: "Bike · Indoor" },
  { value: "run", label: "Run" },
  { value: "brick", label: "Brick" },
  { value: "strength", label: "Strength" },
];

export function Workout() {
  const [data, setData] = useState<NextSession | null>(null);
  const [week, setWeek] = useState<WeekPlan | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [zones, setZones] = useState<ZonesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [workouts, setWorkouts] = useState<WorkoutDetail[]>([]);
  const [metrics, setMetrics] = useState<Record<number, Metric>>({});
  const [actions, setActions] = useState<Record<number, ActionState>>({});

  const workoutsRef = useRef<WorkoutDetail[]>([]);
  const timers = useRef<Record<number, number>>({});

  useEffect(() => {
    Promise.all([api.nextSession(), api.week(), api.garminStatus()])
      .then(([next, w, s]) => {
        setData(next);
        setWeek(w);
        setConnected(s.connected);
        const sessions = next.sessions.map((x) => structuredClone(x));
        setWorkouts(sessions);
        workoutsRef.current = sessions;
        const m: Record<number, Metric> = {};
        sessions.forEach((x, i) => {
          m[i] = { duration_min: x.duration_min, planned_tss: x.planned_tss, loading: false };
        });
        setMetrics(m);
      })
      .catch((e) => setError(String(e)));
    // zones are optional (needs max_hr) — don't block the page on them
    api.zones().then(setZones).catch(() => setZones(null));
  }, []);

  function schedulePreview(idx: number, w: WorkoutDetail) {
    setMetrics((m) => ({ ...m, [idx]: { ...m[idx], loading: true } }));
    if (timers.current[idx]) window.clearTimeout(timers.current[idx]);
    timers.current[idx] = window.setTimeout(async () => {
      try {
        const r = await api.previewWorkout(w);
        setMetrics((m) => ({
          ...m,
          [idx]: { duration_min: r.duration_min, planned_tss: r.planned_tss, loading: false },
        }));
      } catch (e) {
        // Surface the backend's validation message (see the error banner on the card).
        setMetrics((m) => ({ ...m, [idx]: { ...m[idx], loading: false, error: String(e) } }));
      }
    }, 450);
  }

  function commit(idx: number, w: WorkoutDetail) {
    const next = [...workoutsRef.current];
    next[idx] = w;
    workoutsRef.current = next;
    setWorkouts(next);
    setActions((a) => (a[idx] ? { ...a, [idx]: { state: "idle" } } : a));
    schedulePreview(idx, w);
  }

  function patchStep(
    wIdx: number, topIdx: number, innerIdx: number | null, patch: Partial<WorkoutStepDetail>,
  ) {
    const w = structuredClone(workoutsRef.current[wIdx]);
    const target = innerIdx == null ? w.steps[topIdx] : w.steps[topIdx].steps![innerIdx];
    Object.assign(target, patch);
    commit(wIdx, w);
  }

  function patchWorkout(wIdx: number, patch: Partial<WorkoutDetail>) {
    const w = structuredClone(workoutsRef.current[wIdx]);
    Object.assign(w, patch);
    commit(wIdx, w);
  }

  function changeSport(wIdx: number, sport: Sport) {
    const w = structuredClone(workoutsRef.current[wIdx]);
    // Re-target steps only when the sport family changes (bike↔run↔swim↔strength);
    // an indoor↔outdoor toggle keeps each step's target as-is.
    const groupChanged = sportGroup(w.sport) !== sportGroup(sport);
    w.sport = sport;
    const timeOnly = BIKE_SPORTS.has(sport) || sport === "strength";
    const fix = (s: WorkoutStepDetail) => {
      if (timeOnly) s.distance_meters = null;
      if (groupChanged) s.target = normalizeTarget(s.target, sport);
    };
    for (const item of w.steps) {
      if (item.kind === "repeat") (item.steps ?? []).forEach(fix);
      else fix(item);
    }
    commit(wIdx, w);
  }

  function setBlockType(wIdx: number, topIdx: number, type: BlockKind) {
    const w = structuredClone(workoutsRef.current[wIdx]);
    w.steps[topIdx] = convertBlock(w.steps[topIdx], type, w.sport);
    commit(wIdx, w);
  }

  function addBlock(wIdx: number, type: BlockKind) {
    const w = structuredClone(workoutsRef.current[wIdx]);
    w.steps.push(makeFreshBlock(type, w.sport));
    commit(wIdx, w);
  }

  function deleteBlock(wIdx: number, topIdx: number) {
    const w = structuredClone(workoutsRef.current[wIdx]);
    w.steps.splice(topIdx, 1);
    commit(wIdx, w);
  }

  function moveBlock(wIdx: number, topIdx: number, dir: -1 | 1) {
    const j = topIdx + dir;
    const w = structuredClone(workoutsRef.current[wIdx]);
    if (j < 0 || j >= w.steps.length) return;
    [w.steps[topIdx], w.steps[j]] = [w.steps[j], w.steps[topIdx]];
    commit(wIdx, w);
  }

  function moveInnerStep(wIdx: number, topIdx: number, innerIdx: number, dir: -1 | 1) {
    const w = structuredClone(workoutsRef.current[wIdx]);
    const arr = w.steps[topIdx].steps;
    if (!arr) return;
    const j = innerIdx + dir;
    if (j < 0 || j >= arr.length) return;
    [arr[innerIdx], arr[j]] = [arr[j], arr[innerIdx]];
    commit(wIdx, w);
  }

  async function publish(idx: number) {
    setActions((a) => ({ ...a, [idx]: { state: "working" } }));
    const w = workoutsRef.current[idx];
    try {
      if (w.sport === "bike_indoor") {
        await api.downloadZwo(w);
        setActions((a) => ({ ...a, [idx]: { state: "done", msg: "Downloaded .zwo" } }));
      } else {
        await api.pushWorkout(w);
        setActions((a) => ({ ...a, [idx]: { state: "done", msg: "Published to Garmin" } }));
      }
    } catch (e) {
      setActions((a) => ({ ...a, [idx]: { state: "error", msg: String(e) } }));
    }
  }

  if (error) {
    return (
      <div className="p-8 text-error font-mono text-sm">
        Failed to load: {error}
        <div className="text-on-surface-variant mt-2">
          Is the backend running on the API base in <code>.env</code>?
        </div>
      </div>
    );
  }
  if (!data || !week) {
    return <div className="p-8 text-on-surface-variant">Loading…</div>;
  }
  if (!data.date || workouts.length === 0) {
    return (
      <div className="p-5 md:p-8 max-w-[1200px] mx-auto">
        <h1 className="font-display font-extrabold text-3xl tracking-tight">Workout</h1>
        <Card className="mt-6 text-on-surface-variant">
          No sessions scheduled in the next 3 weeks.
        </Card>
      </div>
    );
  }

  return (
    <div className="p-5 md:p-8 max-w-[1200px] mx-auto flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <MonoLabel>{relativeDay(data.date)} · {fmtWeekday(data.date)}, {fmtDate(data.date)}</MonoLabel>
          <h1 className="font-display font-extrabold text-3xl md:text-4xl tracking-tight mt-1">
            Next Session{workouts.length > 1 ? "s" : ""}
          </h1>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 flex flex-col gap-6">
          {workouts.map((w, i) => (
            <WorkoutEditor
              key={i}
              w={w}
              zones={zones}
              metric={metrics[i]}
              action={actions[i]}
              onTitle={(title) => patchWorkout(i, { title })}
              onSport={(sport) => changeSport(i, sport)}
              onDate={(date) => patchWorkout(i, { date })}
              onStep={(topIdx, innerIdx, patch) => patchStep(i, topIdx, innerIdx, patch)}
              onBlockType={(topIdx, type) => setBlockType(i, topIdx, type)}
              onBlockDelete={(topIdx) => deleteBlock(i, topIdx)}
              onBlockMove={(topIdx, dir) => moveBlock(i, topIdx, dir)}
              onInnerMove={(topIdx, innerIdx, dir) => moveInnerStep(i, topIdx, innerIdx, dir)}
              onAddBlock={(type) => addBlock(i, type)}
              onPublish={() => publish(i)}
            />
          ))}
        </div>

        <div className="flex flex-col gap-6">
          <TrainingContext week={week} />
          <GarminSync connected={connected} />
        </div>
      </div>
    </div>
  );
}

// ── workout card ────────────────────────────────────────────────────────────

function WorkoutEditor({
  w, zones, metric, action, onTitle, onSport, onDate, onStep, onBlockType, onBlockDelete,
  onBlockMove, onInnerMove, onAddBlock, onPublish,
}: {
  w: WorkoutDetail;
  zones: ZonesResponse | null;
  metric?: Metric;
  action?: ActionState;
  onTitle: (t: string) => void;
  onSport: (s: Sport) => void;
  onDate: (date: string) => void;
  onStep: (topIdx: number, innerIdx: number | null, patch: Partial<WorkoutStepDetail>) => void;
  onBlockType: (topIdx: number, type: BlockKind) => void;
  onBlockDelete: (topIdx: number) => void;
  onBlockMove: (topIdx: number, dir: -1 | 1) => void;
  onInnerMove: (topIdx: number, innerIdx: number, dir: -1 | 1) => void;
  onAddBlock: (type: BlockKind) => void;
  onPublish: () => void;
}) {
  const color = SPORT_COLOR[w.sport];
  const isIndoor = w.sport === "bike_indoor";
  const exportable = ["swim", "run", "bike_outdoor", "bike_indoor"].includes(w.sport);
  const exportHint = isIndoor
    ? "Downloads a .zwo for Rouvy/Zwift"
    : exportable ? "Publishes to your Garmin calendar" : "Not exported (planning only)";
  const dur = metric?.duration_min ?? w.duration_min;
  const tss = metric?.planned_tss ?? w.planned_tss;
  const invalid = metric?.error;

  return (
    <Card className="flex flex-col gap-4">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <span className="h-9 w-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
          <div className="min-w-0 flex-1">
            <input
              className={`${inputBase} w-full font-display text-lg font-semibold`}
              value={w.title}
              onChange={(e) => onTitle(e.target.value)}
            />
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <select
                value={w.sport}
                onChange={(e) => onSport(e.target.value as Sport)}
                className={`${inputBase} text-xs`}
                style={{ color }}
              >
                {SPORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <span className="font-mono text-[11px] text-outline">→ {exportHint}</span>
            </div>
          </div>
        </div>
        <div className="flex gap-4 text-right">
          <div>
            <MonoLabel>Duration</MonoLabel>
            <div className="font-mono font-semibold text-lg">{fmtDuration(dur)}</div>
          </div>
          <div>
            <MonoLabel>TSS</MonoLabel>
            <div className="font-mono font-semibold text-lg" style={{ opacity: metric?.loading ? 0.4 : 1 }}>
              {tss}
            </div>
          </div>
        </div>
      </div>

      {/* schedule / reschedule */}
      <div className="flex items-center gap-2 flex-wrap">
        <MonoLabel>Date</MonoLabel>
        <button
          onClick={() => onDate(shiftDate(w.date, -1))}
          className="rounded-btn border border-outline-variant/50 text-on-surface-variant hover:border-primary hover:text-primary font-mono text-sm w-7 h-7"
          title="Move back a day"
        >
          ‹
        </button>
        <input
          type="date"
          value={w.date}
          onChange={(e) => e.target.value && onDate(e.target.value)}
          className={inputBase}
        />
        <button
          onClick={() => onDate(shiftDate(w.date, 1))}
          className="rounded-btn border border-outline-variant/50 text-on-surface-variant hover:border-primary hover:text-primary font-mono text-sm w-7 h-7"
          title="Move forward a day"
        >
          ›
        </button>
        <span className="font-mono text-[11px] text-outline">
          {relativeDay(w.date)} · {fmtWeekday(w.date)}
        </span>
      </div>

      {/* intensity bar */}
      <IntensityBar steps={w.steps} />

      {w.description && <p className="text-on-surface-variant text-sm">{w.description}</p>}

      {/* blocks */}
      <div className="flex flex-col gap-2">
        {w.steps.map((s, i) => (
          <BlockEditor
            key={i}
            block={s}
            topIdx={i}
            total={w.steps.length}
            sport={w.sport}
            zones={zones}
            onStep={onStep}
            onType={onBlockType}
            onDelete={onBlockDelete}
            onMove={onBlockMove}
            onInnerMove={onInnerMove}
          />
        ))}
        <AddBlock onAdd={onAddBlock} />
      </div>

      {/* validation banner */}
      {invalid && (
        <div className="rounded-btn border border-error/50 bg-error/10 px-3 py-2 font-mono text-xs text-error">
          {invalid}
        </div>
      )}

      {/* action footer */}
      <div className="flex flex-wrap items-center gap-3 pt-1 border-t border-outline-variant/30">
        {exportable ? (
          <button
            onClick={onPublish}
            disabled={action?.state === "working" || !!invalid}
            className="mt-3 rounded-btn bg-primary text-on-primary font-mono text-sm font-medium px-4 py-2 hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed transition"
            title={invalid ? "Fix the issue above before publishing" : undefined}
          >
            {action?.state === "working"
              ? isIndoor ? "Preparing…" : "Publishing…"
              : isIndoor ? "Download .zwo" : "Publish to Garmin"}
          </button>
        ) : (
          <span className="mt-3 font-mono text-xs text-outline">
            {w.sport === "brick" ? "Brick/multisport export not supported yet."
              : "Strength sessions aren't exported as structured workouts."}
          </span>
        )}
        {action?.state === "done" && (
          <span className="mt-3 font-mono text-xs text-secondary">✓ {action.msg}</span>
        )}
        {action?.state === "error" && (
          <span className="mt-3 font-mono text-xs text-error">{action.msg}</span>
        )}
      </div>
    </Card>
  );
}

// ── block editor (type selector + repeat count + steps) ───────────────────────

function BlockEditor({
  block, topIdx, total, sport, zones, onStep, onType, onDelete, onMove, onInnerMove,
}: {
  block: WorkoutStepDetail;
  topIdx: number;
  total: number;
  sport: Sport;
  zones: ZonesResponse | null;
  onStep: (topIdx: number, innerIdx: number | null, patch: Partial<WorkoutStepDetail>) => void;
  onType: (topIdx: number, type: BlockKind) => void;
  onDelete: (topIdx: number) => void;
  onMove: (topIdx: number, dir: -1 | 1) => void;
  onInnerMove: (topIdx: number, innerIdx: number, dir: -1 | 1) => void;
}) {
  const kind = blockKindOf(block);
  const isRepeat = block.kind === "repeat";
  const innerSteps = block.steps ?? [];
  return (
    <div className="rounded-btn border border-outline-variant/40 bg-surface-container-low/60 p-2 flex flex-col gap-2">
      {/* toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={kind}
          onChange={(e) => onType(topIdx, e.target.value as BlockKind)}
          className={inputBase}
        >
          <option value="steady">Steady block</option>
          <option value="interval2">2-step interval</option>
          <option value="interval3">3-step interval</option>
        </select>
        {isRepeat && (
          <div className="flex items-center gap-1">
            <span className="font-mono text-xs text-on-surface-variant">repeat ×</span>
            <input
              type="number"
              min={1}
              max={30}
              value={block.repeat_count ?? 1}
              onChange={(e) => onStep(topIdx, null, { repeat_count: Math.max(1, parseInt(e.target.value || "1", 10)) })}
              className={`${inputBase} w-14 text-center`}
            />
          </div>
        )}
        <div className="ml-auto flex items-center gap-1">
          <MoveButtons
            up={topIdx > 0}
            down={topIdx < total - 1}
            onUp={() => onMove(topIdx, -1)}
            onDown={() => onMove(topIdx, 1)}
          />
          <button
            onClick={() => onDelete(topIdx)}
            className="text-outline hover:text-error font-mono text-sm px-2"
            title="Delete block"
          >
            ✕
          </button>
        </div>
      </div>

      {/* steps */}
      <div className={isRepeat ? "flex flex-col gap-2 pl-3 border-l-2 border-outline-variant/40" : "flex flex-col gap-2"}>
        {isRepeat
          ? innerSteps.map((s, j) => (
              <StepEditor
                key={j}
                step={s}
                sport={sport}
                zones={zones}
                onChange={(patch) => onStep(topIdx, j, patch)}
                move={innerSteps.length > 1 ? {
                  up: j > 0, down: j < innerSteps.length - 1,
                  onUp: () => onInnerMove(topIdx, j, -1), onDown: () => onInnerMove(topIdx, j, 1),
                } : undefined}
              />
            ))
          : <StepEditor step={block} sport={sport} zones={zones}
              onChange={(patch) => onStep(topIdx, null, patch)} />}
      </div>
    </div>
  );
}

function MoveButtons({
  up, down, onUp, onDown,
}: { up: boolean; down: boolean; onUp: () => void; onDown: () => void }) {
  const cls = "font-mono text-xs w-6 h-6 rounded-btn text-on-surface-variant hover:text-primary disabled:opacity-25 disabled:hover:text-on-surface-variant";
  return (
    <>
      <button className={cls} disabled={!up} onClick={onUp} title="Move up">↑</button>
      <button className={cls} disabled={!down} onClick={onDown} title="Move down">↓</button>
    </>
  );
}

function AddBlock({ onAdd }: { onAdd: (type: BlockKind) => void }) {
  const btn =
    "rounded-btn border border-outline-variant/50 text-on-surface-variant hover:border-primary hover:text-primary " +
    "font-mono text-xs px-3 py-1.5 transition-colors";
  return (
    <div className="flex items-center gap-2 flex-wrap pt-1">
      <MonoLabel>Add</MonoLabel>
      <button className={btn} onClick={() => onAdd("steady")}>+ Steady</button>
      <button className={btn} onClick={() => onAdd("interval2")}>+ 2-step interval</button>
      <button className={btn} onClick={() => onAdd("interval3")}>+ 3-step interval</button>
    </div>
  );
}

// ── intensity-bar motif ───────────────────────────────────────────────────────

function stepZone(s: WorkoutStepDetail): number {
  const t = s.target;
  if (!t || t.type === "open") return 1;
  if (t.type === "power_pct" && t.pct_of_anchor != null) {
    const p = t.pct_of_anchor;
    if (p < 0.55) return 1;
    if (p < 0.75) return 2;
    if (p < 0.9) return 3;
    if (p < 1.05) return 4;
    if (p < 1.2) return 5;
    return 6;
  }
  return t.zone ?? 1;
}

function flattenSteps(steps: WorkoutStepDetail[]): { zone: number; seconds: number }[] {
  const out: { zone: number; seconds: number }[] = [];
  for (const s of steps) {
    if (s.kind === "repeat") {
      for (let r = 0; r < (s.repeat_count ?? 1); r++)
        for (const inner of s.steps ?? [])
          out.push({ zone: stepZone(inner), seconds: inner.duration_seconds ?? 0 });
    } else {
      out.push({ zone: stepZone(s), seconds: s.duration_seconds ?? 0 });
    }
  }
  return out.filter((b) => b.seconds > 0);
}

function IntensityBar({ steps }: { steps: WorkoutStepDetail[] }) {
  const blocks = flattenSteps(steps);
  if (blocks.length === 0) return null;
  return (
    <div className="flex items-end gap-px h-16 rounded-btn bg-surface-container-lowest/60 p-1">
      {blocks.map((b, i) => (
        <div
          key={i}
          className="rounded-[2px]"
          style={{
            flexGrow: b.seconds,
            flexBasis: 0,
            minWidth: 3,
            height: `${28 + b.zone * 11}%`,
            backgroundColor: ZONE_COLOR[b.zone],
          }}
          title={`Z${b.zone} · ${secToMmss(b.seconds)}`}
        />
      ))}
    </div>
  );
}

// ── step editor ───────────────────────────────────────────────────────────────

function StepEditor({
  step, sport, zones, onChange, move,
}: {
  step: WorkoutStepDetail;
  sport: Sport;
  zones: ZonesResponse | null;
  onChange: (patch: Partial<WorkoutStepDetail>) => void;
  move?: { up: boolean; down: boolean; onUp: () => void; onDown: () => void };
}) {
  const zone = stepZone(step);
  const timeOnly = BIKE_SPORTS.has(sport) || sport === "strength";
  const isDistance = step.distance_meters != null;
  const metric = (step.target?.type ?? "open") as IntensityMetric;

  // metric options for this sport, plus the current one if it's unusual (e.g. power_pct)
  const baseOpts = METRIC_OPTIONS[sportGroup(sport)] ?? METRIC_OPTIONS.strength;
  const opts = baseOpts.some((o) => o.value === metric)
    ? baseOpts
    : [{ value: metric, label: METRIC_LABEL[metric] }, ...baseOpts];

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-btn bg-surface-container-high/40 px-3 py-2">
      <span className="h-6 w-1 rounded-full shrink-0" style={{ backgroundColor: ZONE_COLOR[zone] }} />
      {move && (
        <div className="flex flex-col -my-1">
          <button className="font-mono text-[10px] leading-none h-3 text-outline hover:text-primary disabled:opacity-25"
            disabled={!move.up} onClick={move.onUp} title="Move up">▲</button>
          <button className="font-mono text-[10px] leading-none h-3 text-outline hover:text-primary disabled:opacity-25"
            disabled={!move.down} onClick={move.onDown} title="Move down">▼</button>
        </div>
      )}
      <input
        className={`${inputBase} flex-1 min-w-[6rem]`}
        value={step.name}
        onChange={(e) => onChange({ name: e.target.value })}
      />

      {/* end condition: time-only sports show just a duration; others get a Time/Dist toggle */}
      {!timeOnly && (
        <div className="flex rounded-btn border border-outline-variant/50 overflow-hidden">
          {([["time", "Time"], ["dist", "Dist"]] as const).map(([k, lbl]) => {
            const active = k === "dist" ? isDistance : !isDistance;
            return (
              <button
                key={k}
                onClick={() =>
                  onChange({ distance_meters: k === "dist" ? (sport === "swim" ? 100 : 1000) : null })
                }
                className={`px-2 py-1 font-mono text-[11px] transition-colors ${
                  active ? "bg-primary text-on-primary" : "text-on-surface-variant hover:bg-surface-container-high"
                }`}
              >
                {lbl}
              </button>
            );
          })}
        </div>
      )}

      {isDistance && !timeOnly ? (
        <>
          <label className="flex items-center gap-1">
            <input
              type="number"
              min={0}
              step={sport === "swim" ? 25 : 100}
              value={step.distance_meters ?? 0}
              onChange={(e) => onChange({ distance_meters: parseInt(e.target.value || "0", 10) })}
              className={`${inputBase} w-20 text-right`}
            />
            <span className="font-mono text-xs text-on-surface-variant">m</span>
          </label>
          <label className="flex items-center gap-1" title="Estimated time — drives the training-load (TSS) calc">
            <MonoLabel>~</MonoLabel>
            <DurationInput seconds={step.duration_seconds ?? 0} onChange={(s) => onChange({ duration_seconds: s })} />
          </label>
        </>
      ) : (
        <label className="flex items-center gap-1">
          <MonoLabel>time</MonoLabel>
          <DurationInput seconds={step.duration_seconds ?? 0} onChange={(s) => onChange({ duration_seconds: s })} />
        </label>
      )}

      {/* intensity metric + zone/percent editor */}
      {opts.length > 1 ? (
        <select
          value={metric}
          onChange={(e) => onChange({ target: targetForMetric(e.target.value as IntensityMetric, step.target) })}
          className={inputBase}
        >
          {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      ) : (
        <span className="font-mono text-xs text-outline">free</span>
      )}
      <TargetEditor step={step} sport={sport} zones={zones} onChange={onChange} />
    </div>
  );
}

/** Renders the zone dropdown or %FTP field for the step's current metric (nothing for Free). */
function TargetEditor({
  step, sport, zones, onChange,
}: {
  step: WorkoutStepDetail;
  sport: Sport;
  zones: ZonesResponse | null;
  onChange: (patch: Partial<WorkoutStepDetail>) => void;
}) {
  const t = step.target;
  if (!t || t.type === "open") return null;

  if (t.type === "power_pct") {
    return (
      <label className="flex items-center gap-1">
        <input
          type="number"
          min={30}
          max={200}
          value={Math.round((t.pct_of_anchor ?? 0) * 100)}
          onChange={(e) =>
            onChange({ target: { ...t, pct_of_anchor: parseInt(e.target.value || "0", 10) / 100 } })
          }
          className={`${inputBase} w-16 text-center`}
        />
        <span className="font-mono text-xs text-on-surface-variant">%FTP</span>
      </label>
    );
  }

  const maxZone = t.type === "power_zone" ? 6 : 5;
  const { list, unit, pace } = zoneListFor(t.type, sport, zones);
  return (
    <select
      value={t.zone ?? 1}
      onChange={(e) => onChange({ target: { ...t, zone: parseInt(e.target.value, 10) } })}
      className={inputBase}
    >
      {Array.from({ length: maxZone }, (_, i) => i + 1).map((z) => {
        const zo = list?.find((x) => x.number === z);
        const range = zo ? ` · ${fmtZoneRange(zo, unit, pace)}` : "";
        return <option key={z} value={z}>Z{z}{range}</option>;
      })}
    </select>
  );
}

function DurationInput({ seconds, onChange }: { seconds: number; onChange: (s: number) => void }) {
  const [text, setText] = useState(secToMmss(seconds));
  useEffect(() => { setText(secToMmss(seconds)); }, [seconds]);
  return (
    <input
      className={`${inputBase} w-16 text-center`}
      value={text}
      placeholder="m:ss"
      onChange={(e) => {
        setText(e.target.value);
        const s = mmssToSec(e.target.value);
        if (s != null) onChange(s);
      }}
      onBlur={() => setText(secToMmss(seconds))}
    />
  );
}

// ── sidebar cards ─────────────────────────────────────────────────────────────

function TrainingContext({ week }: { week: WeekPlan }) {
  const phaseColor = PHASE_COLOR[week.phase] ?? "#4fdbc8";
  const tsb = week.fitness.tsb;
  return (
    <Card className="flex flex-col gap-3">
      <SectionTitle>Training Context</SectionTitle>
      <div className="flex items-center justify-between">
        <MonoLabel>Phase</MonoLabel>
        <span
          className="font-mono text-xs uppercase tracking-wider rounded-full px-3 py-1 border"
          style={{ color: phaseColor, borderColor: phaseColor + "66", backgroundColor: phaseColor + "1a" }}
        >
          {week.phase}
        </span>
      </div>
      <Row label="Weeks to race" value={`${Math.round(week.weeks_to_race)}`} />
      <Row label="Week load" value={`${week.planned_tss} / ${week.target_tss} TSS`} />
      <div className="flex items-center justify-between">
        <MonoLabel>Form · TSB</MonoLabel>
        <span className="font-mono font-semibold" style={{ color: tsbColor(tsb) }}>
          {tsb > 0 ? `+${tsb}` : tsb}
        </span>
      </div>
      <p className="text-on-surface-variant text-sm border-t border-outline-variant/30 pt-3">
        {week.rationale}
      </p>
    </Card>
  );
}

function GarminSync({ connected }: { connected: boolean | null }) {
  const dot = connected === null ? "#ffd34f" : connected ? "#4ae176" : "#ffb4ab";
  const label = connected === null ? "Checking…" : connected ? "Connected" : "Not connected";
  return (
    <Card className="flex flex-col gap-3">
      <SectionTitle>Garmin Sync</SectionTitle>
      <div className="flex items-center gap-2">
        <span
          className="h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: dot, boxShadow: `0 0 8px ${dot}` }}
        />
        <span className="font-mono text-sm text-on-surface-variant">{label}</span>
      </div>
      <p className="text-on-surface-variant text-sm">
        Publishing sends the structured workout to your Garmin Connect calendar so it
        appears on your watch. Indoor rides download as a <code>.zwo</code> file for
        Rouvy/Zwift instead.
      </p>
      {connected === false && (
        <p className="font-mono text-xs text-error">
          Sync your Garmin account from the Dashboard first.
        </p>
      )}
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <MonoLabel>{label}</MonoLabel>
      <span className="font-mono text-sm">{value}</span>
    </div>
  );
}

function shiftDate(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function relativeDay(iso: string): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(iso + "T00:00:00");
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Tomorrow";
  return `In ${diff} days`;
}
