import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine,
} from "recharts";
import { api } from "../api/client";
import type { FullPlan, WeekPlan } from "../api/types";
import { Card, SectionTitle, MonoLabel } from "../components/Card";
import {
  SPORT_COLOR, SPORT_LABEL, PHASE_COLOR, tsbColor, fmtDate, fmtWeekday, fmtDuration,
} from "../lib/format";

export function Dashboard() {
  const [plan, setPlan] = useState<FullPlan | null>(null);
  const [week, setWeek] = useState<WeekPlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.fullPlan(), api.week()])
      .then(([p, w]) => { setPlan(p); setWeek(w); })
      .catch((e) => setError(String(e)));
  }, []);

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
  if (!plan || !week) {
    return <div className="p-8 text-on-surface-variant">Loading…</div>;
  }

  const fit = week.fitness;
  const chartData = plan.weeks.map((w) => ({
    label: fmtDate(w.week_start),
    CTL: w.ctl,
    TSB: w.tsb,
    target: w.target_tss,
  }));

  return (
    <div className="p-5 md:p-8 max-w-[1200px] mx-auto flex flex-col gap-6">
      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <MonoLabel>Race in {Math.round(week.weeks_to_race)} weeks · {plan.race_date}</MonoLabel>
          <h1 className="font-display font-extrabold text-3xl md:text-4xl tracking-tight mt-1">
            {week.phase} Phase
          </h1>
        </div>
        <PhasePill phase={week.phase} />
      </header>

      {/* Fitness cards */}
      <div className="grid grid-cols-3 gap-4">
        <MetricCard label="Fitness · CTL" value={fit.ctl} color="#4fdbc8" />
        <MetricCard label="Fatigue · ATL" value={fit.atl} color="#adc6ff" />
        <MetricCard label="Form · TSB" value={fit.tsb} color={tsbColor(fit.tsb)} signed />
      </div>

      {/* Plan-to-race chart */}
      <Card>
        <div className="flex items-baseline justify-between">
          <SectionTitle>Plan to Race</SectionTitle>
          <MonoLabel>
            peak CTL {plan.projected_peak_ctl} · race-day TSB {plan.race_day_fitness.tsb}
          </MonoLabel>
        </div>
        <div className="h-64 mt-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="#2d3449" strokeDasharray="3 3" />
              <XAxis dataKey="label" stroke="#859490" fontSize={11} tickMargin={8} />
              <YAxis stroke="#859490" fontSize={11} />
              <ReferenceLine y={0} stroke="#3c4947" />
              <Tooltip
                contentStyle={{
                  background: "#171f33", border: "1px solid #3c4947",
                  borderRadius: 8, fontFamily: "JetBrains Mono", fontSize: 12,
                }}
              />
              <Line type="monotone" dataKey="CTL" stroke="#4fdbc8" strokeWidth={2.5} dot={false} />
              <Line type="monotone" dataKey="TSB" stroke="#4ae176" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* This week */}
      <Card>
        <div className="flex items-baseline justify-between">
          <SectionTitle>This Week</SectionTitle>
          <MonoLabel>{week.planned_tss} / {week.target_tss} TSS planned</MonoLabel>
        </div>
        <p className="text-on-surface-variant text-sm mb-4">{week.rationale}</p>
        <div className="flex flex-col divide-y divide-outline-variant/30">
          {week.workouts.map((w, i) => (
            <div key={i} className="flex items-center gap-4 py-3">
              <div className="w-10 text-center">
                <div className="font-mono text-xs text-on-surface-variant">{fmtWeekday(w.date)}</div>
                <div className="font-mono text-[10px] text-outline">{fmtDate(w.date)}</div>
              </div>
              <span
                className="h-9 w-1.5 rounded-full shrink-0"
                style={{ backgroundColor: SPORT_COLOR[w.sport] }}
              />
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{w.title}</div>
                <div className="font-mono text-xs text-on-surface-variant">
                  {SPORT_LABEL[w.sport]} · {fmtDuration(w.duration_min)}
                </div>
              </div>
              {/* TSS bar */}
              <div className="hidden sm:block w-40">
                <div className="h-2 rounded-full bg-surface-container-highest overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.min(100, (w.planned_tss / 90) * 100)}%`,
                      backgroundColor: SPORT_COLOR[w.sport],
                    }}
                  />
                </div>
              </div>
              <div className="font-mono text-sm w-12 text-right">{w.planned_tss}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function MetricCard({
  label, value, color, signed = false,
}: { label: string; value: number; color: string; signed?: boolean }) {
  const display = signed && value > 0 ? `+${value}` : `${value}`;
  return (
    <Card className="flex flex-col gap-1">
      <MonoLabel>{label}</MonoLabel>
      <span className="font-mono font-semibold text-3xl md:text-4xl" style={{ color }}>
        {display}
      </span>
    </Card>
  );
}

function PhasePill({ phase }: { phase: string }) {
  const c = PHASE_COLOR[phase] ?? "#4fdbc8";
  return (
    <span
      className="font-mono text-xs uppercase tracking-wider rounded-full px-3 py-1 border"
      style={{ color: c, borderColor: c + "66", backgroundColor: c + "1a" }}
    >
      {phase}
    </span>
  );
}
